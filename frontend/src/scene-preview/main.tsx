import React,{useEffect,useRef,useState} from 'react';
import{createRoot}from'react-dom/client';
import * as T from 'three';
import{GLTFLoader}from'three/examples/jsm/loaders/GLTFLoader.js';
import '../preview-original.css';
import './preview.css';

export type Status='idle'|'working'|'waiting'|'completed'|'error'|'paused';
const labels:Record<Status,string>={idle:'空闲',working:'工作中',waiting:'等待确认',completed:'完成',error:'失败',paused:'已暂停'};
const statusCode:Record<Status,string>={idle:'IDLE',working:'ACTIVE',waiting:'HOLD',completed:'DONE',error:'ERR',paused:'PAUSED'};
const regions=['Reception','Inspiration','Creation','Review','Theater','Analysis','Delivery'];
const titles=['需求与运营','灵感选题','内容创作','独立审稿','观众试映','数据分析','展示与交付'];
// 暗黑霓虹配色：每区一个主色，光束 / 光圈 / 弹窗 / 面板共用
const accent=['#a98bff','#5cf2b4','#ffb066','#ffd166','#ff6fd8','#4fd8ff','#ff6b5e'];

export const backendDisplay:Record<string,Status>={DRAFT:'idle',PLANNING:'working',QUEUED:'idle',GENERATING:'working',VALIDATING:'working',REVISING:'working',EXPORTING:'working',WAITING_CONFIRMATION:'waiting',WAITING_INPUT:'waiting',NEEDS_REVIEW:'waiting',READY:'completed',ACCEPTED:'completed',FAILED:'error',INTERRUPTED:'paused',CANCELLED:'paused'};

const BEAM_VERT=`
varying vec2 vUv; varying vec3 vN; varying vec3 vV;
void main(){
  vUv=uv;
  vec4 mv=modelViewMatrix*vec4(position,1.0);
  vN=normalize(normalMatrix*normal);
  vV=normalize(-mv.xyz);
  gl_Position=projectionMatrix*mv;
}`;
const BEAM_FRAG=`
uniform vec3 uColor; uniform float uOpacity; uniform float uTime;
varying vec2 vUv; varying vec3 vN; varying vec3 vV;
void main(){
  float h=clamp(vUv.y,0.0,1.0);
  float fade=pow(1.0-h,1.65);                      // 底部强、向上逐渐衰减
  float rim=pow(1.0-abs(dot(normalize(vN),normalize(vV))),1.0);  // 柱体边缘更亮
  float streak=0.62+0.38*sin(vUv.x*6.2831*56.0+uTime*1.6);
  float scan=0.80+0.20*sin(h*34.0-uTime*2.2);      // 竖向扫描条纹
  float a=fade*(0.26+0.74*rim)*streak*scan*uOpacity*1.9;
  gl_FragColor=vec4(uColor,a);
}`;

interface Props{statuses:Record<string,Status>;selected:string|null;onSelect:(id:string)=>void}

