import csv
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from test_backend import app_env, submit, png_bytes
from backend.kg import import_table, parse_node
from backend.planning import impact, thermal_curve
from backend.schemas import PlanningInputs


def node(kind, identifier, name):
    return f'(:{kind} {{name: {name}, :LABEL: {kind}, id:ID({kind}): {identifier}}})'


@pytest.fixture
def graph_env(app_env):
    client, directory, factory, building = app_env
    building['entities'][4]['ifcType'] = 'IfcFan'
    building['entities'][4]['name'] = 'Supply fan'
    building['entities'][5]['ifcType'] = 'IfcElectricDistributionBoard'
    (directory / 'building.json').write_text(json.dumps(building), encoding='utf-8')
    equipment = node('Equipment', 'fan', 'Supply fan')
    failure = node('FailureMode', 'low', 'Low airflow')
    cause = node('RootCause', 'motor', 'Fan motor failure')
    check = node('DiagnosticCheck', 'inspect', 'Inspect fan, motor current, controller alarms')
    rows = [(equipment, '[:HAS_FAILURE_MODE]', failure), (failure, '[:HAS_ROOT_CAUSE]', cause),
            (failure, '[:CHECK_WITH]', check), (node('Location', 'roof', 'Roof'), 'null', 'null'),
            (equipment, '[:HAS_FAILURE_MODE]', node('FailureMode', 'missing', 'Noise too high'))]
    path = directory / 'source.csv'
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['n', 'r', 'm'])
        writer.writerows(rows)
    doc = import_table(path)
    (directory / 'causal-graph.json').write_text(json.dumps(doc), encoding='utf-8')
    return client, directory, factory, building, doc


def diagnosis(client, issue):
    r = client.post(f"/api/issues/{issue['id']}/analysis", json={'observations': ''})
    assert r.status_code == 200, r.text
    return r.json()


def link(client, source, target, requires='ventilation_loss', produces='ventilation_loss', relation='SERVES'):
    r = client.post('/api/topology', json={'sourceId': source, 'targetId': target, 'relation': relation,
        'requires': requires, 'produces': produces, 'basis': 'assumption', 'note': 'Assumed connection for test, not verified'})
    assert r.status_code == 201, r.text
    return r.json()


def simulate(client, issue, analysis, action='local_repair', parameters=None):
    r = client.post(f"/api/issues/{issue['id']}/simulations", json={'analysisId': analysis['id'],
        'causeId': analysis['candidates'][0]['id'], 'action': action, 'parameters': parameters})
    assert r.status_code == 200, r.text
    return r.json()


def test_import_preserves_commas_ids_directions_and_missing_coverage(graph_env):
    *_, doc = graph_env
    assert doc['audit']['errors'] == []
    assert doc['audit']['failuresWithoutCauses'] == 1
    check = next(n for n in doc['nodes'] if n['kind'] == 'DiagnosticCheck')
    assert check['label'] == 'Inspect fan, motor current, controller alarms'
    edge = next(e for e in doc['edges'] if e['relation'] == 'HAS_ROOT_CAUSE')
    assert edge['source'] == 'FailureMode:low' and edge['target'] == 'RootCause:motor'
    assert edge['sourceRows'] == [3]
    assert parse_node(node('Equipment', 'fan', 'Supply fan'))['id'] != parse_node(node('System', 'fan', 'Supply fan'))['id']


def test_real_export_audit_and_round_trip():
    path = Path(__file__).resolve().parents[1] / 'data' / 'causal-graph.json'
    if not path.exists():
        pytest.skip('Actual CSV snapshot not imported in this environment')
    doc = json.loads(path.read_text(encoding='utf-8'))
    ids = {n['id'] for n in doc['nodes']}
    assert doc['audit']['errors'] == []
    assert doc['audit']['rowCount'] == 5000 and len(doc['edges']) == 4959
    assert all(e['source'] in ids and e['target'] in ids for e in doc['edges'])
    assert doc['audit']['failuresWithoutCauses'] == 431
    assert any('5,000' in warning for warning in doc['audit']['warnings'])


