"""Audited Neo4j table import and explicit graph queries. Never execute CSV contents."""
import csv
import hashlib
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

RELATIONS = {'HAS_SYSTEM', 'HAS_EQUIPMENT_TYPE', 'HAS_FAILURE_MODE', 'OCCURS_AT', 'HAS_ROOT_CAUSE', 'CHECK_WITH'}
KEY = re.compile(r'(?:^|,\s*)(id:ID\([^)]+\)|:LABEL|name|fault|id|context_key):\s*')


def parse_node(raw):
    match = re.fullmatch(r'\(:([A-Za-z][A-Za-z0-9_]*)\s+\{(.*)\}\)', raw, re.S)
    if not match:
        raise ValueError('Unsupported node display syntax')
    label, body = match.groups()
    keys = list(KEY.finditer(body))
    props = {m.group(1): body[m.end():keys[i+1].start() if i+1 < len(keys) else len(body)].strip()
             for i, m in enumerate(keys)}
    original = props.get(f'id:ID({label})') or props.get('id')
    if not original or not props.get('name'):
        raise ValueError('Node has no stable source ID or name')
    return {'id': f'{label}:{original}', 'originalId': original, 'kind': label,
            'label': props['name'], 'properties': props}


def import_table(path: Path):
    nodes, edges, errors, duplicate_rows = {}, {}, [], 0
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ['n', 'r', 'm']:
            raise ValueError('Expected Neo4j table columns n,r,m')
        count = 0
        for count, row in enumerate(reader, 1):
            line = count + 1
            try:
                left = parse_node(row['n'])
                for side in ('n', 'm'):
                    if row[side] == 'null':
                        continue
                    node = parse_node(row[side])
                    if node['id'] in nodes and nodes[node['id']]['label'] != node['label']:
                        raise ValueError('Conflicting labels for one source ID')
                    nodes.setdefault(node['id'], {**node, 'sourceRows': []})['sourceRows'].append(line)
                if row['r'] == 'null' and row['m'] == 'null':
                    continue
                relation = re.fullmatch(r'\[:([A-Z_]+)\]', row['r'])
                if not relation or relation[1] not in RELATIONS:
                    raise ValueError('Unknown relationship syntax or type')
                right = parse_node(row['m'])
                identity = f"{left['id']}|{relation[1]}|{right['id']}"
                edge_id = 'edge_' + hashlib.sha256(identity.encode()).hexdigest()[:20]
                if edge_id in edges:
                    duplicate_rows += 1
                    edges[edge_id]['sourceRows'].append(line)
                else:
                    edges[edge_id] = {'id': edge_id, 'source': left['id'], 'target': right['id'],
                                      'relation': relation[1], 'sourceRows': [line]}
            except (ValueError, TypeError) as e:
                errors.append({'row': line, 'error': str(e)})
    failure_ids = {n['id'] for n in nodes.values() if n['kind'] == 'FailureMode'}
    cause_ids = {e['source'] for e in edges.values() if e['relation'] == 'HAS_ROOT_CAUSE'}
    check_ids = {e['source'] for e in edges.values() if e['relation'] == 'CHECK_WITH'}
    warnings = []
    if count == 5000:
        warnings.append('Exactly 5,000 exported rows: a query/export limit may have truncated this snapshot. Re-export without LIMIT to verify completeness.')
    warnings.extend([
        'HAS_ROOT_CAUSE points from a failure mode to a candidate cause; it is diagnostic lookup, not physical fault propagation.',
        'This export has no IFC instance IDs, physical connectivity, service zones, repair actions, validated prices, work durations or calibrated probabilities.',
        'Missing graph edges mean unknown coverage, not evidence that a failure has no cause.'
    ])
    return {'version': 1, 'sourceFile': path.name, 'sourceHash': digest,
            'nodes': list(nodes.values()), 'edges': list(edges.values()),
            'audit': {'rowCount': count, 'nodeCount': len(nodes), 'edgeCount': len(edges),
                      'duplicateRows': duplicate_rows, 'errors': errors,
                      'nodeTypes': dict(Counter(n['kind'] for n in nodes.values())),
                      'relationTypes': dict(Counter(e['relation'] for e in edges.values())),
                      'failuresWithoutCauses': len(failure_ids - cause_ids),
                      'failuresWithoutChecks': len(failure_ids - check_ids), 'warnings': warnings}}


