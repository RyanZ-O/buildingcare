# BuildingCare

English | [简体中文](README.zh-CN.md)

A component-level maintenance decision-support platform for residential occupants and maintenance teams. Residents report a room, a specific location, a problem description and photos. Maintenance staff locate the issue in a shared 3D model and causal knowledge graph, investigate possible causes, and compare repair options by cost, duration, affected rooms and comfort impacts.

## Features

- **Resident reporting**: mobile pages, English and Chinese descriptions, photo uploads, and room or individual component selection.
- **3D localization**: a real Rhino model converted to GLB with preserved IFC identifiers; floor, system and component filtering and highlighting.
- **Root-cause investigation**: a node-and-edge knowledge graph, highlighted query paths, selectable candidate causes, inspection records and bindings to actual components.
- **Repair simulation**: observation, local repair, replacement and branch shutdown; comparison of costs, work hours, service interruptions, affected rooms and temperature recovery, with animated impact propagation.
- **Reports and assistance**: reports tied to the current analysis and repair scenario, bilingual interim guidance for residents, and optional maintenance LLM chat and photo recognition through chat-completions-compatible services.

## Project structure

```text
BuildingCare/
├── backend/                  FastAPI APIs, graph queries, investigation, simulation and storage
├── frontend/                 React + TypeScript + Three.js application
├── data/
│   ├── building.json         Building, room and component mappings to the web model
│   ├── model-properties.json Original component properties
│   ├── causal-graph.json     Knowledge graph imported from a Neo4j CSV export
│   └── models/               30 GLB models organized by system and floor
├── source/                   Original Rhino model and Neo4j CSV export
├── tools/                    Model conversion, data import and local Neo4j setup
├── tests/                    API, diagnosis, simulation and model-mapping tests
├── docs/                     Deployment, API and formal project documentation
├── .env.example              Local configuration template
├── requirements*.txt         Runtime, test and model-conversion dependencies
└── *.ps1                     Windows setup, start, restart and stop scripts
```

## Quick start (Windows)

Install Python 3.12, Node.js 22 and Git LFS. The original Rhino model and web GLB models are stored with [Git LFS](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage); download the actual files after cloning.

```powershell
git lfs install
git clone https://github.com/RyanZ-O/buildingcare.git
cd buildingcare
git lfs pull
.\setup.ps1
.\start.ps1
```

| Page | Address |
| --- | --- |
| Maintenance workbench | [localhost:8000](http://localhost:8000/) |
| Resident reporting | [localhost:8000/report](http://localhost:8000/report) |
| Resident assistant | [localhost:8000/resident](http://localhost:8000/resident) |
| Project documentation | [localhost:8000/project-docs](http://localhost:8000/project-docs/) |
| Interactive API documentation | [localhost:8000/docs](http://localhost:8000/docs) |

The first run creates an empty local issue database. Click **Open demo case** on the maintenance homepage to create and open the HVAC low-airflow case, then run root-cause analysis and repair simulations. Use `.\restart.ps1` to start or restart the background service, `.\restart.ps1 -Build` after frontend changes, and `.\stop-background.ps1` to stop it.

For mobile access, connect the phone and computer to a mutually accessible network and use the `http://<computer-LAN-IP>:8000/report` address printed by the startup script.

## Configuration and data

`setup.ps1` creates a local `.env` from `.env.example`. The default `KNOWLEDGE_BACKEND=snapshot` queries the included graph snapshot imported from Neo4j CSV, without requiring a database service. Setting it to `neo4j` enables actual parameterized Cypher queries; database failures are reported explicitly.

See the [deployment guide](docs/deployment.md) for Neo4j, LLM and vision configuration and model rebuilding, and the [API guide](docs/api.md) for endpoints and data flow. These two guides are currently in Chinese. The [formal project documentation](docs/project/) includes Chinese, English and bilingual PDFs and editable Word documents, plus a component name register.

Issues, inspections, repair scenarios and uploaded photos are stored locally in `data/maintenance.sqlite3` and `data/uploads/` and are excluded from the repository. Git also ignores `.env`, installed dependency environments, runtime logs and temporary files.

## Validation

```powershell
.\setup.ps1 -Dev
.\.venv\Scripts\python.exe -m pytest tests -q
npm.cmd --prefix frontend run build
```

## Current scope

The building model and knowledge graph come from actual source files. Faults, service connections, inspection findings, costs, staffing and thermal inputs in the demo are identified assumptions. Diagnostic knowledge-graph relations and building service-propagation relations are handled separately; geometric proximity does not automatically establish connections.

Temperature results are uncalibrated single-zone air-temperature scenarios. The resident assistant uses preset rules by default; live LLM and vision outputs require service configuration. The platform currently has no user authentication or role-based access control and is intended primarily for local course demonstrations.