export function CourtyardPreview({statuses,selected,onSelect}:Props){
const host=useRef<HTMLDivElement>(null),api=useRef<any>(null),latest=useRef({statuses,selected,onSelect});latest.current={statuses,selected,onSelect};
const [ready,setReady]=useState(false),[error,setError]=useState(''),[positions,setPositions]=useState<any[]>([]);

useEffect(()=>{const el=host.current!;let disposed=false;const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;

// ---- 渲染器：近黑紫底、低曝光 ----
const renderer=new T.WebGLRenderer({antialias:true,alpha:false});
renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));
renderer.setClearColor('#07050c');
renderer.outputColorSpace=T.SRGBColorSpace;
renderer.toneMapping=T.ACESFilmicToneMapping;
renderer.toneMappingExposure=1.02;
el.appendChild(renderer.domElement);

const scene=new T.Scene();
const camera=new T.OrthographicCamera();
// 环绕参数：以 ORBIT 为中心做球面环绕，拖拽改 theta/phi，滚轮只改 zoom
const ORBIT=new T.Vector3(2,0,-1);
const HOME={theta:0.5977,phi:0.9223,radius:71.29};
let theta=HOME.theta,phi=HOME.phi,radius=HOME.radius;
function applyOrbit(){
  const s=Math.sin(phi),c=Math.cos(phi);
  camera.position.set(ORBIT.x+radius*s*Math.sin(theta),ORBIT.y+radius*c,ORBIT.z+radius*s*Math.cos(theta));
  camera.lookAt(ORBIT);camera.updateProjectionMatrix();
}
applyOrbit();

// ---- 低照度灯光：环境压暗，但保留可辨形体的冷光 ----
scene.add(new T.HemisphereLight('#3b3560','#0a0814',1.15));
// 主光：冷白，从上前方打下来，让墙面/体块产生明暗面差（不与区域彩色光效同色系）
const key=new T.DirectionalLight('#cfe0ff',2.6);key.position.set(12,30,24);scene.add(key);
const fill=new T.DirectionalLight('#7f95ff',.85);fill.position.set(-24,14,-18);scene.add(fill);
const rimA=new T.DirectionalLight('#7c5cff',1.25);rimA.position.set(-20,16,-14);scene.add(rimA);
const rimB=new T.DirectionalLight('#3fd6ff',.95);rimB.position.set(22,12,18);scene.add(rimB);

let model:T.Group|undefined,user:T.Object3D|null=null,path:T.Vector3[]=[],hover:string|null=null;
const rings:T.Mesh[]=[],beams:T.Mesh[]=[],discs:T.Mesh[]=[],obstacles:T.Box3[]=[];
const sparks:{geo:T.BufferGeometry;mat:T.PointsMaterial;pts:T.Points;data:Float32Array;speed:Float32Array;radius:number;cx:number;cz:number;height:number;seed:number}[]=[];
const ray=new T.Raycaster(),pointer=new T.Vector2();
let lastTarget='',lastMove=0,rushMode=false;
const ground=new T.Plane(new T.Vector3(0,1,0),-.23);

function syncLabels(){if(!model)return;const w=el.clientWidth,h=el.clientHeight;camera.updateMatrixWorld(true);setPositions(regions.map(id=>{const o=model!.getObjectByName('LabelAnchor_'+id);if(!o)return{id,x:-9999,y:-9999};const p=o.getWorldPosition(new T.Vector3()).project(camera);return{id,x:(p.x+1)/2*w,y:(1-p.y)/2*h}}))}
function resize(){const w=el.clientWidth,h=el.clientHeight;renderer.setSize(w,h);const a=w/h;camera.left=-27;camera.right=27;camera.top=27/a;camera.bottom=-27/a;camera.updateProjectionMatrix();syncLabels()}
const CAMTARGET=new T.Vector3(2,0,-1);
function resetView(){ORBIT.copy(CAMTARGET);theta=HOME.theta;phi=HOME.phi;radius=HOME.radius;camera.zoom=1;applyOrbit();syncLabels()}
function zoomAt(e:WheelEvent){e.preventDefault();const r=renderer.domElement.getBoundingClientRect();pointer.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);ray.setFromCamera(pointer,camera);const before=new T.Vector3();const hit=ray.ray.intersectPlane(ground,before);
const k=Math.pow(1.0016,-e.deltaY);camera.zoom=T.MathUtils.clamp(camera.zoom*k,.55,3.4);camera.updateProjectionMatrix();
if(hit){ray.setFromCamera(pointer,camera);const after=new T.Vector3();if(ray.ray.intersectPlane(ground,after))ORBIT.add(before.sub(after))}
// 平移范围限制在场景内，避免拖出画面
ORBIT.x=T.MathUtils.clamp(ORBIT.x,CAMTARGET.x-15,CAMTARGET.x+15);
ORBIT.z=T.MathUtils.clamp(ORBIT.z,CAMTARGET.z-15,CAMTARGET.z+15);
applyOrbit();syncLabels()}
const ro=new ResizeObserver(resize);ro.observe(el);resize();

