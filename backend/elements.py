"""Instance catalogue and explainable bilingual location suggestions."""
import math
import re

TYPE_TERMS = {
    'IfcDuctSegment': ['duct', '风管', '风道', 'kanava'],
    'IfcDuctFitting': ['duct fitting', '风管接头', '风管弯头'],
    'IfcPipeSegment': ['pipe', 'water pipe', '水管', '管段', 'putki'],
    'IfcPipeFitting': ['pipe fitting', 'elbow', '管接头', '弯头'],
    'IfcDamper': ['damper', '风阀'],
    'IfcValve': ['valve', '阀', 'venttiili'],
    'IfcAirTerminal': ['vent', 'diffuser', 'grille', '风口', '出风口'],
    'IfcFan': ['fan', '风机'], 'IfcPump': ['pump', '水泵'],
    'IfcSpaceHeater': ['radiator', 'heater', '暖气', '散热器'],
    'IfcLightFixture': ['light', '灯', '照明'],
    'IfcOutlet': ['socket', 'outlet', '插座'],
    'IfcSwitchingDevice': ['switch', '开关'],
    'IfcElectricDistributionBoard': ['panel', 'breaker', '配电', '断路器'],
    'IfcUnitaryEquipment': ['ahu', 'air handler', '空调机组'],
}
EQUIPMENT_TERMS = {
    'IfcDuctSegment': ['ductwork', 'flexible duct'], 'IfcDuctFitting': ['ductwork', 'flexible duct'],
    'IfcPipeSegment': ['plant system', 'ancillary component'], 'IfcPipeFitting': ['ancillary component'],
    'IfcValve': ['valve'], 'IfcDamper': ['damper'], 'IfcAirTerminal': ['grille', 'diffuser'],
    'IfcFan': ['fan'], 'IfcPump': ['pump'], 'IfcUnitaryEquipment': ['air handling', 'fan coil'],
    'IfcSpaceHeater': ['room/zone'], 'IfcSensor': ['sensor'],
    'IfcElectricDistributionBoard': ['motor/vfd/controls'], 'IfcSwitchingDevice': ['motor/vfd/controls'],
}
SYMPTOMS = [
    (['没有风', '没风', '风量不足', '通风弱', '闷', 'no airflow', 'low airflow', 'weak airflow'], ['airflow', 'low', 'insufficient', 'ventilation']),
    (['漏水', '滴水', 'water leak', 'dripping'], ['water', 'leak', 'leakage', 'condensate']),
    (['漏风', 'air leak'], ['air', 'leakage']),
    (['不冷', '太热', '升温', '温度高', 'too hot', 'not cooling', 'warm'], ['temperature', 'high', 'cooling', 'capacity']),
    (['噪音', '异响', 'noise', 'noisy'], ['noise', 'abnormal']),
    (['震动', '振动', 'vibration'], ['vibration']),
    (['停电', '跳闸', '没电', 'power loss', 'no power', 'trip'], ['power', 'trip', 'voltage', 'electrical']),
    (['堵塞', '堵', 'blocked', 'clog'], ['blocked', 'restriction', 'pressure', 'flow']),
    (['气味', '异味', '臭', 'odour', 'odor'], ['odour', 'odor', 'ventilation']),
]


def expanded_words(text):
    low = text.casefold()
    words = set(re.findall(r'[a-z]{3,}', low)) - {'the', 'and', 'from', 'this', 'room', 'with', 'issue', 'check', 'please'}
    for terms, expansion in SYMPTOMS:
        if any(t in low for t in terms):
            words.update(expansion)
    return words


def system_tag(entity):
    return str(entity.get('properties', {}).get('FI_Sijainti', {}).get('Järjestelmien tunnukset', ''))


def distance_to_room(entity, room):
    if not room:
        return 0.0
    # Bounding-box proximity is a locator only; it never creates a SERVES edge.
    return math.sqrt(sum(max(room['bounds']['min'][i] - entity['center'][i], 0,
                             entity['center'][i] - room['bounds']['max'][i]) ** 2 for i in range(3)))


def catalogue(building, query='', floor='', system='', room_id='', limit=40, offset=0):
    room = next((e for e in building['entities'] if e['id'] == room_id and e['kind'] == 'room'), None)
    terms = query.casefold().split()
    matched_types = {t for t, aliases in TYPE_TERMS.items() if any(a in query.casefold() for a in aliases)} if query else set()
    results = []
    for entity in building['entities']:
        if entity['kind'] == 'room' or (floor and entity['floorId'] != floor) or (system and entity['systemId'] != system):
            continue
        haystack = ' '.join(str(x) for x in (entity['id'], entity['name'], entity.get('originalName', ''), entity['ifcType'], entity.get('ifcGlobalId'),
                                               entity.get('properties', {}).get('tag'), system_tag(entity))).casefold()
        if terms and not all(t in haystack for t in terms) and entity['ifcType'] not in matched_types:
            continue
        results.append({**entity, 'distanceMetres': round(distance_to_room(entity, room), 2), 'systemTag': system_tag(entity)})
    results.sort(key=lambda e: (e['floorId'] != room['floorId'] if room else False, e['distanceMetres'], e['ifcType'], e['id']))
    return {'total': len(results), 'items': results[offset:offset + limit], 'offset': offset,
            'note': 'Distance is to the room bounding box; proximity does not prove connectivity or the location of a defect.'}


def suggest(building, room_id, system, text):
    room = next(e for e in building['entities'] if e['id'] == room_id)
    low = text.casefold()
    types = {t for t, aliases in TYPE_TERMS.items() if any(a in low for a in aliases)}
    results = []
    for entity in building['entities']:
        if entity['kind'] == 'room' or entity['systemId'] != system:
            continue
        identifiers = [entity['id'], entity.get('ifcGlobalId', ''), str(entity.get('properties', {}).get('tag', ''))]
        exact = any(len(x) >= 4 and re.search(r'(?<!\w)' + re.escape(x.casefold()) + r'(?!\w)', low) for x in identifiers)
        name_match = len(entity['name']) > 4 and entity['name'].casefold() in low
        type_match = entity['ifcType'] in types
        if not (exact or name_match or type_match):
            continue
        if not exact and entity['floorId'] != room['floorId']:
            continue
        distance = distance_to_room(entity, room)
        score = (100 if exact else 30 if name_match else 15) - min(distance, 30)
        results.append({'assetId': entity['id'], 'name': entity['name'], 'ifcType': entity['ifcType'],
                        'ifcGlobalId': entity.get('ifcGlobalId'), 'distanceMetres': round(distance, 2), 'score': score,
                        'basis': 'Exact identifier in report' if exact else 'Name/type match, ranked by room proximity; requires selection'})
    results.sort(key=lambda item: (-item['score'], item['assetId']))
    return {'mode': 'text-rules', 'candidates': results[:8], 'symptomTerms': sorted(expanded_words(text)),
            'requiresConfirmation': True, 'note': 'Suggestions are locations to inspect, not confirmed defects. Select a specific element or keep room-level reporting.'}


def equipment_matches(entity, label):
    return bool(entity and any(term in label.casefold() for term in EQUIPMENT_TERMS.get(entity['ifcType'], [])))
