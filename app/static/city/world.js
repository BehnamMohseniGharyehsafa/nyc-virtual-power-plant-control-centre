import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {mergeGeometries} from '/static/vendor/BufferGeometryUtils.js';

const host=document.querySelector('#world');
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(43,1,.4,4500);
const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'high-performance'});
renderer.setPixelRatio(Math.min(devicePixelRatio,1.25));
renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.14;
renderer.outputColorSpace=THREE.SRGBColorSpace;
host.appendChild(renderer.domElement);
const controls=new OrbitControls(camera,renderer.domElement);
controls.enableDamping=true;controls.dampingFactor=.075;controls.screenSpacePanning=false;
controls.minDistance=12;controls.maxDistance=1500;controls.maxPolarAngle=Math.PI*.485;
controls.target.set(0,24,0);camera.position.set(...(innerHeight<450?[230,205,300]:[330,285,430]));controls.update();
const hemi=new THREE.HemisphereLight(0xe8f5ff,0x8e806a,1.55);scene.add(hemi);
const sun=new THREE.DirectionalLight(0xffefd4,3.1);sun.position.set(-260,350,230);
sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);sun.shadow.camera.left=-430;sun.shadow.camera.right=430;
sun.shadow.camera.top=430;sun.shadow.camera.bottom=-430;sun.shadow.camera.near=10;sun.shadow.camera.far=1500;
sun.shadow.bias=-.00016;sun.shadow.normalBias=.18;sun.shadow.radius=2;scene.add(sun);scene.add(sun.target);
scene.fog=new THREE.Fog(0xdce7ea,950,2300);
const clock=new THREE.Clock();
const buildings=new Map(),pickables=[],windowFrames=[],windowGlass=[],windowBars=[],roofPanels=[],treePoints=[],carParts=[];
const networkGroup=new THREE.Group();networkGroup.visible=false;scene.add(networkGroup);
const overlayGroup=new THREE.Group();scene.add(overlayGroup);
const vehicleGroup=new THREE.Group();scene.add(vehicleGroup);
const materials={};const boxGeo=new THREE.BoxGeometry(1,1,1);
let data,traffic,state,selected=0,runId=new URLSearchParams(location.search).get('run');
let pausedTraffic=false,trafficTime=0,night=false,manualLight=false,networkVisible=false;
let lastStep=-1,lastMap=0,flight=null,pendingState=null,waterMaterials=[];
let renderFrames=0,trafficFrame=0,selectedRing=null,readyForRender=false,lastRender=0;
const pointer=new THREE.Vector2(),raycaster=new THREE.Raycaster();
const dummy=new THREE.Object3D(),transform=new THREE.Matrix4();
const rand=(n)=>{let x=Math.sin(n*12.9898+78.233)*43758.5453;return x-Math.floor(x);};
const clamp=THREE.MathUtils.clamp;
const loading=(text)=>{document.querySelector('#loading-detail').textContent=text;};
const colour=(hex)=>new THREE.Color(hex);

function mat(name,params){return materials[name]??=(new THREE.MeshStandardMaterial(params));}
function makeCanvas(w,h){const c=document.createElement('canvas');c.width=w;c.height=h;return c;}
function environment(){
  const c=makeCanvas(1024,512),g=c.getContext('2d');const grad=g.createLinearGradient(0,0,0,512);
  grad.addColorStop(0,'#91b9d7');grad.addColorStop(.43,'#d3e5ec');grad.addColorStop(.55,'#f5ebdb');grad.addColorStop(1,'#6c7368');
  g.fillStyle=grad;g.fillRect(0,0,1024,512);
  const t=new THREE.CanvasTexture(c);t.mapping=THREE.EquirectangularReflectionMapping;t.colorSpace=THREE.SRGBColorSpace;
  const pmrem=new THREE.PMREMGenerator(renderer);scene.environment=pmrem.fromEquirectangular(t).texture;
  scene.environmentIntensity=.7;t.dispose();pmrem.dispose();
}
environment();