const cell=.45,minX=-15,maxX=19,minZ=-11,maxZ=11,N=Math.floor((maxX-minX)/cell)+1,M=Math.floor((maxZ-minZ)/cell)+1;let walk:boolean[]=[];
function cellAt(p:T.Vector3){return[Math.round((p.x-minX)/cell),Math.round((p.z-minZ)/cell)]}
function index(x:number,z:number){return z*N+x}
function valid(x:number,z:number){return x>=0&&z>=0&&x<N&&z<M&&!!walk[index(x,z)]}
function point(x:number,z:number){return new T.Vector3(minX+x*cell,.23,minZ+z*cell)}
function navigate(target:T.Vector3){if(!user)return;const start=cellAt(user.position),end=cellAt(target);if(!valid(end[0],end[1]))return;const goal=index(end[0],end[1]),first=index(start[0],start[1]);const queue=[first],seen=new Map<number,number>([[first,-1]]);for(let q=0;q<queue.length;q++){const v=queue[q];if(v===goal)break;const x=v%N,z=Math.floor(v/N);for(const[dx,dz]of[[1,0],[-1,0],[0,1],[0,-1]]){const a=x+dx,b=z+dz,k=index(a,b);if(valid(a,b)&&!seen.has(k)){seen.set(k,v);queue.push(k)}}}if(!seen.has(goal))return;const steps=[];for(let k=goal;k!==first;k=seen.get(k)!){steps.push(point(k%N,Math.floor(k/N)))}path=steps.reverse();}
function nearestWalkable(cx:number,cz:number){for(let r=0;r<=8;r++){for(let dz=-r;dz<=r;dz++)for(let dx=-r;dx<=r;dx++){if(Math.max(Math.abs(dx),Math.abs(dz))!==r)continue;const x=cx+dx,z=cz+dz;if(valid(x,z))return[x,z]}}return null}
function rushTo(id:string){if(!user)return;const ring=rings.find(r=>r.userData.id===id);if(!ring)return;const c=cellAt(ring.userData.center as T.Vector3);const near=nearestWalkable(c[0],c[1]);if(!near)return;rushMode=true;navigate(point(near[0],near[1]))}

