import {useEffect, useState} from 'react';
import {ArrowRight, Building2, CircleAlert, LoaderCircle, MoreHorizontal, Plus, Search, Wind, Zap} from 'lucide-react';
import ModelViewer from './ModelViewer';
import {Studio} from './Studio';
import {ResidentAssistant} from './ResidentAssistant';
import {api} from './api';
import type {Building, Evidence, Issue} from './types';
import {dateLabel, statusLabels} from './types';
import {ResidentPage, ReportPage} from './Pages';
import {ElementPicker, KnowledgeStatus, TopologyEditor} from './Features';
import './workspace.css';

export function EvidenceList({items}:{items:Evidence[]}){return items.length?<details className="evidence"><summary>{items.length} supporting source{items.length===1?'':'s'}</summary>{items.map((s,i)=><div key={`${s.id}-${i}`}><strong>[{s.id}] {s.text}</strong><span>{/^https?:\/\//.test(s.source)?<a href={s.source} target="_blank" rel="noreferrer">{s.source}</a>:s.source}</span></div>)}</details>:null;}
export function Notice({children,error=false}:{children:React.ReactNode;error?:boolean}){return <div className={`notice ${error?'error':''}`} role={error?'alert':undefined}><CircleAlert size={16}/><div>{children}</div></div>;}
export function Brand(){return <a href="/" className="brand"><span className="brand-mark"><Building2 size={22}/></span><span>building<span className="brand-light">care</span></span></a>;}
export const shortName=(name:string)=>name.replace(/ · B1-[A-Z0-9-]+$/,'');
export function WorkspaceMenu({issueId}:{issueId?:string}){return <details className="workspace-menu"><summary aria-label="More options"><MoreHorizontal size={19}/></summary><div><a href="/report">Resident report</a><a href={`/resident${issueId?'?issueId='+issueId:''}`}>Resident assistant</a><a href="/project-docs/" target="_blank" rel="noreferrer">Project documents</a></div></details>;}
export default function App(){const path=location.pathname;if(path==='/resident')return <ResidentAssistant/>;if(path.startsWith('/investigate/'))return <Studio issueId={decodeURIComponent(path.split('/')[2]||'')}/>;if(path==='/report')return <ResidentPage/>;if(path.startsWith('/reports/'))return <ReportPage issueId={decodeURIComponent(path.split('/')[2]||'')}/>;return <Workbench/>;}

function Workbench(){
  const [building,setBuilding]=useState<Building|null>(null),[issues,setIssues]=useState<Issue[]>([]),[error,setError]=useState('');
  const [search,setSearch]=useState(''),[filter,setFilter]=useState('all'),[selectedId,setSelectedId]=useState<string|null>(null),[floor,setFloor]=useState('all');
  const [focus,setFocus]=useState({id:null as string|null,tick:0}),[busy,setBusy]=useState(false),[setup,setSetup]=useState(false);
  useEffect(()=>{const c=new AbortController();Promise.all([api<Building>('/api/building',{signal:c.signal}),api<Issue[]>('/api/issues',{signal:c.signal})]).then(([b,i])=>{setBuilding(b);setIssues(i);}).catch(e=>e.name!=='AbortError'&&setError(e.message));const timer=window.setInterval(()=>{void api<Issue[]>('/api/issues',{signal:c.signal}).then(setIssues).catch(e=>e.name!=='AbortError'&&setError('Reports could not refresh. '+e.message));},10000);return()=>{c.abort();clearInterval(timer);};},[]);
  const select=(id:string)=>{const e=building?.entities.find(e=>e.id===id);if(e){setSelectedId(id);setFloor(e.floorId);setFocus(f=>({id,tick:f.tick+1}));}};
  const room=(id:string)=>shortName(building?.entities.find(e=>e.id===id)?.name||id);
  const visible=issues.filter(i=>(filter==='all'||i.status===filter)&&`${i.title} ${i.description} ${room(i.roomId)}`.toLowerCase().includes(search.toLowerCase()));
  const demo=async()=>{setBusy(true);setError('');try{const i=await api<Issue>('/api/demo/case-study',{method:'POST'});location.href='/investigate/'+i.id;}catch(e){setError((e as Error).message);setBusy(false);}};
  return <div className="clear-workspace inbox-workspace">
    <header className="clear-header"><Brand/><span className="clear-header-label">Building 1 <span>/</span> Maintenance</span><div className="clear-header-actions"><a className="button secondary compact" href="/report"><Plus size={14}/>Report an issue</a><WorkspaceMenu/></div></header>
    {!building?<main className="startup-state">{error?<Notice error>{error}</Notice>:<><LoaderCircle className="spin"/><p>Loading building…</p></>}</main>:<main className="clear-layout inbox-layout">
      <div className="clear-model"><ModelViewer compact building={building} selectedId={selectedId} onSelect={select} focus={focus} impact={null} phase="during" floor={floor} setFloor={setFloor} reportedIds={issues.filter(i=>i.status!=='resolved').map(i=>i.assetId||i.roomId)} suspectIds={[]}/></div>
      <aside className="clear-work inbox-panel"><div className="section-heading"><h1>Reported issues</h1><span className="muted">{issues.filter(i=>i.status!=='resolved').length} open</span></div>
        {error&&<Notice error>{error}</Notice>}
        <div className="inbox-filter"><label><Search size={15}/><input aria-label="Search issues" placeholder="Search reports or rooms" value={search} onChange={e=>setSearch(e.target.value)}/></label><select aria-label="Filter by status" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">All statuses</option>{Object.entries(statusLabels).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></div>
        <div className="clear-issue-list">{visible.map(i=><a className="clear-issue" key={i.id} href={`/investigate/${i.id}`}><span className="clear-system-icon">{i.system==='hvac'?<Wind size={19}/>:<Zap size={19}/>}</span><div><div className="clear-issue-title"><strong>{i.title.replace('[CASE STUDY] ','')}</strong><ArrowRight size={15}/></div><p>{room(i.roomId)}{i.isDemo&&<span className="demo-tag">Demo</span>}</p><small><span className={`status ${i.status}`}>{statusLabels[i.status]}</span>{dateLabel(i.createdAt)}</small></div></a>)}</div>
        {!visible.length&&<div className="quiet-empty">{search||filter!=='all'?'No matching reports.':'No issues reported yet.'}</div>}
        <div className="inbox-secondary"><button className="text-button" disabled={busy} onClick={()=>void demo()}>{busy?'Opening…':'Open demo case'}<ArrowRight size={13}/></button><button className="muted-button" onClick={()=>setSetup(!setup)} aria-expanded={setup}>Model & connections</button></div>
        {setup&&<div className="setup-panel"><KnowledgeStatus/><ElementPicker building={building} value={selectedId} onChange={id=>id&&select(id)} onFocus={select}/><TopologyEditor building={building} selectedId={selectedId} onSelect={select}/></div>}
      </aside>
    </main>}
  </div>;
}
