import { useEffect, useMemo, useRef, useState } from "react";
import { RoundedBox } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { AGENT_META, STATUS_META } from "@/domain/agents";
import type { AgentId, AgentVM } from "@/domain/types";
import { Character } from "./Character";
import { createScreenTexture, type ScreenVariant } from "./screenTexture";

interface WorkstationProps {
  agent: AgentVM;
  selected: boolean;
  dimmed: boolean;
  reducedMotion: boolean;
  onSelect: (id: AgentId) => void;
}

const DESK = "#4a3d30";
const DESK_DARK = "#2b241c";
const METAL = "#6b5a45";
const FABRIC = "#3b3930";

const SCREEN_VARIANTS: Partial<Record<AgentId, ScreenVariant>> = {
  pr_analyst: "brief",
  traffic_scout: "scout",
  content_creator: "creator",
  editorial_reviewer: "review",
  simulated_audience: "audience",
  data_analyst: "data",
};

/**
 * 3D-facing nametag. Drawn into a canvas texture rather than mounted as a Drei
 * <Html> portal — the DOM portal destabilises the React 19 render loop here and
 * blanked the WebGL canvas.
 */
function useLabelTexture({
  name,
  statusLabel,
  statusColor,
  accent,
  selected,
  subtitle,
}: {
  name: string;
  statusLabel: string;
  statusColor: string;
  accent: string;
  selected: boolean;
  subtitle?: string;
}) {
  return useMemo(() => {
    const width = 340;
    const height = 110;
    const dpr = 3;
    const canvas = document.createElement("canvas");
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const x = 12;
    const y = 8;
    const w = width - 24;
    const h = height - 16;
    const radius = 16;

    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();

    ctx.fillStyle = selected ? "rgba(31,27,21,0.97)" : "rgba(18,16,13,0.88)";
    if (selected) {
      ctx.shadowColor = accent;
      ctx.shadowBlur = 18;
    }
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.lineWidth = selected ? 2.5 : 1.4;
    ctx.strokeStyle = selected ? accent : "rgba(94,82,64,0.85)";
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(32, 40, 5, 0, Math.PI * 2);
    ctx.fillStyle = statusColor;
    ctx.fill();

    ctx.textBaseline = "middle";
    ctx.font =
      '600 30px "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = "#f4ecdc";
    ctx.fillText(name, 50, 41, w - 60);

    ctx.font =
      '500 18px "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = "#b8ae98";
    const secondary = subtitle ? `${statusLabel} · ${subtitle}` : statusLabel;
    // Keep the line at its intended size instead of letting canvas squeeze a
    // long task title into unreadable glyphs.
    ctx.fillText(
      secondary.length > 16 ? `${secondary.slice(0, 16)}…` : secondary,
      32,
      79,
      w - 44,
    );

    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = 4;
    texture.needsUpdate = true;
    return texture;
  }, [name, statusLabel, statusColor, accent, selected, subtitle]);
}

function AgentLabel({
  name,
  statusLabel,
  statusColor,
  accent,
  selected,
  dimmed,
  subtitle,
  positionY,
}: {
  name: string;
  statusLabel: string;
  statusColor: string;
  accent: string;
  selected: boolean;
  dimmed: boolean;
  subtitle?: string;
  positionY: number;
}) {
  const texture = useLabelTexture({
    name,
    statusLabel,
    statusColor,
    accent,
    selected,
    subtitle,
  });
  useEffect(() => () => texture?.dispose(), [texture]);
  if (!texture) return null;
  return (
    <sprite position={[0, positionY, 0]} scale={[2.25, 0.73, 1]}>
      <spriteMaterial
        map={texture}
        transparent
        opacity={dimmed && !selected ? 0.62 : 1}
        depthWrite={false}
        toneMapped={false}
      />
    </sprite>
  );
}

