"""Instance trace and human inspection records, distinct from diagnostic KG edges."""
from collections import deque
from copy import deepcopy
from uuid import uuid4
from .engine import now


def instance_trace(issue, candidate, analysis, building):
    entities = {e['id']: e for e in building['entities']}
    links = analysis.get('topologySnapshot', [])
    reported = issue.get('assetId') or issue['roomId']
    root = candidate.get('assetId')
    # Include only this hypothesis and its directed path to the reported object.
    queue = deque([(root, [])]) if root else deque()
    visited, chosen = set(), []
    while queue:
        node, path = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        if node == reported:
            chosen = path
            break
        for edge in links:
            if edge['sourceId'] == node:
                queue.append((edge['targetId'], path + [edge]))
    # The downstream view shows only entered immediate service links from the report.
    downstream = [e for e in links if e['sourceId'] == reported]
    selected_edges = {e['id']: e for e in chosen + downstream}
    ids = {reported, *([root] if root else [])}
    for e in selected_edges.values():
        ids.update([e['sourceId'], e['targetId']])
    return {'nodes': [{'id': i, 'label': entities[i]['name'], 'kind': 'Reported' if i == reported else 'Candidate' if i == root else 'Room' if entities[i]['kind'] == 'room' else 'Element'} for i in sorted(ids) if i in entities],
            'edges': [{'id': e['id'], 'source': e['sourceId'], 'target': e['targetId'],
                       'relation': e['relation'], 'basis': e['basis'], 'note': e['note'],
                       'condition': e['requires'] + ' → ' + e['produces']} for e in selected_edges.values()],
            'connected': bool(root and (root == reported or chosen)),
            'note': 'Entered physical service links, with their assumptions. Arrow direction is service flow; see conditions for fault propagation. No link is invented to connect an unmapped hypothesis.'}


def inspect(analysis, request):
    updated = deepcopy(analysis)
    candidate = next((c for c in updated['candidates'] if c['id'] == request.causeId), None)
    if candidate is None:
        raise ValueError('Candidate does not belong to this analysis.')
    if request.status == 'confirmed' and not candidate.get('assetId'):
        raise ValueError('Bind the hypothesis to a model component before recording confirmation.')
    event = {'id': uuid4().hex, 'status': request.status, 'note': request.note.strip(), 'createdAt': now()}
    if len(event['note']) < 5:
        raise ValueError('Record an inspection observation or evidence reference (at least five characters).')
    candidate['inspection'] = event
    candidate.setdefault('inspectionHistory', []).append(event)
    updated['parentAnalysisId'] = analysis['id']
    updated.update(id=uuid4().hex, createdAt=now())
    evidence = {'id': 'inspection-' + event['id'], 'text': f"{candidate['label']}: {request.status}. {event['note']}",
                'source': 'Human-entered inspection record; not sensor verification or graph probability'}
    candidate['evidence'].append(evidence)
    updated['sources'].append(evidence)
    return updated
