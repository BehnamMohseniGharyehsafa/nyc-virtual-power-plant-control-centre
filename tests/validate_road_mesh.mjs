// Exercise the actual Three.js mesh generator, without a browser or GPU.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=process.cwd(),three=pathToFileURL(path.join(root,'app/static/vendor/three.module.js')).href;
const source=fs.readFileSync('app/static/city/transport.js','utf8').replace("'three'",JSON.stringify(three));
const {ribbonGeometry,shapeOf}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const THREE=await import(three);
const scene=JSON.parse(fs.readFileSync(0,'utf8')),nodes=new Map();let meshes=0,joins=0;const folds=[];
for(const road of scene.roads){
  if(road.walk||road.heights.every(y=>Math.abs(y)<.01))continue;
  for(const extra of [0,.7]){
    const offsets=road.end_joins.map(j=>j?j.miter.map(v=>v*(j.width+extra)/2):null);
    const sections=road.sections.map(s=>[s[0]+s[2]*extra/2,s[1]+s[3]*extra/2]);
    const mesh=ribbonGeometry(road.points,road.render_width+extra,road.heights,extra?.6:0,offsets,sections);
    const p=mesh.attributes.position,index=mesh.index;
    assert.ok([...p.array].every(Number.isFinite),road.id+' finite vertices');
    // The top faces must not fold over on tight bends or become back-facing.
    for(let i=0;i<(road.points.length-1)*6;i+=3){
      const a=index.getX(i),b=index.getX(i+1),c=index.getX(i+2);
      const cross=(p.getZ(b)-p.getZ(a))*(p.getX(c)-p.getX(a))-(p.getX(b)-p.getX(a))*(p.getZ(c)-p.getZ(a));
      if(cross < -1e-3)folds.push({id:road.id,name:road.name,segment:Math.floor(i/6),extra,area:cross});
    }
    for(const [end,vertex] of [[0,0],[-1,(road.points.length-1)*2]]){
      if(!road.end_joins[end===0?0:1])continue;
      const node=road.points.at(end).map(v=>Math.round(v*100)).join(',')+'/'+road.levels.at(end)+'/'+extra;
      const edges=[0,1].map(k=>[p.getX(vertex+k),p.getY(vertex+k),p.getZ(vertex+k)]);
      if(nodes.has(node)){
        const other=nodes.get(node);
        const error=Math.min(...[other,[...other].reverse()].map(pair=>Math.max(...pair.map((v,k)=>Math.hypot(...v.map((x,j)=>x-edges[k][j]))))));
        assert.ok(error<.003,road.id+' deck-edge seam: '+error);joins++;
      }else nodes.set(node,edges);
    }
    mesh.dispose();meshes++;
  }
}
if(folds.length)console.error(JSON.stringify(folds));
assert.equal(folds.length,0,'inverted road triangles');
assert.ok(joins>100,'insufficient real raised-road joins checked');
const ground=scene.road_terrain.terrain.map(rings=>{
  const geometry=new THREE.ShapeGeometry(shapeOf(rings));geometry.rotateX(-Math.PI/2);
  const mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({side:THREE.DoubleSide}));mesh.position.y=-.15;mesh.updateMatrixWorld(true);return mesh;
});
const ray=new THREE.Raycaster();let openCutSamples=0;
for(const road of scene.roads)if(!road.walk)for(let i=0;i<road.points.length;i++)if(road.heights[i]<-.2){
  ray.set(new THREE.Vector3(road.points[i][0],100,road.points[i][1]),new THREE.Vector3(0,-1,0));
  assert.equal(ray.intersectObjects(ground,false).length,0,road.id+' hidden by rendered terrain');openCutSamples++;
}
assert.ok(openCutSamples>100);
console.log(JSON.stringify({meshes,matchedDeckEdgeJoins:joins,openCutSamples}));
