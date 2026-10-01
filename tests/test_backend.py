import io
import json
from pathlib import Path

import httpx
import networkx as nx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.knowledge import DemoKnowledgeProvider, propagate


def entity(identifier, kind, system="architecture"):
    return {"id": identifier, "name": identifier, "kind": kind, "systemId": system,
            "floorId": "02_Kerros", "ifcGlobalId": f"IFC-{identifier}", "ifcType": "IfcSpace" if kind == "room" else "IfcFlowTerminal",
            "center": [0, 1, 0], "bounds": {"min": [0, 0, 0], "max": [1, 2, 1]},
            "properties": {}, "source": "model"}


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("MAINTENANCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv('KNOWLEDGE_BACKEND', 'snapshot')
    for name in ('VISION_MODEL', 'VISION_BASE_URL', 'VISION_API_KEY'):
        monkeypatch.setenv(name, '')
    building = {
        "model": {"name": "test-real-model", "sourceFile": "fixture.3dm", "units": "metres", "coordinateSystem": "Y-up"},
        "floors": [{"id": "02_Kerros", "name": "02_Kerros", "elevation": 3}],
        "systems": [], "chunks": [],
        "entities": [*[entity(f"r{i}", "room") for i in range(1, 5)],
                     entity("fan", "asset", "hvac"), entity("board", "asset", "electrical")],
        "demo": {"roomIds": ["r1", "r2", "r3", "r4"], "assetIds": ["fan", "board"], "note": "Fixture selection"},
        "audit": {},
    }
    (tmp_path / "building.json").write_text(json.dumps(building), encoding="utf-8")
    (tmp_path / "models").mkdir()
    from backend.main import create_app
    app = create_app(tmp_path)
    return TestClient(app), tmp_path, create_app, building


def submit(client, **extra):
    data = {"roomId": "r1", "system": "hvac", "title": "空调没有风", "description": "昨天晚上开始感觉房间很闷。"}
    data.update(extra)
    response = client.post("/api/issues", data=data)
    assert response.status_code == 201, response.text
    return response.json()


def diagnose(client, issue):
    response = client.post(f"/api/issues/{issue['id']}/analysis", json={"observations": "Fan operating state not yet checked."})
    assert response.status_code == 200, response.text
    return response.json()


def scenario(client, issue, analysis, cause="hvac_fan_fault", action="observe"):
    response = client.post(f"/api/issues/{issue['id']}/simulations", json={
        "analysisId": analysis["id"], "causeId": cause, "action": action})
    assert response.status_code == 200, response.text
    return response.json()


def png_bytes():
    out = io.BytesIO()
    Image.new("RGB", (12, 10), "#007766").save(out, format="PNG")
    return out.getvalue()


def test_persistent_upload_unicode_status_and_restart(app_env):
    client, directory, create_app, _ = app_env
    response = client.post("/api/issues", data={"roomId": "r1", "system": "hvac", "title": "风量不足", "description": "照片作为证据"},
                           files=[("photos", ("../../卧室.png", png_bytes(), "image/png"))])
    assert response.status_code == 201, response.text
    issue = response.json()
    assert issue["isDemo"] is False and issue["photos"][0]["name"] == "卧室.png"
    photo_response = client.get(issue["photos"][0]["url"])
    assert photo_response.status_code == 200 and photo_response.content == png_bytes()
    assert client.patch(f"/api/issues/{issue['id']}", json={"status": "in_progress"}).status_code == 200
    restarted = TestClient(create_app(directory))
    saved = restarted.get(f"/api/issues/{issue['id']}").json()
    assert saved["description"] == "照片作为证据" and saved["status"] == "in_progress"
    assert restarted.get("/api/issues").json() == [saved]
    assert restarted.get(issue["photos"][0]["url"]).content == png_bytes()


def test_upload_validation_has_no_partial_writes(app_env):
    client, directory, _, _ = app_env
    data = {"roomId": "r1", "system": "hvac", "title": "Ventilation", "description": "Low airflow"}
    cases = [
        ([("photos", ("bad.png", b"not a photograph", "image/png"))], 422),
        ([("photos", ("spoof.jpg", png_bytes(), "image/jpeg"))], 422),
        ([("photos", ("bad.svg", b"<svg/>", "image/svg+xml"))], 422),
        ([("photos", ("big.png", b"x" * (10 * 1024 * 1024 + 1), "image/png"))], 413),
        ([("photos", (f"{i}.png", png_bytes(), "image/png")) for i in range(6)], 422),
        ([("photos", ("valid.png", png_bytes(), "image/png")), ("photos", ("invalid.png", b"bad", "image/png"))], 422),
    ]
    for files, expected in cases:
        assert client.post("/api/issues", data=data, files=files).status_code == expected
    assert client.get("/api/issues").json() == []
    assert list((directory / "uploads").iterdir()) == []


@pytest.mark.parametrize("field,value", [("roomId", "fan"), ("roomId", "missing"), ("system", "plumbing"),
                                         ("title", "  "), ("description", "  "), ("occurredAt", "not-date")])
def test_issue_input_validation(app_env, field, value):
    client, *_ = app_env
    data = {"roomId": "r1", "system": "hvac", "title": "Example", "description": "Check this room", field: value}
    assert client.post("/api/issues", data=data).status_code == 422


def test_no_automatic_seed_and_explicit_seed_is_idempotent(app_env):
    client, *_ = app_env
    assert client.get("/api/issues").json() == []
    first = client.post("/api/demo/seed").json()
    second = client.post("/api/demo/seed").json()
    assert first == second and len(first) == 2
    assert {issue["system"] for issue in first} == {"hvac", "electrical"}
    assert all(issue["isDemo"] and issue["title"].startswith("[DEMO]") for issue in first)


def test_candidates_have_provenance_and_no_fake_certainty(app_env):
    client, *_ = app_env
    issue = submit(client)
    analysis = diagnose(client, issue)
    assert len(analysis["candidates"]) == 3
    assert any("Neo4j" in limitation for limitation in analysis["limitations"])
    assert all(c["evidence"] and c["checks"] and "probability" not in c for c in analysis["candidates"])
    assert any(e["id"].startswith("kg-edge-demo-") for e in analysis["sources"])
    assert client.get(f"/api/issues/{issue['id']}/analysis").json() == analysis


def test_conditional_propagation_unrelated_rooms_and_repair(app_env):
    client, *_ = app_env
    issue = submit(client)
    analysis = diagnose(client, issue)
    observe = scenario(client, issue, analysis)
    assert observe["during"]["affectedRoomIds"] == ["r1", "r2"]
    assert observe["during"]["affectedAssetIds"] == ["fan"]
    assert observe["after"]["affectedRoomIds"] == ["r1", "r2"]
    assert any("not verified" in text for text in observe["assumptions"])
    repair = scenario(client, issue, analysis, action="local_repair")
    shutdown = scenario(client, issue, analysis, action="system_shutdown")
    assert repair["during"]["affectedAssetIds"] == ["fan"]
    assert shutdown["during"]["affectedAssetIds"] == ["board", "fan"]
    assert repair["after"]["affectedRoomIds"] == []
    assert shutdown["after"]["affectedRoomIds"] == []
    assert client.get(f"/api/issues/{issue['id']}").json()["status"] == "submitted"


def test_electrical_cascade_and_cross_issue_rejection(app_env):
    client, *_ = app_env
    issue = submit(client, system="electrical", title="Power is out")
    other = submit(client, roomId="r2")
    analysis = diagnose(client, issue)
    result = scenario(client, issue, analysis, cause="electrical_overload")
    assert result["during"]["affectedAssetIds"] == ["board", "fan"]
    assert any(p["nodes"] == ["board", "fan"] for p in result["during"]["paths"])
    assert client.post(f"/api/issues/{other['id']}/simulations", json={"analysisId": analysis["id"],
                       "causeId": "electrical_overload", "action": "observe"}).status_code == 422
    assert client.post(f"/api/issues/{issue['id']}/simulations", json={"analysisId": analysis["id"],
                       "causeId": "invented-cause", "action": "observe"}).status_code == 422


def test_unmapped_room_does_not_claim_missing_topology_is_no_impact(app_env):
    client, *_ = app_env
    issue = submit(client, roomId="r4")
    analysis = diagnose(client, issue)
    assert all(c["assetId"] is None for c in analysis["candidates"])
    result = scenario(client, issue, analysis)
    assert result["during"]["affectedRoomIds"] == ["r4"]
    assert any("wider impacts are unknown" in text for text in result["assumptions"])


def test_cycles_and_mismatched_conditions_do_not_spread():
    graph = nx.DiGraph()
    graph.add_edge("board", "fan", requires="power_loss", produces="ventilation_loss")
    graph.add_edge("fan", "board", requires="ventilation_loss", produces="power_loss")
    graph.add_edge("fan", "r1", requires="ventilation_loss", produces="ventilation_loss")
    graph.add_edge("fan", "r2", requires="flooding", produces="flooding")
    entities = {e["id"]: e for e in [entity("board", "asset"), entity("fan", "asset"), entity("r1", "room"), entity("r2", "room")]}
    result = propagate(graph, "board", "power_loss", entities)
    assert result["affectedRoomIds"] == ["r1"]
    assert result["affectedAssetIds"] == ["board", "fan"]
    assert len(result["paths"]) == 2


def test_report_snapshot_consistency_and_persistence(app_env):
    client, directory, create_app, _ = app_env
    issue = submit(client)
    analysis = diagnose(client, issue)
    result = scenario(client, issue, analysis)
    restarted = TestClient(create_app(directory))
    report = restarted.get(f"/api/issues/{issue['id']}/report").json()
    assert report["analysis"] == analysis and report["simulation"] == result
    newer = diagnose(restarted, issue)
    report = restarted.get(f"/api/issues/{issue['id']}/report").json()
    assert report["analysis"] == newer and report["simulation"] is None
    assert restarted.get(f"/api/issues/{issue['id']}/simulations").json() == [result]


def test_selected_simulation_scopes_report_and_chat(app_env, monkeypatch):
    client, *_ = app_env
    issue = submit(client)
    other = submit(client, roomId="r2")
    analysis = diagnose(client, issue)
    observe = scenario(client, issue, analysis)
    repair = scenario(client, issue, analysis, action="local_repair")
    selected_report = client.get(f"/api/issues/{issue['id']}/report", params={"simulationId": observe["id"]})
    assert selected_report.status_code == 200 and selected_report.json()["simulation"] == observe
    assert client.get(f"/api/issues/{issue['id']}/report").json()["simulation"] == repair
    assert client.get(f"/api/issues/{other['id']}/report", params={"simulationId": observe["id"]}).status_code == 422
    from backend import chat
    captured = {}

    async def fake_answer(report, request):
        captured.update(report)
        return {"answer": "Scoped", "sources": report["sources"], "mode": "llm"}

    monkeypatch.setattr(chat, "answer", fake_answer)
    response = client.post(f"/api/issues/{issue['id']}/chat", json={"message": "Explain this scenario", "simulationId": observe["id"]})
    assert response.status_code == 200 and captured["simulation"] == observe
    diagnose(client, issue)
    assert client.get(f"/api/issues/{issue['id']}/report", params={"simulationId": observe["id"]}).status_code == 422
    assert client.post(f"/api/issues/{issue['id']}/chat", json={"message": "Explain", "simulationId": observe["id"]}).status_code == 422


def test_missing_llm_and_reserved_neo4j_config_are_truthful(app_env, monkeypatch):
    client, *_ = app_env
    config = client.get("/api/config").json()
    assert config["llmConfigured"] is False and config["knowledgeBackend"] == "demo"
    assert config["neo4jConfigured"] is False and config["neo4jConnected"] is False
    for name, value in [("NEO4J_URI", "bolt://example:7687"), ("NEO4J_USERNAME", "neo4j"), ("NEO4J_PASSWORD", "secret")]:
        monkeypatch.setenv(name, value)
    config = client.get("/api/config").json()
    assert config["neo4jConfigured"] is True and config["neo4jConnected"] is False
    assert "secret" not in json.dumps(config)
    issue = submit(client)
    response = client.post(f"/api/issues/{issue['id']}/chat", json={"message": "Why is it hot?"})
    assert response.status_code == 503 and "not configured" in response.json()["detail"]
    assert client.get(f"/api/issues/{issue['id']}").status_code == 200


def test_chat_provider_context_scoped_and_credentials_not_returned(app_env, monkeypatch):
    client, *_ = app_env
    monkeypatch.setenv("LLM_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "hidden-api-key")
    monkeypatch.setenv("LLM_MODEL", "example-model")
    issue = submit(client, title="This issue only")
    other = submit(client, title="OTHER PRIVATE ISSUE")
    diagnose(client, issue)
    seen = {}

    async def fake_post(self, url, **kwargs):
        seen.update({"url": url, **kwargs})
        return httpx.Response(200, request=httpx.Request("POST", url), json={"choices": [{"message": {"content": "Check the current issue evidence."}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = client.post(f"/api/issues/{issue['id']}/chat", json={"message": "Explain", "history": []})
    assert response.status_code == 200
    assert response.json()["mode"] == "llm" and response.json()["sources"]
    assert "hidden-api-key" not in response.text
    messages = json.dumps(seen["json"]["messages"])
    assert "This issue only" in messages and "OTHER PRIVATE ISSUE" not in messages and other["id"] not in messages
    assert "untrusted data" in messages and seen["url"] == "https://provider.example/v1/chat/completions"


def test_chat_provider_failure_preserves_saved_issue(app_env, monkeypatch):
    client, *_ = app_env
    for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.setenv(key, "https://example.test" if key == "LLM_BASE_URL" else "secret")

    async def fail(self, *args, **kwargs):
        raise httpx.ConnectError("provider unavailable with sensitive credentials")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail)
    issue = submit(client)
    response = client.post(f"/api/issues/{issue['id']}/chat", json={"message": "Explain"})
    assert response.status_code == 503 and "sensitive" not in response.text
    assert client.get(f"/api/issues/{issue['id']}").json() == issue


def test_knowledge_provider_ignores_archived_gephi(app_env):
    client, directory, _, building = app_env
    (directory / "knowledge.json").write_text(json.dumps({"nodes": [{"id": "legacy", "label": "GEPhI marker"}]}), encoding="utf-8")
    provider = DemoKnowledgeProvider(directory, building)
    assert "legacy" not in provider.graph
    summary = client.get("/api/knowledge/summary").json()
    assert summary["backend"] == "demo" and summary["nodeCount"] == 7


def test_invalid_status_unknown_api_and_traversal(app_env):
    client, *_ = app_env
    issue = submit(client)
    assert client.patch(f"/api/issues/{issue['id']}", json={"status": "deleted"}).status_code == 422
    assert client.get("/api/not-real").status_code == 404
    assert client.get("/api/issues/missing").status_code == 404
    assert client.get("/uploads/%2e%2e%2fmaintenance.sqlite3").status_code == 404
    assert client.get("/%2e%2e/README.md").status_code == 404