def test_full_graph_view_preserves_isolated_nodes_and_query_paths(graph_env):
    client, _, _, _, doc = graph_env
    response = client.get('/api/knowledge/graph')
    assert response.status_code == 200
    graph = response.json()
    assert graph['sourceHash'] == doc['sourceHash']
    assert {n['id'] for n in graph['nodes']} == {n['id'] for n in doc['nodes']}
    assert 'Location:roof' in {n['id'] for n in graph['nodes']}
    assert graph['edges'] == doc['edges']
    analysis = diagnosis(client, submit(client, assetId='fan'))
    edge_ids = {e['id'] for e in graph['edges']}
    for candidate in analysis['candidates']:
        assert all(e['id'] in edge_ids for e in candidate['graph']['edges'])


def test_element_upload_mapping_search_and_location_revision(graph_env):
    client, directory, factory, *_ = graph_env
    assert client.post('/api/issues', data={'roomId':'r1','system':'hvac','title':'Bad','description':'Invalid element','assetId':'r2'}).status_code == 422
    issue = submit(client, assetId='fan', locationDetail='Motor housing / 电机外壳')
    assert issue['assetId'] == 'fan'
    elements = client.get('/api/elements', params={'q':'风机','roomId':'r1'}).json()
    assert elements['total'] == 1 and elements['items'][0]['id'] == 'fan'
    suggestions = client.post('/api/identify', json={'roomId':'r1','system':'hvac','text':'请检查 IFC-fan，电机没有风'}).json()
    assert suggestions['candidates'][0]['assetId'] == 'fan' and suggestions['requiresConfirmation']
    analysis = diagnosis(client, issue)
    saved = simulate(client, issue, analysis)
    update = client.put(f"/api/issues/{issue['id']}/location", json={'assetId':'board','locationDetail':'upstream'}).json()
    assert update['locationRevision'] == 1
    restarted = TestClient(factory(directory))
    assert restarted.get(f"/api/issues/{issue['id']}/analysis").json() is None
    assert restarted.get(f"/api/issues/{issue['id']}/simulations").json()[0]['id'] == saved['id']
    assert restarted.get(f"/api/issues/{issue['id']}/report", params={'simulationId':saved['id']}).status_code == 422


def test_graph_queries_real_paths_checks_and_no_fabricated_probability(graph_env):
    client, *_ = graph_env
    issue = submit(client, assetId='fan', title='Low airflow')
    analysis = diagnosis(client, issue)
    assert analysis['knowledgeBackend'] == 'neo4j-csv-snapshot'
    candidate = analysis['candidates'][0]
    assert candidate['label'] == 'Fan motor failure'
    assert candidate['checks'] == ['Inspect fan, motor current, controller alarms']
    assert 'probability' not in candidate and 'confirmed' not in candidate
    assert candidate['assetIds'] == ['fan']
    assert {e['relation'] for e in candidate['graph']['edges']} == {'HAS_FAILURE_MODE','HAS_ROOT_CAUSE','CHECK_WITH'}
    assert any('CSV row(s) 3' in e['source'] for e in candidate['evidence'])


def test_conditional_topology_costs_thermal_and_snapshot_isolation(graph_env):
    client, _, _, building, _ = graph_env
    link(client, 'fan', 'r1')
    second = link(client, 'fan', 'r2')
    link(client, 'fan', 'r3', 'water_loss', 'water_loss')
    link(client, 'board', 'fan', 'power_loss', 'ventilation_loss', 'SUPPLIES_POWER')
    link(client, 'fan', 'board', 'ventilation_loss', 'power_loss', 'FEEDS')
    issue = submit(client, assetId='fan')
    analysis = diagnosis(client, issue)
    client.delete('/api/topology/' + second['id'])
    params = {'workers':3,'durationHours':2,'hourlyRate':50,'materialCost':200,'uncertaintyPercent':20,
              'coolingUnavailable':True,'horizonHours':24,'roomClosure':True}
    result = simulate(client, issue, analysis, parameters=params)
    assert result['during']['affectedRoomIds'] == ['r1','r2']
    assert result['resources']['totalCost'] == 500 and result['resources']['personHours'] == 6
    assert result['resources']['lowCost'] == 400 and result['resources']['highCost'] == 600
    curve = result['roomImpacts'][0]['comfort']
    assert curve['points'][0]['temperature'] == 24
    assert max(curve['points'],key=lambda x:x['temperature'])['hour'] == 2
    assert curve['points'][-1]['temperature'] < curve['peakTemperature']
    assert all(n['status'] == 'draft' for n in result['occupantNotices'])
    assert result['after']['affectedRoomIds'] == []
    assert len(result['during']['paths']) < 10
    assert result['solutionGraph']['edges']
    rerun = diagnosis(client, issue)
    new_result = simulate(client, issue, rerun)
    assert new_result['during']['affectedRoomIds'] == ['r1']
    assert new_result['roomImpacts'][0]['comfort'] is None


