import { useEffect, useRef, useState, type CSSProperties } from "react";
import * as T from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import type { AgentId, AgentStatus, AgentVM } from "@/domain/types";
import { STATUS_META } from "@/domain/agents";
import "./courtyard-canvas.css";

/**
 * 众幕庭院场景（暗黑霓虹 HUD 版）——七个工位用发光圆环 + 上升光柱标记。
 * 交互：移动鼠标小人自动走过去；左键拖拽旋转视角；双击复位。
 * 缩放由外层（Headquarters3D 的 zoom 按钮）通过 userZoom 传入。
 */

type RegionId =
  | "Reception"
  | "Inspiration"
  | "Creation"
  | "Review"
  | "Theater"
  | "Analysis"
  | "Delivery";

const REGIONS: RegionId[] = [
  "Reception",
  "Inspiration",
  "Creation",
  "Review",
  "Theater",
  "Analysis",
  "Delivery",
];
const TITLES: Record<RegionId, string> = {
  Reception: "需求与运营",
  Inspiration: "灵感选题",
  Creation: "内容创作",
  Review: "独立审稿",
  Theater: "观众试映",
  Analysis: "数据分析",
  Delivery: "展示与交付",
};
const CODES: Record<RegionId, string> = {
  Reception: "REC",
  Inspiration: "INS",
  Creation: "CRE",
  Review: "REV",
  Theater: "THE",
  Analysis: "ANA",
  Delivery: "DEL",
};
// 区域 ↔ 角色：区域是流程站点，角色是站在站点上的人
const REGION_AGENT: Record<RegionId, AgentId> = {
  Reception: "operations_officer",
  Inspiration: "traffic_scout",
  Creation: "content_creator",
  Review: "editorial_reviewer",
  Theater: "simulated_audience",
  Analysis: "data_analyst",
  Delivery: "pr_analyst",
};
const AGENT_REGION = Object.fromEntries(
  Object.entries(REGION_AGENT).map(([region, agent]) => [agent, region]),
) as Record<AgentId, RegionId>;

const ACCENT = [
  "#a98bff",
  "#5cf2b4",
  "#ffb066",
  "#ffd166",
  "#ff6fd8",
  "#4fd8ff",
  "#ff6b5e",
];

const BEAM_VERT = `
varying vec2 vUv; varying vec3 vN; varying vec3 vV;
void main(){
  vUv=uv;
  vec4 mv=modelViewMatrix*vec4(position,1.0);
  vN=normalize(normalMatrix*normal);
  vV=normalize(-mv.xyz);
  gl_Position=projectionMatrix*mv;
}`;
const BEAM_FRAG = `
uniform vec3 uColor; uniform float uOpacity; uniform float uTime;
varying vec2 vUv; varying vec3 vN; varying vec3 vV;
void main(){
  float h=clamp(vUv.y,0.0,1.0);
  float fade=pow(1.0-h,1.65);
  float rim=pow(1.0-abs(dot(normalize(vN),normalize(vV))),1.0);
  float streak=0.62+0.38*sin(vUv.x*6.2831*56.0+uTime*1.6);
  float scan=0.80+0.20*sin(h*34.0-uTime*2.2);
  float a=fade*(0.26+0.74*rim)*streak*scan*uOpacity*1.9;
  gl_FragColor=vec4(uColor,a);
}`;

export interface CourtyardCanvasProps {
  agents: AgentVM[];
  selectedAgentId: AgentId | null;
  onSelectAgent: (id: AgentId | null) => void;
  userZoom: number;
  reducedMotion: boolean;
  immersive: boolean;
  onReady: () => void;
}

const STATUS_TO_SCENE: Record<AgentStatus, string> = {
  idle: "idle",
  working: "working",
  waiting: "waiting",
  review: "waiting",
  completed: "completed",
  error: "error",
};

