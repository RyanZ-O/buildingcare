"""Trace failure -> cause relationships, preserving direction and instance uncertainty."""
from uuid import uuid4
from .elements import expanded_words, equipment_matches, distance_to_room, TYPE_TERMS
from .engine import now
from .knowledge import dedupe
from .kg import neo4j_enabled, CAUSE_QUERY


def analyse_graph(issue, observations, building, graph, topology, identifications=None):
    entities = {e['id']: e for e in building['entities']}
    selected = entities.get(issue.get('assetId'))
    room = entities[issue['roomId']]
    vision = next((r for r in (identifications or []) if r['mode'] == 'vision'), None)
    vision_text = ' '.join(vision.get('observations', []) + vision.get('possibleProblems', [])) if vision else ''
    words = expanded_words(f"{issue['title']} {issue['description']} {observations} {vision_text}")
    matches = []
    for node in graph.nodes.values():
        if node['kind'] != 'FailureMode':
            continue
        label = node['label'].casefold()
        if 'airflow' in words and ('low' in words or 'insufficient' in words) and any(t in label for t in ('excessive airflow', 'airflow above', 'airflow too high')):
            continue
        if 'hot' in words and 'too cold' in label or 'cold' in words and 'too hot' in label:
            continue
        tokens = set(__import__('re').findall(r'[a-z]{3,}', label))
        score = len(words & tokens)
        if score == 0:
            continue
        equipment_edges = graph.related(node['id'], 'HAS_FAILURE_MODE', reverse=True)
        eq_match = any(equipment_matches(selected, graph.nodes[e['source']]['label']) for e in equipment_edges)
        if selected and eq_match:
            service = selected.get('serviceName', '').lower()
            labels = ' '.join(graph.nodes[e['source']]['label'].lower() for e in equipment_edges)
            if service.startswith('supply air') and 'supply' in labels:
                score += 3
            elif service.startswith('extract air') and any(v in labels for v in ('return', 'exhaust')):
                score += 2
        electrical = 'electrical' in node.get('properties', {}).get('context_key', '').casefold()
        if selected and eq_match:
            score += 5
        if issue['system'] == 'electrical':
            if not electrical:
                continue
            score += 2
        matches.append((score, node, eq_match))
    matches.sort(key=lambda x: (-x[0], x[1]['id']))
    # Show both covered and uncovered matches instead of silently pretending the export is complete.
    selected_matches = matches[:8]
    records = graph.causes([m[1]['id'] for m in selected_matches])
    rank = {m[1]['id']: m[0] for m in selected_matches}
    records.sort(key=lambda r: (-rank.get(r['failureId'], 0), r['causeId']))
    report_source = {'id': f"issue-{issue['id']}", 'text': f"{issue['title']} — {issue['description']}",
                     'source': 'Occupant observation; location selected by reporter, not a verified cause'}
    vision_source = ({'id': 'vision-' + vision['id'], 'text': vision_text,
                      'source': 'Unverified vision observation of this issue’s saved photos; not a confirmed defect or exact location'} if vision else None)
    candidates, seen = [], set()
    # Round robin across failure modes so a single mode does not consume all candidate slots.
    ordered = []
    for index in range(120):
        for _, mode, _ in selected_matches:
            group = [r for r in records if r['failureId'] == mode['id']]
            if index < len(group):
                ordered.append(group[index])
    for record in ordered:
        cause = graph.nodes.get(record['causeId'])
        if not cause or cause['id'] in seen:
            continue
        seen.add(cause['id'])
        fid = record['failureId']
        edge_ids = [record['edgeId']] + [c['edgeId'] for c in record['checks'] if c.get('id')]
        equipment_edges = graph.related(fid, 'HAS_FAILURE_MODE', reverse=True)
        edge_ids.extend(e['id'] for e in equipment_edges)
        relevant_types = {t for t, aliases in TYPE_TERMS.items() if any(a in cause['label'].casefold() for a in aliases if a.isascii())}
        if 'access panel' in cause['label'].casefold():
            relevant_types.discard('IfcElectricDistributionBoard')
            if selected and any(equipment_matches(selected, graph.nodes[e['source']]['label']) for e in equipment_edges):
                relevant_types.add(selected['ifcType'])
        pool = [e for e in entities.values() if e['kind'] == 'asset' and e['floorId'] == room['floorId']
                and e['ifcType'] in relevant_types]
        upstream = set()
        frontier = [selected['id']] if selected else []
        while frontier:
            target = frontier.pop()
            for edge in topology:
                if edge['targetId'] == target and edge['sourceId'] not in upstream:
                    upstream.add(edge['sourceId'])
                    frontier.append(edge['sourceId'])
        pool.sort(key=lambda e: (e['id'] not in upstream, distance_to_room(e, room)))
        mapped = [selected['id']] if selected and selected['ifcType'] in relevant_types else [e['id'] for e in pool[:1]]
        if not mapped and not relevant_types and selected and any(equipment_matches(selected, graph.nodes[e['source']]['label']) for e in equipment_edges):
            mapped = [selected['id']]
        graph_view = graph.view(edge_ids)
        checks = [graph.nodes[c['id']]['label'] for c in record['checks'] if c.get('id') in graph.nodes]
        candidates.append({'id': cause['id'], 'label': cause['label'], 'assetId': mapped[0] if mapped else None,
            'assetIds': mapped, 'mappingBasis': 'Suggested type/proximity match only; inspect or explicitly bind a model element.',
            'failureModeId': fid, 'failureMode': graph.nodes[fid]['label'],
            'reason': f"The graph links ‘{graph.nodes[fid]['label']}’ to this candidate via HAS_ROOT_CAUSE. Symptom matching selects the failure mode; this does not establish that the cause exists in this building.",
            'evidence': [report_source, *([vision_source] if vision_source else []), *[graph.evidence(e) for e in edge_ids if e in graph.edges]],
            'checks': checks or ['No diagnostic check was exported for this failure mode; obtain equipment inspection guidance.'],
            'missingEvidence': ['Verify that this failure mode applies to the selected equipment.',
                                'Confirm the actual fault location and physical service connections.'], 'graph': graph_view})
        if len(candidates) == 8:
            break
    source = 'neo4j' if neo4j_enabled() else 'neo4j-csv-snapshot'
    return {'id': uuid4().hex, 'issueId': issue['id'], 'createdAt': now(), 'observations': observations,
            'candidates': candidates, 'knowledgeBackend': source, 'datasetHash': graph.document['sourceHash'],
            'inputSnapshot': {'roomId': issue['roomId'], 'assetId': issue.get('assetId'), 'locationDetail': issue.get('locationDetail', '')},
            'topologySnapshot': topology,
            'queryTrace': {'query': CAUSE_QUERY.strip(), 'parameters': {'dataset': graph.document['sourceHash'], 'failure_ids': [m[1]['id'] for m in selected_matches]}, 'returnedRows': len(records), 'backend': source},
            'recognitionId': vision['id'] if vision else None,
            'matchedFailureModes': [{'id': n['id'], 'label': n['label'], 'matchScore': s,
                'hasCauses': bool(graph.related(n['id'], 'HAS_ROOT_CAUSE'))} for s, n, _ in selected_matches],
            'limitations': [*graph.document['audit']['warnings'],
                'Lexical and bilingual symptom matching ranks applicability, not causal probability.',
                'Amber components are unverified candidate locations; red indicates a reported location only.',
                'Physical propagation uses separately entered directed service links, never taxonomy or proximity.'],
            'sources': dedupe([report_source] + [s for c in candidates for s in c['evidence']])}
