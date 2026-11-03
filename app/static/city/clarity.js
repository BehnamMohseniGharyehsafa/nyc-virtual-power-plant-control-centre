/** Filter window coverage over a pixel instead of drawing sub-pixel geometry.
 * Exposed-wall metadata follows the same bays/floors as the close-up windows.
 * No invented architectural detail is added to the source geometry. */
import * as THREE from 'three';

export const DETAIL_DISTANCE=160;

export function facadeAttributes(geometry,building,part){
  const p=geometry.attributes.position,n=geometry.attributes.normal;
  const uv=new Float32Array(p.count*2),shape=new Float32Array(p.count*4);
  const floors=THREE.MathUtils.clamp(building.floors,1,45),fh=building.height/floors;
  const edges=part.rings[0].map((a,j)=>{
    const b=part.rings[0][(j+1)%part.rings[0].length],dx=b[0]-a[0],dz=b[1]-a[1],length=Math.hypot(dx,dz);
    const bays=Math.floor(length/(building.style==='glass'?2.05:2.85));
    return {a,dx,dz,length,bays,exposed:part.exposed[j]&&length>=2.4&&bays>0};
  }).filter(e=>e.exposed);
  for(let i=0;i<p.count;i+=3){
    if(Math.abs(n.getY(i))>.5)continue;
    const x=(p.getX(i)+p.getX(i+1)+p.getX(i+2))/3,z=(p.getZ(i)+p.getZ(i+1)+p.getZ(i+2))/3;
    const edge=edges.find(e=>{
      const along=((x-e.a[0])*e.dx+(z-e.a[1])*e.dz)/e.length;
      return along>=-.01&&along<=e.length+.01&&Math.abs((x-e.a[0])*e.dz-(z-e.a[1])*e.dx)/e.length<.015;
    });
    if(!edge)continue;
    const spacing=edge.length/edge.bays,ww=Math.min(spacing*.66,building.style==='glass'?1.8:1.75),wh=Math.min(fh*.65,2.5);
    for(let v=i;v<i+3;v++){
      uv[v*2]=((p.getX(v)-edge.a[0])*edge.dx+(p.getZ(v)-edge.a[1])*edge.dz)/(edge.length*spacing);
      uv[v*2+1]=p.getY(v)/fh;
      shape.set([ww/spacing,wh/fh,1,building.index*.137],v*4);
    }
  }
  geometry.setAttribute('facadeUv',new THREE.BufferAttribute(uv,2));
  geometry.setAttribute('facadeShape',new THREE.BufferAttribute(shape,4));
}

export function patchFacade(material,night){
  material.onBeforeCompile=shader=>{
    shader.uniforms.uFacadeNight=night;
    shader.vertexShader=`attribute vec2 facadeUv; attribute vec4 facadeShape;
      varying vec2 vFacadeUv; varying vec4 vFacadeShape; varying vec3 vFacadePosition;\n`+shader.vertexShader
      .replace('#include <begin_vertex>',`#include <begin_vertex>
        vFacadeUv=facadeUv; vFacadeShape=facadeShape;
        vFacadePosition=(modelMatrix*vec4(transformed,1.0)).xyz;`);
    shader.fragmentShader=`uniform float uFacadeNight;
      varying vec2 vFacadeUv; varying vec4 vFacadeShape; varying vec3 vFacadePosition;
      float pulseIntegral(float x,float width){return floor(x)*width+clamp(fract(x)-(0.5-width*0.5),0.0,width);}
      float filteredPulse(float x,float width,float pixel){
        float h=max(pixel*0.5,0.0001);
        return clamp((pulseIntegral(x+h,width)-pulseIntegral(x-h,width))/(2.0*h),0.0,1.0);
      }\n`+shader.fragmentShader
      .replace('#include <map_fragment>',`#include <map_fragment>
        vec2 pixel=max(fwidth(vFacadeUv),vec2(0.0001));
        vec2 cell=vFacadeUv-vec2(0.0,0.03);
        float panes=filteredPulse(cell.x,vFacadeShape.x,pixel.x)*filteredPulse(cell.y,vFacadeShape.y,pixel.y)*vFacadeShape.z;
        float frames=filteredPulse(cell.x,min(0.9,vFacadeShape.x+0.06),pixel.x)*filteredPulse(cell.y,min(0.9,vFacadeShape.y+0.05),pixel.y)*vFacadeShape.z;
        float room=fract(sin(dot(floor(cell)+vFacadeShape.w,vec2(12.9898,39.425)))*43758.5453);
        float resolved=1.0-smoothstep(0.25,0.8,max(pixel.x,pixel.y));
        vec3 glazing=vec3(0.105,0.175,0.205)*(0.96+(room-0.5)*0.12*resolved);
        diffuseColor.rgb=mix(diffuseColor.rgb,vec3(0.105,0.12,0.125),max(0.0,frames-panes)*0.65);
        diffuseColor.rgb=mix(diffuseColor.rgb,glazing,panes);`)
      .replace('#include <roughnessmap_fragment>',`#include <roughnessmap_fragment>
        roughnessFactor=mix(roughnessFactor,0.38,panes);`)
      .replace('#include <normal_fragment_maps>',`vec3 facadeBaseNormal=normal;
        #include <normal_fragment_maps>
        normal=normalize(mix(normal,facadeBaseNormal,smoothstep(70.0,210.0,distance(cameraPosition,vFacadePosition))));`)
      .replace('#include <emissivemap_fragment>',`#include <emissivemap_fragment>
        float occupied=mix(0.56,step(0.44,room),resolved);
        totalEmissiveRadiance+=vec3(0.85,0.49,0.22)*uFacadeNight*occupied*panes*0.45;`);
  };
  material.customProgramCacheKey=()=> 'vpp-filtered-facade-v1';
}

export function patchNearDetail(material,far=false){
  const previous=material.onBeforeCompile,cache=material.customProgramCacheKey.bind(material);
  const key=cache();
  material.onBeforeCompile=shader=>{
    previous.call(material,shader);
    // mvPosition is in view space after project_vertex, including instancing.
    shader.vertexShader='varying vec3 vDetailPosition;\n'+shader.vertexShader.replace('#include <project_vertex>',`#include <project_vertex>
      vDetailPosition=mvPosition.xyz;`);
    shader.fragmentShader='varying vec3 vDetailPosition;\n'+shader.fragmentShader.replace('#include <clipping_planes_fragment>',`#include <clipping_planes_fragment>
      if(length(vDetailPosition)${far?'<':'>'}${DETAIL_DISTANCE.toFixed(1)})discard;`);
  };
  material.customProgramCacheKey=()=>key+(far?'-far-v1':'-near-v1');
}
