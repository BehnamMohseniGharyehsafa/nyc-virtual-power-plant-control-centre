import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {mergeGeometries} from '/static/vendor/BufferGeometryUtils.js';
import {RoundedBoxGeometry} from 'three/addons/geometries/RoundedBoxGeometry.js';
import {createRendering,patchWindows,patchFoliage,motionPreference,U} from './rendering.js';
import {facadeAttributes,patchFacade,patchNearDetail,DETAIL_DISTANCE} from './clarity.js';
import {ribbonGeometry,ribbonEdges,buildBridges,shapeOf} from './transport.js';

const host=document.querySelector('#world');
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(38,1,1,7000);
const renderer=new THREE.WebGLRenderer({antialias:false,alpha:false,powerPreference:'high-performance'});
host.appendChild(renderer.domElement);
const presentation=createRendering(renderer,scene,camera,host);
const controls=new OrbitControls(camera,renderer.domElement);
controls.enableDamping=true;controls.dampingFactor=.075;controls.screenSpacePanning=false;
controls.minDistance=12;controls.maxDistance=5500;controls.maxPolarAngle=Math.PI*.485;
controls.target.set(0,24,0);camera.position.set(...(innerHeight<450?[230,205,300]:[330,285,430]));controls.update();
const clock=new THREE.Clock();
const buildings=new Map(),pickables=[],windowFrames=[],windowGlass=[],windowBars=[],windowSills=[],roofPanels=[],treePoints=[],lampPoints=[],carParts=[],nearDetails=[];
const networkGroup=new THREE.Group();networkGroup.visible=false;scene.add(networkGroup);
const overlayGroup=new THREE.Group();scene.add(overlayGroup);
const vehicleGroup=new THREE.Group();scene.add(vehicleGroup);
const materials={};const boxGeo=new THREE.BoxGeometry(1,1,1);
let data,traffic,state,selected=0,runId=new URLSearchParams(location.search).get('run');
let pausedTraffic=motionPreference.matches,trafficTime=0,networkVisible=false;
let lightMode='simulation';
let lastStep=-1,lastMap=0,flight=null,pendingState=null,waterMaterials=[];
let renderFrames=0,trafficFrame=0,selectedRing=null,readyForRender=false,renderDirty=true;
let lastPointerCheck=0,recording=false;
const pointer=new THREE.Vector2(),raycaster=new THREE.Raycaster();
const dummy=new THREE.Object3D(),transform=new THREE.Matrix4(),carBase=new THREE.Matrix4();
const rand=(n)=>{let x=Math.sin(n*12.9898+78.233)*43758.5453;return x-Math.floor(x);};
const clamp=THREE.MathUtils.clamp;
const loading=(text)=>{document.querySelector('#loading-detail').textContent=text;};
const colour=(hex)=>new THREE.Color(hex);
const textureCache=new Map();
let inspectorOpen=false;