def test_shutdown_requires_valid_scope_and_observe_keeps_fault(graph_env):
    client, *_ = graph_env
    link(client,'board','fan','power_loss','ventilation_loss','SUPPLIES_POWER')
    link(client,'fan','r1')
    issue = submit(client,assetId='fan')
    analysis = diagnosis(client,issue)
    body = {'analysisId':analysis['id'],'causeId':analysis['candidates'][0]['id'],'action':'system_shutdown'}
    assert client.post(f"/api/issues/{issue['id']}/simulations",json=body).status_code == 422
    result = simulate(client,issue,analysis,action='system_shutdown',parameters={'isolationAssetId':'board','serviceState':'power_loss'})
    assert result['during']['affectedAssetIds'] == ['board','fan']
    observed = simulate(client,issue,analysis,action='observe',parameters={'horizonHours':12,'coolingUnavailable':True})
    assert observed['after']['affectedRoomIds'] == ['r1']
    assert observed['resources']['outageHours'] == 12
    assert observed['roomImpacts'][0]['comfort']['points'][-1]['temperature'] == observed['roomImpacts'][0]['comfort']['peakTemperature']


def test_manual_binding_preserves_old_analysis_and_rejects_cross_case(graph_env):
    client, directory, factory, *_ = graph_env
    issue = submit(client,assetId='fan')
    other = submit(client)
    analysis = diagnosis(client,issue)
    body = {'analysisId':analysis['id'],'causeId':analysis['candidates'][0]['id'],'assetId':'board','reason':'Inspect electrical supply as possible origin'}
    assert client.post(f"/api/issues/{other['id']}/bindings",json=body).status_code == 422
    bound = client.post(f"/api/issues/{issue['id']}/bindings",json=body).json()
    assert bound['id'] != analysis['id'] and bound['candidates'][0]['assetId'] == 'board'
    assert TestClient(factory(directory)).get(f"/api/issues/{issue['id']}/analysis").json()['id'] == bound['id']
    assert client.app.state.store.analysis(issue['id'],analysis['id']) == analysis


def test_old_demo_analysis_remains_readable_but_requires_graph_refresh(graph_env):
    client, *_ = graph_env
    issue = submit(client, assetId='fan')
    from backend.engine import analyse
    from backend.knowledge import DemoKnowledgeProvider
    legacy = analyse(issue, '', DemoKnowledgeProvider(client.app.state.data_dir, graph_env[3]))
    client.app.state.store.add_analysis(legacy)
    assert client.get(f"/api/issues/{issue['id']}/analysis").json()['id'] == legacy['id']
    response = client.post(f"/api/issues/{issue['id']}/simulations", json={'analysisId':legacy['id'],
        'causeId':legacy['candidates'][0]['id'], 'action':'local_repair'})
    assert response.status_code == 422 and 'predates' in response.json()['detail']
    upgraded = diagnosis(client, issue)
    assert simulate(client, issue, upgraded)['resources']