function OfficeChair() {
  return (
    <group>
      <RoundedBox args={[0.58, 0.1, 0.54]} radius={0.04} position={[0, 0.44, 0.62]}>
        <meshStandardMaterial color={FABRIC} roughness={0.95} />
      </RoundedBox>
      <RoundedBox
        args={[0.56, 0.54, 0.1]}
        radius={0.04}
        position={[0, 0.7, 0.88]}
        rotation={[-0.08, 0, 0]}
      >
        <meshStandardMaterial color={FABRIC} roughness={0.95} />
      </RoundedBox>
      {[-0.33, 0.33].map((x) => (
        <mesh key={x} position={[x, 0.58, 0.68]}>
          <boxGeometry args={[0.055, 0.06, 0.36]} />
          <meshStandardMaterial color="#2c2822" roughness={0.8} />
        </mesh>
      ))}
      <mesh position={[0, 0.22, 0.62]}>
        <cylinderGeometry args={[0.05, 0.15, 0.38, 12]} />
        <meshStandardMaterial color={METAL} metalness={0.45} roughness={0.5} />
      </mesh>
      {[0, 1, 2, 3, 4].map((index) => (
        <mesh
          key={index}
          position={[0, 0.06, 0.62]}
          rotation={[0, (index / 5) * Math.PI * 2, 0]}
        >
          <boxGeometry args={[0.5, 0.04, 0.06]} />
          <meshStandardMaterial color="#2c2822" roughness={0.7} />
        </mesh>
      ))}
    </group>
  );
}

function Sofa() {
  return (
    <group>
      <RoundedBox args={[0.98, 0.16, 0.56]} radius={0.06} position={[0, 0.4, 0.62]}>
        <meshStandardMaterial color="#4a4338" roughness={0.98} />
      </RoundedBox>
      <RoundedBox args={[0.98, 0.52, 0.16]} radius={0.05} position={[0, 0.66, 0.96]}>
        <meshStandardMaterial color="#443d33" roughness={0.98} />
      </RoundedBox>
      {[-0.45, 0.45].map((x) => (
        <RoundedBox
          key={x}
          args={[0.14, 0.3, 0.58]}
          radius={0.05}
          position={[x, 0.5, 0.64]}
        >
          <meshStandardMaterial color="#4a4338" roughness={0.98} />
        </RoundedBox>
      ))}
      {[-0.42, 0.42].map((x) => (
        <mesh key={x} position={[x, 0.08, 0.62]}>
          <boxGeometry args={[0.08, 0.2, 0.08]} />
          <meshStandardMaterial color="#2c2822" roughness={0.8} />
        </mesh>
      ))}
    </group>
  );
}

function Keyboard() {
  return (
    <group position={[0, 0.815, 0.14]}>
      <RoundedBox args={[0.44, 0.025, 0.15]} radius={0.012}>
        <meshStandardMaterial color="#1e1b16" roughness={0.6} metalness={0.15} />
      </RoundedBox>
      {[0, 1, 2].map((row) => (
        <mesh key={row} position={[0, 0.016, -0.04 + row * 0.035]}>
          <boxGeometry args={[0.38, 0.004, 0.018]} />
          <meshStandardMaterial color="#3a352d" roughness={0.7} />
        </mesh>
      ))}
    </group>
  );
}

function HoloBars({ accent, reducedMotion }: { accent: string; reducedMotion: boolean }) {
  const group = useRef<THREE.Group>(null);
  useFrame((state) => {
    if (!group.current || reducedMotion) return;
    group.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.4) * 0.12;
    group.current.position.y =
      1.16 + Math.sin(state.clock.elapsedTime * 0.9) * 0.02;
  });
  const bars = [0.22, 0.36, 0.3, 0.46, 0.38];
  return (
    <group ref={group} position={[0.64, 1.16, -0.06]}>
      {bars.map((height, index) => (
        <mesh key={index} position={[index * 0.055 - 0.11, height / 2 - 0.16, 0]}>
          <boxGeometry args={[0.034, height, 0.034]} />
          <meshBasicMaterial color={accent} transparent opacity={0.7} />
        </mesh>
      ))}
      <mesh position={[0, -0.18, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.16, 0.19, 32]} />
        <meshBasicMaterial color={accent} transparent opacity={0.35} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}