function mat(name,params){return materials[name]??=(new THREE.MeshStandardMaterial(params));}
function makeCanvas(w,h){const c=document.createElement('canvas');c.width=w;c.height=h;return c;}
function brickTexture(style,tint){
  const key=`brick-${style}-${tint}`;if(textureCache.has(key))return textureCache.get(key);
  const c=makeCanvas(512,512),g=c.getContext('2d');g.fillStyle=tint;g.fillRect(0,0,512,512);
  const bw=style==='stone'?256:128,bh=style==='stone'?128:51.2;
  for(let y=0,row=0;y<512;y+=bh,row++)for(let x=-bw;x<512;x+=bw){
    const xx=x+(row%2)*bw/2,v=rand(x*3+y*7+33);
    g.fillStyle=`rgba(${v>.5?'255,218,185':'40,26,21'},${.04+v*.17})`;g.fillRect(xx+2,y+2,bw-4,bh-4);
    g.fillStyle=style==='stone'?'#77766b':'#b6a28c';g.globalAlpha=.48;g.fillRect(xx,y,bw,2.5);g.fillRect(xx,y,2.5,bh);g.globalAlpha=1;
  }
  const image=g.getImageData(0,0,512,512);for(let i=0;i<image.data.length;i+=4){const noise=(rand(i+83)-.5)*16;for(let k=0;k<3;k++)image.data[i+k]+=noise;}g.putImageData(image,0,0);
  const texture=new THREE.CanvasTexture(c);texture.wrapS=texture.wrapT=THREE.RepeatWrapping;
  texture.repeat.set(style==='stone'?.5:1,style==='stone'?.5:1);texture.colorSpace=THREE.SRGBColorSpace;
  texture.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());textureCache.set(key,texture);return texture;
}
function mortarTexture(style){
  const key=`mortar-${style}`;if(textureCache.has(key))return textureCache.get(key);
  const c=makeCanvas(512,512),g=c.getContext('2d');g.fillStyle='#bcbcbc';g.fillRect(0,0,512,512);
  const bw=style==='stone'?256:128,bh=style==='stone'?128:51.2;
  g.strokeStyle='#323232';g.lineWidth=3;
  for(let y=0,row=0;y<512;y+=bh,row++)for(let x=-bw;x<512;x+=bw)g.strokeRect(x+(row%2)*bw/2,y,bw,bh);
  const t=new THREE.CanvasTexture(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;t.repeat.set(style==='stone'?.5:1,style==='stone'?.5:1);
  t.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());textureCache.set(key,t);return t;
}
function pavementTexture(){
  const c=makeCanvas(512,512),g=c.getContext('2d');g.fillStyle='#b0afa3';g.fillRect(0,0,512,512);
  g.strokeStyle='#7c7e75';g.lineWidth=1.7;for(let p=0;p<512;p+=128){g.beginPath();g.moveTo(p,0);g.lineTo(p,512);g.moveTo(0,p);g.lineTo(512,p);g.stroke();}
  for(let i=0;i<12000;i++){const p=rand(i+5)*512,q=rand(i+17)*512;g.fillStyle=i%2?'#d5d2c340':'#62665f20';g.fillRect(p,q,1,1);}
  const t=new THREE.CanvasTexture(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;t.repeat.set(.16,.16);t.colorSpace=THREE.SRGBColorSpace;return t;
}
function asphaltTexture(){
  const c=makeCanvas(256,256),g=c.getContext('2d'),im=g.createImageData(256,256);
  for(let i=0;i<im.data.length;i+=4){const v=92+rand(i)*25;im.data[i]=v*.88;im.data[i+1]=v*.94;im.data[i+2]=v;im.data[i+3]=255;}
  g.putImageData(im,0,0);const t=new THREE.CanvasTexture(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;t.repeat.set(.12,.12);t.colorSpace=THREE.SRGBColorSpace;return t;
}
function panelTexture(){
  const c=makeCanvas(128,256),g=c.getContext('2d');g.fillStyle='#182a40';g.fillRect(0,0,128,256);
  for(let y=3;y<254;y+=31)for(let x=3;x<126;x+=31){g.fillStyle=(x+y)%3?'#233c58':'#294865';g.fillRect(x,y,28,28);}
  g.strokeStyle='#7893ad';g.lineWidth=.6;for(let y=16;y<256;y+=31){g.beginPath();g.moveTo(0,y);g.lineTo(128,y);g.stroke();}
  g.strokeStyle='#a4b1b9';g.lineWidth=3;g.strokeRect(0,0,128,256);const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;return t;
}
function glazingTexture(){
  const c=makeCanvas(128,256),g=c.getContext('2d'),grad=g.createLinearGradient(0,0,45,256);
  grad.addColorStop(0,'#536f7a');grad.addColorStop(.42,'#90aab3');grad.addColorStop(.51,'#6d838b');grad.addColorStop(1,'#334951');
  g.fillStyle=grad;g.fillRect(0,0,128,256);
  g.fillStyle='#b6cbd0';g.globalAlpha=.1;g.fillRect(7,0,13,256);g.fillRect(90,0,6,256);g.globalAlpha=1;
  const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;return t;
}
// Explicit depth ordering keeps almost-coplanar map layers from striping when
// seen at grazing angles. Geometry coordinates remain the observed street data.
const roadMaterial=mat('asphalt',{map:asphaltTexture(),color:0xc5c4bd,roughness:.94,polygonOffset:true,polygonOffsetFactor:-3,polygonOffsetUnits:-3});
const walkMaterial=mat('pavement',{map:pavementTexture(),color:0xe4e0d4,roughness:.96,polygonOffset:true,polygonOffsetFactor:-2,polygonOffsetUnits:-2});
const curbMaterial=mat('curb',{color:0xa6a99e,roughness:.94,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1});
const whitePaint=mat('white-road-paint',{color:0xe5e1ce,roughness:.92,polygonOffset:true,polygonOffsetFactor:-4,polygonOffsetUnits:-4});
const yellowPaint=mat('yellow-road-paint',{color:0xcbb56b,roughness:.92,polygonOffset:true,polygonOffsetFactor:-4,polygonOffsetUnits:-4});
const copper=mat('copper',{color:0x685347,roughness:.8});
const mechanical=mat('mechanical',{color:0xaeb6b6,roughness:.64,metalness:.28});
const dark=mat('dark-metal',{color:0x27383d,roughness:.52,metalness:.32});
const frameMaterial=mat('window-frame',{color:0x4c514d,roughness:.57,metalness:.3,side:THREE.DoubleSide});
const glassMaterial=mat('window-glass',{color:0xa0b0b2,map:glazingTexture(),roughness:.16,metalness:.32,envMapIntensity:1.15,side:THREE.DoubleSide});
patchWindows(glassMaterial);
patchNearDetail(glassMaterial);patchNearDetail(frameMaterial);
const panelMaterial=mat('solar-panel',{color:0xffffff,map:panelTexture(),metalness:.35,roughness:.29});
patchNearDetail(panelMaterial);

function object(geometry,material,position,scale=null,parent=scene){
  const mesh=new THREE.Mesh(geometry,material);mesh.position.set(...position);if(scale)mesh.scale.set(...scale);parent.add(mesh);return mesh;
}
function cube(material,x,y,z,sx,sy,sz,parent=scene){return object(boxGeo,material,[x,y,z],[sx,sy,sz],parent);}
function flatShape(rings,y,material){
  const geometry=new THREE.ShapeGeometry(shapeOf(rings));geometry.rotateX(-Math.PI/2);
  const mesh=object(geometry,material,[0,y,0]);mesh.receiveShadow=true;return mesh;
}
function inside(p,ring){
  let found=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){
    const a=ring[i],b=ring[j];if(((a[1]>p[1])!==(b[1]>p[1]))&&(p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]))found=!found;
  }return found;
}
function onBuilding(p,margin=0){
  return data.buildings.some(b=>Math.hypot(p[0]-b.centre[0],p[1]-b.centre[1])<Math.sqrt(b.area)+margin&&b.parts.some(part=>inside(p,part.rings[0])));
}
function ribbon(points,width,y,material,thickness=0,endOffsets=[null,null],pointOffsets=null){
  const mesh=object(ribbonGeometry(points,width,y,thickness,endOffsets,pointOffsets),material,[0,0,0]);mesh.receiveShadow=true;return mesh;
}
function roadOffsets(road,width){return road.end_joins.map(join=>join?join.miter.map(v=>v*(join.width+width-road.render_width)/2):null);}
function roadSections(road,width){const extra=(width-road.render_width)/2;return road.sections.map(s=>[s[0]+s[2]*extra,s[1]+s[3]*extra]);}
function roadRibbon(road,width,ys,material,thickness=0){return ribbon(road.points,width,ys,material,thickness,roadOffsets(road,width),roadSections(road,width));}
function segmentBox(a,b,y,width,height,material,endY=y){
  // Paint is a two-triangle surface, rather than a twelve-triangle solid.
  if(material===whitePaint||material===yellowPaint)return ribbon([a,b],width,[y,endY],material);
  const d=new THREE.Vector3(b[0]-a[0],endY-y,b[1]-a[1]),length=d.length();if(length<.01)return;
  const mesh=cube(material,(a[0]+b[0])/2,(y+endY)/2,(a[1]+b[1])/2,width,height,length);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),d.multiplyScalar(1/length));return mesh;
}
function ground(){
  const groundMaterial=mat('ground',{color:0xa6ad9e,roughness:1});
  for(const polygon of data.road_terrain.terrain)flatShape(polygon,-.15,groundMaterial);
  const floorGeometry=new THREE.BufferGeometry();floorGeometry.setAttribute('position',new THREE.Float32BufferAttribute(data.road_terrain.floor_vertices.flat(),3));floorGeometry.computeVertexNormals();
  object(floorGeometry,mat('cut-floor',{color:0x8d9287,roughness:1}),[0,0,0]).receiveShadow=true;
  const wallVertices=[];
  for(const ring of data.road_terrain.walls)for(let i=1;i<ring.length;i++){
    const a=ring[i-1],b=ring[i],A=[a[0],-.15,a[2]],B=[b[0],-.15,b[2]];
    wallVertices.push(...A,...a,...B,...B,...a,...b);
  }
  const walls=new THREE.BufferGeometry();walls.setAttribute('position',new THREE.Float32BufferAttribute(wallVertices,3));walls.computeVertexNormals();
  const retaining=object(walls,mat('retaining-wall',{color:0xa4a69e,roughness:.96,side:THREE.DoubleSide}),[0,0,0]);retaining.receiveShadow=true;retaining.castShadow=true;
  const pixels=new Uint8Array(256*256*4);
  for(let y=0;y<256;y++)for(let x=0;x<256;x++){
    const i=(y*256+x)*4,nx=Math.sin(x*.22+y*.13)*.16+Math.sin(y*.39)*.08,ny=Math.cos(y*.27-x*.11)*.17;
    pixels[i]=(nx*.5+.5)*255;pixels[i+1]=(ny*.5+.5)*255;pixels[i+2]=Math.sqrt(1-nx*nx-ny*ny)*255;pixels[i+3]=255;
  }
  const normal=new THREE.DataTexture(pixels,256,256);normal.wrapS=normal.wrapT=THREE.RepeatWrapping;normal.repeat.set(.028,.028);normal.magFilter=THREE.LinearFilter;normal.minFilter=THREE.LinearMipmapLinearFilter;normal.generateMipmaps=true;normal.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());normal.needsUpdate=true;
  for(const polygon of data.water){
    const water=new THREE.MeshStandardMaterial({color:0x285461,metalness:.12,roughness:.32,normalMap:normal,normalScale:new THREE.Vector2(.055,.055),envMapIntensity:1.1,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-4});
    waterMaterials.push(water);const surface=flatShape(polygon,-.05,water);surface.userData.noAO=true;
  }
}
function streets(){
  // Unioned surfaces share intersection interiors; pavements cannot cover a neighbouring road.
  for(const [key,y,material] of [['curb',.02,curbMaterial],['pavement',.045,walkMaterial],['asphalt',.075,roadMaterial]]){
    for(const polygon of data.street_surfaces[key])flatShape(polygon,y,material);
  }
  const bridgeConcrete=mat('bridge-concrete',{color:0xaaa9a1,roughness:1});
  const bridgeEdge=mat('bridge-edge',{color:0x89928f,roughness:.8});
  for(const junction of data.road_terrain.junctions){
    flatShape(junction.rings,junction.height+.075,roadMaterial);
    const g=new THREE.ExtrudeGeometry(shapeOf(junction.rings),{depth:.6,bevelEnabled:false});g.rotateX(-Math.PI/2);
    object(g,bridgeEdge,[0,junction.height-.7,0]).receiveShadow=true;
  }
  const groundRoads=data.roads.filter(r=>!r.walk&&r.heights.every(y=>Math.abs(y)<.05));
  const blocksPier=p=>groundRoads.some(r=>r.points.slice(1).some((b,i)=>{
    const a=r.points[i],dx=b[0]-a[0],dz=b[1]-a[1],f=clamp(((p[0]-a[0])*dx+(p[1]-a[1])*dz)/(dx*dx+dz*dz||1),0,1);
    return Math.hypot(p[0]-a[0]-f*dx,p[1]-a[1]-f*dz)<r.width/2+1;
  }));
  for(let ri=0;ri<data.roads.length;ri++){
    const road=data.roads[ri],pts=road.points,width=road.width,ys=road.heights;
    const raised=ys.some(y=>Math.abs(y)>.01);
    if(road.walk){roadRibbon(road,road.render_width,ys.map(y=>y+.12),walkMaterial,raised?.25:0);continue;}
    if(raised){
      roadRibbon(road,width+.7,ys.map(y=>y-.1),bridgeEdge,.6);
      roadRibbon(road,width,ys.map(y=>y+.075),roadMaterial);
      roadRails(road);
    }
    let cumulative=0;
    for(let j=0;j<pts.length-1;j++){
      const a=pts[j],b=pts[j+1],dx=b[0]-a[0],dz=b[1]-a[1],length=Math.hypot(dx,dz),ux=dx/length,uz=dz/length;
      if(length<.01)continue;
      const y=ys[j],endY=ys[j+1],height=s=>y+(endY-y)*s/length;
      const start=(!raised&&j===0&&road.crosswalks[0])?12:0;
      const end=(!raised&&j===pts.length-2&&road.crosswalks[1])?length-12:length;
      if(road.direction==='TW'&&end>start){
        for(const offset of [-.15,.15])segmentBox([a[0]+ux*start-uz*offset,a[1]+uz*start+ux*offset],[a[0]+ux*end-uz*offset,a[1]+uz*end+ux*offset],height(start)+.1,.08,.018,yellowPaint,height(end)+.1);
      }else if(width>6.4){
        const lanes=Math.max(1,Math.min(4,Math.round(road.lanes)||Math.round(width/3.3)));
        for(let lane=1;lane<lanes;lane++){
          const offset=-width/2+width*lane/lanes;
          for(let s=Math.ceil((cumulative+start)/10)*10-cumulative;s<end;s+=10){
            const e=Math.min(s+3,end);if(e<=s)continue;
            segmentBox([a[0]+ux*s-uz*offset,a[1]+uz*s+ux*offset],[a[0]+ux*e-uz*offset,a[1]+uz*e+ux*offset],height(s)+.1,.12,.018,whitePaint,height(e)+.1);
          }
        }
      }
      if(raised){
        // Every segment gets a slab and rails; suspension supports serve the channel.
        const bridge=road.spine?data.bridges.find(v=>v.id===road.bridge):null,mid=[(a[0]+b[0])/2,(a[1]+b[1])/2];
        const station=bridge?(mid[0]-bridge.centre[0])*bridge.axis[0]+(mid[1]-bridge.centre[1])*bridge.axis[1]:Infinity;
        const approach=!bridge||Math.abs(station)>bridge.main_span/2+bridge.side_span;
        if(approach){
          for(let s=Math.ceil((cumulative+1)/48)*48-cumulative;s<length;s+=48){
            const h=height(s);if(h<3)continue;
            for(const side of [-1,1]){
              const off=(width/2+.9)*side,p=[a[0]+ux*s-uz*off,a[1]+uz*s+ux*off];
              if(!blocksPier(p)&&!onBuilding(p,1)&&!data.road_terrain.cutouts.some(poly=>inside(p,poly[0]))&&!data.water.some(poly=>inside(p,poly[0])))cube(bridgeConcrete,p[0],h/2,p[1],.9,h,1.5);
            }
          }
        }
      }
      if(!raised&&road.kind==='1'&&length>28){
        const ends=[];if(j===0&&road.crosswalks[0])ends.push(8);if(j===pts.length-2&&road.crosswalks[1])ends.push(length-8);
        for(const end of ends)for(let w=-width/2+.6;w<width/2-.6;w+=1.35){
          const cx=a[0]+ux*end-uz*w,cz=a[1]+uz*end+ux*w;
          segmentBox([cx-ux*1.4,cz-uz*1.4],[cx+ux*1.4,cz+uz*1.4],.105,.62,.025,whitePaint);
        }
      }
      if(!raised&&road.kind==='1'&&Math.hypot(a[0],a[1])<850)for(let s=20;s<length-8;s+=37){
        const side=ri%2?1:-1,off=width/2+1.3,pos=[a[0]+ux*s-uz*off*side,a[1]+uz*s+ux*off*side];
        if(!onBuilding(pos,2))treePoints.push({p:pos,seed:ri*49+s});
        if(s%74<40&&!onBuilding(pos,2))streetLight(pos,[-uz*side,ux*side]);
      }
      cumulative+=length;
    }
  }
  buildBridges(scene,data.bridges,U.night);
}
function contextBuildings(){
  const batches=new Map();
  for(const [index,b] of data.context_buildings.entries()){
    const variant=Math.floor(rand(Number(b.bin))*3),material=mat('context',{color:0xffffff,vertexColors:true,roughness:.92});
    if(!material.userData.filteredFacade){patchFacade(material,U.night);material.userData.filteredFacade=true;}
    for(const part of b.parts){
      const geo=new THREE.ExtrudeGeometry(shapeOf(part),{depth:b.height,bevelEnabled:false,curveSegments:1});geo.rotateX(-Math.PI/2);
      facadeAttributes(geo,{height:b.height,floors:Math.max(1,Math.round(b.height/3.4)),style:'stone',index:index+1000},{rings:part,exposed:part[0].map(()=>true)});
      const tint=new THREE.Color([0xaaa699,0xb5b2a7,0x9a9d95][variant]),colours=new Float32Array(geo.attributes.position.count*3);
      for(let i=0;i<colours.length;i+=3)colours.set([tint.r,tint.g,tint.b],i);
      geo.setAttribute('color',new THREE.BufferAttribute(colours,3));
      const c=part[0][0],key=`${Math.floor(c[0]/360)},${Math.floor(c[1]/360)}`;
      if(!batches.has(key))batches.set(key,{material,geometries:[]});batches.get(key).geometries.push(geo);
    }
  }
  for(const {material,geometries} of batches.values()){
    const mesh=object(mergeGeometries(geometries),material,[0,0,0]);mesh.receiveShadow=true;mesh.userData.noAO=true;
    geometries.forEach(g=>g.dispose());
  }
}
function roadRails(road){
  const edges=ribbonEdges(road.points,road.width+.4,road.heights,roadOffsets(road,road.width+.4),roadSections(road,road.width+.4));
  const lengths=[0];for(let i=1;i<road.points.length;i++)lengths.push(lengths[i-1]+Math.hypot(road.points[i][0]-road.points[i-1][0],road.points[i][1]-road.points[i-1][1]));
  const from=road.junction_clearance[0],to=lengths.at(-1)-road.junction_clearance[1];
  const bridge=road.spine?data.bridges.find(b=>b.id===road.bridge):null;
  const station=p=>bridge?(p[0]-bridge.centre[0])*bridge.axis[0]+(p[1]-bridge.centre[1])*bridge.axis[1]:Infinity;
  const anchor=bridge?bridge.main_span/2+bridge.side_span:0;
  for(const side of [0,1]){
    let points=[],ys=[];
    const flush=()=>{if(points.length>1)ribbon(points,.16,ys,dark,1.05);points=[];ys=[];};
    for(let i=1;i<edges.length;i++){
      const length=lengths[i]-lengths[i-1],cuts=[0,1],a=edges[i-1][side],b=edges[i][side];
      for(const s of [from,to]){const t=(s-lengths[i-1])/length;if(t>0&&t<1)cuts.push(t);}
      if(bridge){const sa=station(road.points[i-1]),sb=station(road.points[i]);for(const s of [-anchor,anchor]){const t=(s-sa)/(sb-sa);if(t>0&&t<1)cuts.push(t);}}
      cuts.sort((a,b)=>a-b);
      for(let j=1;j<cuts.length;j++){
        const lo=cuts[j-1],hi=cuts[j],mid=(lo+hi)/2,s=lengths[i-1]+length*mid;
        const p=[road.points[i-1][0]+(road.points[i][0]-road.points[i-1][0])*mid,road.points[i-1][1]+(road.points[i][1]-road.points[i-1][1])*mid];
        if(s<from||s>to||(bridge&&Math.abs(station(p))<=anchor)){flush();continue;}
        const sample=t=>[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t+1.17,a[2]+(b[2]-a[2])*t];
        const A=sample(lo),B=sample(hi);if(!points.length){points.push([A[0],A[2]]);ys.push(A[1]);}points.push([B[0],B[2]]);ys.push(B[1]);
      }
    }
    flush();
  }
}
function streetLight(p,n){
  lampPoints.push({p:[p[0]-n[0]*1.2,.135,p[1]-n[1]*1.2],s:[12,1,12]});
  const pole=object(new THREE.CylinderGeometry(.065,.095,6.8,6),dark,[p[0],3.4,p[1]]);
  const arm=cube(dark,p[0]-n[0]*.65,6.75,p[1]-n[1]*.65,1.4,.08,.08);arm.rotation.y=-Math.atan2(n[1],n[0]);
  cube(mat('lamp',{color:0xd3d9d6,emissive:0xffdb94,emissiveIntensity:.13}),p[0]-n[0]*1.2,6.73,p[1]-n[1]*1.2,.6,.12,.28);
}
function streetGlow(){
  // Estimated lamp pools add street readability without hundreds of real lights.
  const c=makeCanvas(128,128),g=c.getContext('2d'),gradient=g.createRadialGradient(64,64,2,64,64,64);
  gradient.addColorStop(0,'#ffd89d60');gradient.addColorStop(.45,'#e4b77025');gradient.addColorStop(1,'#d3b18000');g.fillStyle=gradient;g.fillRect(0,0,128,128);
  const material=new THREE.MeshBasicMaterial({map:new THREE.CanvasTexture(c),transparent:true,opacity:0,depthWrite:false,blending:THREE.AdditiveBlending});materials['street-pools']=material;
  const geo=new THREE.PlaneGeometry(1,1);geo.rotateX(-Math.PI/2);const mesh=instances(lampPoints,geo,material);mesh.userData.noAO=true;
}

