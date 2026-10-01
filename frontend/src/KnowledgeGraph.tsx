import {useEffect, useMemo, useRef, useState} from 'react';
import {Crosshair, Expand, LoaderCircle, Minus, Plus, Search, X} from 'lucide-react';
import {api} from './api';
import type {Analysis, Candidate, GraphData} from './types';

type Dataset=GraphData & {sourceHash:string;sourceFile:string;scope:string;queryBackend:string};
type Point={id:string;x:number;y:number};
type View={x:number;y:number;k:number};
type Hit={id:string;x:number;y:number;r:number};
const colors:Record<string,string>={System:'#7f8d9d',Building:'#66798c',Equipment:'#299b8d',FailureMode:'#d36366',RootCause:'#d79d45',DiagnosticCheck:'#7f75c2'};
const kindLabel=(s:string)=>s.replace(/([a-z])([A-Z])/g,'$1 $2');
const relationLabel:Record<string,string>={HAS_ROOT_CAUSE:'possible cause',HAS_FAILURE_MODE:'failure mode',CHECK_WITH:'check with',OCCURS_AT:'occurs at',HAS_EQUIPMENT_TYPE:'equipment type',HAS_SYSTEM:'system'};

export default function KnowledgeGraph({analysis,candidate,onCandidate}:{analysis:Analysis;candidate?:Candidate;onCandidate:(id:string)=>void}){
  const [data,setData]=useState<Dataset|null>(null),[error,setError]=useState(''),[points,setPoints]=useState<Point[]>([]);
  const [size,setSize]=useState({w:600,h:380}),[view,setView]=useState<View>({x:0,y:0,k:1});
  const [showAll,setShowAll]=useState(false),[selected,setSelected]=useState(''),[hover,setHover]=useState(''),[search,setSearch]=useState('');
  const host=useRef<HTMLDivElement>(null),canvas=useRef<HTMLCanvasElement>(null),hits=useRef<Hit[]>([]);
  const drag=useRef<{x:number;y:number;view:View;moved:boolean}|null>(null);
  const nodes=useMemo(()=>new Map(data?.nodes.map(n=>[n.id,n])||[]),[data]);
  const positions=useMemo(()=>new Map(points.map(p=>[p.id,p])),[points]);
  const related=useMemo(()=>new Set(analysis.candidates.flatMap(c=>c.graph?.nodes.map(n=>n.id)||[])),[analysis]);
  const active=useMemo(()=>new Set(candidate?.graph?.nodes.map(n=>n.id)||[]),[candidate]);
  const activeEdges=useMemo(()=>new Set(candidate?.graph?.edges.map(e=>e.id)||[]),[candidate]);
  const relatedEdges=useMemo(()=>new Set(analysis.candidates.flatMap(c=>c.graph?.edges.map(e=>e.id)||[])),[analysis]);
  const mismatch=!!data&&!!analysis.datasetHash&&data.sourceHash!==analysis.datasetHash;
  const result=selected?nodes.get(selected):undefined;
  const matches=search.trim()?data?.nodes.filter(n=>`${n.label} ${n.kind}`.toLowerCase().includes(search.toLowerCase())).slice(0,8)||[]:[];

  useEffect(()=>{const controller=new AbortController();api<Dataset>('/api/knowledge/graph',{signal:controller.signal}).then(setData).catch(e=>e.name!=='AbortError'&&setError(e.message));return()=>controller.abort();},[]);
  useEffect(()=>{if(!data)return;const worker=new Worker(new URL('./graphLayout.worker.ts',import.meta.url),{type:'module'});worker.onmessage=(e:MessageEvent<Point[]>)=>setPoints(e.data);worker.onerror=()=>setError('Graph layout could not load. Refresh to retry.');worker.postMessage({...data,relevantIds:Array.from(related)});return()=>worker.terminate();},[data,analysis.id]);
  useEffect(()=>{if(!host.current)return;const observer=new ResizeObserver(([entry])=>setSize({w:entry.contentRect.width,h:entry.contentRect.height}));observer.observe(host.current);return()=>observer.disconnect();},[]);
  const fit=(ids?:Set<string>)=>{
    const group=ids?.size?points.filter(p=>ids.has(p.id)):points;if(!group.length)return;
    const minX=Math.min(...group.map(p=>p.x)),maxX=Math.max(...group.map(p=>p.x)),minY=Math.min(...group.map(p=>p.y)),maxY=Math.max(...group.map(p=>p.y));
    const k=Math.max(.07,Math.min(4,(size.w-160)/(maxX-minX+40),(size.h-120)/(maxY-minY+30)));
    setView({x:size.w/2-(maxX+minX)*k/2,y:size.h/2-(maxY+minY)*k/2,k});
  };
  useEffect(()=>{if(points.length){fit(showAll?undefined:active.size?active:related);}},[points,size.w,size.h,showAll,analysis.id,candidate?.id]);
  useEffect(()=>{setSelected('');setHover('');},[candidate?.id]);
  const zoom=(factor:number,x=size.w/2,y=size.h/2)=>setView(v=>{const k=Math.max(.04,Math.min(6,v.k*factor)),ratio=k/v.k;return{x:x-(x-v.x)*ratio,y:y-(y-v.y)*ratio,k};});
  useEffect(()=>{const el=canvas.current;if(!el)return;const wheel=(e:WheelEvent)=>{if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();const b=el.getBoundingClientRect();zoom(Math.exp(-e.deltaY*.003),e.clientX-b.left,e.clientY-b.top);};el.addEventListener('wheel',wheel,{passive:false});return()=>el.removeEventListener('wheel',wheel);},[size]);
  useEffect(()=>{
    const el=canvas.current,ctx=el?.getContext('2d');if(!ctx||!el||!data||!points.length)return;
    const dpr=Math.min(window.devicePixelRatio||1,2);el.width=size.w*dpr;el.height=size.h*dpr;ctx.scale(dpr,dpr);ctx.clearRect(0,0,size.w,size.h);
    const project=(p:Point)=>({x:p.x*view.k+view.x,y:p.y*view.k+view.y});
    const highlighted=(id:string)=>!mismatch&&active.has(id);
    const radius=(id:string)=>highlighted(id)&&!showAll?13:!mismatch&&related.has(id)&&!showAll?6:Math.min(4.5,Math.max(1.8,view.k*5));
    const line=(e:GraphData['edges'][number],strong:boolean)=>{
      const p=positions.get(e.source),q=positions.get(e.target);if(!p||!q)return;const a=project(p),b=project(q),dx=b.x-a.x,dy=b.y-a.y,dist=Math.hypot(dx,dy);if(dist<1)return;
      const ux=dx/dist,uy=dy/dist,r1=radius(e.source)+1,r2=radius(e.target)+4,ax=a.x+ux*r1,ay=a.y+uy*r1,bx=b.x-ux*r2,by=b.y-uy*r2;
      ctx.globalAlpha=strong?1:(!mismatch&&relatedEdges.has(e.id)?.25:showAll?.3:.045);
      ctx.strokeStyle=strong?'#78988f':'#7d9293';ctx.lineWidth=strong?1.7:.65;ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(bx,by);ctx.stroke();
      if(strong){ctx.fillStyle='#78988f';ctx.beginPath();ctx.moveTo(bx,by);ctx.lineTo(bx-ux*7-uy*3.5,by-uy*7+ux*3.5);ctx.lineTo(bx-ux*7+uy*3.5,by-uy*7-ux*3.5);ctx.fill();
        if(dist>95){const text=relationLabel[e.relation]||e.relation.toLowerCase().replaceAll('_',' '),cx=(ax+bx)/2,cy=(ay+by)/2;ctx.font='10px "Segoe UI",sans-serif';const tw=ctx.measureText(text).width;ctx.fillStyle='#f8faf9';ctx.fillRect(cx-tw/2-5,cy-9,tw+10,15);ctx.fillStyle='#58746f';ctx.textAlign='center';ctx.fillText(text,cx,cy+2);}
      }
    };
    data.edges.filter(e=>mismatch||!activeEdges.has(e.id)).forEach(e=>line(e,false));
    if(!mismatch)data.edges.filter(e=>activeEdges.has(e.id)).forEach(e=>line(e,true));
    const ordered=[...points].sort((a,b)=>Number(highlighted(a.id))-Number(highlighted(b.id)));
    hits.current=[];const labelBoxes=points.filter(p=>highlighted(p.id)).map(p=>{const s=project(p);return{x:s.x-20,y:s.y-20,w:40,h:40};});
    for(const p of ordered){const node=nodes.get(p.id);if(!node)continue;const {x,y}=project(p);if(x< -60||y< -50||x>size.w+60||y>size.h+50)continue;
      const strong=highlighted(p.id),isRelated=!mismatch&&related.has(p.id),isHover=p.id===hover||p.id===selected,r=radius(p.id),color=colors[node.kind]||'#8594a7';
      ctx.globalAlpha=strong||isHover?1:isRelated?.5:showAll?.72:.095;
      if(strong){ctx.fillStyle=color+'1c';ctx.beginPath();ctx.arc(x,y,r+7,0,2*Math.PI);ctx.fill();}
      ctx.beginPath();ctx.arc(x,y,r,0,2*Math.PI);ctx.fillStyle=color;ctx.fill();ctx.strokeStyle=isHover?'#1b514c':'#fff';ctx.lineWidth=isHover?2:1.3;ctx.stroke();hits.current.push({id:p.id,x,y,r:Math.max(r,7)});
    }
    // Label only the selected path (and a hovered node); the rest remains spatial context.
    for(const p of ordered.filter(p=>(!showAll&&highlighted(p.id))||p.id===hover||p.id===selected)){
      const n=nodes.get(p.id)!;const {x,y}=project(p);if(x<0||x>size.w||y<0||y>size.h)continue;
      const text=n.label.length>64?n.label.slice(0,61)+'…':n.label;ctx.globalAlpha=1;ctx.font='600 11px "Segoe UI",sans-serif';
      const lines:string[]=[];let current='';for(const word of text.split(' ')){if(current&&ctx.measureText(current+' '+word).width>157){lines.push(current);current=word;}else current+=(current?' ':'')+word;}if(current)lines.push(current);
      const w=Math.max(...lines.map(l=>ctx.measureText(l).width))+14,h=lines.length*15+9;
      const options=[{x:x-w/2,y:y+22},{x:x-w/2,y:y-h-23},{x:x+23,y:y-h/2},{x:x-w-23,y:y-h/2},{x:x-w-15,y:y-h-22},{x:x+15,y:y+22}].map(b=>({...b,x:Math.max(5,Math.min(size.w-w-5,b.x)),y:Math.max(5,Math.min(size.h-h-5,b.y)),w,h}));
      const box=options.find(a=>!labelBoxes.some(b=>a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y))||options[0];
      labelBoxes.push(box);ctx.fillStyle='#fffffff0';ctx.beginPath();ctx.roundRect(box.x,box.y,w,h,5);ctx.fill();ctx.fillStyle='#314d4b';ctx.textAlign='left';lines.forEach((line,i)=>ctx.fillText(line,box.x+7,box.y+16+i*15));
    }
    ctx.globalAlpha=1;
  },[data,points,positions,nodes,size,view,active,activeEdges,related,relatedEdges,hover,selected,showAll,mismatch]);
  const hitAt=(x:number,y:number)=>[...hits.current].reverse().find(p=>Math.hypot(x-p.x,y-p.y)<p.r+4);
  const choose=(id:string)=>{setSelected(id);const c=analysis.candidates.find(c=>c.id===id);if(c)onCandidate(c.id);};
  return <section className="knowledge-network" aria-label="Causal knowledge graph">
    <div className="network-toolbar"><span>Knowledge graph <small>{data?`${data.nodes.length.toLocaleString()} nodes · ${data.edges.length.toLocaleString()} links`:''}</small></span><div><button title="Focus current problem" aria-label="Focus current problem" onClick={()=>{setShowAll(false);fit(active.size?active:related);}}><Crosshair size={14}/></button><button className={showAll?'active':''} title="View whole knowledge graph" aria-label="View whole knowledge graph" onClick={()=>{setShowAll(true);fit();}}><Expand size={14}/></button><button aria-label="Zoom graph out" onClick={()=>zoom(.8)}><Minus size={14}/></button><button aria-label="Zoom graph in" onClick={()=>zoom(1.25)}><Plus size={14}/></button></div></div>
    <div className="network-search"><Search size={12}/><input aria-label="Find a knowledge graph node" placeholder="Find a node…" value={search} onChange={e=>setSearch(e.target.value)}/>{search&&<button aria-label="Clear graph search" onClick={()=>setSearch('')}><X size={12}/></button>}{search&&<div className="network-matches">{matches.length?matches.map(n=><button key={n.id} onClick={()=>{choose(n.id);const p=positions.get(n.id);if(p)setView(v=>({...v,x:size.w/2-p.x*v.k,y:size.h/2-p.y*v.k}));setSearch('');}}><span style={{background:colors[n.kind]}}/>{n.label}<small>{kindLabel(n.kind)}</small></button>):<span>No matching nodes</span>}</div>}</div>
    <div className="network-canvas" ref={host}>
      {error?<p role="alert">{error}</p>:!points.length?<div className="network-loading"><LoaderCircle className="spin" size={18}/>Laying out knowledge graph…</div>:null}
      <canvas ref={canvas} role="img" aria-label={`Full imported knowledge graph. ${data?.nodes.length||0} nodes and ${data?.edges.length||0} relationships. Highlighted hypothesis: ${candidate?.label||'none'}.`} data-node-count={data?.nodes.length||0} data-edge-count={data?.edges.length||0} data-active-nodes={mismatch?'':Array.from(active).join('|')} data-active-edges={mismatch?'':Array.from(activeEdges).join('|')} style={{cursor:drag.current?'grabbing':hover?'pointer':'grab',touchAction:'none'}}
        onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);drag.current={x:e.clientX,y:e.clientY,view,moved:false};}}
        onPointerMove={e=>{if(drag.current){const d=drag.current,dx=e.clientX-d.x,dy=e.clientY-d.y;if(Math.hypot(dx,dy)>4)d.moved=true;if(d.moved)setView({...d.view,x:d.view.x+dx,y:d.view.y+dy});}else{const r=e.currentTarget.getBoundingClientRect();setHover(hitAt(e.clientX-r.left,e.clientY-r.top)?.id||'');}}}
        onPointerUp={e=>{const d=drag.current;drag.current=null;if(d&&!d.moved){const r=e.currentTarget.getBoundingClientRect(),hit=hitAt(e.clientX-r.left,e.clientY-r.top);if(hit)choose(hit.id);else setSelected('');}e.currentTarget.releasePointerCapture(e.pointerId);}}
        onPointerCancel={()=>{drag.current=null;}} onPointerLeave={()=>setHover('')}/>
    </div>
    <div className="network-legend">{['Equipment','FailureMode','RootCause','DiagnosticCheck'].map(k=><span key={k}><i style={{background:colors[k]}}/>{kindLabel(k)}</span>)}</div>
    {result?<div className="network-node-detail"><span><strong>{result.label}</strong><small>{kindLabel(result.kind)} · {related.has(result.id)?'Related to this report':'Outside the current query result'}</small></span><button aria-label="Close node details" onClick={()=>setSelected('')}><X size={13}/></button></div>:<p className="network-caption">{mismatch?'Graph version changed. Update analysis to highlight matching paths.':'Bright: selected path · Faded: other knowledge · Drag to pan'}</p>}
    <details className="network-accessible"><summary>Path & source</summary><p>Imported dataset: {data?.sourceFile}. Query: {analysis.queryTrace?.backend||analysis.knowledgeBackend}. HAS_ROOT_CAUSE retrieves possible causes; arrows are knowledge relationships, not physical propagation.</p>{candidate?.graph?.edges.map(e=><p key={e.id}>{nodes.get(e.source)?.label} → <strong>{e.relation}</strong> → {nodes.get(e.target)?.label}</p>)}<p>Only the supplied export is displayed; completeness beyond that export is unverified.</p></details>
  </section>;
}