new GLTFLoader().load('/zhongmu.glb',g=>{if(disposed)return;model=g.scene;scene.add(model);model.updateMatrixWorld(true);

// ---- 暗黑材质：整体压暗，但按构件分层提亮，保证形体可读 ----
// 菲涅尔边缘光：只勾轮廓，冷白细边，与区域彩色光柱区分开
const rimMat=new T.ShaderMaterial({
  uniforms:{uColor:{value:new T.Color('#a9c2f5')},uOpacity:{value:.40},uPower:{value:3.2}},
  vertexShader:`varying vec3 vN;varying vec3 vV;void main(){vec4 mv=modelViewMatrix*vec4(position,1.0);vN=normalize(normalMatrix*normal);vV=normalize(-mv.xyz);gl_Position=projectionMatrix*mv;}`,
  fragmentShader:`uniform vec3 uColor;uniform float uOpacity;uniform float uPower;varying vec3 vN;varying vec3 vV;void main(){float f=pow(1.0-abs(dot(normalize(vN),normalize(vV))),uPower);gl_FragColor=vec4(uColor,f*uOpacity);}`,
  transparent:true,depthWrite:false,side:T.FrontSide,blending:T.AdditiveBlending
});
// 结构线：极细冷白描边，用于交代墙体/台阶/台面的转折（HUD 线稿感）
const lineMat=new T.LineBasicMaterial({color:'#8ba6e0',transparent:true,opacity:.20,depthWrite:false,blending:T.AdditiveBlending});
function shade(n:string,mn:string){
  const mat=new T.MeshStandardMaterial({roughness:.9,metalness:.04});
  const isFloor=/Floor|Courtyard|Promenade|Path|Connector|Ground/i.test(n);
  const isWall=/Wall|Column|Tier|Pillar|Frame|Backdrop/i.test(n);
  if(mn.includes('Coral')||/Coral/i.test(n)){mat.color.set('#4a1720');mat.emissive.set('#ff6b5e');mat.emissiveIntensity=.44}
  else if(isFloor){mat.color.set('#121028');mat.emissive.set('#181634');mat.emissiveIntensity=.22}
  else if(isWall){mat.color.set('#31355a');mat.emissive.set('#333d68');mat.emissiveIntensity=.46}
  else if(/Seat|Chair|Bench/i.test(n)){mat.color.set('#2b2e4d');mat.emissive.set('#262d56');mat.emissiveIntensity=.40}
  else if(/Data|Screen|Panel|Sign|Monitor/i.test(n)){mat.color.set('#212a4c');mat.emissive.set('#3d5c9c');mat.emissiveIntensity=.55}
  else{mat.color.set('#272a44');mat.emissive.set('#2a3058');mat.emissiveIntensity=.42}
  return mat;
}
const edgeTargets:T.Mesh[]=[],lineTargets:T.Mesh[]=[];
model.traverse(o=>{
  if(o.name.startsWith('Guide_')||o.name.startsWith('Label_'))o.visible=false;
  // 模型自带的地面感应圈（Sensor_*）由发光圆环替代，隐藏掉以免和光效圈重叠/残留
  if(o.name.startsWith('Sensor_')){o.visible=false;return}
  const mesh=o as T.Mesh;
  if(!mesh.isMesh)return;
  mesh.castShadow=false;mesh.receiveShadow=false;
  const src=(Array.isArray(mesh.material)?mesh.material[0]:mesh.material) as T.MeshStandardMaterial;
  const mn=src?.name||'';
  mesh.material=shade(o.name,mn);
  // 地面不勾边（避免一片网格噪点），立面/道具加冷白轮廓，让建模结构在暗场里能看清
  if(!/Floor|Courtyard|Promenade|Path|Connector/i.test(o.name))edgeTargets.push(mesh);
  // 结构线只给大构件，避免桌椅变噪点
  if(/Wall|Column|Tier|Step|Courtyard|Promenade|DataColumn/i.test(o.name))lineTargets.push(mesh);
  if(!/Floor|Courtyard|Promenade|Connector|Path|Sensor|Guide|User|DemoBar|Paper|Annotation/.test(o.name)){
    const b=new T.Box3().setFromObject(o);
    if(b.min.y<1.8&&b.max.y>.3)obstacles.push(b.expandByVector(new T.Vector3(.30,0,.30)));
  }
});
for(const m of edgeTargets){const edge=new T.Mesh(m.geometry,rimMat);edge.userData.rim=true;edge.matrixAutoUpdate=false;edge.renderOrder=1;m.add(edge)}
for(const m of lineTargets){const g=m.geometry;const pos=g.getAttribute('position') as T.BufferAttribute|undefined;if(!pos||pos.count>3000)continue;
  const ln=new T.LineSegments(new T.EdgesGeometry(g,32),lineMat);ln.userData.rim=true;ln.matrixAutoUpdate=false;m.add(ln)}

// ---- 人物根节点 ----
user=model.getObjectByName('User')||null;
if(!user){const parts:T.Object3D[]=[];model.traverse(o=>{if(o.name.startsWith('User_'))parts.push(o)});const grp=new T.Group();grp.position.set(4.15,.2,7);scene.add(grp);grp.updateMatrixWorld(true);for(const o of parts)grp.attach(o);user=grp}
if(user){const world=user.getWorldPosition(new T.Vector3());scene.attach(user);user.position.copy(world);user.position.set(0,.23,1)}
// 人物：压成暗色剪影 + 冷白细边，别像发光幽灵
const userMeshes:T.Mesh[]=[];user?.traverse(o=>{const m=o as T.Mesh;if(m.isMesh&&!m.userData.rim&&(m.material as any)?.color)userMeshes.push(m)});
const userRim=new T.ShaderMaterial({uniforms:{uColor:{value:new T.Color('#d7e4ff')},uOpacity:{value:.45},uPower:{value:2.2}},vertexShader:`varying vec3 vN;varying vec3 vV;void main(){vec4 mv=modelViewMatrix*vec4(position,1.0);vN=normalize(normalMatrix*normal);vV=normalize(-mv.xyz);gl_Position=projectionMatrix*mv;}`,fragmentShader:`uniform vec3 uColor;uniform float uOpacity;uniform float uPower;varying vec3 vN;varying vec3 vV;void main(){float f=pow(1.0-abs(dot(normalize(vN),normalize(vV))),uPower);gl_FragColor=vec4(uColor,f*uOpacity);}`,transparent:true,depthWrite:false,blending:T.AdditiveBlending});
for(const m of userMeshes){const mat=(m.material as T.MeshStandardMaterial).clone();mat.color.set('#383d5e');mat.emissive.set('#d2e2ff');mat.emissiveIntensity=.14;mat.roughness=.82;m.material=mat;
  const edge=new T.Mesh(m.geometry,userRim);edge.userData.rim=true;edge.matrixAutoUpdate=false;m.add(edge)}

for(let z=0;z<M;z++)for(let x=0;x<N;x++){const p=point(x,z);walk[index(x,z)]=!obstacles.some(b=>p.x>=b.min.x&&p.x<=b.max.x&&p.z>=b.min.z&&p.z<=b.max.z)}

// ---- 每个区域：地面细环 + 向上光柱 + 上升光粒 ----
const BEAM_H=3.4;
// 个别站点微调：观众试映的圆环挪到大屏幕正前方（屏幕在 12,2,-1.5），和标签靠近
const ringOverride:Record<string,[number,number]>={Theater:[12.2,-.9]};
regions.forEach((id,i)=>{
  const a=model!.getObjectByName('HitBase_'+id);if(!a)return;
  const p=a.getWorldPosition(new T.Vector3());const ov=ringOverride[id];if(ov)p.set(ov[0],p.y,ov[1]);
  const col=new T.Color(accent[i]);

  // depthTest:false —— 圆环是"跟踪标记"，被墙挡住也要能定位（HUD 语义）
  const ring=new T.Mesh(new T.RingGeometry(.62,.74,64),new T.MeshBasicMaterial({color:col,transparent:true,opacity:.5,side:T.DoubleSide,depthWrite:false,depthTest:false,blending:T.AdditiveBlending}));
  ring.rotation.x=-Math.PI/2;ring.position.copy(p);ring.position.y+=.03;ring.renderOrder=4;
  ring.userData={id,center:p.clone(),base:ring.position.y};scene.add(ring);rings.push(ring);

  const outer=new T.Mesh(new T.RingGeometry(1.0,1.03,64),new T.MeshBasicMaterial({color:col,transparent:true,opacity:.18,side:T.DoubleSide,depthWrite:false,depthTest:false,blending:T.AdditiveBlending}));
  outer.rotation.x=-Math.PI/2;outer.position.copy(p);outer.position.y+=.025;outer.renderOrder=3;outer.userData={id,center:p.clone(),base:outer.position.y,outer:true};scene.add(outer);rings.push(outer);

  // 光柱：竖直向上发散
  const beamMat=new T.ShaderMaterial({uniforms:{uColor:{value:col.clone()},uOpacity:{value:.5},uTime:{value:0}},vertexShader:BEAM_VERT,fragmentShader:BEAM_FRAG,transparent:true,depthWrite:false,side:T.DoubleSide,blending:T.AdditiveBlending});
  const beam=new T.Mesh(new T.CylinderGeometry(.66,.80,BEAM_H,44,1,true),beamMat);
  beam.position.set(p.x,p.y+BEAM_H/2,p.z);
  beam.userData={id,center:p.clone()};scene.add(beam);beams.push(beam);

  // 地面辉光底晕：径向衰减，让光柱像"从圆里升起"
  const discMat=new T.ShaderMaterial({uniforms:{uColor:{value:col.clone()},uOpacity:{value:.34}},transparent:true,depthWrite:false,blending:T.AdditiveBlending,
    vertexShader:`varying vec2 vUv;void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`,
    fragmentShader:`uniform vec3 uColor;uniform float uOpacity;varying vec2 vUv;void main(){float r=length(vUv-0.5)*2.0;float a=pow(max(0.0,1.0-r),3.2)*uOpacity;gl_FragColor=vec4(uColor,a);}`});
  const disc=new T.Mesh(new T.CircleGeometry(1.75,48),discMat);
  disc.rotation.x=-Math.PI/2;disc.position.set(p.x,p.y+.015,p.z);
  disc.userData={id,center:p.clone()};scene.add(disc);discs.push(disc);

  // 上升光粒（流萤）
  const COUNT=44,geo=new T.BufferGeometry(),data=new Float32Array(COUNT*3),speed=new Float32Array(COUNT);
  for(let k=0;k<COUNT;k++){const ang=Math.random()*Math.PI*2,rad=.15+Math.random()*.55;
    data[k*3]=Math.cos(ang)*rad;data[k*3+1]=Math.random()*BEAM_H;data[k*3+2]=Math.sin(ang)*rad;
    speed[k]=.35+Math.random()*.85}
  geo.setAttribute('position',new T.BufferAttribute(data,3));
  const pmat=new T.PointsMaterial({color:col,size:.045,transparent:true,opacity:.85,depthWrite:false,blending:T.AdditiveBlending,sizeAttenuation:true});
  const pts=new T.Points(geo,pmat);pts.position.set(p.x,p.y,p.z);scene.add(pts);
  sparks.push({geo,mat:pmat,pts,data,speed,radius:.62,cx:p.x,cz:p.z,height:BEAM_H,seed:i});
});

resize();setReady(true);
api.current={navigate,user,walk,obstacles,rushTo};
(window as any).__scenePreview={loaded:true,get position(){return user?.position.toArray()},get moving(){return path.length>0},navigate:(x:number,z:number)=>navigate(new T.Vector3(x,.23,z)),rushTo,get obstacles(){return obstacles.length},get rings(){return rings.filter(r=>!r.userData.outer).map(r=>({id:r.userData.id,center:(r.userData.center as T.Vector3).toArray().map(v=>+v.toFixed(2))}))},get beams(){return beams.length},get zoom(){return camera.zoom},setZoom:(z:number)=>{camera.zoom=T.MathUtils.clamp(z,.55,3.4);camera.updateProjectionMatrix();syncLabels()},get orbit(){return{theta:+theta.toFixed(3),phi:+phi.toFixed(3),target:ORBIT.toArray().map(v=>+v.toFixed(2))}},setOrbit:(t:number,p:number)=>{theta=t;phi=T.MathUtils.clamp(p,.20,1.34);applyOrbit();syncLabels()},resetView,noGuides:true};
},undefined,e=>{console.error('SCENE_LOAD_ERROR',(e as any)?.stack||e);setError(String(e))});

