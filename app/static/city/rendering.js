/** Rendering methods adapted from open-3d-skills: coherent light, fitted shadows,
 * multisampled post-processing, quality tiers and measured frame budgets.
 * Uses the project's pinned Three.js r180, with no remote runtime dependency. */
import * as THREE from 'three';
import {Sky} from 'three/addons/objects/Sky.js';
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js';
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js';
import {GTAOPass} from 'three/addons/postprocessing/GTAOPass.js';
import {UnrealBloomPass} from 'three/addons/postprocessing/UnrealBloomPass.js';
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js';
import {ShaderPass} from 'three/addons/postprocessing/ShaderPass.js';
import {FXAAShader} from 'three/addons/shaders/FXAAShader.js';

export const motionPreference=matchMedia('(prefers-reduced-motion: reduce)');
export const U={time:{value:0},night:{value:0},wind:{value:motionPreference.matches?0:1}};
const clamp=THREE.MathUtils.clamp,lerp=THREE.MathUtils.lerp;
const PRESETS={
  daylight:{elevation:38,azimuth:225,sun:3.25,sunColor:0xfff2df,skyColor:0xc7ddf0,groundColor:0x81735f,hemi:1.05,fog:0xd4e2ec,exposure:.86,environment:.55,night:0,turbidity:2.4},
  golden:{elevation:9,azimuth:135,sun:3.9,sunColor:0xffc27b,skyColor:0xc8d3e9,groundColor:0xa58263,hemi:1.65,fog:0xd6c4b2,exposure:.84,environment:.76,night:0,turbidity:5},
  blue:{elevation:-4,azimuth:255,sun:.32,sunColor:0xaac4ef,skyColor:0x7c9cc7,groundColor:0x514d56,hemi:.8,fog:0x536985,exposure:.88,environment:.45,night:.75,turbidity:4},
  night:{elevation:-14,azimuth:220,sun:.14,sunColor:0x91b4ed,skyColor:0x435777,groundColor:0x222532,hemi:.58,fog:0x142138,exposure:.9,environment:.27,night:1,turbidity:3},
};
const COLOR_KEYS=['sunColor','skyColor','groundColor','fog'];
const NUM_KEYS=['elevation','azimuth','sun','hemi','exposure','environment','night','turbidity'];
function values(p){const v={...p};for(const k of COLOR_KEYS)v[k]=new THREE.Color(p[k]);return v;}
function direction(elevation,azimuth){const e=THREE.MathUtils.degToRad(elevation),a=THREE.MathUtils.degToRad(azimuth);return new THREE.Vector3(Math.sin(a)*Math.cos(e),Math.sin(e),-Math.cos(a)*Math.cos(e));}

