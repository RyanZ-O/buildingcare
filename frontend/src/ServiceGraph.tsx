import {useEffect,useMemo,useRef,useState} from 'react';
import {ArrowLeft,Download,Expand,Minus,Plus,Search} from 'lucide-react';
import {api} from './api';
import {Brand,Notice,shortName} from './App';
import ModelViewer from './ModelViewer';
import type {Building} from './types';
import './service-graph.css';

type Node={id:string;label:string;originalName?:string;equipmentTag?:string;sourceTag?:string;kind:string;floorId:string;discipline:string;ifcType?:string;ifcGlobalId?:string;center:number[]|null;networks:string[];serviceTypes:string[];isServiceComponent:boolean};
type Edge={id:string;source:string;target:string;relation:string;basis:string;directed:boolean;evidence:Record<string,unknown>;simulationEligible:boolean};
type Dataset={nodes:Node[];edges:Edge[];gaps:{entityId:string;category:string;service?:string;reason:string}[];policy:string;summary:{modelEntities:number;rooms:number;networks:number;nodes:number;edges:number;relations:Record<string,number>;roomServiceCoverage:Record<string,number>;unresolved:number}};
const colors:Record<string,string>={ventilation:'#168f83',heating:'#dc8653',water:'#4d91c7',drainage:'#827256',power:'#ac7b22',data:'#766bc2',Room:'#906caf',other:'#87979a'};
const relationNames:Record<string,string>={PART_OF_SYSTEM:'System membership',POSSIBLE_CONNECTION:'Pipe / duct contact',INFERRED_FEEDS:'Upstream / downstream',POSSIBLE_SYSTEM_FEED:'Equipment dependency',POSSIBLE_POWER_FEED:'Power supply',POSSIBLE_SERVICE:'Room service'};

