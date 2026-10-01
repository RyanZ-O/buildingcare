"""Reproducible case: real model instances, explicitly assumed service links."""
from uuid import NAMESPACE_URL, uuid5
from .engine import now

ROOMS = ['room_eab06f1e26e2c84f', 'room_110491bcb49e136a', 'room_dc0fa6764f728e32', 'room_70e685f06b5e1f68']
DUCT = 'asset_05050d9591661e63'
FAN = 'asset_153de8eda3c22936'
BOARD = 'asset_3313a248aec6c28f'


def create_case(building):
    entities = {e['id']: e for e in building['entities']}
    if not all(i in entities for i in [DUCT, FAN, BOARD, *ROOMS]):
        raise ValueError('This case requires the original Building 1 model instances.')
    second = next(e['id'] for e in building['entities'] if e['ifcType'] == 'IfcDuctSegment' and e['floorId'] == '02_Kerros' and e.get('serviceTag') == 'T3' and e['id'] != DUCT)
    links = []
    def link(a, b, relation, requires='ventilation_loss', produces='ventilation_loss'):
        links.append({'id': 'case-v3-' + str(len(links)), 'sourceId': a, 'targetId': b, 'relation': relation,
                      'requires': requires, 'produces': produces, 'basis': 'assumption', 'createdAt': now(),
                      'note': 'Case-study teaching assumption only. Source tags support service identity, not verified connectivity or room service. Confined to this demo issue.'})
    link(BOARD, FAN, 'SUPPLIES_POWER', 'power_loss')
    link(FAN, DUCT, 'FEEDS')
    link(FAN, second, 'FEEDS')
    link(DUCT, ROOMS[0], 'SERVES')
    link(DUCT, ROOMS[1], 'SERVES')
    link(second, ROOMS[2], 'SERVES')
    # ROOM 4 is deliberately disconnected as a negative control.
    return {'id': uuid5(NAMESPACE_URL, 'buildingcare-case-v3-airflow').hex, 'roomId': ROOMS[0], 'assetId': DUCT,
            'system': 'hvac', 'title': '[CASE STUDY] Low airflow · Level 02 supply duct',
            'description': 'Demonstration occupant report: low airflow and weak ventilation at the selected supply duct. Compare local obstruction, duct leakage and an upstream fan pressure problem. No site inspection has been performed.',
            'locationDetail': 'Source service tag T3; selected individual duct segment in the model.',
            'locationRevision': 0, 'locationBasis': 'case-study model selection', 'createdAt': now(), 'occurredAt': now(),
            'status': 'submitted', 'photos': [], 'isDemo': True, 'demoTopology': links,
            'demoContext': {'title': 'Building 1 · Low-airflow investigation', 'unaffectedRoomId': ROOMS[3], 'fanId': FAN, 'boardId': BOARD,
                            'note': 'Demonstration report and topology. No measured fault, occupancy, cost or temperature data.'}}