function brickTexture(style,tint){
  const c=makeCanvas(256,256),g=c.getContext('2d');g.fillStyle=tint;g.fillRect(0,0,256,256);
  const bw=style==='stone'?128:64,bh=style==='stone'?64:25.6;
  for(let y=0,row=0;y<256;y+=bh,row++)for(let x=-bw;x<256;x+=bw){
    const xx=x+(row%2)*bw/2,v=rand(x*3+y*7+33);
    g.fillStyle=`rgba(${v>.5?'255,239,218':'35,23,19'},${.025+v*.07})`;g.fillRect(xx+1,y+1,bw-2,bh-2);
    g.fillStyle=style==='stone'?'#99968c':'#988475';g.globalAlpha=.32;g.fillRect(xx,y,bw,1.1);g.fillRect(xx,y,1.1,bh);g.globalAlpha=1;
  }
  const texture=new THREE.CanvasTexture(c);texture.wrapS=texture.wrapT=THREE.RepeatWrapping;
  texture.repeat.set(style==='stone'?.5:1,style==='stone'?.5:1);texture.colorSpace=THREE.SRGBColorSpace;
  texture.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());return texture;
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
const roadMaterial=mat('asphalt',{map:asphaltTexture(),color:0xbfc5c9,roughness:.96});
const walkMaterial=mat('pavement',{color:0xbcbcb2,roughness:.94});
const curbMaterial=mat('curb',{color:0xd8d5c9,roughness:.9});
const whitePaint=mat('white-road-paint',{color:0xe5e1ce,roughness:.92});
const yellowPaint=mat('yellow-road-paint',{color:0xcbb56b,roughness:.92});
const roofMaterial=mat('roof',{color:0x6f7775,roughness:1});
const copper=mat('copper',{color:0x685347,roughness:.8});
const mechanical=mat('mechanical',{color:0xaeb6b6,roughness:.64,metalness:.28});
const dark=mat('dark-metal',{color:0x27383d,roughness:.52,metalness:.32});
const frameMaterial=mat('window-frame',{color:0x606b65,roughness:.68,metalness:.22});
const glassMaterial=mat('window-glass',{color:0xa2b5b9,map:glazingTexture(),roughness:.12,metalness:.58,envMapIntensity:1.6});
const panelMaterial=mat('solar-panel',{color:0xffffff,map:panelTexture(),metalness:.35,roughness:.29});

