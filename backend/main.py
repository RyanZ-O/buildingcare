"""Run from project root: python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000."""

import io
import os
import re
import warnings
import copy
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from starlette.middleware.gzip import GZipMiddleware

from . import chat, investigation, resident, service_graph
from .engine import analyse, now, simulate
from .knowledge import dedupe, get_provider, load_building
from .schemas import AnalysisRequest, ChatRequest, SimulationRequest, StatusUpdate
from .storage import Store
from . import elements, kg, recognition
from .graph_analysis import analyse_graph
from .planning import plans, simulate_plan
from .schemas import LocateRequest, LocationUpdate, TopologyLink, BindingRequest, VisionRequest, InspectionRequest, ResidentRequest

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "backend" / ".env")
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTO_PIXELS = 40_000_000
PHOTO_TYPES = {"image/jpeg": ("JPEG", ".jpg"), "image/png": ("PNG", ".png"),
               "image/webp": ("WEBP", ".webp")}


def create_app(data_dir: str | Path | None = None):
    directory = Path(data_dir or os.getenv("MAINTENANCE_DATA_DIR") or ROOT / "data").resolve()
    uploads = directory / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    store = Store(directory / "maintenance.sqlite3")
    api = FastAPI(title="Building Maintenance Workbench", version="3.0.0")
    api.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=3)
    api.state.store = store
    api.state.data_dir = directory

    def building():
        result = load_building(directory)
        if result is None:
            raise HTTPException(503, "Building model is not ready. Run tools/prepare_model.py to generate data/building.json and model assets.")
        return result

    def knowledge():
        return get_provider(directory, building())

    def current_analysis(issue):
        result = store.analysis(issue['id'])
        return result if result and result.get('locationRevision', 0) == issue.get('locationRevision', 0) else None

    def validate_asset(asset_id, model):
        if asset_id and not any(e['id'] == asset_id and e['kind'] != 'room' for e in model['entities']):
            raise HTTPException(422, 'Select a valid model element.')

    def issue_or_404(issue_id: str):
        issue = store.issue(issue_id)
        if issue is None:
            raise HTTPException(404, "Issue not found.")
        return issue

    def get_report(issue_id: str, simulation_id: str | None = None):
        issue = issue_or_404(issue_id)
        analysis = current_analysis(issue)
        # A report must never combine a fresh diagnosis with a stale scenario.
        simulations = store.simulations(issue_id)
        if simulation_id is not None:
            simulation = next((s for s in simulations if s["id"] == simulation_id and analysis
                               and s["analysisId"] == analysis["id"]), None)
            if simulation is None:
                raise HTTPException(422, "Selected simulation must belong to this issue and its latest analysis.")
        else:
            simulation = next((s for s in simulations if analysis and s["analysisId"] == analysis["id"]), None)
        sources = dedupe((analysis or {}).get("sources", []) + (simulation or {}).get("sources", []))
        limitations = list((analysis or {}).get("limitations", []))
        limitations.extend((simulation or {}).get("assumptions", []))
        if analysis is None:
            limitations.append("No root-cause analysis has been run for this issue.")
        if simulation is None:
            limitations.append("No scenario has been run for the current analysis.")
        return {"issue": issue, "analysis": analysis, "simulation": simulation,
                "comparisons": [s for s in simulations if analysis and s["analysisId"] == analysis["id"]],
                "identifications": store.identifications(issue_id),
                "sources": sources, "limitations": list(dict.fromkeys(limitations))}

    @api.get("/api/building")
    def read_building():
        return building()

    @api.get("/api/config")
    def read_config():
        snapshot = kg.load_snapshot(directory)
        health = kg.connection_status(snapshot.document['sourceHash']) if snapshot else {'connected': False, 'importedNodes': 0}
        return {"llmConfigured": chat.configured(), "modelReady": (directory / "building.json").is_file(),
                "llmModel": chat.llm_settings()[2] or None,
                "visionConfigured": all(recognition.settings()),
                "knowledgeBackend": ('neo4j' if kg.neo4j_enabled() else 'neo4j-csv-snapshot') if snapshot else 'demo',
                "neo4jConfigured": all(os.getenv(name, "").strip() for name in
                                       ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")),
                "neo4jConnected": health['connected'],
                "neo4jDatasetReady": bool(snapshot and health['importedNodes'] == len(snapshot.nodes))}

    @api.get("/api/issues")
    def list_issues():
        return store.issues()

    @api.post("/api/issues", status_code=201)
    async def create_issue(
        roomId: Annotated[str, Form(min_length=1, max_length=200)],
        system: Annotated[Literal["hvac", "electrical"], Form()],
        title: Annotated[str, Form(min_length=1, max_length=200)],
        description: Annotated[str, Form(min_length=1, max_length=10000)],
        occurredAt: Annotated[str | None, Form(max_length=100)] = None,
        assetId: Annotated[str | None, Form(max_length=200)] = None,
        locationDetail: Annotated[str, Form(max_length=1000)] = '',
        photos: list[UploadFile] | None = File(default=None),
    ):
        if not title.strip() or not description.strip():
            raise HTTPException(422, "Title and description must contain text.")
        model = building()
        validate_asset(assetId, model)
        if not any(e["id"] == roomId and e["kind"] == "room" for e in model["entities"]):
            raise HTTPException(422, "Select a valid room from the building model.")
        if occurredAt:
            try:
                parsed = datetime.fromisoformat(occurredAt.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    # Browser datetime-local is an explicit local wall-clock time.
                    occurredAt = parsed.astimezone().isoformat()
            except ValueError:
                raise HTTPException(422, "occurredAt must be an ISO date and time.") from None
        files = photos or []
        if len(files) > 5:
            raise HTTPException(422, "Upload at most five photos.")
        prepared = []
        for upload in files:
            if upload.content_type not in PHOTO_TYPES:
                raise HTTPException(422, "Photos must be JPEG, PNG or WebP images.")
            content = await upload.read(MAX_PHOTO_BYTES + 1)
            if len(content) > MAX_PHOTO_BYTES:
                raise HTTPException(413, "Each photo must be at most 10 MB.")
            expected_format, extension = PHOTO_TYPES[upload.content_type]
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(content)) as image:
                        if image.format != expected_format or image.width * image.height > MAX_PHOTO_PIXELS:
                            raise ValueError("Unsupported image dimensions or format")
                        image.verify()
                    with Image.open(io.BytesIO(content)) as image:
                        image.load()  # Verify the pixel payload, not merely the header.
            except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
                    Image.DecompressionBombError, Image.DecompressionBombWarning):
                raise HTTPException(422, "One photo could not be decoded as a valid JPEG, PNG or WebP image (maximum 40 megapixels).") from None
            photo_id = uuid4().hex
            filename = photo_id + extension
            display_name = Path((upload.filename or filename).replace("\\", "/")).name[:200]
            prepared.append((filename, content, {"id": photo_id, "url": f"/uploads/{filename}", "name": display_name}))
        created_files = []
        issue = {"id": uuid4().hex, "roomId": roomId, "system": system,
                 "assetId": assetId or None, "locationDetail": locationDetail,
                 "locationBasis": "human-selected", "locationRevision": 0,
                 "title": title.strip(), "description": description.strip(),
                 "occurredAt": occurredAt or now(), "createdAt": now(), "status": "submitted",
                 "photos": [photo[2] for photo in prepared], "isDemo": False}
        try:
            for filename, content, _ in prepared:
                destination = uploads / filename
                destination.write_bytes(content)
                created_files.append(destination)
            return store.add_issue(issue)
        except Exception:
            for path in created_files:
                path.unlink(missing_ok=True)
            raise

    @api.get("/api/issues/{issue_id}")
    def read_issue(issue_id: str):
        return issue_or_404(issue_id)

    @api.patch("/api/issues/{issue_id}")
    def update_issue(issue_id: str, request: StatusUpdate):
        result = store.update_status(issue_id, request.status)
        if result is None:
            raise HTTPException(404, "Issue not found.")
        return result

    @api.post("/api/issues/{issue_id}/analysis")
    def run_analysis(issue_id: str, request: AnalysisRequest):
        issue = issue_or_404(issue_id)
        graph = kg.load_snapshot(directory)
        result = (analyse_graph(issue, request.observations.strip(), building(), graph, store.links() + issue.get('demoTopology', []), store.identifications(issue_id)) if graph else
                  analyse(issue, request.observations.strip(), knowledge()))
        result['locationRevision'] = issue.get('locationRevision', 0)
        return store.add_analysis(result)

    @api.get("/api/issues/{issue_id}/analysis")
    def read_analysis(issue_id: str):
        return current_analysis(issue_or_404(issue_id))

    @api.post("/api/issues/{issue_id}/simulations")
    def run_simulation(issue_id: str, request: SimulationRequest):
        issue = issue_or_404(issue_id)
        analysis = current_analysis(issue)
        if analysis is None or analysis['id'] != request.analysisId:
            raise HTTPException(422, "Use the latest analysis of this issue and its current location.")
        if kg.load_snapshot(directory) and not analysis.get('datasetHash'):
            raise HTTPException(422, 'This saved analysis predates the imported graph. Run Update root cause analysis before creating a new scenario.')
        try:
            result = (simulate_plan(issue, analysis, request.causeId, request.action, request.parameters, building())
                      if analysis.get('datasetHash') else simulate(issue, analysis, request.causeId, request.action, knowledge()))
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        return store.add_simulation(result)

    @api.get("/api/issues/{issue_id}/simulations")
    def read_simulations(issue_id: str):
        issue_or_404(issue_id)
        return store.simulations(issue_id)

    @api.post('/api/issues/{issue_id}/inspections')
    def record_inspection(issue_id: str, request: InspectionRequest):
        analysis = current_analysis(issue_or_404(issue_id))
        if not analysis or analysis['id'] != request.analysisId:
            raise HTTPException(422, 'Use the latest analysis before recording an inspection.')
        try:
            updated = investigation.inspect(analysis, request)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        return store.add_analysis(updated)

    @api.get('/api/issues/{issue_id}/trace')
    def hypothesis_trace(issue_id: str, causeId: str):
        issue = issue_or_404(issue_id)
        analysis = current_analysis(issue)
        candidate = next((c for c in (analysis or {}).get('candidates', []) if c['id'] == causeId), None)
        if not candidate:
            raise HTTPException(422, 'Choose a hypothesis from the current analysis.')
        return investigation.instance_trace(issue, candidate, analysis, building())

    @api.post('/api/resident/chat')
    def resident_chat(request: ResidentRequest):
        if not request.message.strip():
            raise HTTPException(422, 'Please enter a question.')
        return resident.respond(request.message, get_report(request.issueId) if request.issueId else None, building())

    @api.get("/api/issues/{issue_id}/report")
    def read_report(issue_id: str, simulationId: str | None = None):
        return get_report(issue_id, simulationId)

    @api.post("/api/issues/{issue_id}/chat")
    async def assistant_chat(issue_id: str, request: ChatRequest):
        if not request.message.strip():
            raise HTTPException(422, "Message must contain text.")
        return await chat.answer(get_report(issue_id, request.simulationId), request)

    @api.get("/api/knowledge/summary")
    def knowledge_summary():
        snapshot = kg.load_snapshot(directory)
        if not snapshot:
            return knowledge().summary()
        return {'backend': 'neo4j' if kg.neo4j_enabled() else 'neo4j-csv-snapshot',
                'sourceFile': snapshot.document['sourceFile'], 'sourceHash': snapshot.document['sourceHash'],
                **snapshot.document['audit']}

    @api.get('/api/knowledge/graph')
    def knowledge_graph():
        snapshot = kg.load_snapshot(directory)
        if not snapshot:
            raise HTTPException(404, 'No causal knowledge graph has been imported.')
        # Display the entire imported dataset, including isolated nodes. Query results
        # refer to these same stable IDs; this endpoint never invents diagnostic edges.
        return {
            'nodes': [{k: n[k] for k in ('id', 'label', 'kind')} for n in snapshot.nodes.values()],
            'edges': list(snapshot.edges.values()),
            'sourceHash': snapshot.document['sourceHash'],
            'sourceFile': snapshot.document['sourceFile'],
            'scope': 'Complete imported snapshot',
            'queryBackend': 'neo4j' if kg.neo4j_enabled() else 'neo4j-csv-snapshot',
        }

    @api.post('/api/knowledge/connection')
    def verify_neo4j():
        snapshot = kg.load_snapshot(directory)
        if not all(kg.neo4j_settings()):
            raise HTTPException(503, 'Configure the Neo4j URI, username and password in the server .env file first.')
        try:
            with kg.driver() as connection:
                connection.verify_connectivity()
                rows, _, _ = connection.execute_query('MATCH (n:MaintenanceKnowledge {dataset:$dataset}) RETURN count(n) AS count',
                    dataset=snapshot.document['sourceHash'] if snapshot else '', database_=os.getenv('NEO4J_DATABASE', 'neo4j'), routing_='r')
                return {'connected': True, 'importedNodes': rows[0]['count'], 'expectedNodes': len(snapshot.nodes) if snapshot else 0}
        except Exception:
            raise HTTPException(503, 'Neo4j connection check failed. Check server settings and database availability; no credentials are returned.') from None

    @api.get('/api/elements')
    def list_elements(q: str = Query(default='', max_length=300), floor: str = '', system: str = '', roomId: str = '',
                      limit: int = Query(default=40, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        return elements.catalogue(building(), q, floor, system, roomId, limit, offset)

    @api.post('/api/identify')
    def identify_text(request: LocateRequest):
        model = building()
        if not any(e['id'] == request.roomId and e['kind'] == 'room' for e in model['entities']):
            raise HTTPException(422, 'Select a valid room first.')
        return elements.suggest(model, request.roomId, request.system, request.text)

    @api.put('/api/issues/{issue_id}/location')
    def set_location(issue_id: str, request: LocationUpdate):
        issue_or_404(issue_id)
        validate_asset(request.assetId, building())
        return store.update_location(issue_id, request.assetId, request.locationDetail.strip())

    @api.post('/api/issues/{issue_id}/identify')
    async def identify_issue(issue_id: str, request: VisionRequest):
        issue = issue_or_404(issue_id)
        return store.add_identification(await recognition.identify(issue, building(), directory, request.usePhotos))

    @api.get('/api/issues/{issue_id}/identifications')
    def read_identifications(issue_id: str):
        issue_or_404(issue_id)
        return store.identifications(issue_id)

    @api.post('/api/issues/{issue_id}/bindings')
    def bind_candidate(issue_id: str, request: BindingRequest):
        issue = issue_or_404(issue_id)
        analysis = current_analysis(issue)
        if not analysis or analysis['id'] != request.analysisId:
            raise HTTPException(422, 'Use the latest analysis for this issue.')
        validate_asset(request.assetId, building())
        updated = copy.deepcopy(analysis)
        candidate = next((c for c in updated['candidates'] if c['id'] == request.causeId), None)
        if not candidate:
            raise HTTPException(422, 'Candidate is not part of this analysis.')
        if candidate.get('assetId') != request.assetId and candidate.get('inspection'):
            candidate['inspection'] = {'id': uuid4().hex, 'status': 'untested', 'note': 'Component association changed; inspect the new component.', 'createdAt': now()}
            candidate.setdefault('inspectionHistory', []).append(candidate['inspection'])
        candidate.update(assetId=request.assetId, assetIds=[request.assetId], mappingBasis='Human-bound hypothesis: ' + request.reason)
        evidence = {'id': 'binding-' + uuid4().hex, 'text': f"{request.causeId} associated with {request.assetId}: {request.reason}",
                    'source': 'Maintenance-entered hypothesis binding; not confirmation of the cause'}
        candidate['evidence'].append(evidence)
        updated['sources'].append(evidence)
        updated.update(id=uuid4().hex, createdAt=now(), topologySnapshot=store.links() + issue.get('demoTopology', []))
        return store.add_analysis(updated)

    @api.get('/api/issues/{issue_id}/plans')
    def available_plans(issue_id: str, causeId: str):
        analysis = current_analysis(issue_or_404(issue_id))
        candidate = next((c for c in (analysis or {}).get('candidates', []) if c['id'] == causeId), None)
        if not candidate:
            raise HTTPException(422, 'Select a candidate from the latest analysis.')
        return {'plans': plans(candidate), 'basis': 'Editable planning templates; not part of the supplied causal KG.'}

    @api.get('/api/topology')
    def read_topology():
        return store.links()

    @api.post('/api/topology', status_code=201)
    def add_topology(request: TopologyLink):
        model = {e['id']: e for e in building()['entities']}
        if request.sourceId not in model or request.targetId not in model or request.sourceId == request.targetId:
            raise HTTPException(422, 'Choose two different existing model objects.')
        if model[request.sourceId]['kind'] == 'room':
            raise HTTPException(422, 'A service link must start at an element, not a room.')
        if request.relation == 'SERVES' and model[request.targetId]['kind'] != 'room':
            raise HTTPException(422, 'SERVES must target a room.')
        if request.relation != 'SERVES' and model[request.targetId]['kind'] == 'room':
            raise HTTPException(422, 'Use SERVES when the target is a room.')
        if not request.note.strip() or len(request.note.strip()) < 5:
            raise HTTPException(422, 'Provide the relationship evidence or assumption.')
        identity = '|'.join([request.sourceId, request.targetId, request.relation, request.requires, request.produces])
        return store.put_link({'id': 'link-' + hashlib.sha256(identity.encode()).hexdigest()[:20],
                               **request.model_dump(), 'createdAt': now()})

    @api.delete('/api/topology/{link_id}')
    def delete_topology(link_id: str):
        store.delete_link(link_id)
        return {'deleted': True}

    @api.get('/api/service-graph')
    def read_service_graph():
        graph = service_graph.load(directory)
        if graph is None:
            raise HTTPException(503, 'Run tools/build_service_graph.py to prepare the building service graph.')
        return graph

    @api.get('/api/service-graph/download')
    def download_service_graph():
        graph = read_service_graph()
        return JSONResponse(graph, headers={'Content-Disposition': 'attachment; filename="building-service-graph.json"'})

    @api.post('/api/demo/case-study')
    def seed_case_study():
        from .case_study import create_case
        try:
            return store.add_issue(create_case(building()))
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @api.post("/api/demo/seed")
    def seed_demo():
        context = knowledge()
        if len(context.demo_rooms) < 2:
            raise HTTPException(503, "The prepared model needs at least two demo rooms before demo issues can be created.")
        result = []
        for system, room_id, title, description in [
            ("hvac", context.demo_rooms[0], "[DEMO] Low airflow in room",
             "Demonstration report: the ventilation seems weak and the room feels stuffy. No root cause is confirmed."),
            ("electrical", context.demo_rooms[1], "[DEMO] Lighting and equipment power interruption",
             "Demonstration report: lights and some equipment appear to have lost power. Please investigate the affected circuit."),
        ]:
            issue_id = uuid5(NAMESPACE_URL, f"maintenance-demo-v1:{system}:{room_id}").hex
            issue = {"id": issue_id, "roomId": room_id, "system": system, "title": title,
                     "description": description, "occurredAt": now(), "createdAt": now(),
                     "status": "submitted", "photos": [], "isDemo": True}
            result.append(store.add_issue(issue))
        return result

    @api.get("/uploads/{filename}")
    def read_upload(filename: str):
        if not re.fullmatch(r"[0-9a-f]{32}\.(?:jpg|png|webp)", filename):
            raise HTTPException(404, "Photo not found.")
        path = uploads / filename
        if not path.is_file():
            raise HTTPException(404, "Photo not found.")
        return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})

    api.mount("/project-docs", StaticFiles(directory=ROOT / "docs" / "project", html=True, check_dir=False), name="project-docs")

    api.mount("/models", StaticFiles(directory=directory / "models", check_dir=False), name="models")
    frontend = ROOT / "frontend" / "dist"

    @api.get("/{path:path}", include_in_schema=False)
    def frontend_page(path: str):
        if path == "api" or path.startswith(("api/", "uploads/")):
            raise HTTPException(404, "Not found.")
        candidate = (frontend / path).resolve()
        if not candidate.is_relative_to(frontend.resolve()):
            raise HTTPException(404, "Not found.")
        if candidate.is_file():
            return FileResponse(candidate)
        # Only known application routes receive the SPA entry point.
        if path not in ("", "report", "resident", "systems") and not re.fullmatch(r"(?:reports|investigate)/[0-9a-f]{32}", path):
            raise HTTPException(404, "Not found.")
        index = frontend / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(status_code=503, content={"detail": "Frontend has not been built. Run npm install and npm run build inside frontend."})

    return api


app = create_app()