export function ServiceGraph(){
  const [building,setBuilding]=useState<Building|null>(null),[data,setData]=useState<Dataset|null>(null),[error,setError]=useState('');
  const [floor,setFloor]=useState('all'),[service,setService]=useState('all'),[network,setNetwork]=useState('all'),[relation,setRelation]=useState('all'),[basis,setBasis]=useState('all');
  const [membership,setMembership]=useState(false),[inventory,setInventory]=useState(false),[query,setQuery]=useState(''),[selectedId,setSelectedId]=useState<string|null>(null);
  const [direction,setDirection]=useState('neighbors'),[hops,setHops]=useState(1),[focus,setFocus]=useState({id:null as string|null,tick:0});
  useEffect(()=>{const c=new AbortController();Promise.all([api<Building>('/api/building',{signal:c.signal}),api<Dataset>('/api/service-graph',{signal:c.signal})]).then(([b,g])=>{setBuilding(b);setData(g);}).catch(e=>e.name!=='AbortError'&&setError(e.message));return()=>c.abort();},[]);
  const nodeMap=useMemo(()=>new Map(data?.nodes.map(n=>[n.id,n])||[]),[data]);
  const powerScope=useMemo(()=>{
    const scope=new Map<string,Set<string>>();
    for(const edge of data?.edges||[])if(edge.relation==='POSSIBLE_POWER_FEED'){
      const tags=nodeMap.get(edge.source)?.networks||[];
      for(const id of [edge.source,edge.target]){const values=scope.get(id)||new Set<string>();tags.forEach(tag=>values.add(tag));scope.set(id,values);}
    }
    return scope;
  },[data,nodeMap]);
  const visibleNodes=useMemo(()=>data?.nodes.filter(n=>(inventory||n.isServiceComponent||n.kind==='Room')&&(floor==='all'||n.floorId===floor||n.kind==='System')&&(service==='all'||n.serviceTypes.includes(service)||(service==='power'&&powerScope.has(n.id))||n.kind==='Room')&&(network==='all'||n.networks.includes(network)||powerScope.get(n.id)?.has(network)||n.kind==='Room'))||[],[data,inventory,floor,service,network,powerScope]);
  const visibleIds=useMemo(()=>new Set(visibleNodes.map(n=>n.id)),[visibleNodes]);
  const edges=useMemo(()=>data?.edges.filter(e=>visibleIds.has(e.source)&&visibleIds.has(e.target)&&(membership||relation==='PART_OF_SYSTEM'||basis==='source_model'||e.relation!=='PART_OF_SYSTEM')&&(relation==='all'||e.relation===relation)&&(basis==='all'||e.basis===basis))||[],[data,visibleIds,membership,relation,basis]);
  const related=useMemo(()=>{
    if(!selectedId)return new Set<string>();
    const result=new Set([selectedId]);let frontier=new Set([selectedId]);
    for(let step=0;step<hops;step++){const next=new Set<string>();for(const e of edges){if(e.relation==='PART_OF_SYSTEM'&&nodeMap.get(selectedId)?.kind!=='System')continue;
      if(frontier.has(e.source)&&(direction!=='upstream'||!e.directed))next.add(e.target);
      if(frontier.has(e.target)&&(direction!=='downstream'||!e.directed))next.add(e.source);
    }frontier=new Set([...next].filter(i=>!result.has(i)));frontier.forEach(i=>result.add(i));if(!frontier.size)break;}return result;
  },[selectedId,edges,direction,hops,nodeMap]);
  const selected=selectedId?nodeMap.get(selectedId):undefined;
  const select=(id:string)=>{setSelectedId(id);if(nodeMap.get(id)?.center)setFocus(f=>({id,tick:f.tick+1}));};
  const matches=query.trim()?data?.nodes.filter(n=>`${n.label} ${n.originalName||''} ${n.equipmentTag||''} ${n.sourceTag||''} ${n.ifcGlobalId||''} ${n.id} ${n.networks.join(' ')}`.toLowerCase().includes(query.trim().toLowerCase())).slice(0,12)||[]:[];
  const incident=selectedId?edges.filter(e=>e.source===selectedId||e.target===selectedId):[];
  const gaps=data?.gaps.filter(g=>!selectedId||g.entityId===selectedId)||[];
  return <div className="service-page">
    <header className="clear-header"><Brand/><span className="clear-header-label">Building 1 <span>/</span> Building systems</span><a className="muted-button" href="/"><ArrowLeft size={14}/>Workbench</a></header>
    {error?<Notice error>{error}</Notice>:!building||!data?<div className="startup-state">Loading building relationships…</div>:<>
      <div className="service-summary"><div><h1>Whole-building service graph</h1><p>Model memberships · reconstructed connection proposals · room service candidates</p></div><span><strong>{data.summary.modelEntities.toLocaleString()}</strong> components</span><span><strong>{data.summary.networks}</strong> networks</span><span><strong>{data.summary.rooms}</strong> rooms</span><a className="muted-button" href="/api/service-graph/download"><Download size={14}/>Export JSON</a></div>
      <div className="service-filters">
        <label>Floor<select aria-label="Graph floor" value={floor} onChange={e=>setFloor(e.target.value)}><option value="all">All floors</option>{building.floors.map(f=><option key={f.id} value={f.id}>{f.name}</option>)}</select></label>
        <label>Service<select aria-label="Graph service" value={service} onChange={e=>{setService(e.target.value);setNetwork('all');}}><option value="all">All services</option>{Object.keys(colors).filter(k=>!['Room','other'].includes(k)).map(s=><option key={s} value={s}>{s}</option>)}</select></label>
        <label>Network<select aria-label="Graph network" value={network} onChange={e=>setNetwork(e.target.value)}><option value="all">All networks</option>{data.nodes.filter(n=>n.kind==='System'&&(service==='all'||n.serviceTypes.includes(service))).sort((a,b)=>a.label.localeCompare(b.label)).map(n=><option key={n.id} value={n.networks[0]}>{n.label}</option>)}</select></label>
        <label>Relationship<select aria-label="Graph relationship" value={relation} onChange={e=>setRelation(e.target.value)}><option value="all">All relationships</option>{Object.entries(relationNames).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
        <label>Evidence<select aria-label="Graph evidence" value={basis} onChange={e=>setBasis(e.target.value)}><option value="all">All evidence</option><option value="source_model">Model property</option><option value="inferred">Inferred proposal</option></select></label>
        <label className="service-check"><input type="checkbox" checked={membership} onChange={e=>setMembership(e.target.checked)}/>Membership links</label>
        <label className="service-check"><input type="checkbox" checked={inventory} onChange={e=>setInventory(e.target.checked)}/>All building components</label>
      </div>
      <main className="service-layout"><div className="service-model"><ModelViewer compact serviceMode building={building} selectedId={selected?.center?selectedId:null} onSelect={select} focus={focus} impact={null} phase="during" floor={floor} setFloor={setFloor} reportedIds={[]} suspectIds={selectedId?[...related].filter(i=>i!==selectedId):[]}/></div>
        <section className="service-network"><div className="service-search"><Search size={15}/><input aria-label="Search building graph" placeholder="Find component, IFC ID or system tag…" value={query} onChange={e=>setQuery(e.target.value)}/>{query&&<div className="service-matches">{matches.length?matches.map(n=><button key={n.id} onClick={()=>{setFloor(n.floorId==='all'?'all':n.floorId);setService('all');setNetwork('all');setInventory(true);select(n.id);setQuery('');}}>{shortName(n.label)}<small>{n.ifcType||'System'} · {n.floorId}</small></button>):<span>No matching component</span>}</div>}</div>
          <div className="service-trace-controls"><span>{visibleNodes.length.toLocaleString()} nodes · {edges.length.toLocaleString()} visible links</span><select aria-label="Trace direction" value={direction} onChange={e=>setDirection(e.target.value)}><option value="neighbors">Connected neighborhood</option><option value="upstream">Upstream candidates</option><option value="downstream">Downstream candidates</option></select><select aria-label="Trace depth" value={hops} onChange={e=>setHops(+e.target.value)}>{[1,2,3,4].map(n=><option key={n} value={n}>{n} hop{n>1?'s':''}</option>)}</select>{selectedId&&<button className="text-button" onClick={()=>setSelectedId(null)}>Clear selection</button>}</div>
          <GraphCanvas nodes={visibleNodes} edges={edges} selectedId={selectedId} related={related} onSelect={select}/>
          <div className="service-legend">{Object.entries(colors).filter(([s])=>s!=='other').map(([s,c])=><span key={s}><i style={{background:c}}/>{s}</span>)}<span>Solid: model membership · Dashed: inferred · Lines without arrows: unknown direction</span></div>
        </section>
      </main>
      <div className="service-details"><section><h2>{selected?shortName(selected.label):'Select a component to inspect its relationships'}</h2>{selected&&<><p>{selected.ifcType||'System'} · {selected.floorId} · {selected.networks.join(', ')||'No exported system tag'}</p>{selected.ifcGlobalId&&<p className="service-id">IFC {selected.ifcGlobalId}</p>}<div className="service-edge-list">{incident.slice(0,100).map(e=>{const other=nodeMap.get(e.source===selectedId?e.target:e.source);return <article key={e.id}><button onClick={()=>other&&select(other.id)}>{!e.directed?'↔':e.source===selectedId?'→':'←'} {shortName(other?.label||'')}</button><strong>{relationNames[e.relation]} · {e.basis==='source_model'?'Model property':'Inferred proposal'}</strong><p>{String(e.evidence.method)}</p>{e.evidence.ambiguous===true&&<small>Multiple candidates: assignment is ambiguous.</small>}{e.evidence.distanceMetres!==undefined&&<small>Geometry / separation: {String(e.evidence.distanceMetres)} m</small>}</article>;})}{incident.length>100&&<p>{incident.length} links total; all links are retained in JSON export.</p>}{!incident.length&&<p>No relationship matches the current filters.</p>}</div></>}</section>
        <section><h2>Service coverage and unresolved evidence</h2><div className="service-coverage">{Object.entries(data.summary.roomServiceCoverage).map(([s,n])=><span key={s}><strong>{n}/{data.summary.rooms}</strong>{s} room proposals</span>)}</div><p>{selectedId?`${gaps.length} unresolved items for this component`:`${data.summary.unresolved} unresolved items across the building`}</p><ul>{gaps.slice(0,6).map((g,i)=><li key={i}>{g.category}{g.service?' · '+g.service:''}: {g.reason}</li>)}</ul><p className="service-policy">{data.policy}</p><p>Unoriented contacts remain included as neighbors during tracing; they do not prove flow direction.</p></section>
      </div>
    </>}
  </div>;
}

function GraphCanvas({nodes,edges,selectedId,related,onSelect}:{nodes:Node[];edges:Edge[];selectedId:string|null;related:Set<string>;onSelect:(id:string)=>void}){
  const host=useRef<HTMLDivElement>(null),canvas=useRef<HTMLCanvasElement>(null),hits=useRef<{id:string;x:number;y:number;r:number}[]>([]),drag=useRef<{x:number;y:number;vx:number;vy:number;moved:boolean}|null>(null);
  const [size,setSize]=useState({w:800,h:520}),[view,setView]=useState({x:15,y:30,k:.65});
  const layout=useMemo(()=>{
    const floors=[...new Set(nodes.filter(n=>n.center).map(n=>n.floorId))].sort();const positions=new Map<string,{x:number;y:number}>();
    for(const n of nodes){if(n.center){const f=floors.indexOf(n.floorId);positions.set(n.id,{x:(f%3)*360+175+n.center[0]*9,y:Math.floor(f/3)*330+145+n.center[2]*9});}}
    nodes.filter(n=>n.kind==='System').forEach((n,i)=>positions.set(n.id,{x:-180,y:i*17}));
    return {positions,floors};
  },[nodes]);
  const fit=()=>{const points=[...layout.positions.values()];if(!points.length)return;const minX=Math.min(...points.map(p=>p.x))-25,maxX=Math.max(...points.map(p=>p.x))+25,minY=Math.min(...points.map(p=>p.y))-45,maxY=Math.max(...points.map(p=>p.y))+25;const k=Math.min(size.w/(maxX-minX),size.h/(maxY-minY),2);setView({x:(size.w-(maxX-minX)*k)/2-minX*k,y:(size.h-(maxY-minY)*k)/2-minY*k,k});};
  useEffect(()=>{if(!host.current)return;const o=new ResizeObserver(([e])=>setSize({w:e.contentRect.width,h:520}));o.observe(host.current);return()=>o.disconnect();},[]);
  useEffect(()=>{fit();},[layout,size.w]);
  useEffect(()=>{
    const el=canvas.current;if(!el)return;const ratio=Math.min(devicePixelRatio,1.5);el.width=size.w*ratio;el.height=size.h*ratio;const ctx=el.getContext('2d');if(!ctx)return;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,size.w,size.h);hits.current=[];
    const project=(p:{x:number;y:number})=>({x:p.x*view.k+view.x,y:p.y*view.k+view.y});
    for(const [i,f] of layout.floors.entries()){const p=project({x:(i%3)*360+25,y:Math.floor(i/3)*330-5});ctx.globalAlpha=.8;ctx.fillStyle='#59766c';ctx.font='600 12px Segoe UI';ctx.fillText(f,p.x,p.y);}
    for(const e of edges){const a=layout.positions.get(e.source),b=layout.positions.get(e.target);if(!a||!b)continue;const pa=project(a),pb=project(b);const active=!selectedId||(related.has(e.source)&&related.has(e.target));ctx.globalAlpha=active?.45:.025;ctx.strokeStyle=e.relation==='POSSIBLE_POWER_FEED'?'#b48a39':e.relation==='POSSIBLE_SERVICE'?'#9273ac':'#4b9f92';ctx.lineWidth=active&&selectedId?1.5:.65;ctx.setLineDash(e.basis==='inferred'?[3,3]:[]);ctx.beginPath();ctx.moveTo(pa.x,pa.y);ctx.lineTo(pb.x,pb.y);ctx.stroke();if(e.directed&&selectedId&&active){const angle=Math.atan2(pb.y-pa.y,pb.x-pa.x),x=(pa.x+pb.x)/2,y=(pa.y+pb.y)/2;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x-6*Math.cos(angle-.5),y-6*Math.sin(angle-.5));ctx.moveTo(x,y);ctx.lineTo(x-6*Math.cos(angle+.5),y-6*Math.sin(angle+.5));ctx.stroke();}}
    ctx.setLineDash([]);
    for(const n of [...nodes].sort((a,b)=>Number(related.has(a.id))-Number(related.has(b.id)))){const p=layout.positions.get(n.id);if(!p)continue;const {x,y}=project(p);if(x<0||y<0||x>size.w||y>size.h)continue;const active=!selectedId||related.has(n.id);const r=n.id===selectedId?7:n.kind==='Room'?4:n.kind==='System'?4:2.2;ctx.globalAlpha=active?1:.09;ctx.fillStyle=colors[n.kind]||colors[n.serviceTypes[0]]||colors.other;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();hits.current.push({id:n.id,x,y,r:Math.max(r,5)});if(n.id===selectedId){ctx.font='600 12px Segoe UI';ctx.fillStyle='#234d43';ctx.fillText(shortName(n.label).slice(0,55),Math.max(8,Math.min(x+10,size.w-250)),Math.max(20,y-10));}}
  },[layout,nodes,edges,selectedId,related,size,view]);
  const zoom=(factor:number)=>setView(v=>{const k=Math.max(.15,Math.min(8,v.k*factor));return {k,x:size.w/2-(size.w/2-v.x)*k/v.k,y:size.h/2-(size.h/2-v.y)*k/v.k};});
  return <div className="service-canvas" ref={host}>
    <div className="service-canvas-tools"><button aria-label="Fit whole building graph" onClick={fit}><Expand size={15}/></button><button aria-label="Zoom building graph in" onClick={()=>zoom(1.25)}><Plus size={15}/></button><button aria-label="Zoom building graph out" onClick={()=>zoom(.8)}><Minus size={15}/></button></div>
    <canvas ref={canvas} aria-label="Whole-building component and service graph" data-node-count={nodes.length} data-edge-count={edges.length} style={{width:'100%',height:520,touchAction:'none'}}
      onWheel={e=>zoom(e.deltaY<0?1.12:.89)}
      onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);drag.current={x:e.clientX,y:e.clientY,vx:view.x,vy:view.y,moved:false};}}
      onPointerMove={e=>{const d=drag.current;if(d){const dx=e.clientX-d.x,dy=e.clientY-d.y;if(Math.abs(dx)+Math.abs(dy)>4)d.moved=true;if(d.moved)setView(v=>({...v,x:d.vx+dx,y:d.vy+dy}));}}}
      onPointerUp={e=>{const d=drag.current;drag.current=null;if(d?.moved)return;const r=e.currentTarget.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;const hit=[...hits.current].reverse().find(p=>Math.hypot(p.x-x,p.y-y)<=p.r);if(hit)onSelect(hit.id);}}/>
  </div>;
}