export default function CourtyardCanvas({
  agents,
  selectedAgentId,
  onSelectAgent,
  userZoom,
  reducedMotion,
  immersive,
  onReady,
}: CourtyardCanvasProps) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef({ agents, selectedAgentId, onSelectAgent });
  live.current = { agents, selectedAgentId, onSelectAgent };
  const api = useRef<{
    reset: () => void;
    setZoom: (z: number) => void;
    rushTo: (region: RegionId) => void;
  } | null>(null);
  const [labels, setLabels] = useState<
    { region: RegionId; x: number; y: number }[]
  >([]);
  const [failed, setFailed] = useState("");

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let disposed = false;

    const renderer = new T.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    renderer.setClearColor("#07050c");
    renderer.outputColorSpace = T.SRGBColorSpace;
    renderer.toneMapping = T.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.02;
    el.appendChild(renderer.domElement);

    const scene = new T.Scene();
    const camera = new T.OrthographicCamera();
    const ORBIT = new T.Vector3(2, 0, -1);
    const HOME = { theta: 0.5977, phi: 0.9223, radius: 71.29 };
    let theta = HOME.theta;
    let phi = HOME.phi;
    let radius = HOME.radius;
    let baseZoom = 1;

    function applyOrbit() {
      const s = Math.sin(phi);
      const c = Math.cos(phi);
      camera.position.set(
        ORBIT.x + radius * s * Math.sin(theta),
        ORBIT.y + radius * c,
        ORBIT.z + radius * s * Math.cos(theta),
      );
      camera.lookAt(ORBIT);
      camera.updateProjectionMatrix();
    }

    scene.add(new T.HemisphereLight("#3b3560", "#0a0814", 1.15));
    const key = new T.DirectionalLight("#cfe0ff", 2.6);
    key.position.set(12, 30, 24);
    scene.add(key);
    const fill = new T.DirectionalLight("#7f95ff", 0.85);
    fill.position.set(-24, 14, -18);
    scene.add(fill);
    const rimA = new T.DirectionalLight("#7c5cff", 1.25);
    rimA.position.set(-20, 16, -14);
    scene.add(rimA);
    const rimB = new T.DirectionalLight("#3fd6ff", 0.95);
    rimB.position.set(22, 12, 18);
    scene.add(rimB);

    let model: T.Group | undefined;
    let user: T.Object3D | null = null;
    let path: T.Vector3[] = [];
    let hover: RegionId | null = null;
    const rings: T.Mesh[] = [];
    const beams: T.Mesh[] = [];
    const discs: T.Mesh[] = [];
    const sparks: {
      geo: T.BufferGeometry;
      mat: T.PointsMaterial;
      speeds: Float32Array;
      height: number;
    }[] = [];
    const obstacles: T.Box3[] = [];
    const ray = new T.Raycaster();
    const pointer = new T.Vector2();
    const ground = new T.Plane(new T.Vector3(0, 1, 0), -0.23);
    let lastTarget = "";
    let lastMove = 0;
    let rushMode = false;

    function syncLabels() {
      if (!model) return;
      const w = el!.clientWidth;
      const h = el!.clientHeight;
      camera.updateMatrixWorld(true);
      const raw = REGIONS.map((region) => {
        const anchor = model!.getObjectByName("LabelAnchor_" + region);
        if (!anchor) return { region, x: -9999, y: -9999 };
        const p = anchor.getWorldPosition(new T.Vector3()).project(camera);
        return {
          region,
          x: Math.min(w - 70, Math.max(70, ((p.x + 1) / 2) * w)),
          y: Math.min(h - 8, Math.max(64, ((1 - p.y) / 2) * h)),
        };
      }).sort((a, b) => a.y - b.y);

      // 简单避让：同一屏内标签互相压住时，下方那个再往下挪
      const placed: { x: number; y: number }[] = [];
      const out = raw.map((l) => {
        let y = l.y;
        for (let guard = 0; guard < 8; guard++) {
          const hit = placed.find(
            (q) => Math.abs(q.x - l.x) < 104 && Math.abs(q.y - y) < 54,
          );
          if (!hit) break;
          y = hit.y + 56;
        }
        y = Math.min(h - 8, y);
        placed.push({ x: l.x, y });
        return { region: l.region, x: l.x, y };
      });
      setLabels(out);
    }

    function resize() {
      const w = el!.clientWidth;
      const h = el!.clientHeight;
      renderer.setSize(w, h);
      const a = w / h;
      // 卡片内画面偏紧一点，让庭院撑满容器
      camera.left = -24;
      camera.right = 24;
      camera.top = 24 / a;
      camera.bottom = -24 / a;
      camera.updateProjectionMatrix();
      syncLabels();
    }
    const CAMTARGET = new T.Vector3(2, 0, -1);
    function resetView() {
      ORBIT.copy(CAMTARGET);
      theta = HOME.theta;
      phi = HOME.phi;
      radius = HOME.radius;
      applyOrbit();
      syncLabels();
    }

    // ---- 寻路网格 ----
    const cell = 0.45;
    const minX = -15;
    const minZ = -11;
    const N = Math.floor((19 - minX) / cell) + 1;
    const M = Math.floor((11 - minZ) / cell) + 1;
    const walk: boolean[] = [];
    const cellAt = (p: T.Vector3): [number, number] => [
      Math.round((p.x - minX) / cell),
      Math.round((p.z - minZ) / cell),
    ];
    const index = (x: number, z: number) => z * N + x;
    const valid = (x: number, z: number) =>
      x >= 0 && z >= 0 && x < N && z < M && !!walk[index(x, z)];
    const point = (x: number, z: number) =>
      new T.Vector3(minX + x * cell, 0.23, minZ + z * cell);

    function navigate(target: T.Vector3) {
      if (!user) return;
      const [sx, sz] = cellAt(user.position);
      const [ex, ez] = cellAt(target);
      if (!valid(ex, ez)) return;
      const goal = index(ex, ez);
      const first = index(sx, sz);
      const queue = [first];
      const seen = new Map<number, number>([[first, -1]]);
      for (let q = 0; q < queue.length; q++) {
        const v = queue[q];
        if (v === goal) break;
        const x = v % N;
        const z = Math.floor(v / N);
        for (const [dx, dz] of [
          [1, 0],
          [-1, 0],
          [0, 1],
          [0, -1],
        ]) {
          const a = x + dx;
          const b = z + dz;
          const k = index(a, b);
          if (valid(a, b) && !seen.has(k)) {
            seen.set(k, v);
            queue.push(k);
          }
        }
      }
      if (!seen.has(goal)) return;
      const steps: T.Vector3[] = [];
      for (let k = goal; k !== first; k = seen.get(k)!) {
        steps.push(point(k % N, Math.floor(k / N)));
      }
      path = steps.reverse();
    }

    function nearestWalkable(cx: number, cz: number) {
      for (let r = 0; r <= 8; r++) {
        for (let dz = -r; dz <= r; dz++)
          for (let dx = -r; dx <= r; dx++) {
            if (Math.max(Math.abs(dx), Math.abs(dz)) !== r) continue;
            if (valid(cx + dx, cz + dz)) return [cx + dx, cz + dz];
          }
      }
      return null;
    }

    function rushTo(region: RegionId) {
      if (!user) return;
      const ring = rings.find((r) => r.userData.region === region);
      if (!ring) return;
      const [cx, cz] = cellAt(ring.userData.center as T.Vector3);
      const near = nearestWalkable(cx, cz);
      if (!near) return;
      rushMode = true;
      navigate(point(near[0], near[1]));
    }

    new GLTFLoader().load(
      "/zhongmu.glb",
      (gltf) => {
        if (disposed) return;
        model = gltf.scene;
        scene.add(model);
        model.updateMatrixWorld(true);

        const rimMat = new T.ShaderMaterial({
          uniforms: {
            uColor: { value: new T.Color("#a9c2f5") },
            uOpacity: { value: 0.4 },
            uPower: { value: 3.2 },
          },
          vertexShader: `varying vec3 vN; varying vec3 vV; void main(){ vec4 mv=modelViewMatrix*vec4(position,1.0); vN=normalize(normalMatrix*normal); vV=normalize(-mv.xyz); gl_Position=projectionMatrix*mv; }`,
          fragmentShader: `uniform vec3 uColor; uniform float uOpacity; uniform float uPower; varying vec3 vN; varying vec3 vV; void main(){ float f=pow(1.0-abs(dot(normalize(vN),normalize(vV))),uPower); gl_FragColor=vec4(uColor,f*uOpacity); }`,
          transparent: true,
          depthWrite: false,
          blending: T.AdditiveBlending,
        });
        const lineMat = new T.LineBasicMaterial({
          color: "#8ba6e0",
          transparent: true,
          opacity: 0.2,
          depthWrite: false,
          blending: T.AdditiveBlending,
        });

        const shade = (name: string, srcName: string) => {
          const mat = new T.MeshStandardMaterial({
            roughness: 0.9,
            metalness: 0.04,
          });
          const isFloor = /Floor|Courtyard|Promenade|Path|Connector|Ground/i.test(
            name,
          );
          const isWall = /Wall|Column|Tier|Pillar|Frame|Backdrop/i.test(name);
          if (srcName.includes("Coral") || /Coral/i.test(name)) {
            mat.color.set("#4a1720");
            mat.emissive.set("#ff6b5e");
            mat.emissiveIntensity = 0.44;
          } else if (isFloor) {
            mat.color.set("#121028");
            mat.emissive.set("#181634");
            mat.emissiveIntensity = 0.22;
          } else if (isWall) {
            mat.color.set("#31355a");
            mat.emissive.set("#333d68");
            mat.emissiveIntensity = 0.46;
          } else if (/Seat|Chair|Bench/i.test(name)) {
            mat.color.set("#2b2e4d");
            mat.emissive.set("#262d56");
            mat.emissiveIntensity = 0.4;
          } else if (/Data|Screen|Panel|Sign|Monitor/i.test(name)) {
            mat.color.set("#212a4c");
            mat.emissive.set("#3d5c9c");
            mat.emissiveIntensity = 0.55;
          } else {
            mat.color.set("#272a44");
            mat.emissive.set("#2a3058");
            mat.emissiveIntensity = 0.42;
          }
          return mat;
        };

        const rimTargets: T.Mesh[] = [];
        const lineTargets: T.Mesh[] = [];
        model.traverse((o) => {
          if (o.name.startsWith("Guide_") || o.name.startsWith("Label_"))
            o.visible = false;
          if (o.name.startsWith("Sensor_")) {
            o.visible = false;
            return;
          }
          const mesh = o as T.Mesh;
          if (!mesh.isMesh) return;
          mesh.castShadow = false;
          mesh.receiveShadow = false;
          const src = (
            Array.isArray(mesh.material) ? mesh.material[0] : mesh.material
          ) as T.MeshStandardMaterial;
          mesh.material = shade(o.name, src?.name || "");
          if (!/Floor|Courtyard|Promenade|Path|Connector/i.test(o.name))
            rimTargets.push(mesh);
          if (/Wall|Column|Tier|Step|Courtyard|Promenade|DataColumn/i.test(o.name))
            lineTargets.push(mesh);
          if (
            !/Floor|Courtyard|Promenade|Connector|Path|Sensor|Guide|User|DemoBar|Paper|Annotation/.test(
              o.name,
            )
          ) {
            const b = new T.Box3().setFromObject(o);
            if (b.min.y < 1.8 && b.max.y > 0.3)
              obstacles.push(b.expandByVector(new T.Vector3(0.3, 0, 0.3)));
          }
        });
        for (const m of rimTargets) {
          const edge = new T.Mesh(m.geometry, rimMat);
          edge.userData.rim = true;
          edge.matrixAutoUpdate = false;
          edge.renderOrder = 1;
          m.add(edge);
        }
        for (const m of lineTargets) {
          const pos = m.geometry.getAttribute("position") as
            | T.BufferAttribute
            | undefined;
          if (!pos || pos.count > 3000) continue;
          const ln = new T.LineSegments(new T.EdgesGeometry(m.geometry, 32), lineMat);
          ln.userData.rim = true;
          ln.matrixAutoUpdate = false;
          m.add(ln);
        }

        // 小人
        user = model.getObjectByName("User") || null;
        if (!user) {
          const parts: T.Object3D[] = [];
          model.traverse((o) => {
            if (o.name.startsWith("User_")) parts.push(o);
          });
          const grp = new T.Group();
          grp.position.set(4.15, 0.2, 7);
          scene.add(grp);
          grp.updateMatrixWorld(true);
          for (const o of parts) grp.attach(o);
          user = grp;
        }
        if (user) {
          const world = user.getWorldPosition(new T.Vector3());
          scene.attach(user);
          user.position.copy(world);
          user.position.set(0, 0.23, 1);
        }
        const userMeshes: T.Mesh[] = [];
        user?.traverse((o) => {
          const m = o as T.Mesh;
          if (m.isMesh && !m.userData.rim && (m.material as T.MeshStandardMaterial)?.color)
            userMeshes.push(m);
        });
        const userRim = new T.ShaderMaterial({
          uniforms: {
            uColor: { value: new T.Color("#d7e4ff") },
            uOpacity: { value: 0.45 },
            uPower: { value: 2.2 },
          },
          vertexShader: `varying vec3 vN; varying vec3 vV; void main(){ vec4 mv=modelViewMatrix*vec4(position,1.0); vN=normalize(normalMatrix*normal); vV=normalize(-mv.xyz); gl_Position=projectionMatrix*mv; }`,
          fragmentShader: `uniform vec3 uColor; uniform float uOpacity; uniform float uPower; varying vec3 vN; varying vec3 vV; void main(){ float f=pow(1.0-abs(dot(normalize(vN),normalize(vV))),uPower); gl_FragColor=vec4(uColor,f*uOpacity); }`,
          transparent: true,
          depthWrite: false,
          blending: T.AdditiveBlending,
        });
        for (const m of userMeshes) {
          const mat = (m.material as T.MeshStandardMaterial).clone();
          mat.color.set("#383d5e");
          mat.emissive.set("#d2e2ff");
          mat.emissiveIntensity = 0.14;
          mat.roughness = 0.82;
          m.material = mat;
          const edge = new T.Mesh(m.geometry, userRim);
          edge.userData.rim = true;
          edge.matrixAutoUpdate = false;
          m.add(edge);
        }

        for (let z = 0; z < M; z++)
          for (let x = 0; x < N; x++) {
            const p = point(x, z);
            walk[index(x, z)] = !obstacles.some(
              (b) =>
                p.x >= b.min.x &&
                p.x <= b.max.x &&
                p.z >= b.min.z &&
                p.z <= b.max.z,
            );
          }

        // 工位：圆环 + 光柱 + 底晕 + 光粒
        const BEAM_H = 3.4;
        const ringOverride: Partial<Record<RegionId, [number, number]>> = {
          Theater: [12.2, -0.9],
        };
        REGIONS.forEach((region, i) => {
          const anchor = model!.getObjectByName("HitBase_" + region);
          if (!anchor) return;
          const p = anchor.getWorldPosition(new T.Vector3());
          const ov = ringOverride[region];
          if (ov) p.set(ov[0], p.y, ov[1]);
          const col = new T.Color(ACCENT[i]);

          const ring = new T.Mesh(
            new T.RingGeometry(0.62, 0.74, 64),
            new T.MeshBasicMaterial({
              color: col,
              transparent: true,
              opacity: 0.5,
              side: T.DoubleSide,
              depthWrite: false,
              depthTest: false,
              blending: T.AdditiveBlending,
            }),
          );
          ring.rotation.x = -Math.PI / 2;
          ring.position.copy(p);
          ring.position.y += 0.03;
          ring.renderOrder = 4;
          ring.userData = { region, center: p.clone() };
          scene.add(ring);
          rings.push(ring);

          const outer = new T.Mesh(
            new T.RingGeometry(1.0, 1.03, 64),
            new T.MeshBasicMaterial({
              color: col,
              transparent: true,
              opacity: 0.18,
              side: T.DoubleSide,
              depthWrite: false,
              depthTest: false,
              blending: T.AdditiveBlending,
            }),
          );
          outer.rotation.x = -Math.PI / 2;
          outer.position.copy(p);
          outer.position.y += 0.025;
          outer.renderOrder = 3;
          outer.userData = { region, outer: true };
          scene.add(outer);
          rings.push(outer);

          const beamMat = new T.ShaderMaterial({
            uniforms: {
              uColor: { value: col.clone() },
              uOpacity: { value: 0.5 },
              uTime: { value: 0 },
            },
            vertexShader: BEAM_VERT,
            fragmentShader: BEAM_FRAG,
            transparent: true,
            depthWrite: false,
            side: T.DoubleSide,
            blending: T.AdditiveBlending,
          });
          const beam = new T.Mesh(
            new T.CylinderGeometry(0.66, 0.8, BEAM_H, 44, 1, true),
            beamMat,
          );
          beam.position.set(p.x, p.y + BEAM_H / 2, p.z);
          beam.userData = { region };
          scene.add(beam);
          beams.push(beam);

          const discMat = new T.ShaderMaterial({
            uniforms: { uColor: { value: col.clone() }, uOpacity: { value: 0.34 } },
            transparent: true,
            depthWrite: false,
            blending: T.AdditiveBlending,
            vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
            fragmentShader: `uniform vec3 uColor; uniform float uOpacity; varying vec2 vUv; void main(){ float r=length(vUv-0.5)*2.0; float a=pow(max(0.0,1.0-r),3.2)*uOpacity; gl_FragColor=vec4(uColor,a); }`,
          });
          const disc = new T.Mesh(new T.CircleGeometry(1.75, 48), discMat);
          disc.rotation.x = -Math.PI / 2;
          disc.position.set(p.x, p.y + 0.015, p.z);
          disc.userData = { region };
          scene.add(disc);
          discs.push(disc);

          const COUNT = 44;
          const geo = new T.BufferGeometry();
          const data = new Float32Array(COUNT * 3);
          const speeds = new Float32Array(COUNT);
          for (let k = 0; k < COUNT; k++) {
            const ang = Math.random() * Math.PI * 2;
            const rad = 0.15 + Math.random() * 0.55;
            data[k * 3] = Math.cos(ang) * rad;
            data[k * 3 + 1] = Math.random() * BEAM_H;
            data[k * 3 + 2] = Math.sin(ang) * rad;
            speeds[k] = 0.35 + Math.random() * 0.85;
          }
          geo.setAttribute("position", new T.BufferAttribute(data, 3));
          const pmat = new T.PointsMaterial({
            color: col,
            size: 0.045,
            transparent: true,
            opacity: 0.85,
            depthWrite: false,
            blending: T.AdditiveBlending,
            sizeAttenuation: true,
          });
          const pts = new T.Points(geo, pmat);
          pts.position.set(p.x, p.y, p.z);
          scene.add(pts);
          sparks.push({ geo, mat: pmat, speeds, height: BEAM_H });
        });

        resize();
        onReady();
        api.current = {
          reset: resetView,
          setZoom: (z: number) => {
            baseZoom = z;
            camera.zoom = z;
            camera.updateProjectionMatrix();
            syncLabels();
          },
          rushTo,
        };
        camera.zoom = baseZoom;
        camera.updateProjectionMatrix();
        syncLabels();
      },
      undefined,
      (err) => {
        console.error("courtyard scene failed:", err);
        setFailed(String(err));
      },
    );

    applyOrbit();
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    const ACTIVE = {
      get selectedRegion(): RegionId | null {
        const id = live.current.selectedAgentId;
        return id ? AGENT_REGION[id] ?? null : null;
      },
    };

    // ---- 交互：拖拽旋转 / 悬停冲刺 / 点击选中 ----
    let drag = false;
    let lastX = 0;
    let lastY = 0;
    let dragDist = 0;

    const onDown = (e: PointerEvent) => {
      if (e.button !== 0) return;
      const target = e.target as HTMLElement;
      if (target?.closest?.(".courtyard-label")) return;
      drag = true;
      lastX = e.clientX;
      lastY = e.clientY;
      dragDist = 0;
      path = [];
      lastTarget = "";
      rushMode = false;
      renderer.domElement.style.cursor = "grabbing";
      window.addEventListener("pointerup", onUp);
    };

    const onUp = () => {
      if (!drag) return;
      drag = false;
      window.removeEventListener("pointerup", onUp);
      renderer.domElement.style.cursor = hover ? "pointer" : "crosshair";
      if (dragDist < 6 && hover) live.current.onSelectAgent(REGION_AGENT[hover]);
    };

    const onMove = (e: PointerEvent) => {
      if (drag) {
        const dx = e.clientX - lastX;
        const dy = e.clientY - lastY;
        lastX = e.clientX;
        lastY = e.clientY;
        dragDist += Math.hypot(dx, dy);
        theta -= dx * 0.0055;
        phi = T.MathUtils.clamp(phi - dy * 0.0045, 0.2, 1.34);
        applyOrbit();
        syncLabels();
        return;
      }
      if (e.target !== renderer.domElement) {
        const t = e.target as HTMLElement;
        if (!t?.closest || !t.closest(".courtyard-label")) path = [];
        return;
      }
      const r = renderer.domElement.getBoundingClientRect();
      pointer.set(
        ((e.clientX - r.left) / r.width) * 2 - 1,
        -((e.clientY - r.top) / r.height) * 2 + 1,
      );
      ray.setFromCamera(pointer, camera);
      const hits = ray.intersectObjects(rings);
      hover = (hits[0]?.object.userData.region as RegionId) || null;
      renderer.domElement.style.cursor = hover ? "pointer" : "crosshair";
      if (hover) {
        path = [];
        return;
      }
      if (performance.now() - lastMove < 100) return;
      lastMove = performance.now();
      const p = new T.Vector3();
      if (ray.ray.intersectPlane(ground, p)) {
        const key = cellAt(p).join(",");
        if (key !== lastTarget) {
          lastTarget = key;
          navigate(p);
        }
      }
    };

    const onLeave = () => {
      path = [];
      lastTarget = "";
      hover = null;
    };
    const onDblClick = () => {
      resetView();
      api.current?.setZoom(1);
    };

    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    el.addEventListener("dblclick", onDblClick);

    // ---- 渲染循环 ----
    let frame = 0;
    let prev = performance.now();

    const loop = (now: number) => {
      if (disposed) return;
      const dt = Math.min((now - prev) / 1000, 0.04);
      prev = now;
      const t = now / 1000;
      const moving = !!path.length;
      if (user && moving) {
        const v = path[0].clone().sub(user.position);
        v.y = 0;
        if (v.length() < 0.06) path.shift();
        else {
          const spd = rushMode ? 16 : 6.5;
          user.position.add(
            v
              .normalize()
              .multiplyScalar(Math.min(dt * spd, path[0].distanceTo(user.position))),
          );
          user.rotation.y = Math.atan2(-v.x, -v.z);
        }
      }
      if (!path.length) rushMode = false;
      if (user)
        user.position.y =
          0.23 + (!reducedMotion && moving ? Math.sin(now * 0.018) * 0.035 : 0);

      const zoomComp = Math.min(1.85, Math.max(1, 1 / camera.zoom));
      const agentsById = new Map(live.current.agents.map((a) => [a.id, a]));
      REGIONS.forEach((region, i) => {
        const ring = rings[i * 2];
        if (!ring) return;
        const agent = agentsById.get(REGION_AGENT[region]);
        const state = agent ? STATUS_TO_SCENE[agent.status] : "idle";
        const lit = user
          ? user.position.distanceTo(ring.userData.center as T.Vector3) < 2.4
          : false;
        const selected = ACTIVE.selectedRegion === region;
        const hv = hover === region;
        const pulse = 0.5 + 0.5 * Math.sin(t * 1.5 + i * 1.3);
        const rm = ring.material as T.MeshBasicMaterial;
        rm.opacity = lit ? 1 : selected || hv ? 0.85 : 0.42 + 0.26 * pulse;
        rm.color.set(state === "error" ? "#ff4d4d" : ACCENT[i]);
        ring.scale.setScalar((lit ? 1.12 : 1 + 0.03 * pulse) * zoomComp);

        const outer = rings[i * 2 + 1];
        if (outer) {
          const om = outer.material as T.MeshBasicMaterial;
          om.opacity = lit ? 0.62 : 0.16 + 0.12 * pulse;
          om.color.set(ACCENT[i]);
          outer.scale.setScalar(zoomComp);
        }

        const beam = beams[i];
        const bm = beam?.material as T.ShaderMaterial | undefined;
        if (bm && beam) {
          bm.uniforms.uTime.value = t;
          const target = lit ? 1.35 : hv ? 0.95 : selected ? 0.85 : 0.52 + 0.22 * pulse;
          bm.uniforms.uOpacity.value +=
            (target - bm.uniforms.uOpacity.value) * Math.min(dt * 6, 1);
          beam.scale.set(1 + (lit ? 0.06 : 0.02 * pulse), 1, 1 + (lit ? 0.06 : 0.02 * pulse));
        }

        const dm = discs[i]?.material as T.ShaderMaterial | undefined;
        if (dm) {
          const target = lit ? 0.75 : hv ? 0.5 : selected ? 0.45 : 0.28 + 0.14 * pulse;
          dm.uniforms.uOpacity.value +=
            (target - dm.uniforms.uOpacity.value) * Math.min(dt * 6, 1);
        }

        const sp = sparks[i];
        if (sp) {
          sp.mat.opacity = lit ? 0.95 : 0.45 + 0.2 * pulse;
          const pos = sp.geo.getAttribute("position") as T.BufferAttribute;
          const speedScale = lit ? 1.9 : 1;
          for (let k = 0; k < sp.speeds.length; k++) {
            let y = pos.getY(k) + dt * sp.speeds[k] * speedScale * (reducedMotion ? 0.3 : 1);
            if (y > sp.height) y = 0;
            pos.setY(k, y);
          }
          pos.needsUpdate = true;
        }
      });

      renderer.render(scene, camera);
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      ro.disconnect();
      window.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
      el.removeEventListener("dblclick", onDblClick);
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [reducedMotion, onReady]);

  // 外层缩放按钮
  useEffect(() => {
    api.current?.setZoom(userZoom);
  }, [userZoom]);

  const hoverRush = (region: RegionId) => () => api.current?.rushTo(region);

  return (
    <div className={"courtyard-stage" + (immersive ? " is-immersive" : "")}>
      <div ref={host} className="courtyard-host" />
      {!immersive &&
        labels.map(({ region, x, y }) => {
          const i = REGIONS.indexOf(region);
          const agent = agents.find((a) => a.id === REGION_AGENT[region]);
          const status = agent ? STATUS_META[agent.status] : null;
          const selected = selectedAgentId === REGION_AGENT[region];
          if (x < -4000) return null;
          return (
            <button
              key={region}
              type="button"
              className={"courtyard-label" + (selected ? " is-selected" : "")}
              style={
                {
                  left: x,
                  top: y,
                  "--c": ACCENT[i],
                } as CSSProperties
              }
              onPointerEnter={hoverRush(region)}
              onClick={() => onSelectAgent(REGION_AGENT[region])}
            >
              <span className="cl-id">
                R{i + 1}·{CODES[region]}
              </span>
              <b>{agent?.name ?? TITLES[region]}</b>
              <small>
                <i className={"cl-dot" + (agent?.status === "error" ? " bad" : "")} />
                {status?.label ?? "空闲"}
              </small>
            </button>
          );
        })}
      {failed ? <p className="courtyard-error">场景加载失败：{failed}</p> : null}
    </div>
  );
}
