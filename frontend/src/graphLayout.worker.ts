import {forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide} from 'd3-force';
import type {SimulationNodeDatum} from 'd3-force';
import type {GraphData} from './types';

type Node = GraphData['nodes'][number] & SimulationNodeDatum;
self.onmessage = ({data}: MessageEvent<GraphData & {relevantIds:string[]}>) => {
  const relevant=new Set(data.relevantIds);
  const nodes: Node[] = data.nodes.map(n => ({...n}));
  const links = data.edges.map(e => ({source:e.source, target:e.target}));
  const simulation = forceSimulation(nodes)
    .force('links', forceLink<Node, {source:string|Node; target:string|Node}>(links).id(n=>n.id).distance(e=>relevant.has(typeof e.source==='string'?e.source:e.source.id)&&relevant.has(typeof e.target==='string'?e.target:e.target.id)?160:55).strength(.3))
    .force('charge', forceManyBody<Node>().strength(n=>relevant.has(n.id)?-350:-95).distanceMax(650))
    .force('collide', forceCollide<Node>(n=>relevant.has(n.id)?37:9))
    .force('center', forceCenter()).stop();
  simulation.tick(260);
  self.postMessage(nodes.map(n=>({id:n.id,x:n.x||0,y:n.y||0})));
  simulation.stop();
};
