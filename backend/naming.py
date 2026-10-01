"""Presentation aliases; original IFC identities, coordinates and properties stay intact."""
import re

FLOORS = {'Sea_level': 'Sea-level datum', 'Foundations': 'Foundations', 'Basement': 'Basement',
          '01_Kerros': 'Level 01', '02_Kerros': 'Level 02', '03_Kerros': 'Level 03',
          '04_Kerros': 'Level 04', 'Roof': 'Roof'}
TYPES = {'IfcPipeSegment': 'Pipe segment', 'IfcPipeFitting': 'Pipe fitting', 'IfcDuctSegment': 'Duct segment',
         'IfcDuctFitting': 'Duct fitting', 'IfcAirTerminal': 'Air terminal', 'IfcDuctSilencer': 'Duct silencer',
         'IfcElectricDistributionBoard': 'Electrical distribution board', 'IfcFan': 'Ventilation fan',
         'IfcSpaceHeater': 'Space heater', 'IfcSwitchingDevice': 'Electrical switch', 'IfcOutlet': 'Electrical outlet',
         'IfcWasteTerminal': 'Drainage terminal', 'IfcSanitaryTerminal': 'Sanitary fixture',
         'IfcCableCarrierSegment': 'Cable carrier segment', 'IfcCableCarrierFitting': 'Cable carrier fitting',
         'IfcElectricAppliance': 'Electrical appliance', 'IfcGeographicElement': 'Landscape element',
         'IfcBuildingElementProxy': 'Generic building element', 'IfcSpace': 'Space'}


def service_label(entity):
    loc = entity.get('properties', {}).get('FI_Sijainti', {})
    raw = str(loc.get('Järjestelmien nimet', ''))
    services = []
    for term, label in [('Tuloilma', 'Supply air'), ('Poistoilma', 'Extract air'), ('Jäteilma', 'Exhaust air'),
                        ('Ulkoilma', 'Outdoor air'), ('Raitisilma', 'Outdoor air'),
                        ('Kylmä käyttövesi', 'Domestic cold water'), ('Lämmin käyttövesi, kierto', 'Hot-water circulation'),
                        ('Lämmin käyttövesi', 'Domestic hot water'), ('Lämmitysverkosto paluu', 'Heating return'),
                        ('Lämmitysverkosto', 'Heating distribution'), ('Jätevesiviemäri', 'Wastewater drainage'),
                        ('Pääjakelu', 'AC power distribution'), ('Yleiskaapelointi', 'Structured cabling'),
                        ('Antenniverkko', 'Antenna network'), ('Asennushyllyjärjestelmä', 'Cable tray'),
                        ('Ripustuskiskojärjestelmä', 'Electrical support rail')]:
        if term.casefold() in raw.casefold() and label not in services:
            if label == 'Domestic hot water' and 'Hot-water circulation' in services:
                continue
            if label == 'Heating distribution' and 'Heating return' in services:
                continue
            services.append(label)
    return ' / '.join(services), str(loc.get('Järjestelmien tunnukset', '')).strip()


def apply_names(building):
    building['model']['originalName'] = building['model'].get('originalName', building['model'].get('name', ''))
    building['model']['name'] = 'Building 1'
    for f in building['floors']:
        f['originalName'] = f.get('originalName', f['name'])
        f['name'] = FLOORS.get(f['id'], f['name'].replace('_', ' ').title())
    floor_names = {f['id']: f['name'] for f in building['floors']}
    for e in building['entities']:
        original = e.setdefault('originalName', e.get('name', ''))
        props = e.get('properties', {})
        e['floorName'] = floor_names.get(e.get('floorId'), 'Unassigned level')
        floor_code = {'Basement': 'B1', 'Roof': 'RF', 'Foundations': 'FD', 'Sea_level': 'DT'}.get(e.get('floorId'), '')
        if not floor_code:
            match = re.match(r'(\d+)_Kerros', e.get('floorId', ''))
            floor_code = 'L' + match[1] if match else 'NA'
        e['displayCode'] = f"B1-{floor_code}-{e['id'].split('_', 1)[-1][:8].upper()}"
        service, tag = service_label(e)
        e['serviceName'], e['serviceTag'] = service, tag
        if e['kind'] == 'room':
            reference = str(props.get('Pset_SpaceCommon', {}).get('Reference', '')).strip()
            base = reference or original.split(':')[0]
            # Source uses English room references. Do not infer bedroom/occupancy from geometry.
            base = base.replace('_', ' ').title().replace('As-', 'AS-')
            if not base or not base.isascii():
                base = 'Room'
            e['name'] = f"{base} · {e['displayCode']}"
            e['namingBasis'] = 'Source space reference and stable model identifier; no inferred room use.'
        else:
            t = e.get('ifcType', '')
            base = TYPES.get(t, re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', t.removeprefix('Ifc')).capitalize() or 'Model element')
            if t == 'IfcElectricDistributionBoard' and 'Structured cabling' in service:
                base = 'Data distribution cabinet'
            prefix = service if service and len(service) < 48 else ('Multi-service ventilation' if t == 'IfcFan' and service else '')
            e['name'] = f"{prefix + ' · ' if prefix else ''}{base} · {tag + ' · ' if tag and len(tag) < 30 else ''}{e['displayCode']}"
            e['namingBasis'] = 'IFC class + translated source service (when recorded) + source tag + stable model identifier.'
        e['locationBasis'] = props.get('floorAssignment', 'Source model floor assignment; service area not inferred')
    return building
