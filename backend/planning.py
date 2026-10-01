"""Explicit resource assumptions and a transparent first-order thermal scenario."""
from collections import deque
import math
from uuid import uuid4
from .engine import now
from .schemas import PlanningInputs


def plans(candidate):
    label = candidate['label'].casefold()
    local = ('Inspect and clean / replace filter' if any(w in label for w in ('filter', 'fouling', 'dirty', 'blocked'))
             else 'Inspect, seal / replace affected section' if any(w in label for w in ('leak', 'seal', 'joint'))
             else 'Inspect and repair selected component')
    return [
        {'method': 'standard', 'materials': [], 'tradeoff': 'Lowest immediate spend; service disruption continues.', 'action': 'observe', 'label': 'Monitor pending diagnosis', 'defaults': {'durationHours': 1, 'workers': 1, 'materialCost': 0},
         'steps': ['Record observations', 'Monitor affected service', 'Escalate if conditions deteriorate'], 'outcome': 'Fault remains unresolved'},
        {'action': 'local_repair', 'method': 'standard', 'materials': ['Compatible consumables', 'Seals / fasteners as inspected'], 'tradeoff': 'Limited access and outage; only suitable if the component is repairable.', 'label': local, 'defaults': {'durationHours': 4, 'workers': 2, 'materialCost': 150},
         'steps': ['Confirm cause and access', 'Confirm local isolation scope', local, 'Test and recommission'], 'outcome': 'Conditional service restoration'},
        {'action': 'local_repair', 'method': 'replace', 'label': 'Replace selected section / component', 'materials': ['Compatible replacement component', 'Mounting and connection kit', 'Seals and test consumables'], 'tradeoff': 'Higher material spend; verify availability and compatibility before scheduling.', 'defaults': {'durationHours': 6, 'workers': 2, 'materialCost': 480, 'repairMethod': 'replace'}, 'steps': ['Confirm diagnosis and compatibility', 'Arrange local isolation', 'Replace inspected component', 'Test and recommission'], 'outcome': 'Conditional service restoration'},
        {'method': 'standard', 'materials': ['Repair parts after inspection', 'Isolation / access consumables', 'Commissioning consumables'], 'tradeoff': 'Wider temporary outage and larger crew; access to the connected branch.', 'action': 'system_shutdown', 'label': 'Isolate branch and repair', 'defaults': {'durationHours': 8, 'workers': 3, 'materialCost': 350},
         'steps': ['Verify upstream service links', 'Plan outage and occupant notice', 'Isolate verified branch', local, 'Test and restore branch'],
         'outcome': 'Conditional branch restoration'},
    ]


def impact(entities, links, start, state):
    queue = deque([(start, state, [start], [])])
    visited, rooms, assets, paths, states = set(), set(), set(), [], {}
    while queue:
        node, current, path, reasons = queue.popleft()
        if (node, current) in visited:
            continue
        visited.add((node, current))
        states.setdefault(node, []).append(current)
        (rooms if entities[node]['kind'] == 'room' else assets).add(node)
        if reasons:
            paths.append({'nodes': path, 'reason': '; '.join(reasons)})
        for edge in links:
            if edge['sourceId'] == node and edge['requires'] == current and edge['targetId'] in entities:
                queue.append((edge['targetId'], edge['produces'], path + [edge['targetId']],
                    reasons + [f"{edge['relation']} ({edge['basis']}): {edge['note']}"]))
    return {'affectedRoomIds': sorted(rooms), 'affectedAssetIds': sorted(assets), 'paths': paths,
            'serviceStates': states, 'explanation': ''}


def thermal_curve(p, outage, repaired):
    ua = p.conductanceWattsPerK / 1000
    tau = p.capacitanceKwhPerK / ua
    equilibrium = p.outdoorTemperature + p.internalGainWatts / p.conductanceWattsPerK
    def free(t):
        return equilibrium + (p.initialTemperature - equilibrium) * math.exp(-t / tau)
    times = sorted(set([round(p.horizonHours * i / 96, 5) for i in range(97)] + ([outage] if outage < p.horizonHours else [])))
    curve = []
    for t in times:
        value = free(t) if not repaired or t <= outage else p.initialTemperature + (free(outage) - p.initialTemperature) * math.exp(-(t - outage) / p.recoveryHours)
        curve.append({'hour': t, 'temperature': round(value, 3)})
    exceed = sum((b['hour'] - a['hour']) for a, b in zip(curve, curve[1:]) if (a['temperature'] + b['temperature']) / 2 > p.comfortUpper)
    return {'points': curve, 'peakTemperature': max(x['temperature'] for x in curve), 'hoursAboveThreshold': round(exceed, 2),
            'threshold': p.comfortUpper, 'timeConstantHours': round(tau, 2),
            'method': 'C dT/dt = UA(Tout - T) + Q; exponential recovery after successful repair. Air temperature only; not operative temperature, PMV or PPD.',
            'basis': 'Uncalibrated planning assumptions, constant weather and gains; no sensor measurements or comfort-standard compliance claim.'}