function object(geometry,material,position,scale=null,parent=scene){
  const mesh=new THREE.Mesh(geometry,material);mesh.position.set(...position);if(scale)mesh.scale.set(...scale);parent.add(mesh);return mesh;
}
function cube(material,x,y,z,sx,sy,sz,parent=scene){return object(boxGeo,material,[x,y,z],[sx,sy,sz],parent);}
function shapeOf(rings){
  const contour=rings[0].map(p=>new THREE.Vector2(p[0],-p[1]));const s=new THREE.Shape(contour);
  for(const ring of rings.slice(1))s.holes.push(new THREE.Path(ring.map(p=>new THREE.Vector2(p[0],-p[1]))));return s;
}
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
function ribbon(points,width,y,material){
  const vertices=[],uv=[],indices=[];
  let cumulative=0;
  for(let i=0;i<points.length;i++){
    const prev=points[Math.max(0,i-1)],next=points[Math.min(points.length-1,i+1)];
    const dx=next[0]-prev[0],dz=next[1]-prev[1],len=Math.hypot(dx,dz)||1,nx=-dz/len,nz=dx/len;
    if(i)cumulative+=Math.hypot(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1]);
    vertices.push(points[i][0]+nx*width/2,y,points[i][1]+nz*width/2,points[i][0]-nx*width/2,y,points[i][1]-nz*width/2);
    uv.push(0,cumulative,width,cumulative);
    if(i){const o=i*2;indices.push(o-2,o,o-1,o-1,o,o+1);}
  }
  const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));geo.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));geo.setIndex(indices);geo.computeVertexNormals();
  const mesh=object(geo,material,[0,0,0]);mesh.receiveShadow=true;return mesh;
}
function segmentBox(a,b,y,width,height,material){
  const dx=b[0]-a[0],dz=b[1]-a[1],length=Math.hypot(dx,dz);if(length<.01)return;
  const mesh=cube(material,(a[0]+b[0])/2,y,(a[1]+b[1])/2,width,height,length);mesh.rotation.y=Math.atan2(dx,dz);return mesh;
}
function ground(){
  const mesh=object(new THREE.PlaneGeometry(7000,7000),mat('ground',{color:0xc4c4b6,roughness:1}),[0,-.15,0]);mesh.rotation.x=-Math.PI/2;mesh.receiveShadow=true;
  for(const polygon of data.water){
    const water=new THREE.MeshStandardMaterial({color:0x286c83,metalness:.16,roughness:.35});waterMaterials.push(water);flatShape(polygon,-.05,water);
  }
}
function streets(){
  for(let ri=0;ri<data.roads.length;ri++){
    const road=data.roads[ri],pts=road.points,y=road.elevation,width=road.width;
    if(road.walk){ribbon(pts,Math.min(width,4),y+.025,walkMaterial);continue;}
    ribbon(pts,width+4.4,y+.02,curbMaterial);ribbon(pts,width+3.8,y+.045,walkMaterial);ribbon(pts,width,y+.075,roadMaterial);
    for(let j=0;j<pts.length-1;j++){
      const a=pts[j],b=pts[j+1],dx=b[0]-a[0],dz=b[1]-a[1],length=Math.hypot(dx,dz),ux=dx/length,uz=dz/length;
      if(length<3)continue;
      if(road.direction==='TW'){
        for(const offset of [-.15,.15])segmentBox([a[0]-uz*offset,a[1]+ux*offset],[b[0]-uz*offset,b[1]+ux*offset],y+.09,.08,.018,yellowPaint);
      }else if(width>9){
        for(let s=8;s<length-6;s+=10)segmentBox([a[0]+ux*s,a[1]+uz*s],[a[0]+ux*Math.min(s+3,length-5),a[1]+uz*Math.min(s+3,length-5)],y+.09,.12,.018,whitePaint);
      }
      if(y>0&&j%3===0){
        const p=[(a[0]+b[0])/2,(a[1]+b[1])/2];const pier=cube(mat('bridge-concrete',{color:0xaaa9a1,roughness:1}),p[0],y/2,p[1],2.6,y,4);pier.castShadow=true;
        segmentBox(a,b,y-.3,width+.5,.5,mat('bridge-edge',{color:0x8e9693,roughness:.8}));
        for(const side of [-1,1]){
          const off=(width/2+.2)*side;
          segmentBox([a[0]-uz*off,a[1]+ux*off],[b[0]-uz*off,b[1]+ux*off],y+.65,.18,1.1,dark);
        }
      }
      if(y===0&&j===0&&length>32&&road.kind==='1'){
        // Crosswalks and street furniture are visual estimates, not surveyed data.
        for(const end of [9,length-9])for(let w=-width/2+.6;w<width/2-.6;w+=1.35){
          const cx=a[0]+ux*end-uz*w,cz=a[1]+uz*end+ux*w;
          const stripe=cube(whitePaint,cx,.105,cz,.62,.025,2.8);stripe.rotation.y=Math.atan2(ux,uz);
        }
      }
      if(y===0&&road.kind==='1')for(let s=20;s<length-8;s+=37){
        const side=ri%2?1:-1,off=width/2+1.3;
        const pos=[a[0]+ux*s-uz*off*side,a[1]+uz*s+ux*off*side];
        if(!onBuilding(pos,2))treePoints.push({p:pos,seed:ri*49+s});
        if(s%74<40&&!onBuilding(pos,2))streetLight(pos,[-uz*side,ux*side]);
      }
    }
  }
}
function streetLight(p,n){
  const pole=object(new THREE.CylinderGeometry(.065,.095,6.8,6),dark,[p[0],3.4,p[1]]);
  const arm=cube(dark,p[0]-n[0]*.65,6.75,p[1]-n[1]*.65,1.4,.08,.08);arm.rotation.y=-Math.atan2(n[1],n[0]);
  cube(mat('lamp',{color:0xd3d9d6,emissive:0xffdb94,emissiveIntensity:.13}),p[0]-n[0]*1.2,6.73,p[1]-n[1]*1.2,.6,.12,.28);
}

