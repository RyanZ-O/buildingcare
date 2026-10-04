"""Evidence boundaries and completeness of the actual reconstructed building."""
import json
from pathlib import Path
import pytest
from test_backend import app_env

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def service_graph():
    path=ROOT/'data/service-graph.json'
    if not path.exists():pytest.skip('Whole-building graph not prepared')
    return json.loads(path.read_text(encoding='utf-8'))

def test_all_source_entities_are_preserved_and_edges_resolve(service_graph):
    model=json.loads((ROOT/'data/building.json').read_text(encoding='utf-8'))
    nodes={n['id']:n for n in service_graph['nodes']}
    assert len(nodes)==len(service_graph['nodes'])
    assert {e['id'] for e in model['entities']}<=nodes.keys()
    assert len({e['id'] for e in service_graph['edges']})==len(service_graph['edges'])
    for e in service_graph['edges']:
        assert e['source'] in nodes and e['target'] in nodes and e['source']!=e['target']

def test_inferences_are_not_verified_or_active_outage_rules(service_graph):
    for e in service_graph['edges']:
        assert e['simulationEligible'] is False
        assert e['evidence']['method']
        assert e['basis']=='source_model' if e['relation']=='PART_OF_SYSTEM' else e['basis']=='inferred'
    assert service_graph['summary']['explicitPortConnections']==0
    assert service_graph['summary']['verifiedCircuitAssignments']==0

def test_contact_candidates_do_not_mix_supply_return_or_services(service_graph):
    nodes={n['id']:n for n in service_graph['nodes']}
    for e in service_graph['edges']:
        if e['relation']!='POSSIBLE_CONNECTION':continue
        a,b=nodes[e['source']],nodes[e['target']]
        assert set(a['networks'])&set(b['networks'])
        assert not e['directed']
        assert e['evidence']['distanceMetres']<=.025
        if a['ifcType']=='IfcPipeSegment' and b['ifcType']=='IfcPipeSegment':
            assert not ({'LP101:supply'}==set(a['networks']) and {'LP101:return'}==set(b['networks']))

def test_telecom_boards_and_outlets_are_not_power_feeders(service_graph):
    nodes={n['id']:n for n in service_graph['nodes']}
    for e in service_graph['edges']:
        if e['relation']=='POSSIBLE_POWER_FEED':
            assert 'S0301' in nodes[e['source']]['networks']
            target=nodes[e['target']]
            assert target['ifcType']=='IfcFan' or 'S0301' in target['networks']
        if e['relation']=='POSSIBLE_SERVICE' and e['evidence']['service']=='power':
            assert 'S0301' in nodes[e['source']]['networks']

def test_room_services_use_terminals_and_expose_ambiguity(service_graph):
    nodes={n['id']:n for n in service_graph['nodes']}
    for e in service_graph['edges']:
        if e['relation']=='POSSIBLE_SERVICE':
            assert nodes[e['target']]['kind']=='Room'
            assert nodes[e['source']]['ifcType'] not in {'IfcPipeSegment','IfcDuctSegment'}
            assert nodes[e['source']]['floorId']==nodes[e['target']]['floorId']
            assert isinstance(e['evidence']['ambiguous'],bool)
    assert service_graph['gaps'], 'Incomplete evidence must remain visible'

def test_new_api_does_not_seed_topology_or_change_issues(app_env):
    client,directory,*_=app_env
    (directory/'service-graph.json').write_text(json.dumps({'nodes':[],'edges':[],'policy':'fixture'}),encoding='utf-8')
    assert client.get('/api/service-graph').status_code==200
    response=client.get('/api/service-graph/download')
    assert response.status_code==200 and 'attachment' in response.headers['content-disposition']
    assert client.get('/api/topology').json()==[]
    assert client.get('/api/issues').json()==[]