let drag=false,lastX=0,lastY=0,dragDist=0;
function onDown(e:PointerEvent){
  if(e.button!==0)return;
  const t=e.target as HTMLElement;
  if(t&&t.closest&&t.closest('.anchor'))return;          // 标签自身点击不触发旋转
  drag=true;lastX=e.clientX;lastY=e.clientY;dragDist=0;
  path=[];lastTarget='';rushMode=false;
  renderer.domElement.style.cursor='grabbing';
  window.addEventListener('pointerup',onUp);
}
function onUp(){
  if(!drag)return;drag=false;window.removeEventListener('pointerup',onUp);
  renderer.domElement.style.cursor=hover?'pointer':'crosshair';
  if(dragDist<6&&hover)latest.current.onSelect(hover);    // 位移很小 → 当作点击
}
function move(e:PointerEvent){
  // 左键拖拽 → 环绕旋转：拖动距离直接映射为旋转角度
  if(drag){
    const dx=e.clientX-lastX,dy=e.clientY-lastY;lastX=e.clientX;lastY=e.clientY;
    dragDist+=Math.hypot(dx,dy);
    theta-=dx*0.0055;
    phi=T.MathUtils.clamp(phi-dy*0.0045,0.20,1.34);
    applyOrbit();syncLabels();return;
  }
  if(e.target!==renderer.domElement){const t=e.target as HTMLElement;if(!t||!t.closest||!t.closest('.anchor'))path=[];return}
const r=renderer.domElement.getBoundingClientRect();pointer.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);ray.setFromCamera(pointer,camera);
const hits=ray.intersectObjects(rings);hover=hits[0]?.object.userData.id||null;
renderer.domElement.style.cursor=hover?'pointer':'crosshair';
if(hover){path=[];return}
if(performance.now()-lastMove<100)return;lastMove=performance.now();
const p=new T.Vector3();if(ray.ray.intersectPlane(ground,p)){const key=cellAt(p).join(',');if(key!==lastTarget){lastTarget=key;navigate(p)}}}
function stop(){path=[];lastTarget='';hover=null}
el.addEventListener('pointerdown',onDown);el.addEventListener('pointermove',move);el.addEventListener('pointerleave',stop);el.addEventListener('wheel',zoomAt,{passive:false});el.addEventListener('dblclick',resetView);