function DeskProps({ agentId, accent }: { agentId: AgentId; accent: string }) {
  return (
    <>
      <Keyboard />
      <mesh position={[0, 0.775, 0.49]}>
        <boxGeometry args={[1.9, 0.018, 0.018]} />
        <meshStandardMaterial
          color={accent}
          emissive={accent}
          emissiveIntensity={0.35}
          roughness={0.6}
        />
      </mesh>

      {agentId === "content_creator" ? (
        <>
          <mesh position={[0.52, 0.885, 0.12]}>
            <cylinderGeometry args={[0.065, 0.055, 0.13, 16]} />
            <meshStandardMaterial color="#d8c3a5" roughness={0.75} />
          </mesh>
          <mesh position={[0.6, 0.9, 0.12]} rotation={[0, 0, Math.PI / 2]}>
            <torusGeometry args={[0.04, 0.011, 8, 16]} />
            <meshStandardMaterial color="#d8c3a5" roughness={0.75} />
          </mesh>
        </>
      ) : null}

      {agentId === "editorial_reviewer" || agentId === "pr_analyst" ? (
        <group position={[-0.46, 0.8, 0.1]} rotation={[-0.04, 0.16, 0]}>
          <mesh>
            <boxGeometry args={[0.3, 0.012, 0.4]} />
            <meshStandardMaterial color="#e6dcc8" roughness={0.9} />
          </mesh>
          {[0, 1, 2].map((row) => (
            <mesh key={row} position={[0, 0.009, -0.12 + row * 0.08]}>
              <boxGeometry args={[0.22, 0.004, 0.012]} />
              <meshStandardMaterial
                color={agentId === "editorial_reviewer" && row === 1 ? "#c76a55" : "#9b917d"}
                roughness={0.9}
              />
            </mesh>
          ))}
        </group>
      ) : null}

      {agentId === "pr_analyst" ? (
        <group position={[0.5, 0.84, -0.08]} rotation={[-0.18, -0.12, 0]}>
          <mesh>
            <boxGeometry args={[0.26, 0.014, 0.34]} />
            <meshStandardMaterial color="#6b5a45" roughness={0.8} />
          </mesh>
          <mesh position={[0, 0.012, 0]}>
            <boxGeometry args={[0.22, 0.006, 0.29]} />
            <meshStandardMaterial color="#efe6d4" roughness={0.9} />
          </mesh>
        </group>
      ) : null}

      {agentId === "simulated_audience" ? (
        <>
          <mesh position={[0.44, 0.855, 0.2]}>
            <cylinderGeometry args={[0.09, 0.07, 0.12, 18]} />
            <meshStandardMaterial color="#c9a9a6" roughness={0.85} />
          </mesh>
          <mesh position={[0.44, 0.925, 0.2]}>
            <sphereGeometry args={[0.08, 12, 8, 0, Math.PI * 2, 0, Math.PI / 2]} />
            <meshStandardMaterial color="#e0c07a" roughness={0.9} />
          </mesh>
        </>
      ) : null}

      {agentId === "data_analyst" ? <HoloBars accent={accent} reducedMotion={false} /> : null}
    </>
  );
}

