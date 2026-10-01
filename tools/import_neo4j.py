"""Explicit idempotent import. Only writes namespaced MaintenanceKnowledge nodes."""
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.kg import driver, RELATIONS

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env')
    directory = Path(os.getenv('MAINTENANCE_DATA_DIR') or root / 'data')
    doc = json.loads((directory / 'causal-graph.json').read_text(encoding='utf-8'))
    with driver() as db:
        db.verify_connectivity()
        database = os.getenv('NEO4J_DATABASE', 'neo4j')
        db.execute_query('CREATE CONSTRAINT maintenance_knowledge_identity IF NOT EXISTS FOR (n:MaintenanceKnowledge) REQUIRE (n.dataset,n.id) IS UNIQUE', database_=database)
        for offset in range(0, len(doc['nodes']), 250):
            db.execute_query('UNWIND $rows AS row MERGE (n:MaintenanceKnowledge {dataset:$dataset,id:row.id}) SET n.label=row.label,n.kind=row.kind,n.originalId=row.originalId',
                             rows=doc['nodes'][offset:offset+250], dataset=doc['sourceHash'], database_=database)
        for rel in sorted(RELATIONS):
            edges = [e for e in doc['edges'] if e['relation'] == rel]
            for offset in range(0, len(edges), 250):
                db.execute_query(f'UNWIND $rows AS row MATCH (a:MaintenanceKnowledge {{dataset:$dataset,id:row.source}}),(b:MaintenanceKnowledge {{dataset:$dataset,id:row.target}}) MERGE (a)-[r:{rel} {{id:row.id}}]->(b) SET r.sourceRows=row.sourceRows',
                                 rows=edges[offset:offset+250], dataset=doc['sourceHash'], database_=database)
        print(f"Imported {len(doc['nodes'])} nodes and {len(doc['edges'])} edges; dataset {doc['sourceHash'][:12]}.")