function makeBuilding(b){
  const variant=Math.floor(rand(Number(b.bin))*5),style=b.style;
  const palette=style==='brick'?['#8e6250','#a27b61','#765e51','#b0987b','#8b7060']:style==='brownstone'?['#7c6254','#9c8069','#7b7062','#9a8977','#786558']:['#b4b3a8','#a7aca7','#c0baaa','#a9a69d','#c2c2b8'];
  const textureKind=style==='stone'||style==='glass'?'stone':'brick';
  const tone=palette[variant],wall=mat(`wall-${style}-${variant}`,{color:0xffffff,map:brickTexture(textureKind,tone),bumpMap:mortarTexture(textureKind),bumpScale:style==='glass'?.008:.035,roughness:style==='glass'?.45:.94,metalness:style==='glass'?.12:0});
  if(!wall.userData.filteredFacade){patchFacade(wall,U.night);wall.userData.filteredFacade=true;}
  const roof=mat(`roof-${variant}`,{color:[0x7f827a,0x777e7d,0x98978b,0x858b88,0x6e7778][variant],roughness:.96});
  const trim=mat(`trim-${variant}`,{color:['#9e9380','#969184','#a19786','#b2a894','#918e83'][variant],roughness:.88});
  const group=new THREE.Group();group.userData.building=b;scene.add(group);
  for(const part of b.parts){
    const s=shapeOf(part.rings),geo=new THREE.ExtrudeGeometry(s,{depth:b.height,bevelEnabled:false,steps:1});geo.rotateX(-Math.PI/2);
    facadeAttributes(geo,b,part);
    const mesh=new THREE.Mesh(geo,[roof,wall]);mesh.castShadow=true;mesh.receiveShadow=true;mesh.userData.building=b;group.add(mesh);pickables.push(mesh);
    const ring=part.rings[0];
    const detailed=Math.hypot(...b.centre)<620&&b.index<600;
    const floors=clamp(b.floors,1,45),fh=b.height/floors;
    for(let j=0;j<ring.length;j++){
      const a=ring[j],c=ring[(j+1)%ring.length],dx=c[0]-a[0],dz=c[1]-a[1],length=Math.hypot(dx,dz);if(length<1)continue;
      const nx=-dz/length,nz=dx/length,rotation=Math.atan2(nx,nz);
      const cornice=segmentBox(a,c,b.height+.1,.45,.38,trim);group.attach(cornice);
      if(detailed){
        group.attach(segmentBox(a,c,b.height-.22,.27,.23,trim));
        group.attach(segmentBox(a,c,.38,.22,.7,trim));
      }
      if(detailed&&style==='brick'&&b.height>15){
        for(let f=3;f<floors;f+=4){const ledge=segmentBox(a,c,f*fh,.16,.12,trim);group.attach(ledge);}
      }
      if(!detailed||!part.exposed[j]||length<2.4)continue;
      const bays=Math.floor(length/(style==='glass'?2.05:2.85));if(!bays)continue;
      const spacing=length/bays,ww=Math.min(spacing*.66,style==='glass'?1.8:1.75),wh=Math.min(fh*.65,2.5);
      for(let floor=0;floor<floors;floor++)for(let bay=0;bay<bays;bay++){
        const along=(bay+.5)*spacing;
        const x=a[0]+dx*along/length+nx*.075,z=a[1]+dz*along/length+nz*.075;
        const y=floor*fh+fh*.53;
        const doorway=floor===0&&bay===Math.floor(bays/2)&&length>7;
        if(doorway){
          const door=cube(dark,x,1.35,z,1.55,2.7,.2);door.rotation.y=rotation;group.attach(door);
          const pane=cube(mat('entry-glass',{color:0x45616b,metalness:.35,roughness:.18}),x+nx*.13,1.5,z+nz*.13,1.22,2.12,.04);pane.rotation.y=rotation;group.attach(pane);
          const handle=cube(mechanical,x+nx*.2+dx/length*.35,1.2,z+nz*.2+dz/length*.35,.035,.45,.04);handle.rotation.y=rotation;group.attach(handle);
          const awning=cube(style==='brick'?dark:trim,x+nx*.65,3.15,z+nz*.65,2.1,.14,1.35);awning.rotation.y=rotation;awning.castShadow=true;group.attach(awning);
          continue;
        }
        windowFrames.push({p:[x,y,z],r:rotation,s:[ww+.17,wh+.19,.12],seed:b.index*91+floor*31+bay});
        windowGlass.push({p:[x+nx*.085,y,z+nz*.085],r:rotation,s:[ww,wh,.05],seed:b.index*91+floor*31+bay});
        if(style!=='glass'){
          windowBars.push({p:[x+nx*.12,y,z+nz*.12],r:rotation,s:[.055,wh,.06]});
          windowBars.push({p:[x+nx*.12,y+.12,z+nz*.12],r:rotation,s:[ww,.05,.06]});
          windowSills.push({p:[x+nx*.04,y-wh/2-.11,z+nz*.04],r:rotation,s:[ww+.28,.14,.3]});
        }
      }
      if(detailed&&style==='brick'&&length>18&&floors>3){
        for(let k=0;k<=bays;k+=3){const along=k*spacing;const pilaster=cube(trim,a[0]+dx*along/length,b.height/2,a[1]+dz*along/length,.22,b.height,.22);group.attach(pilaster);}
      }
    }
    if(detailed){roofEquipment(b,part,group);}
  }
  buildings.set(b.index,{data:b,group});
}
function roofEquipment(b,part,group){
  const c=b.centre,h=b.height,r=rand(Number(b.bin)+81);
  if(!inside(c,part.rings[0]))return;
  const unit=cube(mechanical,c[0],h+1.1,c[1],Math.min(4,Math.sqrt(b.area)*.12),1.8,3);unit.castShadow=true;group.attach(unit);
  for(const off of [-.8,.8]){
    const fan=object(new THREE.CylinderGeometry(.52,.52,.13,14),dark,[c[0]+off,h+2.08,c[1]]);group.attach(fan);
  }
  const access=cube(mat('roof-access',{color:0x96968c,roughness:.95}),c[0]+3,h+1.75,c[1]+3,2.8,3.3,3.2);access.castShadow=true;group.attach(access);
  if(b.height>22&&b.year<1945&&r>.55){
    const tx=c[0]-4,tz=c[1]+3;
    if(inside([tx,tz],part.rings[0])){
      const tank=object(new THREE.CylinderGeometry(1.55,1.55,3.3,14),copper,[tx,h+4.7,tz]);tank.castShadow=true;group.attach(tank);
      const cap=object(new THREE.ConeGeometry(1.75,1.15,14),mat('tank-cap',{color:0x626663,roughness:.8}),[tx,h+6.9,tz]);group.attach(cap);
      for(const ox of [-1,1])for(const oz of [-1,1])group.attach(cube(dark,tx+ox,h+1.7,tz+oz,.12,3.4,.12));
    }
  }
  const asset=data.assets[b.index];if(!asset||asset.pv_kw<1)return;
  const ring=part.rings[0],xs=ring.map(p=>p[0]),zs=ring.map(p=>p[1]);
  const minx=Math.min(...xs)+2,maxx=Math.max(...xs)-2,minz=Math.min(...zs)+2,maxz=Math.max(...zs)-2;
  const maxPanels=Math.min(1600,Math.floor(asset.pv_kw/.44));let count=0;
  for(let z=minz;z<maxz;z+=2.9)for(let x=minx;x<maxx;x+=1.28){
    if(count>=maxPanels)break;
    if(Math.hypot(x-c[0],z-c[1])<5.4||!inside([x,z],ring)||!inside([x+1.1,z+2.15],ring))continue;
    if(part.rings.slice(1).some(hole=>inside([x,z],hole)))continue;
    roofPanels.push({p:[x,b.height+.55,z],r:0,s:[1.08,.055,2.08],tilt:-.18});count++;
  }
}
function instances(items,geometry,material,colours=false){
  const mesh=new THREE.InstancedMesh(geometry,material,items.length);mesh.receiveShadow=true;
  for(let i=0;i<items.length;i++){
    const o=items[i];dummy.position.set(...o.p);dummy.rotation.set(o.tilt||0,o.r||0,0);dummy.scale.set(...o.s);dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix);
    if(colours){const v=rand(o.seed);mesh.setColorAt(i,o.color?new THREE.Color(o.color):material===glassMaterial?new THREE.Color().setRGB(.9+v*.1,.93+v*.07,.95+v*.05):new THREE.Color().setRGB(.63+v*.32,.7+v*.25,.74+v*.24));}
  }
  mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;
  mesh.userData.noAO=material===glassMaterial||material===frameMaterial;scene.add(mesh);return mesh;
}
function tiledInstances(items,geometry,material,colours=false,nearOnly=false){
  const tiles=new Map();
  const tileSize=nearOnly?75:180;
  for(const item of items){const key=`${Math.floor(item.p[0]/tileSize)},${Math.floor(item.p[2]/tileSize)}`;if(!tiles.has(key))tiles.set(key,[]);tiles.get(key).push(item);}
  for(const tile of tiles.values()){const mesh=instances(tile,geometry,material,colours);mesh.computeBoundingSphere();if(nearOnly)nearDetails.push(mesh);}
}
function batchEnvelopes(){
  // Keep original envelopes for accurate picking. Render tiled material batches;
  // batching the whole district in one mesh would defeat frustum culling.
  const batches=new Map();
  for(const original of pickables){
    const b=original.userData.building,tile=`${Math.floor(b.centre[0]/240)},${Math.floor(b.centre[1]/240)}`;
    const geometry=original.geometry.index?original.geometry.toNonIndexed():original.geometry.clone();
    for(const group of geometry.groups){
      const material=original.material[group.materialIndex],key=`${tile}/${material.uuid}`;
      const part=new THREE.BufferGeometry();
      for(const [name,attribute] of Object.entries(geometry.attributes))part.setAttribute(name,new THREE.BufferAttribute(attribute.array.slice(group.start*attribute.itemSize,(group.start+group.count)*attribute.itemSize),attribute.itemSize));
      if(!batches.has(key))batches.set(key,{material,geometries:[]});batches.get(key).geometries.push(part);
    }
    geometry.dispose();original.visible=false;
  }
  for(const {material,geometries} of batches.values()){
    const geometry=mergeGeometries(geometries);const mesh=new THREE.Mesh(geometry,material);mesh.castShadow=true;mesh.receiveShadow=true;scene.add(mesh);
    geometries.forEach(g=>g.dispose());
  }
}
function batchStaticCity(){
  // Merge roads, kerbs, markings, trims and roof furniture by material. Building
  // envelopes remain individually selectable; animated/instanced objects stay separate.
  scene.updateMatrixWorld(true);const batches=new Map();
  scene.traverse(object=>{
    if(!object.isMesh||object.isInstancedMesh||object.userData.building||Array.isArray(object.material))return;
    if(object.userData.noAO)return;
    const key=object.material.uuid;
    if(!batches.has(key))batches.set(key,[]);batches.get(key).push(object);
  });
  for(const objects of batches.values()){
    if(objects.length<2)continue;
    const geometries=objects.map(o=>{let g=o.geometry.clone();g.applyMatrix4(o.matrixWorld);if(g.index)g=g.toNonIndexed();return g;});
    const geometry=mergeGeometries(geometries,false);if(!geometry)continue;
    const mesh=new THREE.Mesh(geometry,objects[0].material);mesh.castShadow=objects.some(o=>o.castShadow);mesh.receiveShadow=true;
    for(const o of objects)o.parent.remove(o);for(const g of geometries)g.dispose();scene.add(mesh);
  }
}
function trees(){
  const geometry=new THREE.IcosahedronGeometry(1,1),pos=geometry.getAttribute('position');
  for(let i=0;i<pos.count;i++){const v=new THREE.Vector3().fromBufferAttribute(pos,i).multiplyScalar(.87+rand(i)*.25);pos.setXYZ(i,v.x,v.y,v.z);}geometry.computeVertexNormals();
  const trunks=[],crowns=[];
  for(let i=0;i<Math.min(treePoints.length,350);i++){
    const {p,seed}=treePoints[i],r=rand(seed);trunks.push({p:[p[0],1.8,p[1]],s:[.14,3.6,.14]});
    for(let k=0;k<3;k++)crowns.push({p:[p[0]+Math.cos(k*2.1)*1.05,4.4+r+rand(seed+k)*.7,p[1]+Math.sin(k*2.1)*.9],s:[1.6+r*.4,1.9+r*.6,1.55+r*.5],seed:seed+k,color:['#657447','#5b733c','#7b8550','#50643b'][Math.floor(rand(seed+k)*4)]});
  }
  instances(trunks,new THREE.CylinderGeometry(1,1.3,1,7),mat('tree-bark',{color:0x635442,roughness:1}));
  const leaves=instances(crowns,geometry,mat('tree-leaves',{color:0xffffff,roughness:.95}),true);leaves.castShadow=true;patchFoliage(leaves);
}
function vehicles(){
  const n=traffic.cars.length;
  const rounded=new RoundedBoxGeometry(1,1,1,2,.11);
  const cabinGeometry=new THREE.BoxGeometry(1,1,1),cabinPosition=cabinGeometry.attributes.position;
  for(let i=0;i<cabinPosition.count;i++)if(cabinPosition.getY(i)>0){cabinPosition.setX(i,cabinPosition.getX(i)*.76);cabinPosition.setZ(i,cabinPosition.getZ(i)*.84);}cabinGeometry.computeVertexNormals();
  const definitions=[
    ['body',rounded,mat('car-paint',{color:0xffffff,metalness:.62,roughness:.26}),[0,.64,0],[4.35,.73,1.8]],
    ['cabin',cabinGeometry,mat('car-body-upper',{color:0xffffff,metalness:.48,roughness:.26}),[-.27,1.14,0],[2.48,.65,1.65]],
    ['glass',cabinGeometry,mat('car-glass',{color:0x354d59,metalness:.4,roughness:.1}),[-.28,1.19,0],[2.4,.49,1.68]],
    ['roof',rounded,mat('car-roof',{color:0xffffff,metalness:.5,roughness:.28}),[-.28,1.47,0],[1.88,.08,1.4]],
    ['headlight',boxGeo,mat('car-headlight',{color:0xf2f0db,emissive:0xffe9ba,emissiveIntensity:.4}),[2.19,.7,0],[.035,.18,1.5]],
    ['taillight',boxGeo,mat('car-taillight',{color:0x8e1f24,emissive:0xff2924,emissiveIntensity:.2}),[-2.19,.7,0],[.035,.15,1.5]],
    ['grille',boxGeo,dark,[2.19,.48,0],[.04,.18,.65]],
    ['bumper',rounded,mechanical,[2.15,.32,0],[.18,.16,1.5]],
  ];
  const palette=['#d4d8d5','#3c4e5b','#c4b9a5','#8d4f43','#6c7d86','#e4e1d6','#33403f','#8c9295'];
  for(const [name,geo,material,p,s] of definitions){
    const mesh=new THREE.InstancedMesh(geo,material,n);mesh.receiveShadow=true;mesh.frustumCulled=false;vehicleGroup.add(mesh);
    if(['body','cabin','roof'].includes(name))for(let i=0;i<n;i++)mesh.setColorAt(i,colour(traffic.cars[i].kind==='taxi'?'#e6af27':palette[traffic.cars[i].colour]));
    carParts.push({mesh,p,s,name});
  }
  const wheelGeo=new THREE.CylinderGeometry(.35,.35,.22,12);wheelGeo.rotateX(Math.PI/2);
  for(const x of [-1.35,1.35])for(const z of [-.9,.9]){
    const wheels=new THREE.InstancedMesh(wheelGeo,mat('rubber',{color:0x20282b,roughness:1}),n);wheels.frustumCulled=false;vehicleGroup.add(wheels);carParts.push({mesh:wheels,p:[x,.35,z],s:[1,1,1],name:'wheel'});
  }
  const signs=new THREE.InstancedMesh(boxGeo,mat('taxi-sign',{color:0xeac554,emissive:0xffd65f,emissiveIntensity:.12}),n);signs.frustumCulled=false;vehicleGroup.add(signs);carParts.push({mesh:signs,p:[-.3,1.65,0],s:[.7,.22,.3],name:'taxi-sign'});
  const c=makeCanvas(64,64),g=c.getContext('2d'),gradient=g.createRadialGradient(32,32,4,32,32,32);gradient.addColorStop(0,'#00000099');gradient.addColorStop(1,'#00000000');g.fillStyle=gradient;g.fillRect(0,0,64,64);
  const shadowGeometry=new THREE.PlaneGeometry(1,1);shadowGeometry.rotateX(-Math.PI/2);
  const shadow=new THREE.InstancedMesh(shadowGeometry,new THREE.MeshBasicMaterial({map:new THREE.CanvasTexture(c),transparent:true,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-1}),n);shadow.frustumCulled=false;shadow.userData.noAO=true;vehicleGroup.add(shadow);carParts.push({mesh:shadow,p:[0,.115,0],s:[5.2,1,2.3],name:'contact-shadow'});
}
function updateVehicles(delta){
  if(!traffic)return;if(!pausedTraffic)trafficTime+=delta;
  const f=(trafficTime/traffic.dt)%(traffic.frames-1),a=Math.floor(f),b=a+1,mix=f-a;trafficFrame=a;
  const pa=traffic.positions[a],pb=traffic.positions[b];
  for(let i=0;i<traffic.cars.length;i++){
    const distance=Math.hypot(pb[i][0]-pa[i][0],pb[i][1]-pa[i][1]);
    let x=THREE.MathUtils.lerp(pa[i][0],pb[i][0],mix),z=THREE.MathUtils.lerp(pa[i][1],pb[i][1],mix);
    let angle=pb[i][2]-pa[i][2];angle=Math.atan2(Math.sin(angle),Math.cos(angle));const yaw=pa[i][2]+angle*mix;
    if(distance>15){x=pa[i][0];z=pa[i][1];}
    dummy.position.set(x,0,z);dummy.rotation.set(0,yaw,0);dummy.scale.set(1,1,1);dummy.updateMatrix();
    carBase.copy(dummy.matrix);
    for(const part of carParts){
      const van=traffic.cars[i].kind==='van';dummy.position.set(...part.p);dummy.rotation.set(0,0,0);dummy.scale.set(...part.s);
      if(van&&['body','cabin','roof','glass'].includes(part.name)){dummy.scale.y*=1.25;dummy.position.y*=1.16;}
      if(part.name==='taxi-sign'&&traffic.cars[i].kind!=='taxi')dummy.scale.setScalar(0);
      if(distance>15)dummy.scale.setScalar(0); // Hide scenario boundary reinsertion instead of animating a cross-city teleport.
      dummy.updateMatrix();transform.multiplyMatrices(carBase,dummy.matrix);part.mesh.setMatrixAt(i,transform);
    }
  }
  for(const part of carParts)part.mesh.instanceMatrix.needsUpdate=true;
}