export function Workstation({
  agent,
  selected,
  dimmed,
  reducedMotion,
  onSelect,
}: WorkstationProps) {
  const meta = AGENT_META[agent.id];
  const status = STATUS_META[agent.status];
  const [hovered, setHovered] = useState(false);
  const ringRef = useRef<THREE.Mesh>(null);
  const screenRef = useRef<THREE.MeshStandardMaterial>(null);
  const lightRef = useRef<THREE.PointLight>(null);
  const pulse = useRef(0);

  const isActive =
    agent.status === "working" ||
    agent.status === "review" ||
    agent.status === "waiting";
  const isAudience = agent.id === "simulated_audience";

  const screenTexture = useMemo(
    () =>
      createScreenTexture({
        name: agent.name,
        accent: meta.accent,
        statusColor: status.color,
        variant: SCREEN_VARIANTS[agent.id] ?? "creator",
        statusLabel: status.label,
      }),
    [agent.name, agent.id, meta.accent, status.color, status.label],
  );
  useEffect(() => () => screenTexture?.dispose(), [screenTexture]);

  useFrame((state, delta) => {
    pulse.current += delta;
    const wave = reducedMotion ? 0.5 : 0.5 + Math.sin(pulse.current * 2.2) * 0.5;
    if (ringRef.current) {
      const material = ringRef.current.material as THREE.MeshBasicMaterial;
      const base = selected ? 0.85 : hovered ? 0.65 : isActive ? 0.42 : 0.16;
      material.opacity = base + (isActive && !reducedMotion ? wave * 0.2 : 0);
    }
    if (screenRef.current) {
      screenRef.current.emissiveIntensity = isActive
        ? 0.95 + (reducedMotion ? 0 : wave * 0.25)
        : 0.6;
    }
    if (lightRef.current) {
      lightRef.current.intensity = isActive
        ? 1.4 + (reducedMotion ? 0 : wave * 0.8)
        : 0.5;
    }
  });

  const accent = meta.accent;
  const statusColor = status.color;
  const scale = selected ? 1.05 : hovered ? 1.02 : dimmed ? 0.975 : 1;
  const yaw =
    meta.position[0] === 0 ? 0 : Math.sign(meta.position[0]) * 0.38;

  return (
    <group
      position={meta.position}
      scale={scale}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(agent.id);
      }}
      onPointerOver={(event) => {
        event.stopPropagation();
        setHovered(true);
        document.body.style.cursor = "pointer";
      }}
      onPointerOut={() => {
        setHovered(false);
        document.body.style.cursor = "";
      }}
    >
      {/* Floor marker */}
      <mesh ref={ringRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.025, 0]}>
        <ringGeometry args={[1.02, 1.14, 56]} />
        <meshBasicMaterial
          color={statusColor}
          transparent
          opacity={0.42}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <circleGeometry args={[1.0, 48]} />
        <meshStandardMaterial
          color="#221f1a"
          emissive={statusColor}
          emissiveIntensity={selected ? 0.14 : 0.05}
          roughness={0.94}
        />
      </mesh>

      {/* Desk */}
      <RoundedBox args={[1.9, 0.1, 1.0]} radius={0.04} position={[0, 0.78, 0]}>
        <meshStandardMaterial color={DESK} roughness={0.68} metalness={0.12} />
      </RoundedBox>
      <RoundedBox args={[1.9, 0.04, 1.0]} radius={0.02} position={[0, 0.725, 0]}>
        <meshStandardMaterial color={DESK_DARK} roughness={0.86} />
      </RoundedBox>
      {[-0.78, 0.78].map((x) =>
        [-0.38, 0.38].map((z) => (
          <mesh key={`${x}-${z}`} position={[x, 0.36, z]}>
            <boxGeometry args={[0.07, 0.72, 0.07]} />
            <meshStandardMaterial color={METAL} roughness={0.55} metalness={0.4} />
          </mesh>
        )),
      )}

      {/* Monitor */}
      <mesh position={[0, 1.03, -0.26]}>
        <boxGeometry args={[0.08, 0.42, 0.08]} />
        <meshStandardMaterial color={METAL} metalness={0.5} roughness={0.45} />
      </mesh>
      <RoundedBox
        args={[1.3, 0.74, 0.07]}
        radius={0.03}
        position={[0, 1.43, -0.26]}
      >
        <meshStandardMaterial color="#12100c" roughness={0.42} metalness={0.28} />
      </RoundedBox>
      <mesh position={[0, 1.43, -0.218]}>
        <planeGeometry args={[1.18, 0.62]} />
        <meshStandardMaterial
          ref={screenRef}
          map={screenTexture ?? undefined}
          emissiveMap={screenTexture ?? undefined}
          color="#ffffff"
          emissive="#ffffff"
          emissiveIntensity={agent.status === "idle" ? 0.6 : 1}
          roughness={0.4}
          toneMapped={false}
        />
      </mesh>

      {agent.id === "content_creator" || agent.id === "traffic_scout" ? (
        <group position={[0.72, 1.36, -0.3]} rotation={[0, -0.48, 0]}>
          <RoundedBox args={[0.66, 0.46, 0.055]} radius={0.025}>
            <meshStandardMaterial color="#12100c" roughness={0.45} metalness={0.25} />
          </RoundedBox>
          <mesh position={[0, 0, 0.032]}>
            <planeGeometry args={[0.58, 0.38]} />
            <meshStandardMaterial
              map={screenTexture ?? undefined}
              emissiveMap={screenTexture ?? undefined}
              color="#ffffff"
              emissive="#ffffff"
              emissiveIntensity={0.55}
              toneMapped={false}
            />
          </mesh>
          <mesh position={[0, -0.31, -0.02]}>
            <boxGeometry args={[0.05, 0.16, 0.05]} />
            <meshStandardMaterial color={METAL} metalness={0.4} roughness={0.5} />
          </mesh>
        </group>
      ) : null}

      {isAudience ? <Sofa /> : <OfficeChair />}

      <group position={[0, 0, 0.56]} rotation={[0, yaw, 0]} scale={1.16}>
        <Character
          agentId={agent.id}
          accent={accent}
          status={agent.status}
          reducedMotion={reducedMotion}
        />
      </group>

      <DeskProps agentId={agent.id} accent={accent} />

      {/* Plant */}
      <mesh position={[-0.78, 0.9, 0.34]}>
        <cylinderGeometry args={[0.11, 0.09, 0.18, 12]} />
        <meshStandardMaterial color="#4a3d30" roughness={0.8} />
      </mesh>
      <mesh position={[-0.78, 1.09, 0.34]}>
        <icosahedronGeometry args={[0.17, 0]} />
        <meshStandardMaterial color="#556b52" roughness={0.95} />
      </mesh>

      {/* Desk lamp */}
      <mesh position={[-0.68, 1.02, -0.34]}>
        <cylinderGeometry args={[0.015, 0.015, 0.42, 8]} />
        <meshStandardMaterial color={METAL} />
      </mesh>
      <mesh position={[-0.68, 1.22, -0.26]} rotation={[0.5, 0, 0]}>
        <coneGeometry args={[0.12, 0.16, 16, 1, true]} />
        <meshStandardMaterial
          color={accent}
          emissive={accent}
          emissiveIntensity={0.55}
          side={THREE.DoubleSide}
        />
      </mesh>

      <pointLight
        ref={lightRef}
        position={[0, 1.55, -0.1]}
        color={statusColor}
        intensity={isActive ? 1.6 : 0.45}
        distance={4.2}
        decay={2}
      />

      <AgentLabel
        name={agent.name}
        statusLabel={status.label}
        statusColor={statusColor}
        accent={accent}
        selected={selected}
        dimmed={dimmed}
        subtitle={
          selected || isActive ? agent.activeTaskTitle ?? undefined : undefined
        }
        positionY={2.26}
      />
    </group>
  );
}

