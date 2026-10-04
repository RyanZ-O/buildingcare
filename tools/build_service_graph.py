"""Reconstruct whole-building service proposals from source properties and meshes.

Inferences are not verified IFC connections and are not active simulation rules.
"""
from collections import Counter, defaultdict, deque
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import re
import struct
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.knowledge import load_building

SEGMENTS = {'IfcPipeSegment', 'IfcDuctSegment'}
AIR = {'IfcDuctSegment', 'IfcDuctFitting', 'IfcAirTerminal', 'IfcFan', 'IfcDamper', 'IfcDuctSilencer', 'IfcFilter', 'IfcCoil'}
WATER = {'IfcPipeSegment', 'IfcPipeFitting', 'IfcValve', 'IfcFlowMeter', 'IfcSpaceHeater', 'IfcSanitaryTerminal', 'IfcWasteTerminal'}
TERMINALS = {'IfcAirTerminal': 'ventilation', 'IfcSpaceHeater': 'heating', 'IfcSanitaryTerminal': 'water', 'IfcWasteTerminal': 'drainage', 'IfcLightFixture': 'power', 'IfcOutlet': 'power', 'IfcSwitchingDevice': 'power'}
CONTACT_TOLERANCE = .025


def channels(entity):
    location = entity.get('properties', {}).get('FI_Sijainti', {})
    tags = [x.strip() for x in str(location.get('Järjestelmien tunnukset', '')).split(',') if x.strip()]
    name = str(location.get('Järjestelmien nimet', ''))
    result = []
    for tag in tags:
        if tag == 'LP101':
            sides = ['supply', 'return'] if entity['ifcType'] == 'IfcSpaceHeater' else ['return' if 'paluu' in name.casefold() else 'supply']
            result.extend((f'{tag}:{side}', 'heating', f'Heating {side} · {tag}') for side in sides)
        else:
            service = ('ventilation' if re.fullmatch(r'(?:T|P|UI|JI|IU)\d+', tag) else 'drainage' if tag == 'JV' else
                       'water' if tag in {'KV', 'LV', 'LVK'} else 'power' if tag == 'S0301' else 'data' if tag.startswith('D0') else 'other')
            title = {'KV': 'Cold domestic water', 'LV': 'Hot domestic water', 'LVK': 'Hot water circulation', 'JV': 'Wastewater', 'S0301': 'Electrical power distribution'}.get(tag, 'Ventilation' if service == 'ventilation' else 'Model system')
            result.append((tag, service, f'{title} · {tag}'))
    return result


def mesh_points(data, identifiers):
    collected = defaultdict(list)
    building = json.loads((data/'building.json').read_text(encoding='utf-8'))
    for chunk in building['chunks']:
        if chunk['systemId'] != 'hvac':
            continue
        raw = (data/'models'/Path(chunk['url']).name).read_bytes()
        size, = struct.unpack_from('<I', raw, 12)
        doc = json.loads(raw[20:20+size]); binary = raw[28+size:]
        for node in doc['nodes']:
            identifier = node.get('extras', {}).get('entityId')
            if identifier not in identifiers:
                continue
            assert not any(k in node for k in ['matrix','translation','rotation','scale']), 'Expected baked coordinates'
            for primitive in doc['meshes'][node['mesh']]['primitives']:
                a = doc['accessors'][primitive['attributes']['POSITION']]; v = doc['bufferViews'][a['bufferView']]
                assert a['componentType'] == 5126 and a['type'] == 'VEC3'
                points = np.ndarray((a['count'],3),dtype='<f4',buffer=binary,offset=v.get('byteOffset',0)+a.get('byteOffset',0),strides=(v.get('byteStride',12),4)).copy()
                collected[identifier].append(points)
    return {k: np.unique(np.round(np.concatenate(v),5),axis=0) for k,v in collected.items()}


def end_rings(points):
    center = points.mean(axis=0)
    values, vectors = np.linalg.eigh((points-center).T @ (points-center))
    if values[-1] < 1e-12 or values[-1] < 1.7 * max(values[-2],1e-12):
        return []
    axial = (points-center) @ vectors[:,-1]; span = float(np.ptp(axial))
    if span < .035:
        return []
    rings = [points[np.abs(axial-extreme) <= max(.001,span*.001)] for extreme in (axial.min(),axial.max())]
    return rings if all(len(r)>=3 for r in rings) else []


def sample(points, count=512):
    return points[np.linspace(0,len(points)-1,min(count,len(points)),dtype=int)]


def cells(lo, hi):
    return itertools.product(*(range(int(np.floor(a/.5)),int(np.floor(b/.5))+1) for a,b in zip(lo,hi)))


