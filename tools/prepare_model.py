"""Read the supplied Rhino model without modifying it; export a mapped web scene.

Run from any directory with the platform virtual environment. GLB meshes retain
entityId extras; metadata retains IFC identifiers and original source bounds.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import time

import numpy as np
import rhino3dm as rhino
import fast_simplification

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source" / "Concrete_Housing_BuildingPermit_Combined.3dm"
SYSTEMS = [
    {"id": "architecture", "name": "Architecture", "color": "#c6c2b4"},
    {"id": "hvac", "name": "HVAC & plumbing", "color": "#16a399"},
    {"id": "electrical", "name": "Electrical", "color": "#dc9f30"},
    {"id": "structural", "name": "Structure", "color": "#8b93a5"},
    {"id": "site", "name": "Site & landscape", "color": "#8daa79"},
]
ALIASES = {"Level_01": "01_Kerros", "Level_02": "02_Kerros", "Level_03": "03_Kerros", "Level_04": "04_Kerros", "Kellari": "Basement", "Perustukset": "Foundations", "Vesikatto": "Roof", "Merenpinta": "Sea_level", "Sea level": "Sea_level"}
LEVELS = {"Foundations": 47.29, "Basement": 49.07, "01_Kerros": 52.0, "02_Kerros": 54.93, "03_Kerros": 58.03, "04_Kerros": 61.13, "Roof": 64.23, "Sea_level": 0.0}


def rounded(value):
    return np.round(np.asarray(value, dtype=float), 6).tolist()


def bounds_of(geometry):
    b = geometry.GetBoundingBox()
    return np.array([[b.Min.X, b.Min.Y, b.Min.Z], [b.Max.X, b.Max.Y, b.Max.Z]], dtype=float)


def convert(points, origin):
    p = np.asarray(points, dtype=float) - origin
    return np.stack((p[..., 0], p[..., 2], -p[..., 1]), axis=-1)


def transformed_bounds(b, origin):
    points = convert(b, origin)
    return {"min": rounded(points.min(axis=0)), "max": rounded(points.max(axis=0))}


def discipline(source):
    if "Terrain" in source:
        return "site"
    return next((v for k, v in (("HVAC", "hvac"), ("ELE_", "electrical"), ("STRUC", "structural")) if k in source), "architecture")


def floor_id(raw, b):
    result = ALIASES.get(raw, raw)
    if result in LEVELS:
        return result, "source storey; equivalent discipline names normalized"
    # Structural IFC has no storeys. Keep geometric assignment explicitly marked.
    z = float((b[0, 2] + b[1, 2]) / 2)
    if z < 48.4:
        return "Foundations", "geometry estimate; source storey missing"
    result = max((k for k, v in LEVELS.items() if k not in ("Foundations", "Sea_level") and v <= z + 0.01), key=lambda k: LEVELS[k], default="Basement")
    return result, "geometry estimate; source storey missing"


def is_room(props):
    if props.get("IFC_Entity") != "IfcSpace":
        return False
    name = props.get("IFC_Name", "")
    return bool(re.match(r"AS-\d+\.\d+", name) or (":" in name and not name.startswith(("CHASE", "SHAFT", "VOLUME", "Pyör", "CARLOT", "BICYCLE"))))


class Glb:
    def __init__(self):
        self.data = bytearray()
        self.doc = {"asset": {"version": "2.0", "generator": "Building Care: read-only Rhino mesh exporter"}, "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [], "materials": [], "accessors": [], "bufferViews": [], "buffers": [], "extensionsUsed": ["KHR_mesh_quantization"], "extensionsRequired": ["KHR_mesh_quantization"]}
        self.materials = {}
        self.triangles = 0

    def accessor(self, values, component_type, kind, target, normalized=False, stride=None):
        while len(self.data) % 4:
            self.data.append(0)
        offset = len(self.data)
        payload = values.tobytes()
        self.data.extend(payload)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(payload), "target": target}
        if stride:
            view["byteStride"] = stride
        index = len(self.doc["bufferViews"])
        self.doc["bufferViews"].append(view)
        a = {"bufferView": index, "byteOffset": 0, "componentType": component_type, "count": len(values), "type": kind}
        if normalized:
            a["normalized"] = True
        if kind == "VEC3" and component_type == 5126:
            a["min"] = values.min(axis=0).astype(float).tolist()
            a["max"] = values.max(axis=0).astype(float).tolist()
        self.doc["accessors"].append(a)
        return len(self.doc["accessors"]) - 1

    def add(self, vertices, normals, triangles, color, entity):
        key = tuple(color)
        if key not in self.materials:
            # Rhino viewport colors are sRGB; glTF baseColorFactor is linear.
            rgb = [v / 255 for v in color[:3]]
            linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
            self.materials[key] = len(self.doc["materials"])
            self.doc["materials"].append({"name": "Rhino " + str(key), "pbrMetallicRoughness": {"baseColorFactor": linear + [1], "metallicFactor": 0.05, "roughnessFactor": 0.83}, "doubleSided": True})
        position = self.accessor(vertices.astype("<f4"), 5126, "VEC3", 34962)
        # Byte normals use four-byte stride as required by KHR_mesh_quantization.
        compact = np.zeros((len(normals), 4), dtype=np.int8)
        compact[:, :3] = np.rint(np.clip(normals, -1, 1) * 127).astype(np.int8)
        normal = self.accessor(compact, 5120, "VEC3", 34962, normalized=True, stride=4)
        indices = triangles.reshape(-1)
        small = len(vertices) <= 65535
        index = self.accessor(indices.astype("<u2" if small else "<u4"), 5123 if small else 5125, "SCALAR", 34963)
        mesh = len(self.doc["meshes"])
        extras = {"entityId": entity["id"], "ifcGlobalId": entity["ifcGlobalId"], "systemId": entity["systemId"], "floorId": entity["floorId"]}
        self.doc["meshes"].append({"name": entity["name"], "extras": extras, "primitives": [{"attributes": {"POSITION": position, "NORMAL": normal}, "indices": index, "material": self.materials[key]}]})
        self.doc["scenes"][0]["nodes"].append(len(self.doc["nodes"]))
        self.doc["nodes"].append({"name": entity["id"], "mesh": mesh, "extras": extras})
        self.triangles += len(triangles)

    def save(self, path):
        while len(self.data) % 4:
            self.data.append(0)
        self.doc["buffers"] = [{"byteLength": len(self.data)}]
        metadata = json.dumps(self.doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        metadata += b" " * (-len(metadata) % 4)
        total = 12 + 8 + len(metadata) + 8 + len(self.data)
        with path.open("wb") as f:
            f.write(struct.pack("<4sII", b"glTF", 2, total))
            f.write(struct.pack("<I4s", len(metadata), b"JSON"))
            f.write(metadata)
            f.write(struct.pack("<I4s", len(self.data), b"BIN\0"))
            f.write(self.data)
        return total


def mesh_arrays(geometry, origin, simplify):
    vertices = np.array([(v.X, v.Y, v.Z) for v in geometry.Vertices], dtype=np.float64)
    faces = np.array(list(geometry.Faces), dtype=np.int32)
    triangles = np.concatenate((faces[:, :3], faces[faces[:, 2] != faces[:, 3]][:, [0, 2, 3]]))
    original = len(triangles)
    reduced = False
    if simplify and original > 10000:
        try:
            target = max(2500, min(8000, original // 3))
            candidate_v, candidate_f = fast_simplification.simplify(vertices, triangles, target_count=target, agg=5)
            # Reject outputs with visibly changed extents. Source bounds stay authoritative.
            drift = max(float(np.abs(candidate_v.min(0) - vertices.min(0)).max()), float(np.abs(candidate_v.max(0) - vertices.max(0)).max()))
            if len(candidate_f) > 0 and drift < 0.025:
                vertices, triangles = candidate_v, candidate_f.astype(np.int32)
                reduced = len(triangles) < original
        except (ValueError, RuntimeError):
            pass
    vertices = convert(vertices, origin)
    if not reduced and len(geometry.Normals) == len(vertices):
        ns = np.array([(v.X, v.Y, v.Z) for v in geometry.Normals], dtype=np.float32)
        normals = np.stack((ns[:, 0], ns[:, 2], -ns[:, 1]), axis=-1)
    else:
        normals = np.zeros_like(vertices)
        face_normals = np.cross(vertices[triangles[:, 1]] - vertices[triangles[:, 0]], vertices[triangles[:, 2]] - vertices[triangles[:, 0]])
        for col in range(3):
            np.add.at(normals, triangles[:, col], face_normals)
    length = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, length, out=np.zeros_like(normals), where=length > 1e-12)
    normals[length[:, 0] <= 1e-12] = [0, 1, 0]
    return vertices, normals, triangles, original, reduced


def prepare(source, output):
    started = time.time()
    output.mkdir(parents=True, exist_ok=True)
    models = output / "models"
    models.mkdir(exist_ok=True)
    print(f"Reading {source.name} ({source.stat().st_size:,} bytes)", flush=True)
    model = rhino.File3dm.Read(str(source))
    if model is None:
        raise RuntimeError("Rhino could not read the source model")
    if model.Settings.ModelUnitSystem != rhino.UnitSystem.Meters:
        raise ValueError("This export profile expects metre source units; do not silently rescale")
    layers = {str(l.Id): l for l in model.Layers}
    paths = {}
    for layer in model.Layers:
        names = [layer.Name]
        parent = str(layer.ParentLayerId)
        while parent in layers:
            names.insert(0, layers[parent].Name)
            parent = str(layers[parent].ParentLayerId)
        paths[layer.Index] = " / ".join(names)
    records, skipped = [], collections.Counter()
    source_types, source_systems = collections.Counter(), collections.Counter()
    for obj in model.Objects:
        p = dict(obj.Attributes.GetUserStrings())
        system = discipline(p.get("IFC_Source", ""))
        source_types[p.get("IFC_Entity", type(obj.Geometry).__name__)] += 1
        source_systems[system] += 1
        layer_path = paths.get(obj.Attributes.LayerIndex, "")
        if not isinstance(obj.Geometry, rhino.Mesh):
            skipped["reference curves"] += 1
            continue
        if "Origin_Markers" in layer_path:
            skipped["origin reference markers"] += 1
            continue
        b = bounds_of(obj.Geometry)
        if not np.isfinite(b).all() or not len(obj.Geometry.Vertices) or not len(obj.Geometry.Faces):
            skipped["empty or nonfinite mesh"] += 1
            continue
        records.append((obj, p, system, b, layer_path))
    physical = [b for _, p, s, b, _ in records if s in ("architecture", "structural") and p.get("IFC_Entity") not in ("IfcSpace", "IfcSite")]
    source_min = np.stack([b[0] for b in physical]).min(0)
    source_max = np.stack([b[1] for b in physical]).max(0)
    origin = np.array([(source_min[0] + source_max[0]) / 2, (source_min[1] + source_max[1]) / 2, source_min[2]])
    entities, groups, full_properties = {}, collections.defaultdict(list), {}
    estimated_floors, missing_ids = 0, 0
    for obj, p, system, b, layer_path in records:
        ifc_id = p.get("IFC_GlobalId", "")
        if not ifc_id:
            missing_ids += 1
        name = p.get("IFC_Name") or obj.Attributes.Name or p.get("IFC_Entity", "Element")
        kind = "room" if is_room(p) else "asset" if system in ("hvac", "electrical") else "element"
        stable = p.get("IFC_Source", "") + "#" + (ifc_id or str(obj.Attributes.Id))
        entity_id = kind + "_" + hashlib.sha1(stable.encode()).hexdigest()[:16]
        floor, method = floor_id(p.get("IFC_Storey", ""), b)
        estimated_floors += int(method.startswith("geometry"))
        psets = json.loads(p.get("IFC_PropertySets_JSON", "{}"))
        external = any(isinstance(v, dict) and v.get("IsExternal") is True for v in psets.values())
        if entity_id not in entities:
            bounds = transformed_bounds(b, origin)
            entity = {"id": entity_id, "name": name, "kind": kind, "ifcGlobalId": ifc_id, "ifcType": p.get("IFC_Entity", "Mesh"), "systemId": system, "floorId": floor, "center": rounded((np.array(bounds["min"]) + bounds["max"]) / 2), "bounds": bounds, "source": "model", "isExternal": external,
                "properties": {"sourceFile": p.get("IFC_Source", ""), "originalStorey": p.get("IFC_Storey", ""), "floorAssignment": method, "layer": layer_path, "sourceObjectIds": [], "tag": p.get("IFC_Tag", ""), "description": p.get("IFC_Description", ""), "geometryRepresentation": "room bounds overlay" if kind == "room" else "source mesh"}}
            # Retain useful source classifications, not a fabricated service topology.
            for section in ("Pset_SpaceCommon", "Pset_SpaceOccupancyRequirements", "Qto_SpaceBaseQuantities", "FI_Sijainti", "FI_Tekninen"):
                if section in psets:
                    entity["properties"][section] = {k: v for k, v in psets[section].items() if k != "id"}
            entities[entity_id] = entity
            full_properties[entity_id] = {"sourceAttributes": p, "sourceBounds": {"min": rounded(b[0]), "max": rounded(b[1])}}
        entity = entities[entity_id]
        entity["properties"]["sourceObjectIds"].append(str(obj.Attributes.Id))
        bb = transformed_bounds(b, origin)
        entity["bounds"]["min"] = np.minimum(entity["bounds"]["min"], bb["min"]).tolist()
        entity["bounds"]["max"] = np.maximum(entity["bounds"]["max"], bb["max"]).tolist()
        entity["center"] = rounded((np.array(entity["bounds"]["min"]) + entity["bounds"]["max"]) / 2)
        if p.get("IFC_Entity") == "IfcSpace":
            skipped["IfcSpace volume: metadata only"] += 1
        else:
            groups[(system, floor)].append((obj, entity))
    entity_list = list(entities.values())
    room_candidates = [e for e in entity_list if e["kind"] == "room" and e["floorId"] == "02_Kerros"]
    preferred = ["AS-1.01", "AS-1.02", "AS-1.05", "AS-1.06"]
    rooms = [next(e for e in room_candidates if e["name"] == name) for name in preferred]
    center = np.mean([e["center"] for e in rooms], axis=0)
    def nearest(types, system):
        options = [e for e in entity_list if e["floorId"] == "02_Kerros" and e["systemId"] == system and e["ifcType"] in types]
        return sorted(options, key=lambda e: (float(np.linalg.norm(np.array(e["center"]) - center)), e["id"]))
    fans = nearest(["IfcFan"], "hvac")
    boards = [e for e in nearest(["IfcElectricDistributionBoard"], "electrical") if "Ryhmäkeskus" in e["name"]]
    selected = fans[:1] + boards[:1] + nearest(["IfcAirTerminal"], "hvac")[:4] + nearest(["IfcLightFixture"], "electrical")[:4]
    floors_used = sorted({e["floorId"] for e in entity_list}, key=lambda f: LEVELS.get(f, 0))
    building = {"model": {"name": source.stem, "sourceFile": source.name, "units": "metres", "coordinateSystem": "Three.js Y-up; local coordinates", "sourceOrigin": rounded(origin), "bounds": transformed_bounds(np.array([source_min, source_max]), origin)}, "floors": [{"id": f, "name": f, "elevation": round(LEVELS.get(f, 0) - origin[2], 4)} for f in floors_used], "systems": SYSTEMS, "chunks": [], "entities": entity_list,
        "demo": {"roomIds": [e["id"] for e in rooms], "assetIds": [e["id"] for e in selected], "note": "Four actual Level_02 / 02_Kerros spaces and nearby actual model devices. Proximity selects demo objects only; service connections and fault propagation are explicit demonstration assumptions, not verified IFC topology."}, "audit": {}}
    original_triangles = exported_triangles = simplified_parts = 0
    print(f"Metadata ready: {len(entity_list)} entities, {sum(e['kind'] == 'room' for e in entity_list)} selectable rooms; {len(groups)} geometry chunks", flush=True)
    for index, ((system, floor), items) in enumerate(sorted(groups.items()), 1):
        glb = Glb()
        before = after = 0
        for obj, entity in items:
            # Preserve all thin MEP components. Only reduce high-detail architecture/site fixtures.
            allow_reduce = system in ("architecture", "site") and entity["ifcType"] in ("IfcSanitaryTerminal", "IfcFurniture", "IfcGeographicElement", "IfcDoor", "IfcRailing")
            vs, ns, ts, count, reduced = mesh_arrays(obj.Geometry, origin, allow_reduce)
            before += count
            after += len(ts)
            simplified_parts += int(reduced)
            color = obj.Attributes.ObjectColor
            if obj.Attributes.ColorSource == rhino.ObjectColorSource.ColorFromLayer:
                color = model.Layers[obj.Attributes.LayerIndex].Color
            glb.add(vs, ns, ts, color, entity)
        name = f"{system}-{floor}"
        file = models / (name + ".glb")
        size = glb.save(file)
        building["chunks"].append({"id": name, "url": "/models/" + file.name, "systemId": system, "floorId": floor, "bytes": size, "meshCount": len(items), "triangles": after})
        original_triangles += before
        exported_triangles += after
        print(f"[{index}/{len(groups)}] {name}: {len(items)} meshes, {after:,} triangles, {size / 1e6:.2f} MB", flush=True)
    audit = {"sourceFile": source.name, "sourceBytes": source.stat().st_size, "sourceSha256": hashlib.file_digest(source.open("rb"), "sha256").hexdigest(), "sourceUnits": str(model.Settings.ModelUnitSystem), "sourceObjectCount": len(model.Objects), "sourceLayerCount": len(model.Layers), "sourceTypes": dict(source_types), "sourceSystems": dict(source_systems), "entityCount": len(entities), "roomCount": sum(e["kind"] == "room" for e in entity_list), "assetCount": sum(e["kind"] == "asset" for e in entity_list), "missingIfcIdCount": missing_ids, "geometricallyAssignedFloorMeshParts": estimated_floors, "skippedGeometry": dict(skipped), "originalExportableTriangles": original_triangles, "exportedTriangles": exported_triangles, "simplifiedMeshParts": simplified_parts, "exportedBytes": sum(c["bytes"] for c in building["chunks"]), "sourceOrigin": rounded(origin), "coordinateTransform": "Subtract sourceOrigin in source metres, then (x,y,z) -> (x,z,-y). Positive determinant rotation, winding preserved.", "floorAliases": ALIASES, "roomSelection": "Named IfcSpace rooms only. Aggregate storey/apartment volumes, clearance circles, shafts, parking and chases excluded from selectable rooms; all spaces retain metadata.", "geometryPolicy": "Source meshes with normals quantized to signed normalized bytes. High-detail architecture/site fixtures over 10,000 triangles may be simplified; accept only bounding-extents deviation below 25 mm. MEP mesh detail is retained. Room overlays use source bounds, not opaque space meshes.", "limitations": ["No electrical feed or HVAC service topology was verified in the source; demo connections must be labelled assumptions.", "Structural objects without source storeys use explicitly labelled geometric floor assignment.", "Geometry bounds are axis aligned; room overlays approximate rotated or irregular space outlines.", "Stored property-set quantities retain their source units and are not automatically interpreted as metres."], "elapsedSeconds": round(time.time() - started, 1)}
    building["audit"] = {k: v for k, v in audit.items() if k not in ("sourceTypes", "sourceSystems", "floorAliases")}
    for filename, value in (("building.json", building), ("model-audit.json", audit), ("model-properties.json", full_properties)):
        (output / filename).write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Complete: {audit['exportedBytes'] / 1e6:.2f} MB geometry in {audit['elapsedSeconds']} seconds", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    prepare(args.source.resolve(), args.output.resolve())
