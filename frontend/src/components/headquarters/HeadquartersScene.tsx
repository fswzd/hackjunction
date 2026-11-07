import { useMemo, useRef } from "react";
import { ContactShadows, Grid, Line, RoundedBox } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { AGENT_META } from "@/domain/agents";
import type { AgentId, AgentVM, AgentStatus } from "@/domain/types";
import { OperatorDesk, Workstation } from "./Workstation";

export interface HeadquartersSceneProps {
  agents: AgentVM[];
  selectedAgentId: AgentId | null;
  onSelectAgent: (id: AgentId) => void;
  immersive?: boolean;
  reducedMotion: boolean;
  userZoom?: number;
}

const ROOM_BOUNDS = [
  new THREE.Vector3(-8.2, 0, -6.2),
  new THREE.Vector3(8.2, 0, -6.2),
  new THREE.Vector3(-8.2, 0, 6.2),
  new THREE.Vector3(8.2, 0, 6.2),
  new THREE.Vector3(-8.1, 3.2, -6.05),
  new THREE.Vector3(8.1, 3.2, -6.05),
];
const fitPoint = new THREE.Vector3();

const ACTIVE_STATUSES: AgentStatus[] = ["working", "review", "waiting"];

function CameraRig({
  selectedAgentId,
  immersive,
  userZoom,
}: {
  selectedAgentId: AgentId | null;
  immersive: boolean;
  userZoom: number;
}) {
  const { camera, pointer, size } = useThree();
  const lookAt = useRef(new THREE.Vector3(0, 0.7, 0));
  const desired = useRef(new THREE.Vector3());
  const focusTarget = useRef(new THREE.Vector3());

  useFrame((_, delta) => {
    const focus = selectedAgentId
      ? AGENT_META[selectedAgentId].position
      : ([0, 0, 0] as [number, number, number]);
    const distance = immersive ? 7.6 : 10.2;
    desired.current.set(
      distance + focus[0] * 0.42 + pointer.x * 0.32,
      (immersive ? 9.4 : 11.2) + focus[1],
      distance + focus[2] * 0.42 - pointer.y * 0.22,
    );
    const smoothing = 1 - Math.pow(0.0016, delta);
    camera.position.lerp(desired.current, smoothing);
    focusTarget.current.set(focus[0] * 0.6, 0.75, focus[2] * 0.6);
    lookAt.current.lerp(focusTarget.current, smoothing);
    camera.lookAt(lookAt.current);
    camera.updateMatrixWorld();

    // Fit the whole room into whatever aspect the panel has. Measuring the
    // projected bounds at zoom 1 keeps the framing correct from mobile to
    // ultrawide instead of relying on a hard-coded zoom.
    const orthographic = camera as THREE.OrthographicCamera;
    const previousZoom = orthographic.zoom;
    orthographic.zoom = 1;
    orthographic.updateProjectionMatrix();
    let maxX = 0;
    let maxY = 0;
    for (const corner of ROOM_BOUNDS) {
      fitPoint.copy(corner).project(camera);
      maxX = Math.max(maxX, Math.abs(fitPoint.x));
      maxY = Math.max(maxY, Math.abs(fitPoint.y));
    }
    orthographic.zoom = previousZoom;
    const fitZoom = 0.9 / Math.max(maxX, maxY, 0.0001);
    // Wide panels get a slightly tighter crop so the room stays a hero
    // element; narrow/portrait panels keep the full room in view.
    const baseFill = size.width / size.height < 1.1 ? 1.04 : 1.46;
    const fill = selectedAgentId ? baseFill + 0.1 : baseFill;
    const targetZoom = Math.min(
      220,
      Math.max(18, fitZoom * fill * userZoom),
    );
    orthographic.zoom += (targetZoom - orthographic.zoom) * smoothing;
    orthographic.updateProjectionMatrix();
  });

  return null;
}

/**
 * A faint cable of light running from the operations desk to a workstation.
 * Active roles get a travelling bead so the hand-off is legible at a glance.
 */
