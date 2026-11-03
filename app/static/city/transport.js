/** Continuous road ribbons and the two distinct East River suspension bridges.
 * CSCL supplies plan geometry. Structural details and vertical profiles are
 * estimated presentation geometry, calibrated to the published DOT main spans.
 */
import * as THREE from 'three';

export function ribbonGeometry(points,width,heights,thickness=0){
  const vertices=[],uv=[],indices=[],edges=[];let distance=0;
  for(let i=0;i<points.length;i++){
    const p=points[i],prev=points[Math.max(0,i-1)],next=points[Math.min(points.length-1,i+1)];
    const before=new THREE.Vector2(p[0]-prev[0],p[1]-prev[1]),after=new THREE.Vector2(next[0]-p[0],next[1]-p[1]);
    if(before.lengthSq()<1e-8)before.copy(after);if(after.lengthSq()<1e-8)after.copy(before);
    before.normalize();after.normalize();
    const n0=new THREE.Vector2(-before.y,before.x),n1=new THREE.Vector2(-after.y,after.x),miter=n0.clone().add(n1).normalize();
    const half=Math.min(width*1.5,width/2/Math.max(.34,miter.dot(n1)));
    const offset=miter.multiplyScalar(half),y=Array.isArray(heights)?heights[i]:heights;
    if(i)distance+=Math.hypot(p[0]-prev[0],p[1]-prev[1]);
    edges.push([[p[0]+offset.x,y,p[1]+offset.y],[p[0]-offset.x,y,p[1]-offset.y]]);
    vertices.push(...edges[i][0],...edges[i][1]);uv.push(0,distance,width,distance);
    if(i){const o=i*2;indices.push(o-2,o,o-1,o-1,o,o+1);}
  }
  if(thickness){
    // All four edges of EVERY deck segment are present, including end caps.
    const topCount=vertices.length/3;
    for(const edge of edges)for(const p of edge){vertices.push(p[0],p[1]-thickness,p[2]);uv.push(0,0);}
    for(let i=1;i<points.length;i++){
      const a=(i-1)*2,b=i*2,A=a+topCount,B=b+topCount;
      indices.push(a,A,b,b,A,B,a+1,b+1,A+1,b+1,B+1,A+1,A,A+1,B,A+1,B+1,B);
    }
    indices.push(0,1,topCount,1,topCount+1,topCount);
    const e=topCount-2;indices.push(e,e+topCount,e+1,e+1,e+topCount,e+topCount+1);
  }
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));
  g.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));g.setIndex(indices);g.computeVertexNormals();return g;
}