let frame=0,prev=performance.now();
function loop(now:number){
  if(disposed)return;
  const dt=Math.min((now-prev)/1000,.04);prev=now;const t=now/1000;
  const moving=!!path.length;
  if(user&&moving){const v=path[0].clone().sub(user.position);v.y=0;
    if(v.length()<.06)path.shift();
    else{const spd=rushMode?16:6.5;user.position.add(v.normalize().multiplyScalar(Math.min(dt*spd,path[0].distanceTo(user.position))));user.rotation.y=Math.atan2(-v.x,-v.z)}}
  if(!path.length)rushMode=false;
  if(user){user.position.y=.23+(!reduced&&moving?Math.sin(now*.018)*.035:0)}

  // 环 / 光柱 / 光粒 状态
  const zc=Math.min(1.85,Math.max(1,1/camera.zoom));   // 缩小时等比例放大圆环，避免小到看不见
  regions.forEach((id,i)=>{
    if(!rings[i*2])return;
    const lit=user?user.position.distanceTo(rings[i*2].userData.center as T.Vector3)<2.4:false;
    const st=latest.current.statuses[id]||'idle',sel=latest.current.selected===id,hv=hover===id;
    const pulse=.5+.5*Math.sin(t*1.5+i*1.3);
    const m=rings[i*2].material as T.MeshBasicMaterial;
    m.opacity=(lit?1:sel||hv?.85:.42+.26*pulse);
    m.color.set(st==='error'?'#ff4d4d':accent[i]);
    rings[i*2].scale.setScalar((lit?1.12:1+.03*pulse)*zc);
    const om=rings[i*2+1].material as T.MeshBasicMaterial;
    om.opacity=lit?.62:.16+.12*pulse;
    om.color.set(accent[i]);
    rings[i*2+1].scale.setScalar(zc);

    const bm=beams[i]?.material as T.ShaderMaterial|undefined;
    if(bm&&beams[i]){
      bm.uniforms.uTime.value=t;
      const target=lit?1.35:hv?.95:sel?.85:.52+.22*pulse;
      bm.uniforms.uOpacity.value+= (target-bm.uniforms.uOpacity.value)*Math.min(dt*6,1);
      beams[i].scale.set(1+(lit?.06:.02*pulse),1,1+(lit?.06:.02*pulse));
    }
    const dm=discs[i]?.material as T.ShaderMaterial|undefined;
    if(dm){const dt2=lit?.75:hv?.5:sel?.45:.28+.14*pulse;dm.uniforms.uOpacity.value+=(dt2-dm.uniforms.uOpacity.value)*Math.min(dt*6,1)}
    const sp=sparks[i];
    if(sp){
      sp.mat.opacity=lit?.95:.45+.2*pulse;
      const pos=sp.geo.getAttribute('position') as T.BufferAttribute;
      const speedScale=lit?1.9:1;
      for(let k2=0;k2<sp.speed.length;k2++){
        let y=pos.getY(k2)+dt*sp.speed[k2]*speedScale*(reduced?.3:1);
        if(y>sp.height)y=0;
        pos.setY(k2,y);
      }
      pos.needsUpdate=true;
    }
  });

  renderer.render(scene,camera);frame=requestAnimationFrame(loop)}
