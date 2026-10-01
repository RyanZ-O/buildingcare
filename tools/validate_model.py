"""Validate generated model mappings and binary geometry without Rhino or a browser."""
from __future__ import annotations

import json
from pathlib import Path
import struct

import numpy as np


def validate(data: Path):
    building = json.loads((data / "building.json").read_text(encoding="utf-8"))
    entities = {e["id"]: e for e in building["entities"]}
    assert len(entities) == len(building["entities"]), "duplicate entity IDs"
    assert len(building["demo"]["roomIds"]) == 4
    for rid in building["demo"]["roomIds"]:
        assert entities[rid]["kind"] == "room"
        assert entities[rid]["floorId"] == "02_Kerros"
    expected = {e["id"] for e in entities.values() if e["ifcType"] != "IfcSpace"}
    found = set()
    mesh_count = triangle_count = 0
    for chunk in building["chunks"]:
        raw = (data / "models" / Path(chunk["url"]).name).read_bytes()
        magic, version, length = struct.unpack_from("<4sII", raw)
        assert magic == b"glTF" and version == 2 and length == len(raw) == chunk["bytes"]
        size, kind = struct.unpack_from("<I4s", raw, 12)
        assert kind == b"JSON"
        gltf = json.loads(raw[20:20 + size])
        bsize, bkind = struct.unpack_from("<I4s", raw, 20 + size)
        assert bkind == b"BIN\0" and bsize == gltf["buffers"][0]["byteLength"]
        binary = memoryview(raw)[28 + size:]
        assert len(binary) == bsize
        for view in gltf["bufferViews"]:
            assert view["byteOffset"] % 4 == 0
            assert view["byteOffset"] + view["byteLength"] <= bsize
        def array(index, dims):
            a = gltf["accessors"][index]
            view = gltf["bufferViews"][a["bufferView"]]
            dtype = np.dtype({5120: "i1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[a["componentType"]])
            offset = view["byteOffset"] + a.get("byteOffset", 0)
            stride = view.get("byteStride", dims * dtype.itemsize)
            assert (a["count"] - 1) * stride + dims * dtype.itemsize <= view["byteLength"]
            return np.ndarray((a["count"], dims), dtype=dtype, buffer=binary, offset=offset, strides=(stride, dtype.itemsize))
        for node in gltf["nodes"]:
            entity_id = node["extras"]["entityId"]
            assert entity_id in entities
            entity = entities[entity_id]
            assert entity["ifcType"] != "IfcSpace", "space must not be rendered opaque"
            assert entity["systemId"] == chunk["systemId"]
            assert entity["floorId"] == chunk["floorId"]
            mesh = gltf["meshes"][node["mesh"]]
            assert mesh["extras"]["entityId"] == entity_id
            found.add(entity_id)
            for primitive in mesh["primitives"]:
                positions = array(primitive["attributes"]["POSITION"], 3)
                normals = array(primitive["attributes"]["NORMAL"], 3)
                indices = array(primitive["indices"], 1)
                assert np.isfinite(positions).all()
                assert len(normals) == len(positions)
                assert indices.max() < len(positions) and len(indices) % 3 == 0
                assert np.all(positions.min(0) >= np.array(entity["bounds"]["min"]) - 0.026)
                assert np.all(positions.max(0) <= np.array(entity["bounds"]["max"]) + 0.026)
                normal_lengths = np.linalg.norm(normals.astype(float) / 127, axis=1)
                assert normal_lengths.min() > 0.98 and normal_lengths.max() < 1.02
                triangle_count += len(indices) // 3
                mesh_count += 1
    assert expected == found, f"unmapped geometry: {len(expected - found)}; extra: {len(found - expected)}"
    assert triangle_count == building["audit"]["exportedTriangles"]
    print(json.dumps({"valid": True, "chunks": len(building["chunks"]), "entities": len(entities), "mappedGeometryEntities": len(found), "meshes": mesh_count, "triangles": triangle_count, "rooms": sum(e["kind"] == "room" for e in entities.values()), "demoRooms": [entities[r]["name"] for r in building["demo"]["roomIds"]]}, indent=2))


if __name__ == "__main__":
    validate(Path(__file__).resolve().parents[1] / "data")
