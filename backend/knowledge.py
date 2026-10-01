"""Demo knowledge provider; replace its interface with Neo4j in a later stage."""

import json
from functools import lru_cache
from .naming import apply_names
from collections import deque
from pathlib import Path
from typing import Protocol

import networkx as nx


ASSUMPTION = {
    "id": "demo-service-topology",
    "text": "Teaching assumption: the first two selected demo rooms share the selected "
            "HVAC unit and electrical branch; the branch supplies that HVAC unit. "
            "Service connections are not verified from model geometry or IFC attributes.",
    "source": "Explicit demonstration assumption; requires as-built verification",
}

DEMO_KNOWLEDGE = {
    "provenance": "Built-in prototype demonstration rules. No Gephi or Neo4j inference is active.",
    "nodes": [
        {"id": "demo-filter", "label": "Restricted filter", "kind": "hypothesis", "source": "Prototype teaching rule"},
        {"id": "demo-fan", "label": "Fan or controller fault", "kind": "hypothesis", "source": "Prototype teaching rule"},
        {"id": "demo-airflow", "label": "Low ventilation airflow", "kind": "symptom", "source": "Prototype teaching rule"},
        {"id": "demo-overload", "label": "Electrical overload", "kind": "hypothesis", "source": "Prototype teaching rule"},
        {"id": "demo-short", "label": "Short circuit fault", "kind": "hypothesis", "source": "Prototype teaching rule"},
        {"id": "demo-trip", "label": "Protective breaker trip", "kind": "symptom", "source": "Prototype teaching rule"},
        {"id": "demo-supply", "label": "Electrical power supply interruption", "kind": "symptom", "source": "Prototype teaching rule"},
    ],
    "edges": [
        {"id": "demo-edge-filter", "source": "demo-filter", "target": "demo-airflow", "relation": "may_cause", "provenance": "Unvalidated demonstration rule"},
        {"id": "demo-edge-fan", "source": "demo-fan", "target": "demo-airflow", "relation": "may_cause", "provenance": "Unvalidated demonstration rule"},
        {"id": "demo-edge-overload", "source": "demo-overload", "target": "demo-trip", "relation": "may_cause", "provenance": "Unvalidated demonstration rule"},
        {"id": "demo-edge-short", "source": "demo-short", "target": "demo-trip", "relation": "may_cause", "provenance": "Unvalidated demonstration rule"},
        {"id": "demo-edge-supply", "source": "demo-trip", "target": "demo-supply", "relation": "may_cause", "provenance": "Unvalidated demonstration rule"},
    ],
    "sources": [{"id": "demo-knowledge", "text": "The prototype demonstrates hypotheses for low airflow and interrupted electrical supply. Rules need domain validation before operational use.",
                 "source": "Project demonstration dataset; no external knowledge service connected"}],
}


class KnowledgeProvider(Protocol):
    """Boundary for a future Neo4j-backed provider. No Neo4j connection is made in v1."""

    graph: nx.MultiDiGraph
    topology: nx.DiGraph
    entities: dict
    demo_rooms: list[str]
    hvac_id: str | None
    electrical_id: str | None

    def evidence(self, keywords: list[str]) -> list[dict]: ...

    def summary(self) -> dict: ...