frame=requestAnimationFrame(loop);
return()=>{disposed=true;cancelAnimationFrame(frame);ro.disconnect();renderer.dispose();renderer.domElement.remove();
  el.removeEventListener('pointerdown',onDown);window.removeEventListener('pointerup',onUp);el.removeEventListener('pointermove',move);el.removeEventListener('pointerleave',stop);el.removeEventListener('wheel',zoomAt);el.removeEventListener('dblclick',resetView)};
},[]);

const selIdx=selected?regions.indexOf(selected):-1;
return <div className="viewport" ref={host} style={{'--accent':selIdx>=0?accent[selIdx]:'#8f9bd6'} as React.CSSProperties}>
  {!ready&&<div className="loading">{error||'INITIALIZING SCENE…'}</div>}
  {positions.map(p=>{
    const i=regions.indexOf(p.id),st=statuses[p.id]||'idle';
    return <button key={p.id} className={'anchor '+(selected===p.id?'chosen':'')} style={{left:p.x,top:p.y,'--c':accent[i]} as React.CSSProperties}
      onPointerEnter={()=>{if(api.current&&api.current.rushTo)api.current.rushTo(p.id)}}
      onClick={()=>onSelect(p.id)}>
      <span className="a-id">R{i+1}·{p.id.slice(0,3).toUpperCase()}</span>
      <b>{titles[i]}</b>
      <small><i className={'dot '+(st==='error'?'bad':'')}/>{statusCode[st]}</small>
    </button>})}
  <div className="hud-lines" aria-hidden>
    <span className="hud-corner tl"/><span className="hud-corner tr"/><span className="hud-corner bl"/><span className="hud-corner br"/>
    <span className="hud-cross c1">+</span><span className="hud-cross c2">+</span><span className="hud-cross c3">+</span><span className="hud-cross c4">+</span>
    <div className="hud-frame f1"/><div className="hud-frame f2"/>
  </div>