def simulate_plan(issue, analysis, cause_id, action, parameters, building):
    candidate = next((c for c in analysis['candidates'] if c['id'] == cause_id), None)
    if candidate is None:
        raise ValueError('Selected cause does not belong to this analysis.')
    if candidate.get('inspection', {}).get('status') == 'ruled_out':
        raise ValueError('This hypothesis was ruled out. Reopen it with new inspection evidence before simulating.')
    method = parameters.repairMethod if parameters else 'standard'
    recipe = next((r for r in plans(candidate) if r['action'] == action and r['method'] == method), None)
    if recipe is None:
        raise ValueError('Select a supported repair method for this intervention.')
    p = parameters or PlanningInputs(**recipe['defaults'], serviceState='power_loss' if issue['system'] == 'electrical' else 'ventilation_loss')
    entities = {e['id']: e for e in building['entities']}
    root = candidate.get('assetId')
    if not root or root not in entities or entities[root]['kind'] == 'room':
        raise ValueError('Bind this hypothesis to a model component before simulating its service impact.')
    links = analysis.get('topologySnapshot', [])
    assumptions = [
        'Resource and cost values are editable planning estimates, not contractor quotations; default values are illustrative.',
        'A knowledge-graph association is a hypothesis. Repair success and recommissioning require verification.',
        'Only entered directed service links propagate effects; unmodelled connections and other affected rooms remain unknown.',
        'Room availability is an operator-selected planning policy, not an automated safety certification.',
    ]
    if p.isolationAssetId:
        if p.isolationAssetId not in entities or entities[p.isolationAssetId]['kind'] == 'room':
            raise ValueError('Choose a valid isolation element.')
        # Validate by the requested state, not just undirected physical proximity.
        reachable = impact(entities, links, p.isolationAssetId, p.serviceState)
        if root and root not in reachable['affectedAssetIds']:
            raise ValueError('Isolation scope must reach the selected cause through configured conditional links.')
        root = p.isolationAssetId
    elif action == 'system_shutdown':
        raise ValueError('Select the upstream isolation element for branch shutdown. Add service links first; branch scope is not inferred from proximity.')
    during = impact(entities, links, root, p.serviceState) if root else {'affectedRoomIds': [], 'affectedAssetIds': [], 'paths': [], 'serviceStates': {}, 'explanation': ''}
    mapped_rooms = list(during['affectedRoomIds'])
    if issue['roomId'] not in mapped_rooms:
        during['affectedRoomIds'].append(issue['roomId'])
        during['serviceStates'][issue['roomId']] = [p.serviceState]
        assumptions.append('The reported room is included as a what-if assumption from the complaint; its service connection has not been established by the configured links.')
    during['explanation'] = 'Potential service loss under the selected cause and isolation assumptions. Other impacts may exist where service links are missing.'
    after = ({**during, 'explanation': 'No repair: assumed fault persists over the planning horizon.'} if action == 'observe' else
             {'affectedRoomIds': [], 'affectedAssetIds': [], 'paths': [], 'serviceStates': {},
              'explanation': 'Service restoration is conditional on correct diagnosis, successful repair and commissioning.'})
    if any(e['basis'] == 'assumption' for e in links):
        assumptions.append('Configured topology includes explicitly assumed links; verify each path before operational use.')
    duration = p.horizonHours if action == 'observe' else p.durationHours
    labour = p.workers * p.durationHours * p.hourlyRate
    total = labour + p.materialCost
    fraction = p.uncertaintyPercent / 100
    resources = {'workers': p.workers, 'workHours': p.durationHours, 'personHours': p.workers * p.durationHours,
                 'outageHours': duration, 'labourCost': round(labour, 2), 'materialCost': p.materialCost,
                 'totalCost': round(total, 2), 'lowCost': round(total * (1 - fraction), 2),
                 'highCost': round(total * (1 + fraction), 2), 'currency': p.currency,
                 'basis': 'User-adjustable scenario assumptions; excludes taxes, overhead, delay and consequential costs.'}
    curve = thermal_curve(p, duration, action != 'observe') if p.coolingUnavailable else None
    impacts, notices = [], []
    for rid in during['affectedRoomIds']:
        states = during['serviceStates'].get(rid, [p.serviceState])
        # Loss of electricity or ventilation alone does not automatically mean loss of cooling.
        comfort = curve if p.coolingUnavailable else None
        availability = 'Planned closure' if p.roomClosure else 'Service limited; occupancy review required'
        impacts.append({'roomId': rid, 'services': states, 'availability': availability, 'hours': duration,
                        'basis': 'Entered service path' if rid in mapped_rooms else 'Reported-room assumption', 'comfort': comfort})
        notices.append({'roomId': rid, 'status': 'draft',
            'en': f"Planning notice — {entities[rid]['name']}: possible {', '.join(states).replace('_', ' ')} for {duration:g} hours. {availability}. " + (f"Illustrative air-temperature peak {comfort['peakTemperature']:.1f} °C; verify local conditions." if comfort else 'No temperature forecast has been made.'),
            'zh': f"计划通知草稿：{entities[rid]['name']} 预计服务受限 {duration:g} 小时。" + ('计划暂停使用房间。' if p.roomClosure else '房间是否继续使用由维护团队评估。') + ('温度曲线为未校准的情景估算。' if comfort else '当前未进行温度预测。')})
    steps = [{'id': f'step-{i}', 'label': step, 'kind': 'Action'} for i, step in enumerate(recipe['steps'])]
    nodes = [{'id': 'hypothesis', 'label': candidate['label'], 'kind': 'Hypothesis'}, *steps,
             {'id': 'outcome', 'label': recipe['outcome'], 'kind': 'Outcome'}]
    solution_graph = {'nodes': nodes, 'edges': [{'id': f'plan-{i}', 'source': a['id'], 'target': b['id'], 'relation': 'PLANNED_NEXT'} for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]}
    metrics, animation = enrich_scenario(p, action, during, after, entities, curve, duration)
    return {'id': uuid4().hex, 'issueId': issue['id'], 'analysisId': analysis['id'], 'causeId': cause_id,
            'metrics': metrics, 'animation': animation,
            'diagnosisStatus': candidate.get('inspection', {}).get('status', 'untested'),
            'materialDescription': p.materialDescription,
            'action': action, 'createdAt': now(), 'during': during, 'after': after, 'parameters': p.model_dump(),
            'resources': resources, 'roomImpacts': impacts, 'occupantNotices': notices,
            'solutionGraph': solution_graph, 'plan': recipe, 'assumptions': assumptions,
            'sources': [*candidate['evidence'], {'id': 'planning-inputs', 'text': 'Saved editable inputs and deterministic resource/RC calculations.',
                         'source': 'Platform planning model; assumptions, not validated engineering predictions'},
                        *[{'id': e['id'], 'text': f"{e['sourceId']} —[{e['relation']}]→ {e['targetId']}: {e['note']}",
                           'source': f"User-entered topology ({e['basis']}); saved with analysis"} for e in links]]}