def test_ne04j_live_query_is_parameterised_and_failure_never_falls_back(graph_env,monkeypatch):
    from backend import kg
    client, *_, doc = graph_env
    monkeypatch.setenv('KNOWLEDGE_BACKEND','neo4j')
    seen = {}
    edge = next(e for e in doc['edges'] if e['relation'] == 'HAS_ROOT_CAUSE')
    check = next(e for e in doc['edges'] if e['relation'] == 'CHECK_WITH')
    class Driver:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def verify_connectivity(self): pass
        def execute_query(self,query,**kwargs):
            seen.update(query=query,**kwargs)
            return ([{'failureId':'FailureMode:low','causeId':'RootCause:motor','edgeId':edge['id'],
                      'checks':[{'id':'DiagnosticCheck:inspect','edgeId':check['id']}]}],None,None)
    monkeypatch.setattr(kg,'driver',Driver)
    issue = submit(client,assetId='fan')
    analysis = diagnosis(client,issue)
    assert analysis['knowledgeBackend'] == 'neo4j'
    assert '$failure_ids' in seen['query'] and seen['dataset'] == doc['sourceHash']
    def fail(): raise RuntimeError('SECRET credential')
    monkeypatch.setattr(kg,'driver',fail)
    r = client.post(f"/api/issues/{issue['id']}/analysis",json={})
    assert r.status_code == 503 and 'SECRET' not in r.text
    assert client.get(f"/api/issues/{issue['id']}/analysis").json() == analysis


def test_vision_failure_and_id_validation_with_saved_photos(graph_env,monkeypatch):
    client, *_ = graph_env
    for k in ['VISION_MODEL','VISION_BASE_URL','VISION_API_KEY']:
        monkeypatch.setenv(k,'')
    response = client.post('/api/issues',data={'roomId':'r1','system':'hvac','title':'fan issue','description':'Low airflow'},
                           files=[('photos',('fan.png',png_bytes(),'image/png'))])
    issue=response.json()
    url=f"/api/issues/{issue['id']}/identify"
    assert client.post(url,json={'usePhotos':True}).status_code == 503
    assert client.get(f"/api/issues/{issue['id']}").json() == issue
    monkeypatch.setenv('VISION_MODEL','test-vision')
    monkeypatch.setenv('VISION_BASE_URL','https://example.test/v1')
    monkeypatch.setenv('VISION_API_KEY','PRIVATE_KEY')
    async def fake(self,url,**kwargs):
        data={'observations':['Low airflow reported; no visible equipment tag.'],'possibleProblems':['Fan airflow restriction'],
              'candidates':[{'assetId':'invented','basis':'guessed'}],'missingEvidence':['Need readable tag']}
        return httpx.Response(200,request=httpx.Request('POST',url),json={'choices':[{'message':{'content':json.dumps(data)}}]})
    monkeypatch.setattr(httpx.AsyncClient,'post',fake)
    r=client.post(url,json={'usePhotos':True})
    assert r.status_code == 200 and r.json()['candidates'] == [] and r.json()['requiresConfirmation']
    assert 'PRIVATE_KEY' not in r.text
    assert client.get(f"/api/issues/{issue['id']}/identifications").json()[0]['id'] == r.json()['id']
    assert client.get(f"/api/issues/{issue['id']}").json().get('assetId') is None
    analysis=diagnosis(client,issue)
    assert analysis['recognitionId'] == r.json()['id']


def test_thermal_equilibrium_analytical_and_input_limits():
    p=PlanningInputs(initialTemperature=24,outdoorTemperature=24,internalGainWatts=0)
    assert all(x['temperature']==24 for x in thermal_curve(p,4,True)['points'])
    p=PlanningInputs(initialTemperature=24,outdoorTemperature=32,internalGainWatts=0,
                     conductanceWattsPerK=1000,capacitanceKwhPerK=1,horizonHours=1)
    assert thermal_curve(p,2,False)['points'][-1]['temperature'] == pytest.approx(32-8/__import__('math').e,abs=.001)
    for kwargs in [{'workers':0},{'durationHours':-1},{'capacitanceKwhPerK':0},{'hourlyRate':float('nan')}]:
        with pytest.raises(ValueError): PlanningInputs(**kwargs)