export function createRendering(renderer,scene,camera,host){
  renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate=false;
  renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.outputColorSpace=THREE.SRGBColorSpace;
  // Canvas MSAA is disabled: antialiasing belongs to this post-processing target.
  const target=new THREE.WebGLRenderTarget(1,1,{type:THREE.HalfFloatType,samples:Math.min(4,renderer.capabilities.maxSamples)});
  const composer=new EffectComposer(renderer,target);
  composer.addPass(new RenderPass(scene,camera));
  class ArchitecturalAO extends GTAOPass{
    setSize(width,height){super.setSize(Math.max(1,Math.round(width*.5)),Math.max(1,Math.round(height*.5)));}
    _overrideVisibility(){
      super._overrideVisibility();
      this.scene.traverse(o=>{if(o.userData.noAO&&o.visible){this._visibilityCache.push(o);o.visible=false;}});
    }
  }
  const ao=new ArchitecturalAO(scene,camera,1,1);
  ao.updateGtaoMaterial({radius:2.2,distanceExponent:1.5,thickness:1.1,scale:1,samples:8});
  ao.updatePdMaterial({radius:4,rings:2,samples:8});ao.blendIntensity=.28;composer.addPass(ao);
  const bloom=new UnrealBloomPass(new THREE.Vector2(1,1),.12,.45,.95);composer.addPass(bloom);
  composer.addPass(new OutputPass());
  const fxaa=new ShaderPass(FXAAShader);composer.addPass(fxaa);

  const sky=new Sky();sky.scale.setScalar(9000);sky.userData.noAO=true;sky.frustumCulled=false;scene.add(sky);
  const nightSky=new THREE.Mesh(new THREE.SphereGeometry(4400,24,12),new THREE.MeshBasicMaterial({color:0x0c1930,side:THREE.BackSide,transparent:true,opacity:0,depthWrite:false,fog:false}));
  nightSky.userData.noAO=true;nightSky.frustumCulled=false;nightSky.renderOrder=-1;scene.add(nightSky);
  const sun=new THREE.DirectionalLight(0xffffff,3.4);sun.castShadow=true;
  sun.shadow.autoUpdate=false;
  sun.shadow.bias=-.00008;sun.shadow.normalBias=.065;sun.shadow.camera.near=.5;sun.shadow.camera.far=3600;
  scene.add(sun,sun.target);
  const hemi=new THREE.HemisphereLight(0xc7ddf0,0x81735f,1.3);scene.add(hemi);
  scene.fog=new THREE.FogExp2(0xd4e2ec,.00015);
  // Reflections use the same analytic sky as the visible background.
  const reflectionScene=new THREE.Scene(),reflectionSky=new Sky();reflectionSky.scale.setScalar(10000);reflectionScene.add(reflectionSky);
  const reflectionGround=new THREE.Mesh(new THREE.CircleGeometry(12000,32),new THREE.MeshBasicMaterial({color:0x6f7263}));
  reflectionGround.rotation.x=-Math.PI/2;reflectionGround.position.y=-8;reflectionScene.add(reflectionGround);
  const pmrem=new THREE.PMREMGenerator(renderer);let environmentTarget=null;
  const previousShadowPosition=new THREE.Vector3(Infinity,Infinity,Infinity),previousShadowTarget=new THREE.Vector3(Infinity,Infinity,Infinity);
  let current=values(PRESETS.daylight),from=null,destination=null,transitionStart=0,transitionDuration=1,reflectionDirty=true;
  let quality='balanced',qualityMode='auto',frameSamples=[],frameCount=0,lastSample=0,readyAt=Infinity,lastFrameTime=null,slowSamples=0,fastSamples=0,lastTierChange=0,lastSize='';
  let diagnostics={fps:0,frameMs:0,p95Ms:0,calls:0,triangles:0};
  const query=new URLSearchParams(location.search),qualitySelect=document.querySelector('#quality');

  function applyLight(){
    for(const s of [sky,reflectionSky]){
      const u=s.material.uniforms;u.turbidity.value=current.turbidity;u.rayleigh.value=2.25;u.mieCoefficient.value=.004;u.mieDirectionalG.value=.82;
      u.sunPosition.value.copy(direction(current.elevation,current.azimuth));
    }
    sun.color.copy(current.sunColor);sun.intensity=current.sun;
    hemi.color.copy(current.skyColor);hemi.groundColor.copy(current.groundColor);hemi.intensity=current.hemi;
    scene.fog.color.copy(current.fog);scene.fog.density=.00015+current.night*.00013;
    renderer.toneMappingExposure=current.exposure;scene.environmentIntensity=current.environment;
    U.night.value=current.night;nightSky.material.opacity=current.night*.95;
    reflectionGround.material.color.copy(current.groundColor).multiplyScalar(.65);
    bloom.strength=.06+current.night*.12;bloom.threshold=.95-current.night*.13;bloom.enabled=quality!=='eco'&&current.night>.05;
    document.body.classList.toggle('night',current.night>.5);
  }
  function refreshReflections(){
    // Dispose after the new environment is ready; retain no old render targets.
    const previous=environmentTarget;environmentTarget=pmrem.fromScene(reflectionScene,.03,1,25000);
    scene.environment=environmentTarget.texture;previous?.dispose();reflectionDirty=false;
  }
  function resize(){
    const w=Math.max(1,host.clientWidth),h=Math.max(1,host.clientHeight);
    // Preserve at least native resolution. Drop costly effects before clarity.
    const ratio=quality==='high'?Math.min(Math.max(devicePixelRatio,1.5),2):quality==='balanced'?Math.min(Math.max(devicePixelRatio,1.25),1.75):Math.min(devicePixelRatio,1.25);
    const size=`${w}/${h}/${ratio}`;
    if(size!==lastSize){
      lastSize=size;frameSamples=[];lastFrameTime=null;slowSamples=fastSamples=0;
      readyAt=performance.now();lastSample=readyAt;
    }
    renderer.setPixelRatio(ratio);renderer.setSize(w,h,false);
    composer.setPixelRatio(ratio);composer.setSize(w,h);
    fxaa.material.uniforms.resolution.value.set(1/(w*ratio),1/(h*ratio));
    camera.aspect=w/h;
    const horizontal=Math.tan(THREE.MathUtils.degToRad(38)/2)*16/9;
    camera.fov=w/h<16/9?Math.min(68,THREE.MathUtils.radToDeg(2*Math.atan(horizontal/(w/h)))):38;
    camera.updateProjectionMatrix();document.body.dataset.pixelRatio=ratio.toFixed(2);
    document.body.dataset.resolution=`${Math.round(w*ratio)}×${Math.round(h*ratio)}`;
  }
  function setTier(next){
    quality=next;ao.enabled=next==='high';
    fxaa.enabled=renderer.capabilities.maxSamples===0;
    const samples=Math.min(next==='high'?4:2,renderer.capabilities.maxSamples);
    for(const rt of [composer.renderTarget1,composer.renderTarget2])if(rt.samples!==samples){rt.samples=samples;rt.dispose();}
    const size=next==='eco'?2048:4096;
    if(sun.shadow.mapSize.x!==size){sun.shadow.mapSize.set(size,size);sun.shadow.map?.dispose();sun.shadow.map=null;renderer.shadowMap.needsUpdate=true;sun.shadow.needsUpdate=true;}
    applyLight();resize();frameSamples=[];slowSamples=fastSamples=0;lastSample=performance.now();lastTierChange=lastSample;
    document.body.dataset.quality=quality;document.querySelector('#quality-state').textContent=qualityMode==='auto'?`Auto · ${quality}`:quality;
  }
  function setQuality(mode){
    qualityMode=['auto','high','balanced','eco'].includes(mode)?mode:'auto';
    if(qualitySelect)qualitySelect.value=qualityMode;
    setTier(qualityMode==='auto'?'balanced':qualityMode);
  }
  function setLight(name,simulation=null,immediate=false){
    let preset=PRESETS[name]||PRESETS.daylight;
    if(name==='simulation'&&simulation){
      const e=simulation.solar_elevation;
      preset={...(e<-8?PRESETS.night:e<1?PRESETS.blue:e<14?PRESETS.golden:PRESETS.daylight),elevation:e,azimuth:simulation.solar_azimuth};
    }
    from=values(current);for(const key of COLOR_KEYS)from[key]=current[key].clone();
    destination=values(preset);transitionStart=performance.now();transitionDuration=immediate||motionPreference.matches?0:1800;
    if(!transitionDuration){current=destination;destination=null;applyLight();reflectionDirty=true;}
    document.body.dataset.light=name;
  }
  function update(now,lookAt){
    U.time.value=now/1000;U.wind.value=motionPreference.matches?0:1;
    // Metre-scale AO is useful in street views, not for sub-pixel distant detail.
    ao.enabled=quality==='high'&&camera.position.distanceTo(lookAt)<240;
    if(destination){
      const k=clamp((now-transitionStart)/transitionDuration,0,1),e=k*k*(3-2*k);
      for(const key of NUM_KEYS)current[key]=lerp(from[key],destination[key],e);
      for(const key of COLOR_KEYS)current[key].copy(from[key]).lerp(destination[key],e);
      applyLight();if(k===1)reflectionDirty=true;
      if(k===1)destination=null;
    }
    if(reflectionDirty)refreshReflections();
    sky.position.copy(camera.position);nightSky.position.copy(camera.position);
    const half=clamp(camera.position.distanceTo(lookAt)*.68,65,710),sc=sun.shadow.camera;
    if(Math.abs(sc.right-half)>.05){sc.left=-half;sc.right=half;sc.top=half;sc.bottom=-half;sc.updateProjectionMatrix();renderer.shadowMap.needsUpdate=true;sun.shadow.needsUpdate=true;}
    const lightDir=direction(current.night>.5?38:Math.max(4,current.elevation),current.azimuth);
    // Snap in the light's own plane, which prevents crawling shadow edges.
    const right=new THREE.Vector3().crossVectors(lightDir,new THREE.Vector3(0,1,0)).normalize();
    const up=new THREE.Vector3().crossVectors(right,lightDir).normalize(),texel=half*2/sun.shadow.mapSize.x;
    const snapped=lookAt.clone().addScaledVector(right,Math.round(lookAt.dot(right)/texel)*texel-lookAt.dot(right));
    snapped.addScaledVector(up,Math.round(lookAt.dot(up)/texel)*texel-lookAt.dot(up));
    sun.target.position.copy(snapped);sun.position.copy(snapped).addScaledVector(lightDir,1500);sun.target.updateMatrixWorld();
    if(previousShadowPosition.distanceToSquared(sun.position)>.0025||previousShadowTarget.distanceToSquared(snapped)>.0025){
      previousShadowPosition.copy(sun.position);previousShadowTarget.copy(snapped);renderer.shadowMap.needsUpdate=true;sun.shadow.needsUpdate=true;
    }
  }
  function render(now){
    renderer.info.autoReset=false;renderer.info.reset();composer.render();frameCount++;
    diagnostics.calls=renderer.info.render.calls;diagnostics.triangles=renderer.info.render.triangles;
    if(lastFrameTime!==null&&now-readyAt>1500&&document.visibilityState==='visible'){
      const dt=now-lastFrameTime;if(dt>0&&dt<250)frameSamples.push(dt);
    }
    lastFrameTime=now;
    if(now-lastSample>3000&&frameSamples.length>=45){
      const sorted=[...frameSamples].sort((a,b)=>a-b),mean=frameSamples.reduce((a,b)=>a+b,0)/frameSamples.length;
      diagnostics.frameMs=mean;diagnostics.fps=1000/mean;diagnostics.p95Ms=sorted[Math.floor(sorted.length*.95)];
      slowSamples=mean>32?slowSamples+1:0;
      fastSamples=mean<22?fastSamples+1:0;
      if(qualityMode==='auto'&&!document.querySelector('#record').disabled&&now-lastTierChange>15000){
        if(slowSamples>=2&&quality!=='eco')setTier(quality==='high'?'balanced':'eco');
        else if(fastSamples>=3&&quality==='eco')setTier('balanced');
      }
      frameSamples=[];lastSample=now;
    }
    if(frameCount%15===0){
      Object.assign(document.body.dataset,{fps:diagnostics.fps.toFixed(1),frameMs:diagnostics.frameMs.toFixed(1),p95Ms:diagnostics.p95Ms.toFixed(1),drawCalls:String(diagnostics.calls),triangles:String(diagnostics.triangles),programs:String(renderer.info.programs.length)});
      const status=document.querySelector('#performance');if(status)status.textContent=diagnostics.fps?`${Math.round(diagnostics.fps)} fps · ${document.body.dataset.resolution}`:'Measuring…';
    }
  }
  qualitySelect?.addEventListener('change',()=>setQuality(qualitySelect.value));
  const gl=renderer.getContext(),debug=gl.getExtension('WEBGL_debug_renderer_info');
  document.body.dataset.gpu=debug?gl.getParameter(debug.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER);
  setQuality(query.get('quality')||'auto');applyLight();
  return {resize,update,render,setLight,setQuality,sun,hemi,composer,ao,get transitioning(){return !!destination;},ready(){readyAt=performance.now();lastFrameTime=null;frameSamples=[];}};
}

