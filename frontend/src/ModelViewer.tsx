import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { Box, Check, Crosshair, Expand, Layers, LoaderCircle, MousePointer2, RotateCcw, X } from 'lucide-react';
import type { Building, Entity, Impact } from './types';
import { entityLabel } from './types';

type Props={compact?:boolean;serviceMode?:boolean;contextIds?:string[];fitContextTick?:number;restoredIds?:string[];reportedIds:string[];suspectIds:string[];building:Building;selectedId:string|null;onSelect:(id:string)=>void;focus:{id:string|null;tick:number};impact:Impact|null;phase:'during'|'after';floor:string;setFloor:(value:string)=>void};
type Engine={scene:THREE.Scene;camera:THREE.PerspectiveCamera;controls:OrbitControls;root:THREE.Group;overlays:THREE.Group;dirty:boolean;fit:(box:THREE.Box3)=>void;home:()=>void;apply:()=>void};
const boxOf=(entity:Entity)=>new THREE.Box3(new THREE.Vector3(...entity.bounds.min as [number,number,number]),new THREE.Vector3(...entity.bounds.max as [number,number,number]));

export default function ModelViewer(props:Props){
  const {building,selectedId,onSelect,focus,impact,phase,floor,setFloor}=props;
  const container=useRef<HTMLDivElement>(null),engine=useRef<Engine|null>(null);
  const [systems,setSystems]=useState<string[]>(props.serviceMode?['architecture','hvac','electrical']:['architecture']);
  const [hideExterior,setHideExterior]=useState(false),[showLayers,setShowLayers]=useState(false);
  const [progress,setProgress]=useState({loaded:0,total:building.chunks.length,failed:0});
  const [error,setError]=useState('');
  const live=useRef({props,systems,hideExterior});live.current={props,systems,hideExterior};
  const mappedEntities=useMemo(()=>new Map(building.entities.map(e=>[e.id,e])),[building]);
  const entityMap=useRef(mappedEntities);entityMap.current=mappedEntities;
  const selected=selectedId?entityMap.current.get(selectedId):undefined;

  useEffect(()=>{
    const host=container.current;if(!host)return;
    let disposed=false,frame=0;
    const scene=new THREE.Scene();scene.background=new THREE.Color('#eaf0f0');
    let renderer:THREE.WebGLRenderer;
    try{renderer=new THREE.WebGLRenderer({antialias:true,powerPreference:'high-performance'});}catch{setError('3D graphics could not start. Enable hardware acceleration or use a WebGL-capable browser.');return;}
    renderer.setPixelRatio(Math.min(window.devicePixelRatio,1.75));renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=.85;renderer.setClearColor('#eaf0f0');
    renderer.domElement.setAttribute('aria-label','Interactive building model. Drag to orbit, right-drag to pan, scroll to zoom.');renderer.domElement.tabIndex=0;
    host.appendChild(renderer.domElement);
    const camera=new THREE.PerspectiveCamera(42,1,.05,4000), controls=new OrbitControls(camera,renderer.domElement);
    controls.enableDamping=true;controls.dampingFactor=.13;controls.maxPolarAngle=Math.PI*.92;controls.minDistance=.5;controls.maxDistance=700;
    controls.listenToKeyEvents(renderer.domElement);
    scene.add(new THREE.HemisphereLight(0xffffff,0x78898a,2.3));
    const sun=new THREE.DirectionalLight(0xfffbf3,2.7);sun.position.set(20,35,25);scene.add(sun);
    const fill=new THREE.DirectionalLight(0xd5ebff,1.2);fill.position.set(-20,12,-15);scene.add(fill);
    const root=new THREE.Group(),overlays=new THREE.Group();scene.add(root,overlays);
    const bounds=new THREE.Box3();const modelBounds=building.model.bounds as {min:[number,number,number];max:[number,number,number]}|undefined;
    if(modelBounds?.min&&modelBounds?.max)bounds.set(new THREE.Vector3(...modelBounds.min),new THREE.Vector3(...modelBounds.max));
    else building.entities.filter(e=>e.systemId!=='site').forEach(e=>bounds.union(boxOf(e)));
    if(bounds.isEmpty())bounds.set(new THREE.Vector3(-15,0,-15),new THREE.Vector3(15,25,15));
    const groundY=bounds.min.y-.08;const grid=new THREE.GridHelper(120,60,0xc1d0cf,0xdde5e4);grid.position.y=groundY;scene.add(grid);
    const fit=(box:THREE.Box3)=>{const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());const distance=Math.max(size.x,size.y,size.z,3)*1.6;
      camera.position.copy(center).add(new THREE.Vector3(1,.72,1.15).normalize().multiplyScalar(distance));controls.target.copy(center);camera.near=Math.max(.03,distance/1000);camera.updateProjectionMatrix();controls.update();engine.current&&(engine.current.dirty=true);};
    const disposeOverlay=()=>{for(const object of [...overlays.children]){overlays.remove(object);if(object instanceof THREE.Mesh||object instanceof THREE.LineSegments){if(!object.userData.borrowedGeometry)object.geometry.dispose();(Array.isArray(object.material)?object.material:[object.material]).forEach(m=>m.dispose());}}};
    const addBox=(entity:Entity,color:number,solid:boolean)=>{
      const bounds=boxOf(entity),size=bounds.getSize(new THREE.Vector3()).max(new THREE.Vector3(.12,.12,.12)),center=bounds.getCenter(new THREE.Vector3());
      const geometry=new THREE.BoxGeometry(size.x,size.y,size.z);
      const edges=new THREE.LineSegments(new THREE.EdgesGeometry(geometry),new THREE.LineBasicMaterial({color,transparent:true,opacity:.95,depthTest:false}));edges.position.copy(center);edges.renderOrder=20;overlays.add(edges);
      if(solid){const mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({color,transparent:true,opacity:.16,depthTest:false,depthWrite:false}));mesh.position.copy(center);mesh.renderOrder=19;overlays.add(mesh);}else geometry.dispose();
    };
    const apply=()=>{const state=live.current;disposeOverlay();
      const colors=new Map<string,number>();
      state.props.restoredIds?.forEach(id=>colors.set(id,0x21ab8b));
      if(state.props.impact){for(const id of [...state.props.impact.affectedRoomIds,...state.props.impact.affectedAssetIds])colors.set(id,state.props.phase==='during'?0x9872ce:0x388eb2);}
      state.props.suspectIds.forEach(id=>colors.set(id,0xe3a02a));state.props.reportedIds.forEach(id=>colors.set(id,0xe44545));
      root.updateMatrixWorld(true);root.traverse(obj=>{if(!(obj instanceof THREE.Mesh))return;const entity=entityMap.current.get(String(obj.userData.entityId));if(entity)obj.visible=state.systems.includes(entity.systemId)&&(state.props.floor==='all'||entity.floorId===state.props.floor)&&!(state.hideExterior&&entity.isExternal)&&entity.kind!=='room';
        const color=colors.get(String(obj.userData.entityId));if(entity&&color!==undefined&&entity.kind!=='room'&&(state.props.floor==='all'||entity.floorId===state.props.floor)){
          const highlight=new THREE.Mesh(obj.geometry,new THREE.MeshBasicMaterial({color,transparent:true,opacity:.88,depthTest:false,depthWrite:false}));
          highlight.userData.borrowedGeometry=true;highlight.matrixAutoUpdate=false;highlight.matrix.copy(obj.matrixWorld);highlight.renderOrder=22;overlays.add(highlight);
        }
      });
      colors.forEach((color,id)=>{const e=entityMap.current.get(id);if(e&&(state.props.floor==='all'||e.floorId===state.props.floor))addBox(e,color,e.kind==='room');});
      if(state.props.impact){for(const path of state.props.impact.paths){const points:THREE.Vector3[]=[];for(let i=1;i<path.nodes.length;i++){const a=entityMap.current.get(path.nodes[i-1]),b=entityMap.current.get(path.nodes[i]);if(a&&b)points.push(new THREE.Vector3(...a.center),new THREE.Vector3(...b.center));}if(points.length){const line=new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color:0x9867cb,depthTest:false,transparent:true,opacity:.85}));line.renderOrder=23;overlays.add(line);for(let j=0;j<points.length;j+=2){const dot=new THREE.Mesh(new THREE.SphereGeometry(.11,8,6),new THREE.MeshBasicMaterial({color:0x6936a2,depthTest:false}));dot.userData.flow=[points[j],points[j+1]];dot.renderOrder=25;overlays.add(dot);}}}}
      const chosen=state.props.selectedId?entityMap.current.get(state.props.selectedId):undefined;if(chosen&&!colors.has(chosen.id))addBox(chosen,0x087f79,chosen.kind==='room');
      if(engine.current)engine.current.dirty=true;
    };
    engine.current={scene,camera,controls,root,overlays,dirty:true,fit,home:()=>fit(bounds),apply};fit(bounds);
    const resize=new ResizeObserver(()=>{const w=host.clientWidth,h=host.clientHeight;if(w&&h){renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();engine.current&&(engine.current.dirty=true);}});resize.observe(host);
    const changed=()=>{if(engine.current)engine.current.dirty=true;};controls.addEventListener('change',changed);
    const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();let down=[0,0];
    const onDown=(e:PointerEvent)=>{down=[e.clientX,e.clientY];};
    const onUp=(event:PointerEvent)=>{if(event.button!==0||Math.hypot(event.clientX-down[0],event.clientY-down[1])>5)return;const rect=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);
      const picks:THREE.Object3D[]=[];root.traverse(o=>{if(o instanceof THREE.Mesh&&o.visible)picks.push(o);});const hit=raycaster.intersectObjects(picks,false)[0];if(hit?.object.userData.entityId)live.current.props.onSelect(String(hit.object.userData.entityId));};
    renderer.domElement.addEventListener('pointerdown',onDown);renderer.domElement.addEventListener('pointerup',onUp);
    const render=()=>{if(disposed)return;controls.update();overlays.children.forEach(o=>{if(o.userData.flow){o.position.lerpVectors(o.userData.flow[0],o.userData.flow[1],(performance.now()%2400)/2400);if(engine.current)engine.current.dirty=true;}});if(engine.current?.dirty){renderer.render(scene,camera);engine.current.dirty=false;}frame=requestAnimationFrame(render);};render();
    const loader=new GLTFLoader();let cursor=0,loaded=0,failed=0;
    const chunks=[...building.chunks].sort((a,b)=>Number(a.systemId==='site'||a.systemId==='structural')-Number(b.systemId==='site'||b.systemId==='structural'));
    const worker=async()=>{while(cursor<chunks.length&&!disposed){const chunk=chunks[cursor++];try{const gltf=await loader.loadAsync(chunk.url);if(disposed){gltf.scene.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();(Array.isArray(o.material)?o.material:[o.material]).forEach(m=>m.dispose());}});return;}
          gltf.scene.traverse(o=>{if(o instanceof THREE.Mesh){let ancestor:THREE.Object3D|null=o;while(ancestor&&!ancestor.userData.entityId)ancestor=ancestor.parent;if(ancestor)o.userData.entityId=ancestor.userData.entityId;const ent=entityMap.current.get(String(o.userData.entityId));const palette:Record<string,string>={architecture:'#dce1de',structural:'#afbeb8',hvac:'#69aaa4',electrical:'#c7a16c',site:'#a5bc9f'};const old=Array.isArray(o.material)?o.material:[o.material];o.material=new THREE.MeshStandardMaterial({color:palette[ent?.systemId||'']||'#d0d8d4',roughness:.8,metalness:.04,side:THREE.DoubleSide,transparent:!!live.current.props.serviceMode&&ent?.systemId==='architecture',opacity:live.current.props.serviceMode&&ent?.systemId==='architecture' ? 0.16 : 1,depthWrite:!(live.current.props.serviceMode&&ent?.systemId==='architecture')});old.forEach(m=>m.dispose());o.castShadow=false;o.receiveShadow=false;}});root.add(gltf.scene);loaded++;apply();
        }catch{failed++;}if(!disposed)setProgress({loaded,total:chunks.length,failed});}};
    void Promise.all([worker(),worker(),worker()]);
    return()=>{disposed=true;cancelAnimationFrame(frame);resize.disconnect();controls.removeEventListener('change',changed);controls.dispose();renderer.domElement.removeEventListener('pointerdown',onDown);renderer.domElement.removeEventListener('pointerup',onUp);scene.traverse(o=>{if(o instanceof THREE.Mesh||o instanceof THREE.LineSegments){o.geometry.dispose();(Array.isArray(o.material)?o.material:[o.material]).forEach(m=>m.dispose());}});renderer.dispose();host.removeChild(renderer.domElement);engine.current=null;};
  },[building]);
  useEffect(()=>{engine.current?.apply();},[systems,hideExterior,floor,selectedId,impact,phase,props.reportedIds,props.suspectIds,props.restoredIds]);
  useEffect(()=>{const e=focus.id?entityMap.current.get(focus.id):undefined;if(e){setSystems(current=>current.includes(e.systemId)?current:[...current,e.systemId]);setHideExterior(true);engine.current?.fit(boxOf(e));}else if(focus.tick)engine.current?.home();},[focus]);
  useEffect(()=>{if(!props.fitContextTick)return;const box=new THREE.Box3();props.contextIds?.forEach(id=>{const e=entityMap.current.get(id);if(e)box.union(boxOf(e));});if(!box.isEmpty())engine.current?.fit(box);},[props.fitContextTick]);
  const complete=progress.loaded+progress.failed===progress.total;
  return <section className={`model-stage ${props.compact?'compact-model':''}`} aria-label="Building model">
    <div className="model-canvas" ref={container}/>
    <div className="stage-heading">{props.compact?<strong>Building 1</strong>:<><div className="eyebrow"><span className="live-dot"/> INTERACTIVE BUILDING MODEL</div><h1>Building 1</h1><p>Building permit model <span> / </span> {floor==='all'?'All levels':building.floors.find(f=>f.id===floor)?.name||floor}</p></>}</div>
    <div className="stage-controls"><label className="floor-picker"><Layers size={16}/><select aria-label="Visible floor" value={floor} onChange={e=>setFloor(e.target.value)}><option value="all">All levels</option>{building.floors.map(f=><option key={f.id} value={f.id}>{f.name}</option>)}</select></label><button className={`control-button ${showLayers?'active':''}`} onClick={()=>setShowLayers(!showLayers)} title="Model layers" aria-label="Model layers"><Layers size={18}/></button><button className="control-button" onClick={()=>engine.current?.home()} title="Reset view" aria-label="Reset view"><RotateCcw size={18}/></button><button className="control-button" onClick={()=>{if(selected)engine.current?.fit(boxOf(selected));}} disabled={!selected} title="Focus selection" aria-label="Focus selection"><Crosshair size={18}/></button><button className="control-button" onClick={()=>{const el=container.current?.parentElement;if(document.fullscreenElement)void document.exitFullscreen();else void el?.requestFullscreen();}} title="Full screen" aria-label="Full screen"><Expand size={18}/></button></div>
    {showLayers&&<div className="layers-popover"><div className="popover-title">Model layers<button className="icon-button" aria-label="Close layers" onClick={()=>setShowLayers(false)}><X size={15}/></button></div>{building.systems.map(s=><label className="layer-toggle" key={s.id}><input type="checkbox" checked={systems.includes(s.id)} onChange={()=>setSystems(current=>current.includes(s.id)?current.filter(i=>i!==s.id):[...current,s.id])}/><span className="swatch" style={{background:s.color}}/>{s.name}</label>)}<label className="layer-toggle divider"><input type="checkbox" checked={hideExterior} onChange={e=>setHideExterior(e.target.checked)}/>Hide external envelope</label></div>}
    {!complete&&<div className="model-progress"><LoaderCircle className="spin" size={16}/><span>Loading model layers <strong>{progress.loaded}/{progress.total}</strong></span><progress value={progress.loaded+progress.failed} max={progress.total}/></div>}
    {(error||progress.failed>0)&&<div className="model-warning" role="alert">{error||`${progress.failed} model layers could not load. Refresh to retry; reports and analysis remain available.`}</div>}
    {selected&&<div className="selection-card"><div className="selection-icon"><Box size={19}/></div><div className="selection-content"><span className="eyebrow">{selected.kind==='room'?'SELECTED ROOM':'SELECTED COMPONENT'}</span><strong>{selected.name||selected.ifcType}</strong><span>{selected.floorName||selected.floorId} · {selected.serviceName||selected.systemId}</span><details><summary>Properties & source</summary><dl><dt>Original model name</dt><dd>{selected.originalName}</dd><dt>Naming basis</dt><dd>{selected.namingBasis}</dd><dt>IFC type</dt><dd>{selected.ifcType||'Not recorded'}</dd><dt>Original ID</dt><dd>{selected.ifcGlobalId||selected.id}</dd><dt>Source</dt><dd>{selected.source==='model'?'Original building model':'Demonstration assumption'}</dd>{Object.entries(selected.properties).slice(0,16).map(([key,value])=><div className="property-row" key={key}><dt>{key}</dt><dd>{typeof value==='object'?JSON.stringify(value):String(value)}</dd></div>)}</dl></details></div></div>}
    <div className="fault-legend">{props.reportedIds.length>0&&<span style={{color:'#c4454d'}}>● Reported</span>}{props.suspectIds.length>0&&<span style={{color:'#996d25'}}>● Candidate</span>}{impact&&<span style={{color:'#8057ad'}}>● Affected</span>}{!!props.restoredIds?.length&&<span style={{color:'#268265'}}>● Restored</span>}</div>{impact&&<div className="impact-key"><span className={`legend-dot ${phase}`}/>{phase==='during'?'During intervention':'After intervention'} · {impact.affectedRoomIds.length} affected rooms</div>}
    <div className="stage-footer"><span><MousePointer2 size={13}/> Drag to orbit <i/> Right-drag to pan <i/> Scroll to zoom</span><span>{complete&&!progress.failed?<Check size={13}/>:<Box size={13}/>} {progress.loaded} layers · {building.model.units}</span></div>
    <div className="model-room-select"><label htmlFor="find-room">Locate a room</label><select id="find-room" value={selected?.kind==='room'?selected.id:''} onChange={e=>e.target.value&&onSelect(e.target.value)}><option value="">Select a room…</option>{building.entities.filter(e=>e.kind==='room').map(e=><option key={e.id} value={e.id}>{entityLabel(e)}</option>)}</select></div>
  </section>;
}
