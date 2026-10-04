"""Import the evidence-bearing instance graph into an independent Neo4j namespace."""
import json
import os
from pathlib import Path
import sys
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.kg import driver

RELATIONS={'PART_OF_SYSTEM','POSSIBLE_CONNECTION','INFERRED_FEEDS','POSSIBLE_SYSTEM_FEED','POSSIBLE_POWER_FEED','POSSIBLE_SERVICE'}

def main():
    load_dotenv(ROOT/'.env')
    data=Path(os.getenv('MAINTENANCE_DATA_DIR') or ROOT/'data')
    graph=json.loads((data/'service-graph.json').read_text(encoding='utf-8'))
    dataset=graph['graphHash'];database=os.getenv('NEO4J_DATABASE','neo4j')
    assert {e['relation'] for e in graph['edges']}<=RELATIONS
    nodes=[{'id':n['id'],'name':n['label'],'kind':n['kind'],'equipmentTag':n.get('equipmentTag'),'sourceTag':n.get('sourceTag'),'ifcGlobalId':n.get('ifcGlobalId'),'ifcType':n.get('ifcType'),'floorId':n['floorId'],'discipline':n['discipline'],'networks':n['networks'],'center':n['center']} for n in graph['nodes']]
    with driver() as db:
        db.verify_connectivity()
        db.execute_query('CREATE CONSTRAINT building_service_identity IF NOT EXISTS FOR (n:BuildingServiceNode) REQUIRE (n.dataset,n.id) IS UNIQUE',database_=database)
        for offset in range(0,len(nodes),400):
            db.execute_query('UNWIND $rows AS row MERGE (n:BuildingServiceNode {dataset:$dataset,id:row.id}) SET n += row',rows=nodes[offset:offset+400],dataset=dataset,database_=database)
        for relation in sorted(RELATIONS):
            rows=[{'id':e['id'],'source':e['source'],'target':e['target'],'basis':e['basis'],'directed':e['directed'],'simulationEligible':False,'evidenceJson':json.dumps(e['evidence'],ensure_ascii=False)} for e in graph['edges'] if e['relation']==relation]
            for offset in range(0,len(rows),400):
                db.execute_query(f'UNWIND $rows AS row MATCH (a:BuildingServiceNode {{dataset:$dataset,id:row.source}}),(b:BuildingServiceNode {{dataset:$dataset,id:row.target}}) MERGE (a)-[r:{relation} {{id:row.id}}]->(b) SET r.basis=row.basis,r.directed=row.directed,r.evidenceJson=row.evidenceJson,r.simulationEligible=false',rows=rows[offset:offset+400],dataset=dataset,database_=database)
        records,_,_=db.execute_query('MATCH (n:BuildingServiceNode {dataset:$dataset}) RETURN count(n) AS nodes',dataset=dataset,database_=database)
        records2,_,_=db.execute_query('MATCH (:BuildingServiceNode {dataset:$dataset})-[r]->(:BuildingServiceNode {dataset:$dataset}) RETURN count(r) AS edges',dataset=dataset,database_=database)
        assert records[0]['nodes']==len(nodes) and records2[0]['edges']==len(graph['edges'])
    print(f"Verified Neo4j instance graph: {len(nodes)} nodes, {len(graph['edges'])} links; dataset {dataset[:12]}.")

if __name__=='__main__':main()