def enrich_scenario(p, action, during, after, entities, curve, duration):
    rooms = len(during['affectedRoomIds'])
    hours = min(duration, p.horizonHours)
    degree_hours = 0
    if curve:
        pts = curve['points']
        degree_hours = sum((b['hour'] - a['hour']) * (max(0, a['temperature'] - p.comfortUpper) + max(0, b['temperature'] - p.comfortUpper)) / 2 for a, b in zip(pts, pts[1:]))
    metrics = {'affectedOccupants': rooms * p.occupantsPerRoom,
               'occupantServiceHours': round(rooms * p.occupantsPerRoom * hours, 2),
               'roomClosureHours': round(rooms * hours if p.roomClosure else 0, 2),
               'serviceAvailabilityPercent': round(100 * (1 - hours / p.horizonHours), 1),
               'temperatureDegreeHoursPerRoom': round(degree_hours, 2) if curve else None,
               'occupantHeatExposureDegreeHours': round(degree_hours * rooms * p.occupantsPerRoom, 2) if curve else None,
               'occupancyBasis': 'Constant assumed occupants per affected room; not actual occupancy or productivity loss.',
               'availabilityBasis': 'Fraction of the chosen horizon with service restored, conditional on repair success; not a measured KPI.'}
    depths = {}
    for path in during['paths']:
        for index, node in enumerate(path['nodes']):
            depths[node] = min(index, depths.get(node, index))
    for node in during['affectedAssetIds'] + during['affectedRoomIds']:
        depths.setdefault(node, 0)
    frames = []
    max_depth = max(depths.values(), default=0)
    for depth in range(max_depth + 1):
        ids = {node for node, level in depths.items() if level <= depth}
        frames.append({'label': 'Selected fault / isolation' if depth == 0 else f'Service dependency hop {depth}', 'phase': 'during',
                       'impact': {**during, 'affectedRoomIds': [i for i in during['affectedRoomIds'] if i in ids],
                                  'affectedAssetIds': [i for i in during['affectedAssetIds'] if i in ids],
                                  'paths': [p for p in during['paths'] if all(i in ids for i in p['nodes'])]}})
    frames.append({'label': 'Fault persists over planning horizon' if action == 'observe' else f'Repair complete at {duration:g} h — restoration assumed',
                   'phase': 'after', 'impact': after})
    return metrics, {'frames': frames, 'basis': 'Dependency traversal animation, not physical travel time. Restoration is conditional on the selected repair. Room-only assumptions may appear at step 0.'}