def build(data):
    building = load_building(data); entities = {e['id']:e for e in building['entities']}
    source_properties = json.loads((data/'model-properties.json').read_text(encoding='utf-8'))
    memberships = {i:channels(e) for i,e in entities.items()}; groups = {i:{x[0] for x in memberships[i]} for i in entities}
    nodes, edges = {}, {}
    def edge(a,b,relation,basis,method,directed=True,**evidence):
        if a == b: return
        if not directed: a,b=sorted([a,b])
        identifier='service_'+hashlib.sha256(f'{a}|{relation}|{b}'.encode()).hexdigest()[:20]
        edges[identifier]={'id':identifier,'source':a,'target':b,'relation':relation,'basis':basis,'directed':directed,
                           'evidence':{'method':method,**evidence},'simulationEligible':False}
    for e in building['entities']:
        attributes = source_properties.get(e['id'], {}).get('sourceAttributes', {})
        property_sets = json.loads(attributes.get('IFC_PropertySets_JSON') or '{}')
        equipment_tag = property_sets.get('FI_Komponentti', {}).get('Laitetunnus', '')
        nodes[e['id']]={'id':e['id'],'label':e['name'],'originalName':e.get('originalName',e['name']),
            'equipmentTag':equipment_tag,'sourceTag':attributes.get('IFC_Tag',''),
            'kind':'Room' if e['kind']=='room' else 'Element','floorId':e['floorId'],'discipline':e['systemId'],
            'ifcType':e['ifcType'],'ifcGlobalId':e.get('ifcGlobalId'),'center':e['center'],'networks':sorted(groups[e['id']]),
            'serviceTypes':sorted({x[1] for x in memberships[e['id']]}),'isServiceComponent':e['ifcType'] in AIR|WATER or e['systemId']=='electrical'}
        for tag,service,title in memberships[e['id']]:
            network='network_'+tag
            nodes[network]={'id':network,'label':title,'kind':'System','floorId':'all','discipline':e['systemId'],'center':None,'networks':[tag],'serviceTypes':[service],'isServiceComponent':True}
            edge(e['id'],network,'PART_OF_SYSTEM','source_model','Exported system property: membership, not connectivity.',systemTag=tag,sourceFields=['FI_Sijainti/Järjestelmien tunnukset','FI_Sijainti/Järjestelmien nimet'])
    services={i:e for i,e in entities.items() if e['ifcType'] in AIR|WATER}
    geometry=mesh_points(data,set(services))
    rings={i:end_rings(geometry[i]) for i,e in services.items() if e['ifcType'] in SEGMENTS and i in geometry}
    contacts,index={},defaultdict(set)
    for i,points in geometry.items():
        if not groups[i]: continue
        regions=rings.get(i,[]) if entities[i]['ifcType'] in SEGMENTS else [points]
        for region in regions:
            lo,hi=region.min(axis=0)-CONTACT_TOLERANCE,region.max(axis=0)+CONTACT_TOLERANCE
            if np.prod(np.ceil((hi-lo)/.5)+1)>8000: continue
            for key in cells(lo,hi): index[key].add(i)
    for a,endpoints in rings.items():
        for ring in endpoints:
            candidates=set()
            for key in cells(ring.min(axis=0)-CONTACT_TOLERANCE,ring.max(axis=0)+CONTACT_TOLERANCE): candidates.update(index.get(key,set()))
            ranked=[]
            for b in candidates-{a}:
                common=groups[a]&groups[b]
                if not common or bool(entities[a]['ifcType'] in AIR)!=bool(entities[b]['ifcType'] in AIR): continue
                regions=rings.get(b,[]) if entities[b]['ifcType'] in SEGMENTS else [geometry[b]]
                distance=min((float(np.sqrt(((sample(ring,96)[:,None]-sample(region)[None,:])**2).sum(axis=2).min())) for region in regions),default=999)
                if distance<=CONTACT_TOLERANCE: ranked.append((distance,b,common))
            for distance,b,common in sorted(ranked)[:3]:
                pair=tuple(sorted([a,b]))
                if distance<contacts.get(pair,(999,set()))[0]: contacts[pair]=(distance,common)
    adjacent=defaultdict(list)
    for (a,b),(distance,common) in sorted(contacts.items()):
        edge(a,b,'POSSIBLE_CONNECTION','inferred','Shared service channel and segment-end mesh contact; no IFC port evidence.',False,
             distanceMetres=round(distance,5),toleranceMetres=CONTACT_TOLERANCE,systemTags=sorted(common))
        adjacent[a].append(b);adjacent[b].append(a)
    for fan in (e for e in entities.values() if e['ifcType']=='IfcFan'):
        for channel in groups[fan['id']]:
            for terminal in (e for e in entities.values() if e['ifcType']=='IfcAirTerminal' and channel in groups[e['id']]):
                edge(fan['id'],terminal['id'],'POSSIBLE_SYSTEM_FEED','inferred','Fan and terminal share a system tag; intervening path is not established.',systemTag=channel,service='ventilation')
            queue,depth=deque([fan['id']]),{fan['id']:0}
            while queue:
                a=queue.popleft()
                for b in sorted(adjacent[a]):
                    if channel not in groups[b] or b in depth: continue
                    depth[b]=depth[a]+1;queue.append(b);outward=channel.startswith(('T','JI'))
                    edge(a if outward else b,b if outward else a,'INFERRED_FEEDS','inferred','Fan-rooted contact path and supply/extract tag; not measured flow.',systemTag=channel,service='ventilation')
    distance=lambda a,b:sum((x-y)**2 for x,y in zip(a['center'],b['center']))**.5
    boards=[e for e in entities.values() if e['ifcType']=='IfcElectricDistributionBoard' and 'S0301' in groups[e['id']]]
    mains=[e for e in boards if 'pääkeskus' in e.get('originalName',e['name']).casefold()]
    for panel in (e for e in boards if e not in mains):
        ranked=sorted(mains,key=lambda e:distance(e,panel))
        if ranked: edge(ranked[0]['id'],panel['id'],'POSSIBLE_POWER_FEED','inferred','Main/group board classification in S0301; feeder circuit not exported.',service='power',distanceMetres=round(distance(ranked[0],panel),3))
    loads=[e for e in entities.values() if e['ifcType']=='IfcFan' or e['ifcType'] in {'IfcOutlet','IfcLightFixture','IfcSwitchingDevice'} and 'S0301' in groups[e['id']]]
    for load in loads:
        options=sorted([e for e in boards if e['floorId']==load['floorId'] and distance(e,load)<=12],key=lambda e:(distance(e,load),e['id']))
        if not options: continue
        chosen=[e for e in options[:2] if distance(e,load)<=distance(options[0],load)+2]
        for panel in chosen:
            edge(panel['id'],load['id'],'POSSIBLE_POWER_FEED','inferred','Same-floor power board/load proposal ranked by distance; wiring and circuit unknown.',service='power',distanceMetres=round(distance(panel,load),3),ambiguous=len(chosen)>1,missingEvidence='Circuit identifiers or as-built wiring diagram')
    rooms=[e for e in entities.values() if e['kind']=='room'];room_services=defaultdict(set)
    for terminal in (e for e in entities.values() if e['ifcType'] in TERMINALS):
        x,y,z=terminal['center'];candidates=[]
        for room in rooms:
            lo,hi=room['bounds']['min'],room['bounds']['max']
            if room['floorId']==terminal['floorId'] and lo[0]-.15<=x<=hi[0]+.15 and lo[2]-.15<=z<=hi[2]+.15 and lo[1]-.15<=y<=hi[1]+.40: candidates.append(room)
        for room in candidates:
            service=TERMINALS[terminal['ifcType']]
            if service == 'power' and 'S0301' not in groups[terminal['id']]:
                # Telecom outlets and automation devices are not power circuits.
                service = 'data' if any(t.startswith('D0') for t in groups[terminal['id']]) else 'control'
            edge(terminal['id'],room['id'],'POSSIBLE_SERVICE','inferred','Terminal in expanded same-floor room bounds; room geometry and service zone need confirmation.',service=service,ambiguous=len(candidates)>1,planToleranceMetres=.15,ceilingToleranceMetres=.40)
            room_services[room['id']].add(service)
    connected={i for pair in contacts for i in pair};powered={e['target'] for e in edges.values() if e['relation']=='POSSIBLE_POWER_FEED'}
    gaps=[{'entityId':i,'category':'connection','reason':'No compatible segment-end contact reconstructed; not bridged by proximity.'} for i in services if i not in connected]
    gaps += [{'entityId':e['id'],'category':'power','reason':'No same-floor power board proposal within 12 m; circuit unknown.'} for e in loads if e['id'] not in powered]
    for room in rooms:
        for service in ['ventilation','heating','power','water']:
            if service not in room_services[room['id']]: gaps.append({'entityId':room['id'],'category':'room_service','service':service,'reason':'No matching room terminal assigned; service coverage remains unknown.'})
    digest=hashlib.sha256((data/'building.json').read_bytes()+(data/'model-properties.json').read_bytes()).hexdigest()
    return {'version':1,'sourceHash':digest,'nodes':list(nodes.values()),'edges':list(edges.values()),'gaps':gaps,
        'summary':{'modelEntities':len(entities),'rooms':len(rooms),'networks':sum(n['kind']=='System' for n in nodes.values()),'nodes':len(nodes),'edges':len(edges),
                   'relations':dict(Counter(e['relation'] for e in edges.values())),'evidence':dict(Counter(e['basis'] for e in edges.values())),
                   'roomServiceCoverage':{s:sum(s in v for v in room_services.values()) for s in ['ventilation','heating','power','water','drainage']},
                   'unresolved':len(gaps),'geometryConnectedEntities':len(connected),'explicitPortConnections':0,'verifiedCircuitAssignments':0},
        'policy':'System memberships are model facts. Physical links, direction, electrical feeders and room services are proposals. They are excluded from outage simulation until an explicit maintenance service relation is entered.',
        'parameters':{'contactToleranceMetres':CONTACT_TOLERANCE,'maxContactsPerEnd':3,'powerProposalMaxDistanceMetres':12},
        'sources':['data/building.json','data/model-properties.json','data/models/*.glb']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--data',type=Path,default=ROOT/'data');args=parser.parse_args()
    graph=build(args.data.resolve())
    graph['graphHash']=hashlib.sha256(json.dumps({'nodes':sorted(graph['nodes'],key=lambda n:n['id']),'edges':sorted(graph['edges'],key=lambda e:e['id'])},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    (args.data/'service-graph.json').write_text(json.dumps(graph,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps(graph['summary'],indent=2))