# Query is fixed and parameterised. Runtime has read access only; import is a separate command.
CAUSE_QUERY = '''
MATCH (f:MaintenanceKnowledge {dataset: $dataset})-[r:HAS_ROOT_CAUSE]->(c:MaintenanceKnowledge {dataset: $dataset})
WHERE f.id IN $failure_ids
OPTIONAL MATCH (f)-[cr:CHECK_WITH]->(ck:MaintenanceKnowledge {dataset: $dataset})
RETURN f.id AS failureId, c.id AS causeId, r.id AS edgeId,
       collect(DISTINCT {id: ck.id, edgeId: cr.id}) AS checks
ORDER BY failureId, causeId LIMIT 120
'''


def neo4j_settings():
    return tuple(os.getenv(k, '').strip() for k in ('NEO4J_URI', 'NEO4J_USERNAME', 'NEO4J_PASSWORD'))


def neo4j_enabled():
    return os.getenv('KNOWLEDGE_BACKEND', 'snapshot').lower() == 'neo4j'


def driver():
    from neo4j import GraphDatabase
    uri, username, password = neo4j_settings()
    if not all((uri, username, password)):
        raise ValueError('Configure NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD.')
    return GraphDatabase.driver(uri, auth=(username, password), connection_timeout=8,
                                connection_acquisition_timeout=10, max_transaction_retry_time=0)


_health = {}


def connection_status(dataset):
    key = (*neo4j_settings(), os.getenv('NEO4J_DATABASE', 'neo4j'), dataset)
    cached = _health.get(key)
    if cached and time.monotonic() - cached[0] < 30:
        return cached[1]
    status = {'connected': False, 'importedNodes': 0}
    if neo4j_enabled() and all(neo4j_settings()):
        try:
            with driver() as db:
                db.verify_connectivity()
                records, _, _ = db.execute_query('MATCH (n:MaintenanceKnowledge {dataset:$dataset}) RETURN count(n) AS count',
                    dataset=dataset, database_=os.getenv('NEO4J_DATABASE', 'neo4j'), routing_='r')
                status = {'connected': True, 'importedNodes': records[0]['count']}
        except Exception:
            pass
    _health[key] = (time.monotonic(), status)
    return status


class SnapshotGraph:
    def __init__(self, document):
        self.document = document
        self.nodes = {n['id']: n for n in document['nodes']}
        self.edges = {e['id']: e for e in document['edges']}
        self.outgoing, self.incoming = {}, {}
        for edge in self.edges.values():
            self.outgoing.setdefault(edge['source'], []).append(edge)
            self.incoming.setdefault(edge['target'], []).append(edge)

    def related(self, node_id, relation, reverse=False):
        return [e for e in (self.incoming if reverse else self.outgoing).get(node_id, []) if e['relation'] == relation]

    def causes(self, failure_ids):
        if neo4j_enabled():
            try:
                with driver() as connection:
                    connection.verify_connectivity()
                    records, _, _ = connection.execute_query(CAUSE_QUERY, dataset=self.document['sourceHash'],
                        failure_ids=failure_ids, database_=os.getenv('NEO4J_DATABASE', 'neo4j'), routing_='r')
                    results = [dict(r) for r in records]
                    # An empty imported dataset must not silently masquerade as a successful query.
                    if not results and any(self.related(f, 'HAS_ROOT_CAUSE') for f in failure_ids):
                        raise ValueError('Dataset not imported')
                    return results
            except Exception:
                from fastapi import HTTPException
                raise HTTPException(503, 'Neo4j query unavailable or this dataset has not been imported. Check connection and run tools/import_neo4j.py. Saved reports are retained; no silent demo fallback was used.') from None
        return [{'failureId': fid, 'causeId': e['target'], 'edgeId': e['id'],
                 'checks': [{'id': c['target'], 'edgeId': c['id']} for c in self.related(fid, 'CHECK_WITH')]}
                for fid in failure_ids for e in self.related(fid, 'HAS_ROOT_CAUSE')][:120]

    def evidence(self, edge_id):
        edge = self.edges[edge_id]
        return {'id': edge_id, 'text': f"{self.nodes[edge['source']]['label']} —[{edge['relation']}]→ {self.nodes[edge['target']]['label']}",
                'source': f"{self.document['sourceFile']}; CSV row(s) {', '.join(map(str, edge['sourceRows']))}; SHA256 {self.document['sourceHash'][:12]}"}

    def view(self, edge_ids):
        edges = [self.edges[e] for e in dict.fromkeys(edge_ids) if e in self.edges]
        ids = {i for e in edges for i in (e['source'], e['target'])}
        return {'nodes': [{'id': i, 'label': self.nodes[i]['label'], 'kind': self.nodes[i]['kind']} for i in sorted(ids)],
                'edges': edges}


def load_snapshot(directory):
    path = directory / 'causal-graph.json'
    return SnapshotGraph(json.loads(path.read_text(encoding='utf-8'))) if path.exists() else None