export function buildBridges(scene,bridges,night){
  const lightPositions=[];
  const steel=new THREE.MeshStandardMaterial({color:0x647f86,metalness:.48,roughness:.57});
  const cable=new THREE.MeshStandardMaterial({color:0x52616a,metalness:.5,roughness:.58});
  const masonry=document.createElement('canvas');masonry.width=masonry.height=512;
  const ink=masonry.getContext('2d');ink.fillStyle='#b4a58f';ink.fillRect(0,0,512,512);
  for(let row=0;row<8;row++)for(let col=-1;col<4;col++){
    const x=col*128+(row%2)*64,y=row*64;
    ink.fillStyle=`rgba(61,52,42,${.025+((row*13+col*7+32)%9)*.008})`;ink.fillRect(x+2,y+2,124,60);
    ink.strokeStyle='#847b6b';ink.lineWidth=1.4;ink.strokeRect(x,y,128,64);
  }
  const stoneMap=new THREE.CanvasTexture(masonry);stoneMap.wrapS=stoneMap.wrapT=THREE.RepeatWrapping;
  stoneMap.repeat.set(.24,.24);stoneMap.colorSpace=THREE.SRGBColorSpace;stoneMap.anisotropy=4;
  const stone=new THREE.MeshStandardMaterial({map:stoneMap,bumpMap:stoneMap,bumpScale:.035,roughness:.95});
  const trim=new THREE.MeshStandardMaterial({color:0xc3b39b,roughness:.91});
  const concrete=new THREE.MeshStandardMaterial({color:0x989c94,roughness:.95});
  const tracks=new THREE.MeshStandardMaterial({color:0x535a57,roughness:.9});
  const rail=new THREE.MeshStandardMaterial({color:0x87928e,metalness:.6,roughness:.5});
  for(const material of [steel,cable,stone,trim,concrete,rail])material.onBeforeCompile=shader=>{
    shader.uniforms.uBridgeNight=night;
    shader.fragmentShader='uniform float uBridgeNight;\n'+shader.fragmentShader.replace('#include <emissivemap_fragment>','#include <emissivemap_fragment>\n totalEmissiveRadiance += diffuseColor.rgb * uBridgeNight * 0.085;');
  };
  const box=new THREE.BoxGeometry(1,1,1),wire=new THREE.CylinderGeometry(1,1,1,6);
  function mesh(g,m){const o=new THREE.Mesh(g,m);scene.add(o);o.castShadow=true;o.receiveShadow=true;return o;}
  function beam(a,b,width,depth,material,round=false){
    const d=new THREE.Vector3().subVectors(b,a),o=mesh(round?wire:box,material);
    o.position.copy(a).add(b).multiplyScalar(.5);o.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),d.clone().normalize());
    o.scale.set(width,d.length(),depth);return o;
  }
  for(const b of bridges){
    const axis=new THREE.Vector2(...b.axis),normal=new THREE.Vector2(-axis.y,axis.x),half=b.main_span/2,anchor=half+b.side_span;
    const point=(s,y,t=0)=>new THREE.Vector3(b.centre[0]+axis.x*s+normal.x*t,y,b.centre[1]+axis.y*s+normal.y*t);
    const deck=s=>{
      if(Math.abs(s)<=half)return 40.5+2*(1-(s/half)**2);
      const end=b.ends[s<0?0:1],t=THREE.MathUtils.clamp((Math.abs(s)-half)/(Math.abs(end)-half),0,1);
      return 40.5*(1-t)**1.12;
    };
    const samples=[];for(let s=-anchor;s<anchor;s+=8)samples.push(s);samples.push(anchor);
    const pts=samples.map(s=>{const p=point(s,0);return[p.x,p.z];}),ys=samples.map(s=>deck(s)-.65);
    mesh(ribbonGeometry(pts,b.width,ys,1.1),b.id==='brooklyn'?stone:steel);
    // Continuous longitudinal stiffening girders, cross beams and safety rails.
    for(let i=1;i<samples.length;i++){
      const a=samples[i-1],c=samples[i];
      for(const t of [-b.width/2,b.width/2]){
        beam(point(a,deck(a)-1.7,t),point(c,deck(c)-1.7,t),.42,1.4,b.id==='brooklyn'?cable:steel);
        beam(point(a,deck(a)+1.15,t),point(c,deck(c)+1.15,t),.14,.14,rail);
        beam(point(a,deck(a)+.5,t),point(c,deck(c)+.5,t),.08,.08,rail);
        beam(point(a,deck(a),t),point(a,deck(a)+1.2,t),.09,.09,rail);
      }
      if(i%3===0)beam(point(a,deck(a)-1.8,-b.width/2),point(a,deck(a)-1.8,b.width/2),.28,.5,steel);
      if(b.id==='manhattan')for(const t of [-14,-10,10,14])for(const off of [-.72,.72])beam(point(a,deck(a)+.13,t+off),point(c,deck(c)+.13,t+off),.075,.075,rail);
    }
    if(b.id==='manhattan')for(const t of [-14,-10,10,14]){
      const path=pts.map(p=>[p[0]+normal.x*t,p[1]+normal.y*t]);mesh(ribbonGeometry(path,2.6,samples.map(s=>deck(s)+.04)),tracks);
    }
    for(const sign of [-1,1]){
      const s=sign*half;
      if(b.id==='brooklyn'){
        // The two pointed openings are holes through a single masonry tower,
        // allowing the carriageways and raised promenade to pass through it.
        const shape=new THREE.Shape();shape.moveTo(-17,0);shape.lineTo(17,0);shape.lineTo(17,b.tower_height);shape.lineTo(-17,b.tower_height);shape.closePath();
        for(const centre of [-7.1,7.1]){
          const h=new THREE.Path(),left=centre-4.8,right=centre+4.8;
          h.moveTo(left,35);h.lineTo(left,68);h.quadraticCurveTo(left,74,centre,79);h.quadraticCurveTo(right,74,right,68);h.lineTo(right,35);h.closePath();shape.holes.push(h);
        }
        const g=new THREE.ExtrudeGeometry(shape,{depth:11.8,bevelEnabled:false,curveSegments:8});g.translate(0,0,-5.9);
        const o=mesh(g,stone);o.position.copy(point(s,0));o.rotation.y=Math.atan2(axis.x,axis.y);
        for(const y of [33,81.5,84])beam(point(s,y,-18),point(s,y,18),y===33?1.5:1,13,trim);
        beam(point(s,2,-19),point(s,2,19),4,15,stone);
      }else{
        // Four slender steel columns, latticed upper portals and stone piers.
        for(const t of [-17,17]){
          beam(point(s,5,t),point(s,14,t),6,12,stone);
          for(const z of [-3.5,3.5]){
            beam(point(s+z,14,t),point(s+z,98,t*.92),1.4,1.6,steel);
            beam(point(s+z,97,t*.92),point(s+z,103,t*.92),.65,.65,steel,true);
          }
          for(let y=20;y<94;y+=12){
            beam(point(s-3.5,y,t),point(s+3.5,y+12,t*.96),.35,.35,steel);
            beam(point(s+3.5,y,t),point(s-3.5,y+12,t*.96),.35,.35,steel);
          }
        }
        for(const y of [53,75,96])beam(point(s,y,-16),point(s,y,16),1.5,2.5,steel);
        for(const y of [75,86])for(const z of [-3.5,3.5]){
          beam(point(s+z,y,-16),point(s+z,y+10,16),.5,.5,steel);
          beam(point(s+z,y,16),point(s+z,y+10,-16),.5,.5,steel);
        }
        // Curved portal over the upper carriageways, below the lattice crown.
        for(let i=1;i<=24;i++){
          const a=-16+(i-1)*32/24,c=-16+i*32/24;
          beam(point(s,64+10*Math.sqrt(Math.max(0,1-(a/16)**2)),a),point(s,64+10*Math.sqrt(Math.max(0,1-(c/16)**2)),c),.9,1.8,steel);
        }
      }
      // Solid anchorages are on the sides of the suspended spans; there are no
      // arbitrary piers under the navigable main channel.
      const ah=deck(sign*anchor)+5;
      beam(point(sign*anchor,0),point(sign*anchor,ah),b.width+7,20,b.id==='brooklyn'?stone:concrete);
    }
    const cableOffsets=b.id==='brooklyn'?[-12,-4.5,4.5,12]:[-17,-13.8,13.8,17];
    const cableY=s=>{
      if(Math.abs(s)<=half)return deck(0)+10+(b.tower_height-2-deck(0)-10)*(s/half)**2;
      const t=(Math.abs(s)-half)/b.side_span;
      return (b.tower_height-2)*(1-t)+(deck(anchor)+7)*t-10*t*(1-t);
    };
    for(const t of cableOffsets){
      for(let s=-anchor;s<anchor;s+=7){const end=Math.min(anchor,s+7);beam(point(s,cableY(s),t),point(end,cableY(end),t),b.id==='brooklyn'?.22:.28,b.id==='brooklyn'?.22:.28,cable,true);}
      for(let s=-anchor+8;s<anchor;s+=12)beam(point(s,deck(s)+.3,t),point(s,cableY(s),t),.045,.045,cable,true);
      if(b.id==='brooklyn')for(const tower of [-half,half])for(const direction of [-1,1])for(let d=25;d<180;d+=28){
        const s=tower+direction*d;beam(point(tower,b.tower_height-4,t),point(s,deck(s)+1,t),.045,.045,cable,true);
      }
      if(Math.abs(t)===Math.max(...cableOffsets))for(let s=-anchor;s<=anchor;s+=16)lightPositions.push(...point(s,cableY(s)+.3,t));
    }
  }
  // Estimated necklace lighting: one inexpensive point batch, no added dynamic
  // lights or shadow passes. It follows the same shared night transition.
  const glow=document.createElement('canvas');glow.width=glow.height=32;
  const glowInk=glow.getContext('2d'),gradient=glowInk.createRadialGradient(16,16,1,16,16,16);
  gradient.addColorStop(0,'#ffffff');gradient.addColorStop(.2,'#ffffff');gradient.addColorStop(1,'#ffffff00');glowInk.fillStyle=gradient;glowInk.fillRect(0,0,32,32);
  const lights=new THREE.PointsMaterial({color:0xffd99b,size:2,sizeAttenuation:false,toneMapped:false,map:new THREE.CanvasTexture(glow),transparent:true,depthWrite:false});
  lights.onBeforeCompile=shader=>{shader.uniforms.uBridgeNight=night;shader.fragmentShader='uniform float uBridgeNight;\n'+shader.fragmentShader.replace('#include <color_fragment>','#include <color_fragment>\n diffuseColor.a *= uBridgeNight;');};
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(lightPositions,3));
  const points=new THREE.Points(geometry,lights);points.userData.noAO=true;scene.add(points);
}
