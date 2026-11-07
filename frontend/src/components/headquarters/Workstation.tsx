import { useEffect, useMemo, useRef, useState } from "react";
import { RoundedBox } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { AGENT_META, STATUS_META } from "@/domain/agents";
import type { AgentId, AgentVM } from "@/domain/types";

interface WorkstationProps {
  agent: AgentVM;
  selected: boolean;
  dimmed: boolean;
  reducedMotion: boolean;
  onSelect: (id: AgentId) => void;
}

const DESK = "#2a3140";
const DESK_DARK = "#1b202b";
const METAL = "#3c4557";

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
    const width = 300;
    const height = 104;
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

    ctx.fillStyle = selected ? "rgba(23,27,37,0.96)" : "rgba(13,16,23,0.86)";
    if (selected) {
      ctx.shadowColor = accent;
      ctx.shadowBlur = 18;
    }
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.lineWidth = selected ? 2.5 : 1.5;
    ctx.strokeStyle = selected ? accent : "rgba(48,56,73,0.9)";
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(32, 42, 5, 0, Math.PI * 2);
    ctx.fillStyle = statusColor;
    ctx.fill();

    ctx.textBaseline = "middle";
    ctx.font =
      '600 24px "Inter", system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = "#F5F6FA";
    ctx.fillText(name, 48, 42, w - 48);

    ctx.font =
      '500 14px "Inter", system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = "#A1A9BB";
    ctx.fillText(
      subtitle ? `${statusLabel} · ${subtitle}` : statusLabel,
      32,
      73,
      w - 20,
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
    <sprite position={[0, positionY, 0]} scale={[2.15, 0.745, 1]}>
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

  useFrame((state, delta) => {
    pulse.current += delta;
    const wave = reducedMotion ? 0.5 : 0.5 + Math.sin(pulse.current * 2.2) * 0.5;
    if (ringRef.current) {
      const material = ringRef.current.material as THREE.MeshBasicMaterial;
      const base = selected ? 0.85 : hovered ? 0.65 : isActive ? 0.45 : 0.18;
      material.opacity = base + (isActive && !reducedMotion ? wave * 0.22 : 0);
    }
    if (screenRef.current) {
      screenRef.current.emissiveIntensity = isActive
        ? 0.9 + (reducedMotion ? 0 : wave * 0.5)
        : 0.25;
    }
    if (lightRef.current) {
      lightRef.current.intensity = isActive
        ? 1.6 + (reducedMotion ? 0 : wave * 1.1)
        : 0.55;
    }
  });

  const accent = meta.accent;
  const statusColor = status.color;
  const scale = selected ? 1.05 : hovered ? 1.02 : dimmed ? 0.975 : 1;

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
      {/* Status ring on the floor — colour plus the text label below */}
      <mesh ref={ringRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.025, 0]}>
        <ringGeometry args={[1.02, 1.14, 56]} />
        <meshBasicMaterial
          color={statusColor}
          transparent
          opacity={0.45}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <circleGeometry args={[1.0, 48]} />
        <meshStandardMaterial
          color="#151a24"
          emissive={statusColor}
          emissiveIntensity={selected ? 0.16 : 0.06}
          roughness={0.92}
        />
      </mesh>

      {/* Desk */}
      <RoundedBox args={[1.9, 0.1, 1.0]} radius={0.04} position={[0, 0.78, 0]}>
        <meshStandardMaterial color={DESK} roughness={0.72} metalness={0.18} />
      </RoundedBox>
      <RoundedBox args={[1.9, 0.04, 1.0]} radius={0.02} position={[0, 0.725, 0]}>
        <meshStandardMaterial color={DESK_DARK} roughness={0.85} />
      </RoundedBox>
      {[-0.78, 0.78].map((x) =>
        [-0.38, 0.38].map((z) => (
          <mesh key={`${x}-${z}`} position={[x, 0.36, z]}>
            <boxGeometry args={[0.07, 0.72, 0.07]} />
            <meshStandardMaterial color={METAL} roughness={0.6} metalness={0.4} />
          </mesh>
        )),
      )}

      {/* Monitor */}
      <mesh position={[0, 1.03, -0.26]}>
        <boxGeometry args={[0.08, 0.42, 0.08]} />
        <meshStandardMaterial color={METAL} metalness={0.5} roughness={0.5} />
      </mesh>
      <RoundedBox
        args={[1.28, 0.72, 0.07]}
        radius={0.03}
        position={[0, 1.42, -0.26]}
      >
        <meshStandardMaterial color="#0f141d" roughness={0.4} metalness={0.3} />
      </RoundedBox>
      <mesh position={[0, 1.42, -0.218]}>
        <planeGeometry args={[1.16, 0.6]} />
        <meshStandardMaterial
          ref={screenRef}
          color="#0c111a"
          emissive={statusColor}
          emissiveIntensity={agent.status === "idle" ? 0.25 : 1}
          roughness={0.3}
        />
      </mesh>
      {/* Screen content bars */}
      {[0.16, 0.05, -0.06, -0.17].map((y, index) => (
        <mesh key={y} position={[-0.36 + index * 0.04, 1.42 + y, -0.205]}>
          <planeGeometry args={[0.5 - index * 0.08, 0.035]} />
          <meshBasicMaterial
            color={index === 0 ? accent : "#aab6cc"}
            transparent
            opacity={0.5 - index * 0.08}
          />
        </mesh>
      ))}

      {/* Chair */}
      <mesh position={[0, 0.42, 0.82]}>
        <boxGeometry args={[0.56, 0.09, 0.5]} />
        <meshStandardMaterial color="#232a37" roughness={0.85} />
      </mesh>
      <mesh position={[0, 0.68, 1.03]}>
        <boxGeometry args={[0.56, 0.5, 0.08]} />
        <meshStandardMaterial color="#232a37" roughness={0.85} />
      </mesh>
      <mesh position={[0, 0.2, 0.82]}>
        <cylinderGeometry args={[0.05, 0.16, 0.36, 10]} />
        <meshStandardMaterial color={METAL} metalness={0.4} roughness={0.6} />
      </mesh>

      {/* Plant */}
      <mesh position={[0.74, 0.94, -0.3]}>
        <cylinderGeometry args={[0.11, 0.09, 0.18, 12]} />
        <meshStandardMaterial color="#323b4a" roughness={0.7} />
      </mesh>
      <mesh position={[0.74, 1.12, -0.3]}>
        <icosahedronGeometry args={[0.16, 0]} />
        <meshStandardMaterial color="#4d7a68" roughness={0.9} />
      </mesh>

      {/* Desk lamp */}
      <mesh position={[-0.72, 1.02, -0.32]}>
        <cylinderGeometry args={[0.015, 0.015, 0.42, 8]} />
        <meshStandardMaterial color={METAL} />
      </mesh>
      <mesh position={[-0.72, 1.22, -0.24]} rotation={[0.5, 0, 0]}>
        <coneGeometry args={[0.12, 0.16, 16, 1, true]} />
        <meshStandardMaterial
          color={accent}
          emissive={accent}
          emissiveIntensity={0.7}
          side={THREE.DoubleSide}
        />
      </mesh>

      <pointLight
        ref={lightRef}
        position={[0, 1.55, -0.15]}
        color={statusColor}
        intensity={isActive ? 1.8 : 0.5}
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
        positionY={2.12}
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
  const pulse = useRef(0);
  const isActive = agent.status === "working" || agent.status === "review";

  useFrame((_, delta) => {
    pulse.current += delta;
    const wave = reducedMotion ? 0.5 : 0.5 + Math.sin(pulse.current * 1.8) * 0.5;
    if (ringRef.current) {
      const material = ringRef.current.material as THREE.MeshBasicMaterial;
      material.opacity = (selected ? 0.8 : hovered ? 0.6 : 0.28) + wave * 0.14;
    }
    if (holoRef.current) {
      holoRef.current.emissiveIntensity =
        (isActive ? 0.85 : 0.4) + (reducedMotion ? 0 : wave * 0.35);
    }
    if (lightRef.current) {
      lightRef.current.intensity = isActive ? 2.2 + wave : 0.9;
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
        <circleGeometry args={[1.35, 64]} />
        <meshStandardMaterial
          color="#171d29"
          emissive={meta.accent}
          emissiveIntensity={selected ? 0.2 : 0.08}
          roughness={0.85}
        />
      </mesh>
      <mesh ref={ringRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}>
        <ringGeometry args={[1.36, 1.48, 64]} />
        <meshBasicMaterial
          color={status.color}
          transparent
          opacity={0.4}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      <mesh position={[0, 0.62, 0]}>
        <cylinderGeometry args={[1.05, 0.9, 0.16, 48]} />
        <meshStandardMaterial color="#252c3a" roughness={0.55} metalness={0.25} />
      </mesh>
      <mesh position={[0, 0.4, 0]}>
        <cylinderGeometry args={[0.28, 0.42, 0.5, 24]} />
        <meshStandardMaterial color="#1c2230" roughness={0.7} metalness={0.2} />
      </mesh>

      {/* Holographic ring above the operator desk */}
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
          emissiveIntensity={0.5}
          transparent
          opacity={0.6}
        />
      </mesh>
      <mesh position={[0, 1.12, 0]}>
        <cylinderGeometry args={[0.05, 0.05, 0.95, 12]} />
        <meshStandardMaterial color="#3c4557" metalness={0.4} roughness={0.5} />
      </mesh>

      <pointLight
        ref={lightRef}
        position={[0, 1.7, 0]}
        color={meta.accent}
        intensity={1.8}
        distance={5}
        decay={2}
      />

      <AgentLabel
        name={agent.name}
        statusLabel={status.label}
        statusColor={status.color}
        accent={meta.accent}
        selected={selected}
        dimmed={dimmed}
        subtitle="总协调"
        positionY={2.42}
      />
    </group>
  );
}