function electrical(){
  const lineMaterial=new THREE.LineBasicMaterial({color:0x2fcbd5,transparent:true,opacity:.78,depthTest:false});
  for(const link of data.network){
    const points=[new THREE.Vector3(link.start[0],1.3,link.start[1]),new THREE.Vector3(link.end[0],1.3,link.end[1])];
    const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),lineMaterial);line.renderOrder=12;networkGroup.add(line);
    const bead=new THREE.Mesh(new THREE.SphereGeometry(.85,6,5),new THREE.MeshBasicMaterial({color:0xa2ffff,depthTest:false}));bead.renderOrder=14;bead.userData.link=link;networkGroup.add(bead);
  }
}
function updateElectrical(now){
  if(!state||!networkVisible)return;
  for(const object of networkGroup.children){
    const link=object.userData.link;if(!link)continue;
    const kw=link.kind==='line'?state.line_kw[link.index]:(link.building!=null?state.assets[link.building]?.net_kw:state.grid_kw);
    object.visible=Number.isFinite(kw)&&Math.abs(kw)>.1;if(!object.visible)continue;
    const progress=(now*(.15+Math.min(Math.abs(kw),3000)/5000))%1,p=kw>=0?progress:1-progress;
    object.position.set(THREE.MathUtils.lerp(link.start[0],link.end[0],p),1.5,THREE.MathUtils.lerp(link.start[1],link.end[1],p));
    object.scale.setScalar(.7+Math.min(Math.abs(kw)/1000,1.4));
  }
}
function overlay(layer){
  overlayGroup.traverse(o=>{o.geometry?.dispose();});
  const oldMaterials=new Set(overlayGroup.children.map(o=>o.material));oldMaterials.forEach(m=>m?.dispose());
  overlayGroup.clear();
  if(!state||layer==='assets')return;
  for(const asset of state.assets){
    const building=buildings.get(asset.index);if(!building)continue;
    const invalid=asset.voltage!=null&&(asset.voltage<.95||asset.voltage>1.05);
    const color=layer==='voltage'?(invalid?0xdc4e59:0x00adbd):new THREE.Color().setHSL(.73,.5,.35+asset.soc*.35);
    const m=new THREE.MeshBasicMaterial({color,transparent:true,opacity:.3,depthWrite:false,side:THREE.DoubleSide});
    for(const part of building.data.parts){const g=new THREE.ShapeGeometry(shapeOf(part.rings));g.rotateX(-Math.PI/2);const mesh=new THREE.Mesh(g,m);mesh.position.y=building.data.height+.24;overlayGroup.add(mesh);}
  }
}
function select(index,notify=false){
  if(!buildings.has(index))return;
  selected=index;const b=buildings.get(index).data;
  if(selectedRing){scene.remove(selectedRing);selectedRing.geometry.dispose();selectedRing.material.dispose();}
  const pts=b.parts[0].rings[0].map(p=>new THREE.Vector3(p[0],b.height+.55,p[1]));pts.push(pts[0].clone());
  selectedRing=new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),new THREE.LineBasicMaterial({color:0x36cbd3,transparent:true,opacity:.95}));scene.add(selectedRing);
  if(notify)inspectorOpen=true;
  const card=document.querySelector('#selection');card.hidden=!inspectorOpen;
  document.querySelector('#inspector-toggle').setAttribute('aria-expanded',String(inspectorOpen));
  document.querySelector('#inspector-toggle').classList.toggle('active',inspectorOpen);renderDirty=true;
  document.querySelector('#selected-address').textContent=b.address;
  document.querySelector('#selected-use').textContent=`${b.use} · BIN ${b.bin}`;
  selectionValues();
  if(notify&&index<data.assets.length)parent.postMessage({type:'vpp-city-select',index},location.origin);
}
function selectionValues(){
  const b=buildings.get(selected)?.data,a=state?.assets[selected];if(!b)return;
  const values=[['Roof height',`${b.height.toFixed(1)} m`],['Solar output',a?`${a.pv_kw.toFixed(1)} kW`:'—'],['Battery SOC',a?`${(a.soc*100).toFixed(1)}%`:'—'],['Bus voltage',a?.voltage?`${a.voltage.toFixed(4)} pu`:'—']];
  const node=document.querySelector('#selected-values');node.replaceChildren(...values.map(([key,value])=>{const dl=document.createElement('dl'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=key;dd.textContent=value;dl.append(dt,dd);return dl;}));
}
function lighting(){
  const labels={simulation:'Sunlight',daylight:'Daylight',golden:'Golden hour',blue:'Blue hour',night:'Night'};
  presentation.setLight(lightMode,state,!readyForRender);renderDirty=true;
  document.querySelector('#lighting span').textContent=labels[lightMode];
  document.querySelector('#lighting').title=`${labels[lightMode]} · click to cycle lighting presets`;
  document.querySelector('#light-preset').value=lightMode;
  document.querySelector('#light-note').textContent=lightMode==='simulation'?'Sun position follows the historical simulation.':'Presentation lighting override · energy results unchanged.';
}
function fly(view){
  const b=buildings.get(selected)?.data,c=b?.centre||[0,0];let target,position;
  controls.maxPolarAngle=Math.PI*.485;
  if(view==='street'){
    const candidates=[];
    for(const road of data.roads.filter(r=>!r.elevation&&!r.walk&&r.kind==='1')){
      for(let i=0;i<road.points.length-1;i++){
        const a=road.points[i],v=road.points[i+1],dx=v[0]-a[0],dz=v[1]-a[1],len=Math.hypot(dx,dz);if(len<1)continue;
        const centre=((c[0]-a[0])*dx+(c[1]-a[1])*dz)/(len*len);
        for(const shift of [-35,0,35]){
          const f=clamp(centre+shift/len,0,1);
          for(const side of [-1,1]){
            const p=[a[0]+dx*f-dz/len*(road.width/2+1)*side,a[1]+dz*f+dx/len*(road.width/2+1)*side];
            const distance=Math.hypot(p[0]-c[0],p[1]-c[1]);
            if(distance<55||distance>140||onBuilding(p))continue;
            candidates.push({p,score:Math.abs(distance-85)+Math.max(0,-(p[0]-c[0])*.15)});
          }
        }
      }
    }
    candidates.sort((a,b)=>a.score-b.score);
    const point=candidates[0]?.p||[c[0]+85,c[1]+65];target=new THREE.Vector3(c[0],Math.min(11,b.height*.27),c[1]);position=new THREE.Vector3(point[0],3.5,point[1]);
    controls.maxPolarAngle=Math.PI*.57;
  }else if(view==='flatbush-approach'){target=new THREE.Vector3(280,6,500);position=new THREE.Vector3(670,220,900);
  }else if(view==='manhattan-approach'){target=new THREE.Vector3(-1130,8,-900);position=new THREE.Vector3(-1580,330,-1450);
  }else if(view==='brooklyn-cut'){target=new THREE.Vector3(-390,-4,220);position=new THREE.Vector3(-640,230,470);
  }else if(view==='brooklyn-approach'){target=new THREE.Vector3(-240,5,230);position=new THREE.Vector3(160,300,700);
  }else if(view==='bridges'){
    const points=data.bridges.flatMap(b=>[-1,1].flatMap(sign=>[-b.width,b.width].map(t=>{const s=sign*(b.main_span/2+b.side_span+170);return new THREE.Vector3(b.centre[0]+b.axis[0]*s-b.axis[1]*t,70,b.centre[1]+b.axis[1]*s+b.axis[0]*t);})));
    const bounds=new THREE.Box3().setFromPoints(points);target=bounds.getCenter(new THREE.Vector3());target.y=25;
    const direction=new THREE.Vector3(.6,.65,.8).normalize(),right=new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0),direction).normalize(),up=new THREE.Vector3().crossVectors(direction,right);
    const tan=Math.tan(THREE.MathUtils.degToRad(camera.fov/2));let distance=1200;
    for(const point of points){const p=point.clone().sub(target);distance=Math.max(distance,p.dot(direction)+Math.abs(p.dot(up))/tan,p.dot(direction)+Math.abs(p.dot(right))/(tan*camera.aspect));}
    position=target.clone().addScaledVector(direction,distance*1.12);
  }else if(view==='top'){target=new THREE.Vector3(0,0,0);position=new THREE.Vector3(0,680,.1);}
  else{target=new THREE.Vector3(0,24,0);position=new THREE.Vector3(...(innerHeight<450?[230,205,300]:[330,285,430]));}
  const from=camera.position.clone(),mid=from.clone().lerp(position,.5);
  mid.y=Math.max(from.y,position.y)+Math.min(110,from.distanceTo(position)*.18);
  flight={start:performance.now(),duration:motionPreference.matches?0:2400,from,to:position,mid,oldTarget:controls.target.clone(),target};
  controls.enabled=false;renderDirty=true;
  document.body.dataset.view=view;
  document.querySelectorAll('button[data-view]').forEach(button=>button.classList.toggle('active',button.dataset.view===view));
}
function zoom(factor){
  const from=camera.position.clone(),offset=from.clone().sub(controls.target),distance=clamp(offset.length()*factor,controls.minDistance,controls.maxDistance);
  const to=controls.target.clone().add(offset.setLength(distance));
  flight={start:performance.now(),duration:motionPreference.matches?0:600,from,to,mid:from.clone().lerp(to,.5),oldTarget:controls.target.clone(),target:controls.target.clone()};
  controls.enabled=false;renderDirty=true;
}
document.querySelector('#zoom-in').addEventListener('click',()=>zoom(.78));
document.querySelector('#zoom-out').addEventListener('click',()=>zoom(1.28));
document.querySelector('#reset-view').addEventListener('click',()=>fly('district'));
function mapScale(){
  const metresPerPixel=2*camera.position.distanceTo(controls.target)*Math.tan(THREE.MathUtils.degToRad(camera.fov)/2)/host.clientHeight;
  const target=metresPerPixel*78,power=10**Math.floor(Math.log10(target));
  const metres=[1,2,5,10].map(n=>n*power).reduce((a,b)=>Math.abs(b-target)<Math.abs(a-target)?b:a);
  document.querySelector('#map-scale').textContent=metres>=1000?`${metres/1000} km`:`${metres} m`;
  document.querySelector('#map-scale-line').style.width=`${metres/metresPerPixel}px`;
}
function minimap(){
  if(!data)return;const canvas=document.querySelector('#minimap'),g=canvas.getContext('2d');g.clearRect(0,0,280,200);g.fillStyle='#e4e8e4';g.fillRect(0,0,280,200);
  const scale=.205,px=x=>140+x*scale,pz=z=>100+z*scale;
  for(const polygon of data.water){g.beginPath();polygon[0].forEach((p,i)=>i?g.lineTo(px(p[0]),pz(p[1])):g.moveTo(px(p[0]),pz(p[1])));g.fillStyle='#b1d0d4';g.fill();}
  g.strokeStyle='#ffffff';g.lineWidth=2.5;
  for(const road of data.roads){g.beginPath();road.points.forEach((p,i)=>i?g.lineTo(px(p[0]),pz(p[1])):g.moveTo(px(p[0]),pz(p[1])));g.stroke();}
  for(const b of data.buildings){g.fillStyle=b.index<data.assets.length?'#7ba7a4':'#afb9b4';g.beginPath();b.parts[0].rings[0].forEach((p,i)=>i?g.lineTo(px(p[0]),pz(p[1])):g.moveTo(px(p[0]),pz(p[1])));g.fill();}
  const target=controls.target;g.beginPath();g.arc(px(target.x),pz(target.z),4,0,Math.PI*2);g.fillStyle='#1c949d';g.fill();
  const b=buildings.get(selected)?.data;if(b){g.strokeStyle='#075b66';g.lineWidth=2;g.strokeRect(px(b.centre[0])-4,pz(b.centre[1])-4,8,8);}
}
let pointerStart=null;
renderer.domElement.addEventListener('pointerdown',event=>{pointerStart=[event.clientX,event.clientY];if(flight){flight=null;controls.enabled=true;}renderDirty=true;});
renderer.domElement.addEventListener('click',event=>{
  if(!pointerStart||Math.hypot(event.clientX-pointerStart[0],event.clientY-pointerStart[1])>5)return;
  const rect=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);
  const hit=raycaster.intersectObjects(pickables,false)[0];if(hit)select(hit.object.userData.building.index,true);
});
renderer.domElement.addEventListener('pointermove',event=>{
  if(!data||event.buttons||performance.now()-lastPointerCheck<85)return;lastPointerCheck=performance.now();const rect=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);
  const hit=raycaster.intersectObjects(pickables,false)[0],tip=document.querySelector('#hover');
  tip.hidden=!hit;if(hit){const b=hit.object.userData.building;tip.replaceChildren(document.createTextNode(b.address));const small=document.createElement('span');small.textContent=`${b.height.toFixed(1)} m · ${b.use} · click to inspect`;tip.appendChild(small);tip.style.left=Math.min(event.clientX+16,innerWidth-250)+'px';tip.style.top=Math.min(event.clientY+16,innerHeight-70)+'px';}
});
renderer.domElement.addEventListener('pointerleave',()=>document.querySelector('#hover').hidden=true);
document.querySelectorAll('button[data-view]').forEach(button=>button.addEventListener('click',()=>fly(button.dataset.view)));
document.querySelector('#focus-building').addEventListener('click',()=>fly('street'));
document.querySelector('#traffic').classList.toggle('active',!pausedTraffic);
document.querySelector('#traffic').setAttribute('aria-pressed',String(!pausedTraffic));
document.querySelector('#traffic').addEventListener('click',event=>{pausedTraffic=!pausedTraffic;event.currentTarget.classList.toggle('active',!pausedTraffic);event.currentTarget.setAttribute('aria-pressed',String(!pausedTraffic));renderDirty=true;});
document.querySelector('#network').addEventListener('click',event=>{networkVisible=!networkVisible;networkGroup.visible=networkVisible;event.currentTarget.classList.toggle('active',networkVisible);event.currentTarget.setAttribute('aria-pressed',String(networkVisible));renderDirty=true;});
document.querySelector('#lighting').addEventListener('click',()=>{const modes=['simulation','golden','blue','night','daylight'];lightMode=modes[(modes.indexOf(lightMode)+1)%modes.length];lighting();});
document.querySelector('#light-preset').addEventListener('change',event=>{lightMode=event.target.value;lighting();});
document.querySelector('#inspector-toggle').addEventListener('click',()=>{inspectorOpen=!inspectorOpen;select(selected);});
function appearance(open){document.querySelector('#appearance').hidden=!open;document.querySelector('#appearance-toggle').setAttribute('aria-expanded',String(open));}
document.querySelector('#appearance-toggle').addEventListener('click',()=>appearance(document.querySelector('#appearance').hidden));
document.querySelector('#appearance-close').addEventListener('click',()=>appearance(false));
document.querySelector('#quality').addEventListener('change',()=>{renderDirty=true;});
window.addEventListener('keydown',event=>{if(event.key==='Escape'){appearance(false);document.querySelector('#provenance').hidden=true;}if(!['INPUT','SELECT','TEXTAREA'].includes(event.target.tagName)){const views={'1':'district','2':'street','3':'top','4':'bridges'};if(views[event.key])fly(views[event.key]);}});
motionPreference.addEventListener('change',()=>{pausedTraffic=motionPreference.matches;document.querySelector('#traffic').classList.toggle('active',!pausedTraffic);document.querySelector('#traffic').setAttribute('aria-pressed',String(!pausedTraffic));renderDirty=true;});
document.querySelector('#fullscreen').addEventListener('click',()=>{if(document.fullscreenElement)document.exitFullscreen();else document.documentElement.requestFullscreen();});
document.querySelector('#record').addEventListener('click',()=>{
  const button=document.querySelector('#record');if(button.disabled)return;
  if(!renderer.domElement.captureStream||!window.MediaRecorder){button.title='Recording is unavailable in this browser';return;}
  recording=true;renderDirty=true;const stream=renderer.domElement.captureStream(60),chunks=[];
  const mime=MediaRecorder.isTypeSupported('video/webm;codecs=vp9')?'video/webm;codecs=vp9':'video/webm';
  const recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:4000000});
  button.disabled=true;button.style.color='#d84b4b';button.title='Recording the moving district…';
  recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
  recorder.onstop=()=>{
    const blob=new Blob(chunks,{type:'video/webm'}),url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download='brooklyn-vpp-district.webm';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
    stream.getTracks().forEach(track=>track.stop());recording=false;button.disabled=false;button.style.color='';button.title='Record a 10-second WebM clip of the moving district';
  };
  recorder.start();setTimeout(()=>recorder.stop(),10000);
});
document.querySelector('#provenance-toggle').addEventListener('click',event=>{const p=document.querySelector('#provenance');p.hidden=!p.hidden;event.currentTarget.setAttribute('aria-expanded',String(!p.hidden));});

