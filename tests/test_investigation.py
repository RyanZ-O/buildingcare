from copy import deepcopy
from pathlib import Path
import pytest
from test_diagnosis import graph_env, diagnosis, simulate, link
from test_backend import app_env, submit
from backend.knowledge import load_building
from backend.planning import simulate_plan
from backend.schemas import PlanningInputs
from backend.case_study import create_case, ROOMS, DUCT, FAN


def test_inspection_versions_prevent_stale_and_ruled_out_simulations(graph_env):
    client, *_ = graph_env
    issue = submit(client, assetId='fan')
    analysis = diagnosis(client, issue)
    old = simulate(client, issue, analysis)
    args = {'analysisId': analysis['id'], 'causeId': analysis['candidates'][0]['id'],
            'status': 'ruled_out', 'note': 'Measured fan current and operation normal.'}
    updated = client.post(f"/api/issues/{issue['id']}/inspections", json=args).json()
    assert updated['id'] != analysis['id']
    assert updated['candidates'][0]['inspection']['status'] == 'ruled_out'
    payload = {'analysisId': updated['id'], 'causeId': args['causeId'], 'action': 'local_repair'}
    assert client.post(f"/api/issues/{issue['id']}/simulations", json=payload).status_code == 422
    assert client.post(f"/api/issues/{issue['id']}/inspections", json=args).status_code == 422
    assert client.get(f"/api/issues/{issue['id']}/report", params={'simulationId': old['id']}).status_code == 422
    assert client.get(f"/api/issues/{issue['id']}/simulations").json()[0]['id'] == old['id']


def test_graph_trace_does_not_invent_service_edges(graph_env):
    client, *_ = graph_env
    issue = submit(client, assetId='fan')
    link(client, 'board', 'fan', 'power_loss', 'ventilation_loss', 'SUPPLIES_POWER')
    a = diagnosis(client, issue)
    a = client.post(f"/api/issues/{issue['id']}/bindings", json={'analysisId': a['id'], 'causeId': a['candidates'][0]['id'], 'assetId': 'board', 'reason': 'Upstream supply test hypothesis'}).json()
    trace = client.get(f"/api/issues/{issue['id']}/trace", params={'causeId': a['candidates'][0]['id']}).json()
    assert trace['connected']
    assert len(trace['edges']) == 1 and trace['edges'][0]['relation'] == 'SUPPLIES_POWER'
    assert trace['edges'][0]['basis'] == 'assumption'
    assert 'power_loss' in trace['edges'][0]['condition']


def test_resident_chat_is_rule_guidance_and_issue_scoped(graph_env):
    client, *_ = graph_env
    i = submit(client, title='Private room report')
    general = client.post('/api/resident/chat', json={'message':'房间很闷怎么办？'}).json()
    assert general['mode'] == 'resident-guidance-rules' and general['sources'] == []
    linked = client.post('/api/resident/chat', json={'message':'What is the status?', 'issueId':i['id']}).json()
    assert i['title'] in linked['answer'] and len(linked['sources']) == 1
    urgent = client.post('/api/resident/chat', json={'message':'I see sparks and smoke'}).json()
    assert 'emergency' in urgent['answer'] and 'Do not open' in urgent['answer']


def test_changing_confirmed_component_requires_new_inspection(graph_env):
    client, *_ = graph_env
    issue = submit(client, assetId='fan')
    analysis = diagnosis(client, issue)
    confirmed = client.post(f"/api/issues/{issue['id']}/inspections", json={
        'analysisId':analysis['id'], 'causeId':analysis['candidates'][0]['id'],
        'status':'confirmed', 'note':'Test inspector confirmed on the selected fan.'}).json()
    changed = client.post(f"/api/issues/{issue['id']}/bindings", json={
        'analysisId':confirmed['id'], 'causeId':confirmed['candidates'][0]['id'],
        'assetId':'board', 'reason':'Rebind to an upstream component for inspection.'}).json()
    assert changed['candidates'][0]['inspection']['status'] == 'untested'


def test_unmapped_cause_cannot_silently_use_reported_duct():
    issue={'id':'i','roomId':'room','assetId':'duct','system':'hvac'}
    analysis={'id':'a','candidates':[{'id':'c','label':'Missing damper','assetId':None,'evidence':[]}], 'topologySnapshot':[]}
    building={'entities':[{'id':'room','kind':'room'}, {'id':'duct','kind':'asset'}]}
    with pytest.raises(ValueError, match='Bind this hypothesis'):
        simulate_plan(issue, analysis, 'c', 'local_repair', PlanningInputs(), building)


def test_case_scope_animation_metrics_and_preserved_names():
    root = Path(__file__).resolve().parents[1]
    if not (root/'data/building.json').exists():
        pytest.skip('Model not present')
    b = load_building(root/'data')
    assert b['model']['name'] == 'Building 1'
    assert len({e['name'] for e in b['entities']}) == len(b['entities'])
    assert all(e['originalName'] and e['displayCode'] for e in b['entities'])
    case = create_case(b)
    analysis = {'id':'a', 'candidates':[{'id':'cause', 'label':'Duct obstruction', 'assetId':DUCT, 'evidence':[]}], 'topologySnapshot':case['demoTopology']}
    p = PlanningInputs(durationHours=4, workers=2, hourlyRate=45, materialCost=150, coolingUnavailable=True, occupantsPerRoom=2)
    local = simulate_plan(case, analysis, 'cause', 'local_repair', p, b)
    assert local['resources']['totalCost'] == 510
    assert set(local['during']['affectedRoomIds']) == set(ROOMS[:2])
    assert local['metrics']['occupantServiceHours'] == 16
    assert local['metrics']['temperatureDegreeHoursPerRoom'] is not None
    assert local['animation']['frames'][-1]['impact']['affectedRoomIds'] == []
    branch = simulate_plan(case, analysis, 'cause', 'system_shutdown', p.model_copy(update={'isolationAssetId':FAN, 'durationHours':8}), b)
    assert set(branch['during']['affectedRoomIds']) == set(ROOMS[:3])
    assert ROOMS[3] not in branch['during']['affectedRoomIds']
    assert branch['metrics']['occupantServiceHours'] == 48
    steps = branch['animation']['frames'][:-1]
    assert all(set(a['impact']['affectedRoomIds']).issubset(z['impact']['affectedRoomIds']) for a,z in zip(steps,steps[1:]))
    replaced = simulate_plan(case, analysis, 'cause', 'local_repair', p.model_copy(update={'repairMethod':'replace'}), b)
    assert 'replacement' in ' '.join(replaced['plan']['materials']).lower()