function FlowLink({
  to,
  accent,
  active,
  reducedMotion,
  seed,
}: {
  to: [number, number, number];
  accent: string;
  active: boolean;
  reducedMotion: boolean;
  seed: number;
}) {
  const bead = useRef<THREE.Mesh>(null);
  const curve = useMemo(() => {
    const direction = new THREE.Vector3(to[0], 0, to[2]);
    const length = direction.length();
    const unit = direction.clone().normalize();
    const start = unit.clone().multiplyScalar(1.58);
    const end = unit.clone().multiplyScalar(Math.max(1.9, length - 1.32));
    start.y = 0.075;
    end.y = 0.075;
    const mid = start.clone().add(end).multiplyScalar(0.5);
    mid.y = 0.2;
    return new THREE.QuadraticBezierCurve3(start, mid, end);
  }, [to]);

  const points = useMemo(() => curve.getPoints(36), [curve]);

  useFrame((state) => {
    if (!bead.current) return;
    if (!active || reducedMotion) {
      bead.current.visible = false;
      return;
    }
    bead.current.visible = true;
    const t = (state.clock.elapsedTime * 0.14 + seed) % 1;
    curve.getPointAt(t, bead.current.position);
    const pulse = 1 + Math.sin(state.clock.elapsedTime * 5 + seed * 9) * 0.18;
    bead.current.scale.setScalar(pulse);
  });

  return (
    <>
      <Line
        points={points}
        color={accent}
        lineWidth={active ? 1.15 : 0.7}
        transparent
        opacity={active ? 0.52 : 0.13}
        depthWrite={false}
      />
      <mesh ref={bead} visible={false}>
        <sphereGeometry args={[0.052, 12, 10]} />
        <meshBasicMaterial color={accent} toneMapped={false} />
      </mesh>
    </>
  );
}

function Plant({
  position,
  scale = 1,
}: {
  position: [number, number, number];
  scale?: number;
}) {
  return (
    <group position={position} scale={scale}>
      <mesh position={[0, 0.24, 0]}>
        <cylinderGeometry args={[0.27, 0.21, 0.48, 16]} />
        <meshStandardMaterial color="#4a3b2d" roughness={0.86} />
      </mesh>
      <mesh position={[0, 0.49, 0]}>
        <cylinderGeometry args={[0.25, 0.25, 0.035, 16]} />
        <meshStandardMaterial color="#2a231c" roughness={0.9} />
      </mesh>
      {[0, 1, 2, 3, 4, 5, 6].map((index) => {
        const angle = (index / 7) * Math.PI * 2;
        const reach = 0.16 + (index % 3) * 0.055;
        return (
          <mesh
            key={index}
            position={[
              Math.cos(angle) * reach,
              0.85 + (index % 3) * 0.15,
              Math.sin(angle) * reach,
            ]}
            rotation={[
              Math.cos(angle) * 0.38,
              angle,
              Math.sin(angle) * 0.38,
            ]}
          >
            <capsuleGeometry args={[0.065, 0.46 + (index % 3) * 0.13, 4, 8]} />
            <meshStandardMaterial
              color={index % 2 === 0 ? "#556b52" : "#485c45"}
              roughness={0.95}
            />
          </mesh>
        );
      })}
    </group>
  );
}

function Bookshelf() {
  const books = useMemo(() => {
    const palette = [
      "#6d5b48",
      "#7a5a4b",
      "#4f5e55",
      "#8a7758",
      "#5c4f42",
      "#6b6350",
      "#845f52",
    ];
    const rows: Array<{ x: number; y: number; h: number; color: string }> = [];
    let x = -2.0;
    for (let index = 0; index < 26; index += 1) {
      const height = 0.24 + ((index * 37) % 11) / 40;
      if (x > 2.0) break;
      rows.push({
        x,
        y: index % 9 < 5 ? 0.84 : 1.39,
        h: height,
        color: palette[index % palette.length],
      });
      x += 0.075 + ((index * 13) % 5) / 90;
    }
    return rows;
  }, []);

  return (
    <group position={[-7.9, 0, -2.6]} rotation={[0, Math.PI / 2, 0]}>
      <RoundedBox args={[4.8, 0.07, 0.42]} radius={0.02} position={[0, 0.78, 0]}>
        <meshStandardMaterial color="#3b3228" roughness={0.72} />
      </RoundedBox>
      <RoundedBox args={[4.8, 0.07, 0.42]} radius={0.02} position={[0, 1.34, 0]}>
        <meshStandardMaterial color="#3b3228" roughness={0.72} />
      </RoundedBox>
      <RoundedBox args={[4.8, 0.07, 0.42]} radius={0.02} position={[0, 1.9, 0]}>
        <meshStandardMaterial color="#3b3228" roughness={0.72} />
      </RoundedBox>
      {[-2.4, 2.4].map((x) => (
        <mesh key={x} position={[x, 1.1, 0]}>
          <boxGeometry args={[0.08, 1.55, 0.42]} />
          <meshStandardMaterial color="#332b22" roughness={0.8} />
        </mesh>
      ))}
      {books.map((book, index) => (
        <mesh
          key={index}
          position={[book.x, book.y + book.h / 2, 0.02]}
          rotation={[0, 0, ((index * 17) % 7) * 0.004]}
        >
          <boxGeometry args={[0.055, book.h, 0.26]} />
          <meshStandardMaterial color={book.color} roughness={0.92} />
        </mesh>
      ))}
      <mesh position={[0, 2.02, 0]}>
        <cylinderGeometry args={[0.1, 0.12, 0.18, 12]} />
        <meshStandardMaterial color="#8a7758" roughness={0.7} />
      </mesh>
    </group>
  );
}