let stateRequest=0;
async function sync(input){
  if(!data){pendingState=input;return;}
  if(input.run&&input.run!==runId){location.replace('/district?run='+encodeURIComponent(input.run));return;}
  selected=Number(input.asset??selected);
  const t=Number(input.step??0);
  if(t!==lastStep){
    const token=++stateRequest;
    const response=await fetch(`/api/city/${runId}/state/${t}`);if(!response.ok)return;
    const next=await response.json();if(token!==stateRequest)return;state=next;lastStep=t;
    document.querySelector('#scene-time').textContent=state.timestamp.slice(0,16).replace('T',' · ')+' New York · illustrative traffic';lighting();
  }
  select(selected);overlay(input.layer||'assets');selectionValues();minimap();
}
window.addEventListener('message',event=>{if(event.origin!==location.origin||event.data?.type!=='vpp-city-state')return;sync(event.data).catch(console.error);});
function resize(){presentation.resize();renderDirty=true;}
new ResizeObserver(resize).observe(host);resize();
controls.addEventListener('change',()=>{renderDirty=true;});
document.addEventListener('visibilitychange',()=>{clock.getDelta();presentation.ready();renderDirty=true;});
function animate(){
  requestAnimationFrame(animate);const now=performance.now();
  const delta=Math.min(clock.getDelta(),.1);
  if(!readyForRender||document.hidden)return;
  if(flight){
    const progress=flight.duration?clamp((now-flight.start)/flight.duration,0,1):1,s=progress<.5?4*progress**3:1-(-2*progress+2)**3/2;
    const a=new THREE.Vector3().lerpVectors(flight.from,flight.mid,s),b=new THREE.Vector3().lerpVectors(flight.mid,flight.to,s);camera.position.lerpVectors(a,b,s);
    controls.target.lerpVectors(flight.oldTarget,flight.target,s);renderDirty=true;if(progress===1){flight=null;controls.enabled=true;}
  }
  controls.update();
  if(pausedTraffic&&!networkVisible&&!flight&&!presentation.transitioning&&!renderDirty&&!recording)return;
  presentation.update(now,controls.target);updateVehicles(delta);updateElectrical(now/1000);
  let detailTiles=0;
  for(const mesh of nearDetails){mesh.visible=camera.position.distanceTo(mesh.boundingSphere.center)<DETAIL_DISTANCE+mesh.boundingSphere.radius;if(mesh.visible)detailTiles++;}
  document.body.dataset.detailTiles=String(detailTiles);
  document.body.dataset.cameraDistance=camera.position.distanceTo(controls.target).toFixed(1);
  for(const water of waterMaterials){water.normalMap.offset.set(now*.0000018,now*.0000011);}
  if(materials.lamp)materials.lamp.emissiveIntensity=.08+U.night.value*2.2;
  if(materials['street-pools'])materials['street-pools'].opacity=U.night.value*.75;
  if(materials['car-headlight'])materials['car-headlight'].emissiveIntensity=.3+U.night.value*2;
  if(now-lastMap>350){minimap();mapScale();lastMap=now;}
  presentation.render(now);renderFrames++;renderDirty=false;
  // Public rendering diagnostics aid browser QA; numerical powers come from state API.
  document.body.dataset.frames=String(renderFrames);document.body.dataset.trafficFrame=String(trafficFrame);
}
animate();
async function boot(){
  if(!runId)throw new Error('Choose a completed energy simulation first.');
  const response=await fetch('/api/city/'+encodeURIComponent(runId)+'?scene=street-repair-v2');if(!response.ok)throw new Error(await response.text());data=await response.json();
  ground();loading('Connecting streets and the East River suspension bridges…');streets();contextBuildings();
  loading('Adding façades, window frames and rooftop equipment…');
  for(let i=0;i<data.buildings.length;i++){makeBuilding(data.buildings[i]);if(i%35===0)await new Promise(requestAnimationFrame);}
  batchStaticCity();batchEnvelopes();const windowPlane=new THREE.PlaneGeometry(1,1);
  tiledInstances(windowFrames,windowPlane,frameMaterial,false,true);tiledInstances(windowGlass,windowPlane,glassMaterial,true,true);tiledInstances(windowBars,windowPlane,frameMaterial,false,true);tiledInstances(windowSills,boxGeo,frameMaterial,false,true);
  // Far panels preserve the same cell texture, footprint and tilt with two
  // triangles, keeping their invisible sides out of district-level rendering.
  tiledInstances(roofPanels,boxGeo,panelMaterial,false,true);
  const farPanel=panelMaterial.clone();patchNearDetail(farPanel,true);
  const panelPlane=new THREE.PlaneGeometry(1,1);panelPlane.rotateX(-Math.PI/2);
  const farPanels=instances(roofPanels,panelPlane,farPanel);farPanels.userData.noAO=true;
  trees();streetGlow();electrical();
  loading('Loading the executed street traffic scenario…');
  const tr=await fetch('/api/city-traffic?scene=street-repair-v2');if(!tr.ok)throw new Error('Traffic scenario could not be loaded');traffic=await tr.json();vehicles();
  document.body.dataset.buildings=String(data.buildings.length);document.body.dataset.windows=String(windowGlass.length);document.body.dataset.roads=String(data.roads.length);document.body.dataset.cars=String(traffic.cars.length);
  document.body.dataset.roofPanels=String(roofPanels.length);
  document.body.dataset.bridges=String(data.bridges.length);document.body.dataset.contextBuildings=String(data.context_buildings.length);
  select(0);minimap();await sync(pendingState||{step:48,asset:0,layer:'assets'});
  loading('Finishing daylight materials…');if(renderer.compileAsync)await renderer.compileAsync(scene,camera);
  const query=new URLSearchParams(location.search);lightMode=['simulation','daylight','golden','blue','night'].includes(query.get('light'))?query.get('light'):'simulation';lighting();
  presentation.update(performance.now(),controls.target);presentation.render(performance.now());presentation.ready();
  readyForRender=true;document.body.dataset.ready='true';document.body.dataset.view='district';
  if(['district','street','top','bridges','manhattan-approach','brooklyn-approach','brooklyn-cut','flatbush-approach'].includes(query.get('view')))fly(query.get('view'));
  const loadingPanel=document.querySelector('#loading');loadingPanel.classList.add('hide');loadingPanel.setAttribute('aria-hidden','true');
  setTimeout(()=>loadingPanel.style.display='none',650);parent.postMessage({type:'vpp-city-ready'},location.origin);
}
boot().catch(error=>{console.error(error);loading(error.message);document.querySelector('#loading strong').textContent='District view unavailable';});
