# Whole-building service graph

Open `/systems`, or choose **Building systems** on the workbench. Filter by floor, service, network, relationship and evidence. Search by component name, equipment tag (for example IVK03), IFC ID or model system tag. Select a component to highlight its neighborhood in both the graph and 3D model; trace upstream or downstream over one to four hops. Contacts with unknown direction are traversed as neighbors, not as evidence of flow. Export JSON includes every node, edge and unresolved item, independent of display filters.

## Data and evidence

The prepared snapshot includes all 10,575 source model entities, 47 system network nodes and 71 selectable rooms. The 81 additional IFC spaces, including shafts, remain in the inventory and can be displayed with **All building components**. They are not counted as occupied rooms.

| Relationship | Count | Basis |
| --- | ---: | --- |
| System membership | 8,018 | Source system properties |
| Pipe / duct contact | 5,754 | Compatible system tags and reconstructed mesh contacts |
| Equipment dependency | 100 | Fan and terminal system tags; intervening path unknown |
| Upstream / downstream | 96 | Ventilation tag convention and connected paths rooted at fans |
| Power supply | 823 | Board type, floor and proximity; circuit assignment unknown |
| Room service | 1,734 | Terminal type and same-floor room bounds |

Source inputs are `data/building.json`, `data/model-properties.json` and the GLB meshes. Heating supply and return share LP101 in the source: the builder separates them using exported Finnish system names. Telecom boards and telecom outlets are excluded from power-feeder assignments.

The export does not retain explicit IFC port connections or usable circuit identifiers. Therefore all physical, directional, electrical and room-service relationships are proposals, with evidence attached to each edge. Membership alone does not prove a connection or equipment flow. Unresolved water/heating direction is left unoriented.

## Reconstruction limits

- Pipe and duct segments use principal-axis end rings. Non-slender segments that do not yield usable ends remain unresolved. Compatible endpoints and fitting/device mesh vertices must be within 25 mm; at most three contact candidates per end are retained. Sampled mesh contacts do not certify a watertight or valid physical connection. Fitting-to-fitting links are not guessed.
- Power loads use compatible same-floor board candidates within 12 m. Close competing boards are marked ambiguous. Main-to-local-board links are hierarchy proposals; no circuit numbers, protection settings or conductor sizes are inferred.
- Room assignments use service terminals rather than pipes passing through a room. Room bounds allow 150 mm in plan and 400 mm above the ceiling; overlapping candidates are marked ambiguous. Bounds are not exact room solids or commissioned service zones.
- Candidate room coverage is ventilation 68/71, heating 56/71, power 71/71, water 49/71 and drainage 40/71. These counts describe terminal proposals, not verified operational coverage. The snapshot retains 1,046 unresolved connection, feeder and room-service items.

All generated edges carry `simulationEligible=false`. The graph is kept separate from `/api/topology`, saved maintenance issues and the diagnostic knowledge graph. Confirmed maintenance service rules must be entered explicitly before use in outage simulations.

## Rebuild and optional Neo4j import

The prepared JSON is included in the repository; the page works with either snapshot or Neo4j diagnostic mode. Rebuilding needs NumPy from the model requirements:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-model.txt
.\.venv\Scripts\python.exe tools/build_service_graph.py
```

To also store the instance graph in a configured, running Neo4j database:

```powershell
.\.venv\Scripts\python.exe tools/import_service_neo4j.py
```

The importer uses `BuildingServiceNode` and a graph-content hash namespace. Reimporting the same graph is idempotent; a changed snapshot has a new namespace. It does not delete diagnostic knowledge or user-entered service rules. The webpage reads the JSON snapshot, so a Neo4j import is optional. API endpoints are `GET /api/service-graph` and `GET /api/service-graph/download`.