export function OperatorDesk({
  agent,
  selected,
  dimmed,
  reducedMotion,
  onSelect,
}: WorkstationProps) {
  const meta = AGENT_META.operations_officer;
  const status = STATUS_META[agent.status];
  const [hovered, setHovered] = useState(false);
  const ringRef = useRef<THREE.Mesh>(null);
  const holoRef = useRef<THREE.MeshStandardMaterial>(null);
  const lightRef = useRef<THREE.PointLight>(null);
  const panelRef = useRef<THREE.Group>(null);
  const pulse = useRef(0);
  const isActive =
    agent.status === "working" ||
    agent.status === "review" ||
    agent.status === "waiting";

  const screenTexture = useMemo(
    () =>
      createScreenTexture({
        name: agent.name,
        accent: meta.accent,
        statusColor: status.color,
        variant: "ops",
        statusLabel: status.label,
      }),
    [agent.name, meta.accent, status.color, status.label],
  );
  useEffect(() => () => screenTexture?.dispose(), [screenTexture]);

  useFrame((_, delta) => {
    pulse.current += delta;
    const wave = reducedMotion ? 0.5 : 0.5 + Math.sin(pulse.current * 1.8) * 0.5;
    if (ringRef.current) {
      const material = ringRef.current.material as THREE.MeshBasicMaterial;
      material.opacity = (selected ? 0.82 : hovered ? 0.62 : 0.28) + wave * 0.12;
    }
    if (holoRef.current) {
      holoRef.current.emissiveIntensity =
        (isActive ? 0.85 : 0.4) + (reducedMotion ? 0 : wave * 0.3);
    }
    if (lightRef.current) {
      lightRef.current.intensity = isActive ? 1.9 + wave : 0.8;
    }
    if (panelRef.current && !reducedMotion) {
      panelRef.current.position.y = 1.62 + Math.sin(pulse.current * 0.7) * 0.03;
    }
  });

  const scale = selected ? 1.06 : hovered ? 1.02 : dimmed ? 0.98 : 1;

  return (
    <group
      position={meta.position}
      scale={scale}
      onClick={(event) => {
        event.stopPropagation();
        onSelect("operations_officer");
      }}
      onPointerOver={(event) => {
        event.stopPropagation();
        setHovered(true);
        document.body.style.cursor = "pointer";
      }}
      onPointerOut={() => {
        setHovered(false);
        document.body.style.cursor = "";
      }}
    >
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <circleGeometry args={[1.4, 64]} />
        <meshStandardMaterial
          color="#231f19"
          emissive={meta.accent}
          emissiveIntensity={selected ? 0.18 : 0.07}
          roughness={0.88}
        />
      </mesh>
      <mesh ref={ringRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}>
        <ringGeometry args={[1.4, 1.53, 64]} />
        <meshBasicMaterial
          color={status.color}
          transparent
          opacity={0.4}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      <mesh position={[0, 0.62, 0]}>
        <cylinderGeometry args={[1.08, 0.92, 0.16, 48]} />
        <meshStandardMaterial color="#4a3d30" roughness={0.5} metalness={0.22} />
      </mesh>
      <mesh position={[0, 0.4, 0]}>
        <cylinderGeometry args={[0.28, 0.42, 0.5, 24]} />
        <meshStandardMaterial color="#2b241c" roughness={0.7} metalness={0.2} />
      </mesh>

      <mesh position={[0, 1.42, 0]} rotation={[Math.PI / 2.35, 0, 0]}>
        <torusGeometry args={[0.52, 0.02, 12, 64]} />
        <meshStandardMaterial
          ref={holoRef}
          color={meta.accent}
          emissive={meta.accent}
          emissiveIntensity={0.8}
          transparent
          opacity={0.9}
        />
      </mesh>
      <mesh position={[0, 1.42, 0]} rotation={[Math.PI / 2.35, 0.6, 0]}>
        <torusGeometry args={[0.66, 0.012, 10, 64]} />
        <meshStandardMaterial
          color="#78E3DE"
          emissive="#78E3DE"
          emissiveIntensity={0.45}
          transparent
          opacity={0.5}
        />
      </mesh>
      <mesh position={[0, 1.12, 0]}>
        <cylinderGeometry args={[0.05, 0.05, 0.95, 12]} />
        <meshStandardMaterial color={METAL} metalness={0.4} roughness={0.5} />
      </mesh>

      {/* Floating brief panels */}
      <group ref={panelRef} position={[0, 1.62, 0]}>
        <mesh position={[0, 0, -0.24]} rotation={[0, Math.PI, 0]}>
          <planeGeometry args={[0.92, 0.52]} />
          <meshBasicMaterial
            map={screenTexture ?? undefined}
            transparent
            opacity={0.72}
            side={THREE.DoubleSide}
            toneMapped={false}
            depthWrite={false}
          />
        </mesh>
      </group>

      <group position={[0, 0, -1.32]} rotation={[0, Math.PI, 0]} scale={1.14}>
        <Character
          agentId="operations_officer"
          accent={meta.accent}
          status={agent.status}
          reducedMotion={reducedMotion}
          pose="standing"
        />
      </group>

      <pointLight
        ref={lightRef}
        position={[0, 1.7, 0]}
        color={meta.accent}
        intensity={1.8}
        distance={5.5}
        decay={2}
      />

      <AgentLabel
        name={agent.name}
        statusLabel={status.label}
        statusColor={status.color}
        accent={meta.accent}
        selected={selected}
        dimmed={dimmed}
<<<<<<< Updated upstream
        subtitle={
          selected || isActive ? agent.activeTaskTitle ?? "任务书整理" : "任务书整理"
        }
        positionY={2.5}
=======
        subtitle="总协调"
        positionY={2.42}
>>>>>>> Stashed changes
      />
    </group>
  );
}
