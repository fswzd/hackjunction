import { useRef } from "react";
import { ContactShadows, Grid, RoundedBox } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { AGENT_META } from "@/domain/agents";
import type { AgentId, AgentVM } from "@/domain/types";
import { OperatorDesk, Workstation } from "./Workstation";

export interface HeadquartersSceneProps {
  agents: AgentVM[];
  selectedAgentId: AgentId | null;
  onSelectAgent: (id: AgentId) => void;
  immersive?: boolean;
  reducedMotion: boolean;
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

function CameraRig({
  selectedAgentId,
  immersive,
}: {
  selectedAgentId: AgentId | null;
  immersive: boolean;
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
    const baseFill = size.width / size.height < 1.1 ? 1 : 1.38;
    const fill = selectedAgentId ? baseFill + 0.12 : baseFill;
    const targetZoom = Math.min(120, Math.max(18, fitZoom * fill));
    orthographic.zoom += (targetZoom - orthographic.zoom) * smoothing;
    orthographic.updateProjectionMatrix();
  });

  return null;
}

export default function HeadquartersScene({
  agents,
  selectedAgentId,
  onSelectAgent,
  immersive = false,
  reducedMotion,
}: HeadquartersSceneProps) {
  const operator = agents.find((agent) => agent.id === "operations_officer");
  const staff = agents.filter((agent) => agent.id !== "operations_officer");

  return (
    <>
      <color attach="background" args={["#191917"]} />
      <fog attach="fog" args={["#191917", 26, 52]} />
      <CameraRig selectedAgentId={selectedAgentId} immersive={immersive} />

      <ambientLight intensity={1.15} color="#e5decf" />
      <directionalLight
        position={[7, 12, 6]}
        intensity={1.5}
        color="#fff1dc"
      />
      <directionalLight position={[-8, 5, -7]} intensity={0.62} color="#b6ad9b" />
      <pointLight position={[0, 5.5, 0]} intensity={1.35} color="#cbb598" distance={16} />

      {/* Floor */}
      <RoundedBox
        args={[16.4, 0.28, 12.4]}
        radius={0.16}
        position={[0, -0.16, 0]}
      >
        <meshStandardMaterial color="#34342e" roughness={0.88} metalness={0.12} />
      </RoundedBox>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.015, 0]}>
        <planeGeometry args={[16, 12]} />
        <meshStandardMaterial color="#3a3932" roughness={0.9} />
      </mesh>
      <Grid
        args={[16, 12]}
        position={[0, 0, 0]}
        cellSize={0.55}
        cellThickness={0.5}
        cellColor="#48473e"
        sectionSize={2.2}
        sectionThickness={1}
        sectionColor="#555247"
        fadeDistance={24}
        fadeStrength={1.4}
        infiniteGrid={false}
      />

      {/* Back walls */}
      <RoundedBox args={[16.2, 3.2, 0.22]} radius={0.06} position={[0, 1.6, -6.05]}>
        <meshStandardMaterial color="#302f29" roughness={0.8} />
      </RoundedBox>
      <RoundedBox
        args={[0.22, 3.2, 12.2]}
        radius={0.06}
        position={[-8.05, 1.6, 0]}
      >
        <meshStandardMaterial color="#33322c" roughness={0.82} />
      </RoundedBox>

      {/* Wall detail panels */}
      {[-5.4, -3.8, 3.8, 5.4].map((x) => (
        <mesh key={x} position={[x, 1.75, -5.92]}>
          <boxGeometry args={[1.1, 1.9, 0.05]} />
          <meshStandardMaterial
            color="#454238"
            emissive="#cbb598"
            emissiveIntensity={0.06}
            roughness={0.7}
          />
        </mesh>
      ))}
      <mesh position={[-7.94, 2.1, 0]}>
        <boxGeometry args={[0.05, 0.06, 9.4]} />
        <meshStandardMaterial
          color="#cbb598"
          emissive="#cbb598"
          emissiveIntensity={0.9}
        />
      </mesh>

      {/* Brand strip on the back wall */}
      <mesh position={[0, 2.55, -5.9]}>
        <planeGeometry args={[4.6, 0.04]} />
        <meshBasicMaterial color="#cbb598" transparent opacity={0.55} />
      </mesh>

      {operator ? (
        <OperatorDesk
          agent={operator}
          selected={selectedAgentId === "operations_officer"}
          dimmed={Boolean(selectedAgentId && selectedAgentId !== "operations_officer")}
          reducedMotion={reducedMotion}
          onSelect={onSelectAgent}
        />
      ) : null}

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
        opacity={0.62}
        scale={18}
        blur={2.6}
        far={5}
        resolution={512}
        color="#000000"
      />
    </>
  );
}
