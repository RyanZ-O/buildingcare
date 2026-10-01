"""Check the actual generated model boundary consumed by browser and backend."""
import json
import math
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / 'data' / 'building.json'
pytestmark = pytest.mark.skipif(not MODEL.exists(), reason='Generate the real model before asset checks')


def building():
    return json.loads(MODEL.read_text(encoding='utf-8'))


def test_entity_coordinates_and_identifiers_are_consistent():
    model = building()
    ids = [e['id'] for e in model['entities']]
    assert len(ids) == len(set(ids)), 'Model entity IDs must not collide'
    floors = {f['id'] for f in model['floors']}
    systems = {s['id'] for s in model['systems']}
    for entity in model['entities']:
        assert entity['floorId'] in floors
        assert entity['systemId'] in systems
        lo, hi, center = entity['bounds']['min'], entity['bounds']['max'], entity['center']
        assert len(lo) == len(hi) == len(center) == 3
        assert all(math.isfinite(v) for v in lo + hi + center)
        assert all(a <= c + 1e-5 and c <= b + 1e-5 for a, b, c in zip(lo, hi, center))
        if entity['source'] == 'model':
            assert entity['ifcGlobalId'], f"Missing source mapping: {entity['id']}"


def test_every_glb_object_maps_to_a_real_entity():
    model = building()
    entities = {e['id']: e for e in model['entities']}
    mapped = set()
    for chunk in model['chunks']:
        assert chunk['url'].startswith('/models/')
        path = ROOT / 'data' / chunk['url'].lstrip('/')
        assert path.is_file(), f'Missing model layer: {path}'
        assert path.stat().st_size == chunk['bytes']
        with path.open('rb') as stream:
            magic, version, size = struct.unpack('<4sII', stream.read(12))
            assert magic == b'glTF' and version == 2 and size == path.stat().st_size
            length, kind = struct.unpack('<II', stream.read(8))
            assert kind == 0x4E4F534A
            document = json.loads(stream.read(length))
        for node in document.get('nodes', []):
            if 'mesh' not in node:
                continue
            entity_id = node.get('extras', {}).get('entityId')
            assert entity_id in entities, f'Unmapped mesh in {path.name}'
            entity = entities[entity_id]
            assert entity['systemId'] == chunk['systemId']
            assert entity['floorId'] == chunk['floorId']
            assert entity['kind'] != 'room', 'Opaque room volumes should not occlude the model'
            mapped.add(entity_id)
    assert len(mapped) > 100, 'Expected the actual building rather than placeholder geometry'
    assert any(entities[i]['systemId'] == 'hvac' for i in mapped)
    assert any(entities[i]['systemId'] == 'electrical' for i in mapped)


def test_demo_uses_real_rooms_and_both_systems():
    model = building()
    entities = {e['id']: e for e in model['entities']}
    rooms = [entities[r] for r in model['demo']['roomIds']]
    assert len(rooms) == 4
    assert all(r['kind'] == 'room' and r['source'] == 'model' for r in rooms)
    assert len({r['floorId'] for r in rooms}) == 1
    assert {'hvac', 'electrical'} <= {entities[a]['systemId'] for a in model['demo']['assetIds']}