function makeBuilding(b){
  const variant=Math.floor(rand(Number(b.bin))*5),style=b.style;
  const palette=style==='brick'?['#8e6250','#a27b61','#765e51','#b0987b','#8b7060']:style==='brownstone'?['#7c6254','#9c8069','#7b7062','#9a8977','#786558']:['#b4b3a8','#a7aca7','#c0baaa','#a9a69d','#c2c2b8'];
  const tone=palette[variant],wall=mat(`wall-${style}-${variant}`,{color:0xffffff,map:brickTexture(style==='stone'?'stone':'brick',tone),roughness:style==='glass'?.56:.92,metalness:style==='glass'?.16:0});
  const trim=mat(`trim-${variant}`,{color:['#c4b7a1','#a9a497','#b6ae9f','#cdc4b0','#b3aea3'][variant],roughness:.88});
  const group=new THREE.Group();group.userData.building=b;scene.add(group);
  for(const part of b.parts){
    const s=shapeOf(part.rings),geo=new THREE.ExtrudeGeometry(s,{depth:b.height,bevelEnabled:false,steps:1});geo.rotateX(-Math.PI/2);
    const mesh=new THREE.Mesh(geo,[roofMaterial,wall]);mesh.castShadow=true;mesh.receiveShadow=true;mesh.userData.building=b;group.add(mesh);pickables.push(mesh);
    const ring=part.rings[0];
    const detailed=Math.hypot(...b.centre)<620&&b.index<600;
    const floors=clamp(b.floors,1,45),fh=b.height/floors;
    for(let j=0;j<ring.length;j++){
      const a=ring[j],c=ring[(j+1)%ring.length],dx=c[0]-a[0],dz=c[1]-a[1],length=Math.hypot(dx,dz);if(length<1)continue;
      const nx=-dz/length,nz=dx/length,rotation=Math.atan2(nx,nz);
      const cornice=segmentBox(a,c,b.height+.1,.45,.38,trim);group.attach(cornice);
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
        windowFrames.push({p:[x,y,z],r:rotation,s:[ww+.22,wh+.24,.12],seed:b.index*91+floor*31+bay});
        windowGlass.push({p:[x+nx*.085,y,z+nz*.085],r:rotation,s:[ww,wh,.05],seed:b.index*91+floor*31+bay});
        if(style!=='glass'){
          windowBars.push({p:[x+nx*.12,y,z+nz*.12],r:rotation,s:[.055,wh,.06]});
          windowBars.push({p:[x+nx*.12,y+.12,z+nz*.12],r:rotation,s:[ww,.05,.06]});
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
    if(colours){const v=rand(o.seed);mesh.setColorAt(i,new THREE.Color().setRGB(.5+v*.35,.61+v*.28,.66+v*.27));}
  }
  mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;scene.add(mesh);return mesh;
}
function tiledInstances(items,geometry,material,colours=false){
  const tiles=new Map();
  for(const item of items){const key=`${Math.floor(item.p[0]/110)},${Math.floor(item.p[2]/110)}`;if(!tiles.has(key))tiles.set(key,[]);tiles.get(key).push(item);}
  for(const tile of tiles.values()){const mesh=instances(tile,geometry,material,colours);mesh.computeBoundingSphere();}
}
function batchStaticCity(){
  // Merge roads, kerbs, markings, trims and roof furniture by material. Building
  // envelopes remain individually selectable; animated/instanced objects stay separate.
  scene.updateMatrixWorld(true);const batches=new Map();
  scene.traverse(object=>{
    if(!object.isMesh||object.isInstancedMesh||object.userData.building||Array.isArray(object.material))return;
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
  const geometry=new THREE.IcosahedronGeometry(1,2),pos=geometry.getAttribute('position');
  for(let i=0;i<pos.count;i++){const v=new THREE.Vector3().fromBufferAttribute(pos,i).multiplyScalar(.87+rand(i)*.25);pos.setXYZ(i,v.x,v.y,v.z);}geometry.computeVertexNormals();
  const trunks=[],crowns=[];
  for(let i=0;i<Math.min(treePoints.length,350);i++){
    const {p,seed}=treePoints[i],r=rand(seed);trunks.push({p:[p[0],1.65,p[1]],s:[.2,3.3,.2]});
    crowns.push({p:[p[0],4.0+r,p[1]],s:[2.3+r,2.5+r,2.3+r],seed});
  }
  instances(trunks,boxGeo,mat('tree-bark',{color:0x69604d,roughness:1}));
  const leaves=instances(crowns,geometry,mat('tree-leaves',{color:0x427153,roughness:1}),true);leaves.castShadow=true;
}
function vehicles(){
  const n=traffic.cars.length;
  const definitions=[
    ['body',boxGeo,mat('car-paint',{color:0xffffff,metalness:.28,roughness:.34}),[0,.64,0],[4.35,.73,1.8]],
    ['cabin',boxGeo,mat('car-body-upper',{color:0xffffff,metalness:.23,roughness:.3}),[-.27,1.14,0],[2.48,.65,1.65]],
    ['glass',boxGeo,mat('car-glass',{color:0x294650,metalness:.45,roughness:.12}),[-.28,1.28,0],[2.25,.4,1.68]],
    ['roof',boxGeo,mat('car-roof',{color:0xffffff,metalness:.25,roughness:.36}),[-.28,1.5,0],[2.4,.09,1.65]],
    ['headlight',boxGeo,mat('car-headlight',{color:0xf2f0db,emissive:0xffe9ba,emissiveIntensity:.4}),[2.19,.7,0],[.035,.18,1.5]],
    ['taillight',boxGeo,mat('car-taillight',{color:0x8e1f24,emissive:0xff2924,emissiveIntensity:.2}),[-2.19,.7,0],[.035,.15,1.5]],
  ];
  const palette=['#d4d8d5','#3c4e5b','#c4b9a5','#8d4f43','#6c7d86','#e4e1d6','#33403f','#8c9295'];
  for(const [name,geo,material,p,s] of definitions){
    const mesh=new THREE.InstancedMesh(geo,material,n);mesh.castShadow=name==='body';mesh.receiveShadow=true;vehicleGroup.add(mesh);
    if(['body','cabin','roof'].includes(name))for(let i=0;i<n;i++)mesh.setColorAt(i,colour(traffic.cars[i].kind==='taxi'?'#e6af27':palette[traffic.cars[i].colour]));
    carParts.push({mesh,p,s,name});
  }
  const wheelGeo=new THREE.CylinderGeometry(.35,.35,.22,12);wheelGeo.rotateX(Math.PI/2);
  for(const x of [-1.35,1.35])for(const z of [-.9,.9]){
    const wheels=new THREE.InstancedMesh(wheelGeo,mat('rubber',{color:0x20282b,roughness:1}),n);vehicleGroup.add(wheels);carParts.push({mesh:wheels,p:[x,.35,z],s:[1,1,1],name:'wheel'});
  }
  const signs=new THREE.InstancedMesh(boxGeo,mat('taxi-sign',{color:0xeac554,emissive:0xffd65f,emissiveIntensity:.12}),n);vehicleGroup.add(signs);carParts.push({mesh:signs,p:[-.3,1.65,0],s:[.7,.22,.3],name:'taxi-sign'});
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
    const base=dummy.matrix.clone();
    for(const part of carParts){
      const van=traffic.cars[i].kind==='van';dummy.position.set(...part.p);dummy.rotation.set(0,0,0);dummy.scale.set(...part.s);
      if(van&&['body','cabin','roof','glass'].includes(part.name)){dummy.scale.y*=1.25;dummy.position.y*=1.16;}
      if(part.name==='taxi-sign'&&traffic.cars[i].kind!=='taxi')dummy.scale.setScalar(0);
      if(distance>15)dummy.scale.setScalar(0); // Hide scenario boundary reinsertion instead of animating a cross-city teleport.
      dummy.updateMatrix();transform.multiplyMatrices(base,dummy.matrix);part.mesh.setMatrixAt(i,transform);
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
  if(selectedRing){scene.remove(selectedRing);selectedRing.geometry.dispose();}
  const pts=b.parts[0].rings[0].map(p=>new THREE.Vector3(p[0],b.height+.55,p[1]));pts.push(pts[0].clone());
  selectedRing=new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),new THREE.LineBasicMaterial({color:0x36cbd3,transparent:true,opacity:.95}));scene.add(selectedRing);
  const card=document.querySelector('#selection');card.hidden=false;
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
  night=manualLight?night:!!(state&&state.solar_elevation<0);
  document.body.classList.toggle('night',night);document.querySelector('#lighting span').textContent=night?'Evening':'Daylight';
  if(night){hemi.intensity=.9;sun.intensity=.45;sun.color.set(0xb1c5ef);scene.fog.color.set(0x293c53);glassMaterial.emissive.set(0xffc271);glassMaterial.emissiveIntensity=.42;renderer.toneMappingExposure=.95;}
  else{
    hemi.intensity=1.55;sun.intensity=3.1;sun.color.set(0xffefd4);scene.fog.color.set(0xdce7ea);glassMaterial.emissive.set(0x000000);renderer.toneMappingExposure=1.02;
    const az=(state?.solar_azimuth??205)*Math.PI/180,el=Math.max(25,state?.solar_elevation??50)*Math.PI/180;
    sun.position.set(Math.sin(az)*430,Math.sin(el)*550,-Math.cos(az)*430);
  }
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
  }else if(view==='top'){target=new THREE.Vector3(0,0,0);position=new THREE.Vector3(0,680,.1);}
  else{target=new THREE.Vector3(0,24,0);position=new THREE.Vector3(...(innerHeight<450?[230,205,300]:[330,285,430]));}
  flight={start:performance.now(),from:camera.position.clone(),to:position,oldTarget:controls.target.clone(),target};
  document.querySelectorAll('[data-view]').forEach(button=>button.classList.toggle('active',button.dataset.view===view));
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
renderer.domElement.addEventListener('pointerdown',event=>{pointerStart=[event.clientX,event.clientY];});
renderer.domElement.addEventListener('click',event=>{
  if(!pointerStart||Math.hypot(event.clientX-pointerStart[0],event.clientY-pointerStart[1])>5)return;
  const rect=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);
  const hit=raycaster.intersectObjects(pickables,false)[0];if(hit)select(hit.object.userData.building.index,true);
});
renderer.domElement.addEventListener('pointermove',event=>{
  if(!data||event.buttons)return;const rect=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);
  const hit=raycaster.intersectObjects(pickables,false)[0],tip=document.querySelector('#hover');
  tip.hidden=!hit;if(hit){const b=hit.object.userData.building;tip.replaceChildren(document.createTextNode(b.address));const small=document.createElement('span');small.textContent=`${b.height.toFixed(1)} m · ${b.use} · click to inspect`;tip.appendChild(small);tip.style.left=Math.min(event.clientX+16,innerWidth-250)+'px';tip.style.top=Math.min(event.clientY+16,innerHeight-70)+'px';}
});
renderer.domElement.addEventListener('pointerleave',()=>document.querySelector('#hover').hidden=true);
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>fly(button.dataset.view)));
document.querySelector('#focus-building').addEventListener('click',()=>fly('street'));
document.querySelector('#traffic').addEventListener('click',event=>{pausedTraffic=!pausedTraffic;event.currentTarget.classList.toggle('active',!pausedTraffic);});
document.querySelector('#network').addEventListener('click',event=>{networkVisible=!networkVisible;networkGroup.visible=networkVisible;event.currentTarget.classList.toggle('active',networkVisible);});
document.querySelector('#lighting').addEventListener('click',()=>{manualLight=true;night=!night;lighting();});
document.querySelector('#fullscreen').addEventListener('click',()=>{if(document.fullscreenElement)document.exitFullscreen();else document.documentElement.requestFullscreen();});
document.querySelector('#record').addEventListener('click',()=>{
  const button=document.querySelector('#record');if(button.disabled)return;
  if(!renderer.domElement.captureStream||!window.MediaRecorder){button.title='Recording is unavailable in this browser';return;}
  const stream=renderer.domElement.captureStream(24),chunks=[];
  const mime=MediaRecorder.isTypeSupported('video/webm;codecs=vp9')?'video/webm;codecs=vp9':'video/webm';
  const recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:4000000});
  button.disabled=true;button.style.color='#d84b4b';button.title='Recording the moving district…';
  recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
  recorder.onstop=()=>{
    const blob=new Blob(chunks,{type:'video/webm'}),url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download='brooklyn-vpp-district.webm';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
    stream.getTracks().forEach(track=>track.stop());button.disabled=false;button.style.color='';button.title='Record a 10-second WebM clip of the moving district';
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
function resize(){const w=host.clientWidth,h=host.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}
new ResizeObserver(resize).observe(host);resize();
function animate(){
  requestAnimationFrame(animate);const now=performance.now();if(now-lastRender<1000/30)return;lastRender=now;
  const delta=Math.min(clock.getDelta(),.1);
  if(!readyForRender)return;
  if(flight){const progress=clamp((now-flight.start)/1400,0,1),s=progress<.5?4*progress**3:1-(-2*progress+2)**3/2;camera.position.lerpVectors(flight.from,flight.to,s);controls.target.lerpVectors(flight.oldTarget,flight.target,s);if(progress===1)flight=null;}
  controls.update();updateVehicles(delta);updateElectrical(now/1000);
  if(now-lastMap>350){minimap();lastMap=now;}
  renderer.render(scene,camera);renderFrames++;
  // Public rendering diagnostics aid browser QA; numerical powers come from state API.
  document.body.dataset.frames=String(renderFrames);document.body.dataset.trafficFrame=String(trafficFrame);document.body.dataset.drawCalls=String(renderer.info.render.calls);
}
animate();
async function boot(){
  if(!runId)throw new Error('Choose a completed energy simulation first.');
  const response=await fetch('/api/city/'+encodeURIComponent(runId));if(!response.ok)throw new Error(await response.text());data=await response.json();
  ground();loading('Laying out the observed NYC street network…');streets();
  loading('Adding façades, window frames and rooftop equipment…');
  for(let i=0;i<data.buildings.length;i++){makeBuilding(data.buildings[i]);if(i%35===0)await new Promise(requestAnimationFrame);}
  batchStaticCity();tiledInstances(windowFrames,boxGeo,frameMaterial);tiledInstances(windowGlass,boxGeo,glassMaterial,true);tiledInstances(windowBars,boxGeo,frameMaterial);instances(roofPanels,boxGeo,panelMaterial);trees();electrical();
  loading('Loading the executed street traffic scenario…');
  const tr=await fetch('/api/city-traffic');if(!tr.ok)throw new Error('Traffic scenario could not be loaded');traffic=await tr.json();vehicles();
  document.body.dataset.buildings=String(data.buildings.length);document.body.dataset.windows=String(windowGlass.length);document.body.dataset.roads=String(data.roads.length);document.body.dataset.cars=String(traffic.cars.length);
  select(0);minimap();await sync(pendingState||{step:48,asset:0,layer:'assets'});
  loading('Finishing daylight materials…');if(renderer.compileAsync)await renderer.compileAsync(scene,camera);
  readyForRender=true;document.body.dataset.ready='true';
  const loadingPanel=document.querySelector('#loading');loadingPanel.classList.add('hide');loadingPanel.setAttribute('aria-hidden','true');
  setTimeout(()=>loadingPanel.style.display='none',650);parent.postMessage({type:'vpp-city-ready'},location.origin);
}
boot().catch(error=>{console.error(error);loading(error.message);document.querySelector('#loading strong').textContent='District view unavailable';});