def load_building(data_dir: Path):
    path = data_dir / "building.json"
    if not path.is_file():
        return None
    return _named_building(str(path.resolve()), path.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _named_building(path, stamp):
    return apply_names(json.loads(Path(path).read_text(encoding="utf-8-sig")))


class DemoKnowledgeProvider:
    def __init__(self, data_dir: Path, building: dict):
        self.building = building
        self.entities = {e["id"]: e for e in building["entities"]}
        path = data_dir / "demo-knowledge.json"
        self.document = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else DEMO_KNOWLEDGE
        self.graph = nx.MultiDiGraph()
        for node in self.document.get("nodes", []):
            if node.get("id"):
                self.graph.add_node(str(node["id"]), **node)
        for index, edge in enumerate(self.document.get("edges", [])):
            if edge.get("source") in self.graph and edge.get("target") in self.graph:
                self.graph.add_edge(edge["source"], edge["target"], key=edge.get("id", str(index)), **edge)
        self.sources = {str(s["id"]): s for s in self.document.get("sources", []) if "id" in s}
        room_ids = building.get("demo", {}).get("roomIds", [])
        self.demo_rooms = [rid for rid in room_ids if rid in self.entities
                           and self.entities[rid].get("kind") == "room"][:4]
        asset_ids = building.get("demo", {}).get("assetIds", [])
        assets = [self.entities[a] for a in asset_ids if a in self.entities]
        self.hvac_id = next((a["id"] for a in assets if a.get("systemId") == "hvac"), None)
        self.electrical_id = next((a["id"] for a in assets if a.get("systemId") == "electrical"), None)
        self.topology = nx.DiGraph()
        for room_id in self.demo_rooms[:2]:
            self.topology.add_node(room_id, kind="room")
            if self.hvac_id:
                self.topology.add_edge(self.hvac_id, room_id, requires="ventilation_loss",
                                       produces="ventilation_loss", reason="Assumed HVAC service connection")
            if self.electrical_id:
                self.topology.add_edge(self.electrical_id, room_id, requires="power_loss",
                                       produces="power_loss", reason="Assumed electrical branch service connection")
        if self.hvac_id and self.electrical_id:
            self.topology.add_edge(self.electrical_id, self.hvac_id, requires="power_loss",
                                   produces="ventilation_loss", reason="Assumed branch supplies the HVAC unit")

    def evidence(self, keywords: list[str]):
        """Retrieve one-hop graph paths without interpreting classification as causation."""
        matched = []
        for node_id, node in self.graph.nodes(data=True):
            label = str(node.get("label", ""))
            if any(word.casefold() in label.casefold() for word in keywords):
                matched.append((node_id, node))
        results = []
        for node_id, node in matched[:3]:
            source = str(node.get("source") or "Prototype demonstration knowledge")
            results.append({"id": f"kg-node-{node_id}", "text": str(node.get("label", node_id)), "source": source})
            for start, end, key, edge in list(self.graph.out_edges(node_id, keys=True, data=True))[:2]:
                relation = edge.get("relation", "unspecified relation")
                start_label = self.graph.nodes[start].get("label", start)
                end_label = self.graph.nodes[end].get("label", end)
                results.append({"id": f"kg-edge-{edge.get('id', key)}",
                                "text": f"{start_label} —[{relation}]→ {end_label}. "
                                        "Demonstration relationship; applicability requires checking.",
                                "source": str(edge.get("provenance") or source)})
        for source in self.sources.values():
            combined = f"{source.get('text', '')} {source.get('source', '')}".casefold()
            if any(word.casefold() in combined for word in keywords):
                results.append({"id": str(source["id"]), "text": str(source.get("text", "")),
                                "source": str(source.get("source", "Project reference"))})
        return dedupe(results)[:10]

    def summary(self):
        return {"backend": "demo", "nodeCount": self.graph.number_of_nodes(), "edgeCount": self.graph.number_of_edges(),
                "sourceCount": len(self.sources), "sources": list(self.sources.values()),
                "provenance": self.document.get("provenance", "Prototype demonstration rules"),
                "topology": {"roomIds": self.demo_rooms[:2], "hvacAssetId": self.hvac_id,
                             "electricalAssetId": self.electrical_id, "assumption": ASSUMPTION},
                "limitations": ["Neo4j is a reserved integration interface; this prototype uses demonstration rules only.",
                                "Classification edges are retrieved as context, never used as fault propagation rules.",
                                "Model geometry does not verify equipment service relationships."]}


def get_provider(data_dir: Path, building: dict) -> KnowledgeProvider:
    """Future provider selection is isolated here; configured credentials never imply connection."""
    return DemoKnowledgeProvider(data_dir, building)


def dedupe(items: list[dict]):
    return list({item["id"]: item for item in items}.values())


def propagate(graph: nx.DiGraph, start: str, state: str, entities: dict):
    """Conditional breadth-first traversal; state-aware visited set safely handles cycles."""
    queue = deque([(start, state, [start], [])])
    visited = set()
    rooms, assets, paths = set(), set(), []
    while queue:
        node, current, path, reasons = queue.popleft()
        if (node, current) in visited:
            continue
        visited.add((node, current))
        if node in entities:
            if entities[node].get("kind") == "room":
                rooms.add(node)
            else:
                assets.add(node)
        if len(path) > 1:
            paths.append({"nodes": path, "reason": "; ".join(reasons)})
        if node not in graph:
            continue
        for target, edge in graph[node].items():
            if edge.get("requires") == current:
                queue.append((target, edge.get("produces", current), path + [target],
                              reasons + [edge.get("reason", "Configured dependency")]))
    return {"affectedRoomIds": sorted(rooms), "affectedAssetIds": sorted(assets),
            "paths": paths, "explanation": ""}