/** Stable per-window room variation, with depth cues and night illumination. */
export function patchWindows(material){
  material.onBeforeCompile=shader=>{
    shader.uniforms.uNight=U.night;
    shader.vertexShader='varying float vRoom;\n'+shader.vertexShader.replace('#include <begin_vertex>',`#include <begin_vertex>
      #ifdef USE_INSTANCING
        vRoom=fract(sin(dot(instanceMatrix[3].xyz,vec3(12.9898,7.233,39.425)))*43758.5453);
      #else
        vRoom=0.5;
      #endif`);
    shader.fragmentShader='uniform float uNight; varying float vRoom;\n'+shader.fragmentShader
      .replace('#include <color_fragment>',`#include <color_fragment>
        float blind=step(0.76,vRoom)*step(1.0-vRoom*0.55,vMapUv.y);
        diffuseColor.rgb=mix(diffuseColor.rgb,vec3(0.45,0.42,0.34),blind*0.7);
        diffuseColor.rgb*=0.92+vRoom*0.13;`)
      .replace('#include <emissivemap_fragment>',`#include <emissivemap_fragment>
        float lit=step(0.43,vRoom)*uNight;
        float edge=smoothstep(0.0,0.12,vMapUv.x)*smoothstep(0.0,0.12,1.0-vMapUv.x);
        totalEmissiveRadiance+=mix(vec3(1.0,0.56,0.21),vec3(0.7,0.83,1.0),step(0.9,vRoom))*lit*(0.35+vRoom*0.35)*edge;`);
  };
  material.customProgramCacheKey=()=> 'vpp-rooms-r180-v1';
}

export function patchFoliage(mesh){
  const sway=`
    #ifdef USE_INSTANCING
      float phase=dot(instanceMatrix[3].xz,vec2(0.13,0.17));
      transformed.x+=sin(uTime*1.4+phase)*0.025*uWind*(position.y+1.0);
      transformed.z+=cos(uTime*1.1+phase)*0.018*uWind*(position.y+1.0);
    #endif`;
  const patch=shader=>{
    shader.uniforms.uTime=U.time;shader.uniforms.uWind=U.wind;
    shader.vertexShader='uniform float uTime,uWind;\n'+shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>'+sway);
  };
  mesh.material.onBeforeCompile=patch;mesh.material.customProgramCacheKey=()=> 'vpp-foliage-v1';
  mesh.customDepthMaterial=new THREE.MeshDepthMaterial({depthPacking:THREE.RGBADepthPacking});
  mesh.customDepthMaterial.onBeforeCompile=patch;mesh.customDepthMaterial.customProgramCacheKey=()=> 'vpp-foliage-depth-v1';
}