export default function HeadquartersScene({
  agents,
  selectedAgentId,
  onSelectAgent,
  immersive = false,
  reducedMotion,
  userZoom = 1,
}: HeadquartersSceneProps) {
  const operator = agents.find((agent) => agent.id === "operations_officer");
  const staff = agents.filter((agent) => agent.id !== "operations_officer");

  return (
    <>
      <color attach="background" args={["#1c1915"]} />
      <fog attach="fog" args={["#1c1915", 30, 60]} />
      <CameraRig
        selectedAgentId={selectedAgentId}
        immersive={immersive}
        userZoom={userZoom}
      />

      <ambientLight intensity={1.95} color="#f0e6d6" />
      <hemisphereLight args={["#f4ead8", "#4a4034", 1.15]} />
      <directionalLight
        position={[7, 12, 6]}
        intensity={2.35}
        color="#fff1dc"
      />
      <directionalLight position={[-8, 6, -7]} intensity={0.9} color="#c3b8a4" />
      {/* Fill from the camera side so the colleagues' backs lift off the room */}
      <directionalLight position={[4, 7, 10]} intensity={1.05} color="#ffe7cc" />
      <pointLight position={[0, 5.5, 0]} intensity={2.2} color="#d8c2a4" distance={18} />
      <pointLight position={[0, 2.6, -5.2]} intensity={1.1} color="#e6d3b6" distance={9} />

      {/* Floor */}
      <RoundedBox
        args={[16.4, 0.28, 12.4]}
        radius={0.16}
        position={[0, -0.16, 0]}
      >
        <meshStandardMaterial color="#403c33" roughness={0.88} metalness={0.12} />
      </RoundedBox>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.015, 0]}>
        <planeGeometry args={[16, 12]} />
        <meshStandardMaterial color="#49443a" roughness={0.9} />
      </mesh>
      <Grid
        args={[16, 12]}
        position={[0, 0, 0]}
        cellSize={0.55}
        cellThickness={0.5}
        cellColor="#565043"
        sectionSize={2.2}
        sectionThickness={1}
        sectionColor="#655e4d"
        fadeDistance={24}
        fadeStrength={1.4}
        infiniteGrid={false}
      />

      {/* Central rug anchors the operations desk */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.012, 0]}>
        <circleGeometry args={[2.45, 64]} />
        <meshStandardMaterial color="#3d372c" roughness={0.98} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.016, 0]}>
        <ringGeometry args={[2.16, 2.23, 64]} />
        <meshBasicMaterial
          color="#cbb598"
          transparent
          opacity={0.22}
          side={THREE.DoubleSide}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.016, 0]}>
        <ringGeometry args={[1.66, 1.7, 64]} />
        <meshBasicMaterial
          color="#cbb598"
          transparent
          opacity={0.14}
          side={THREE.DoubleSide}
        />
      </mesh>

      {/* Back walls */}
      <RoundedBox args={[16.2, 3.2, 0.22]} radius={0.06} position={[0, 1.6, -6.05]}>
        <meshStandardMaterial color="#3b372e" roughness={0.8} />
      </RoundedBox>
      <RoundedBox
        args={[0.22, 3.2, 12.2]}
        radius={0.06}
        position={[-8.05, 1.6, 0]}
      >
        <meshStandardMaterial color="#3e3a31" roughness={0.82} />
      </RoundedBox>

      {/* Wall detail panels with slim frames */}
      {[-5.4, -3.8, 3.8, 5.4].map((x) => (
        <group key={x} position={[x, 1.75, -5.9]}>
          <mesh position={[0, 0, -0.02]}>
            <boxGeometry args={[1.24, 2.04, 0.05]} />
            <meshStandardMaterial color="#241f18" roughness={0.6} />
          </mesh>
          <mesh position={[0, 0, 0.02]}>
            <boxGeometry args={[1.1, 1.9, 0.05]} />
            <meshStandardMaterial
              color="#454238"
              emissive="#cbb598"
              emissiveIntensity={0.06}
              roughness={0.7}
            />
          </mesh>
        </group>
      ))}
      <mesh position={[-7.94, 2.1, 0]}>
        <boxGeometry args={[0.05, 0.06, 9.4]} />
        <meshStandardMaterial
          color="#cbb598"
          emissive="#cbb598"
          emissiveIntensity={0.9}
        />
      </mesh>

      {/* Backlit brand mark on the back wall — two leaves, one seam */}
      <group position={[0, 2.62, -5.9]}>
        <RoundedBox
          args={[0.26, 0.78, 0.06]}
          radius={0.09}
          position={[-0.2, 0, 0]}
          rotation={[0, 0, -0.12]}
        >
          <meshStandardMaterial
            color="#dcc7a8"
            emissive="#dcc7a8"
            emissiveIntensity={0.42}
            roughness={0.42}
          />
        </RoundedBox>
        <RoundedBox
          args={[0.26, 0.78, 0.06]}
          radius={0.09}
          position={[0.2, 0, 0]}
          rotation={[0, 0, 0.12]}
        >
          <meshStandardMaterial
            color="#dcc7a8"
            emissive="#dcc7a8"
            emissiveIntensity={0.42}
            roughness={0.42}
          />
        </RoundedBox>
        <mesh position={[0, 0, 0.05]}>
          <boxGeometry args={[0.016, 0.72, 0.02]} />
          <meshBasicMaterial color="#fff3dc" />
        </mesh>
        <mesh position={[0, -0.58, 0.01]}>
          <boxGeometry args={[1.9, 0.02, 0.01]} />
          <meshBasicMaterial color="#cbb598" transparent opacity={0.4} />
        </mesh>
      </group>

      <Bookshelf />

      <Plant position={[-7.2, 0, -5.35]} scale={1.15} />
      <Plant position={[7.2, 0, -5.35]} scale={1.3} />
      <Plant position={[-7.2, 0, 5.3]} scale={1.05} />
      <Plant position={[7.2, 0, 5.3]} scale={1.2} />
      <Plant position={[6.9, 0, -1.1]} scale={0.85} />

      {operator ? (
        <OperatorDesk
          agent={operator}
          selected={selectedAgentId === "operations_officer"}
          dimmed={Boolean(selectedAgentId && selectedAgentId !== "operations_officer")}
          reducedMotion={reducedMotion}
          onSelect={onSelectAgent}
        />
      ) : null}

      {/* Hand-off threads radiate from the operator to every workstation */}
      {staff.map((agent, index) => {
        const meta = AGENT_META[agent.id];
        const active = ACTIVE_STATUSES.includes(agent.status);
        return (
          <FlowLink
            key={`flow-${agent.id}`}
            to={meta.position}
            accent={meta.accent}
            active={active}
            reducedMotion={reducedMotion}
            seed={index / staff.length}
          />
        );
      })}

      {staff.map((agent) => (
        <Workstation
          key={agent.id}
          agent={agent}
          selected={selectedAgentId === agent.id}
          dimmed={Boolean(selectedAgentId && selectedAgentId !== agent.id)}
          reducedMotion={reducedMotion}
          onSelect={onSelectAgent}
        />
      ))}

      <ContactShadows
        position={[0, 0.03, 0]}
        opacity={0.5}
        scale={20}
        blur={2.4}
        far={5}
        resolution={1024}
        color="#000000"
      />
    </>
  );
}