</div>}

function App(){
const [selected,setSelected]=useState<string|null>(null);
const [statuses,setStatuses]=useState<Record<string,Status>>(Object.fromEntries(regions.map(r=>[r,'idle'])));
const [clock,setClock]=useState('');
useEffect(()=>{const tick=()=>{const d=new Date();const p=(n:number)=>String(n).padStart(2,'0');
  setClock(`${d.getUTCFullYear()}-${p(d.getUTCMonth()+1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}Z`)};
  tick();const id=setInterval(tick,1000);return()=>clearInterval(id)},[]);
const idx=selected?regions.indexOf(selected):-1;
const st=selected?statuses[selected]||'idle':'idle';
return <main style={{'--accent':idx>=0?accent[idx]:'#8f9bd6'} as React.CSSProperties}>
  <header>
    <span className="brand">众幕 AI</span>
    <span className="hud-mono">COURTYARD / SCENE PREVIEW <em>DEMO · NOT CONNECTED</em></span>
    <a className="hud-mono" href="/workspace/overview" target="_blank">OPEN WORKSPACE ↗</a>
  </header>
  <CourtyardPreview statuses={statuses} selected={selected} onSelect={setSelected}/>
  <div className="hud-bar">
    <span className="hud-mono"><i className="dot"/>SYS ONLINE</span>
    <span className="hud-mono">MODE TRACK</span>
    <span className="hud-mono">OBJ 07</span>
    <span className="hud-alert">◤ SIGNAL {statuses[regions[idx>=0?idx:0]]==='error'?'WEAK':'STABLE'}</span>
    <span className="hud-mono right">UTC {clock}</span>
  </div>
  <aside>
    <div className="panel-head">
      <span className="a-id hud-mono">{idx>=0?`R${idx+1}·${regions[idx].slice(0,3).toUpperCase()}`:'SYS'}</span>
      <h2>{idx>=0?titles[idx]:'独立场景预览'}</h2>
      <div className="panel-meta hud-mono">
        <span>STATE</span><b className={st==='error'?'bad':''}>{statusCode[st]}</b>
        <span>LINK</span><b>/workspace</b>
      </div>
    </div>
    <p>{idx>=0?'点击标签即可查看内容，无需人物抵达。这里展示接口占位信息，不会触发真实任务。':'选择一个区域，预览工作状态。正式入口与业务逻辑保持不变。'}</p>
    <label className="hud-mono">DEMO STATE
      <select aria-label="演示状态" disabled={!selected} value={selected?statuses[selected]:'idle'} onChange={e=>selected&&setStatuses({...statuses,[selected]:e.target.value as Status})}>
        {Object.entries(labels).map(([k,v])=><option value={k} key={k}>{v}</option>)}
      </select>
    </label>
    {selected&&<>
      <p role="status" className="hud-mono">当前：{labels[statuses[selected]]}（演示）</p>
      <a className="enter" href={selected==='Analysis'?'/workspace/analytics':'/workspace/tasks'} target="_blank">打开对应业务入口 ↗</a>
      <button onClick={()=>setSelected(null)}>关闭详情</button>
    </>}
    <div className="panel-foot hud-mono">
      <span>移动鼠标探索</span><span>按住左键拖拽旋转</span><span>滚轮缩放</span><span>双击复位</span>
    </div>
  </aside>
</main>}

createRoot(document.getElementById('root')!).render(<App/>);
