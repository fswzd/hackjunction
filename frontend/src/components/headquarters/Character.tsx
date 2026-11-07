import { useMemo, useRef } from "react";
import { RoundedBox } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { AgentId, AgentStatus } from "@/domain/types";

interface Look {
  outfit: string;
  sleeve: string;
  skin: string;
  hair: string;
  accessory: "none" | "glasses" | "headphones" | "beanie" | "cap";
}

const LOOKS: Record<AgentId, Look> = {
  operations_officer: {
    outfit: "#5c5343",
    sleeve: "#4f4839",
    skin: "#cf9f7c",
    hair: "#2b231c",
    accessory: "none",
  },
  pr_analyst: {
    outfit: "#635447",
    sleeve: "#56493d",
    skin: "#e2b690",
    hair: "#221d18",
    accessory: "glasses",
  },
  traffic_scout: {
    outfit: "#4f5e57",
    sleeve: "#45534d",
    skin: "#b9825c",
    hair: "#241f1a",
    accessory: "headphones",
  },
  content_creator: {
    outfit: "#6b5847",
    sleeve: "#5b4c3e",
    skin: "#d8a882",
    hair: "#1d1915",
    accessory: "beanie",
  },
  editorial_reviewer: {
    outfit: "#5f554a",
    sleeve: "#524940",
    skin: "#efc39c",
    hair: "#5a483a",
    accessory: "glasses",
  },
  simulated_audience: {
    outfit: "#555561",
    sleeve: "#494954",
    skin: "#a9764f",
    hair: "#2a211c",
    accessory: "cap",
  },
  data_analyst: {
    outfit: "#4f5c54",
    sleeve: "#44524a",
    skin: "#c99f7e",
    hair: "#211d1a",
    accessory: "glasses",
  },
};

const SEEDS: Record<AgentId, number> = {
  operations_officer: 0.4,
  pr_analyst: 1.7,
  traffic_scout: 3.1,
  content_creator: 4.6,
  editorial_reviewer: 0.9,
  simulated_audience: 5.4,
  data_analyst: 2.6,
};

/** A stylised seated/standing colleague built from primitives. */
export function Character({
  agentId,
  accent,
  status,
  reducedMotion,
  pose = "seated",
}: {
  agentId: AgentId;
  accent: string;
  status: AgentStatus;
  reducedMotion: boolean;
  pose?: "seated" | "standing";
}) {
  const look = LOOKS[agentId];
  const phase = SEEDS[agentId];

  const torsoRef = useRef<THREE.Group>(null);
  const headRef = useRef<THREE.Group>(null);
  const armLRef = useRef<THREE.Group>(null);
  const armRRef = useRef<THREE.Group>(null);
  const elbowLRef = useRef<THREE.Group>(null);
  const elbowRRef = useRef<THREE.Group>(null);
  const handLRef = useRef<THREE.Mesh>(null);
  const handRRef = useRef<THREE.Mesh>(null);

  const typing = status === "working";
  const reviewing = status === "review";
  const waiting = status === "waiting";
  const error = status === "error";
  const completed = status === "completed";

  const accentMaterial = useMemo(
    () => (
      <meshStandardMaterial
        color={accent}
        emissive={accent}
        emissiveIntensity={0.18}
        roughness={0.6}
      />
    ),
    [accent],
  );

  useFrame((state) => {
    const t = state.clock.elapsedTime + phase;
    const motion = reducedMotion ? 0 : 1;

    if (torsoRef.current) {
      const lean = reviewing ? -0.08 : error ? 0.16 : typing ? 0.12 : 0.06;
      torsoRef.current.rotation.x +=
        (lean - torsoRef.current.rotation.x) * 0.06;
      const breathe = Math.sin(t * 1.35) * 0.006 * motion;
      const baseY = pose === "standing" ? 0.86 : 0.55;
      torsoRef.current.position.y = baseY + breathe;
      if (error) torsoRef.current.rotation.z = Math.sin(t * 1.2) * 0.02;
    }

    if (headRef.current) {
      let targetY = 0;
      let targetX = 0.08;
      let targetZ = 0;
      if (typing) {
        targetY = Math.sin(t * 0.7) * 0.05;
        targetX = 0.14;
      } else if (reviewing) {
        targetY = Math.sin(t * 0.45) * 0.42;
        targetX = -0.03;
      } else if (waiting) {
        targetY = Math.sin(t * 0.28) * 0.62;
        targetX = 0.02;
      } else if (completed) {
        targetY = Math.sin(t * 0.9) * 0.12;
        targetX = -0.06;
      } else if (error) {
        targetY = Math.sin(t * 1.1) * 0.18;
        targetX = 0.24;
        targetZ = Math.sin(t * 7.0) * 0.05;
      } else {
        targetY = Math.sin(t * 0.55) * 0.14;
        targetX = 0.05;
      }
      headRef.current.rotation.y +=
        (targetY - headRef.current.rotation.y) * 0.07;
      headRef.current.rotation.x +=
        (targetX - headRef.current.rotation.x) * 0.07;
      headRef.current.rotation.z +=
        (targetZ - headRef.current.rotation.z) * 0.12;
    }

    const typingSpeed = typing ? 9.5 : 0;
    const armTarget = reviewing
      ? { left: 0.95, right: 0.48 }
      : waiting
        ? { left: 1.2, right: 1.2 }
        : { left: 1.2, right: 1.2 };
    const elbowTarget = reviewing ? 1.5 : 0.42;

    if (armLRef.current) {
      const swing = typing ? Math.sin(t * typingSpeed) * 0.055 * motion : 0;
      armLRef.current.rotation.x +=
        (armTarget.left + swing - armLRef.current.rotation.x) * 0.09;
      armLRef.current.rotation.z = -0.08;
    }
    if (armRRef.current) {
      const swing = typing
        ? Math.sin(t * typingSpeed + 1.9) * 0.055 * motion
        : 0;
      armRRef.current.rotation.x +=
        (armTarget.right + swing - armRRef.current.rotation.x) * 0.09;
      armRRef.current.rotation.z = 0.08;
    }
    if (elbowLRef.current) {
      const swing = typing ? Math.sin(t * typingSpeed + 0.8) * 0.1 * motion : 0;
      elbowLRef.current.rotation.x +=
        (elbowTarget + swing - elbowLRef.current.rotation.x) * 0.09;
    }
    if (elbowRRef.current) {
      const swing = typing
        ? Math.sin(t * typingSpeed + 2.7) * 0.1 * motion
        : 0;
      elbowRRef.current.rotation.x +=
        (elbowTarget + swing - elbowRRef.current.rotation.x) * 0.09;
    }

    if (handLRef.current && typing) {
      handLRef.current.position.y =
        -0.235 + Math.sin(t * typingSpeed + 0.4) * 0.012 * motion;
    }
    if (handRRef.current && typing) {
      handRRef.current.position.y =
        -0.235 + Math.sin(t * typingSpeed + 2.4) * 0.012 * motion;
    }
  });

  const skin = (
    <meshStandardMaterial color={look.skin} roughness={0.72} />
  );

  const head = (
    <group ref={headRef} position={[0, 0.62, -0.015]}>
      <mesh castShadow>
        <sphereGeometry args={[0.128, 24, 18]} />
        {skin}
      </mesh>
      <mesh position={[0, 0.022, 0.012]}>
        <sphereGeometry args={[0.132, 24, 18, 0, Math.PI * 2, 0, Math.PI * 0.62]} />
        <meshStandardMaterial color={look.hair} roughness={0.9} />
      </mesh>
      <mesh position={[-0.048, 0.018, -0.118]}>
        <sphereGeometry args={[0.012, 8, 8]} />
        <meshStandardMaterial color="#241d18" roughness={0.6} />
      </mesh>
      <mesh position={[0.048, 0.018, -0.118]}>
        <sphereGeometry args={[0.012, 8, 8]} />
        <meshStandardMaterial color="#241d18" roughness={0.6} />
      </mesh>
      <mesh position={[0, -0.006, -0.132]} rotation={[Math.PI / 2, 0, 0]}>
        <coneGeometry args={[0.018, 0.03, 8]} />
        {skin}
      </mesh>

      {look.accessory === "glasses" ? (
        <group position={[0, 0.018, -0.12]}>
          {[-0.05, 0.05].map((x) => (
            <mesh key={x} position={[x, 0, 0]} rotation={[Math.PI / 2, 0, 0]}>
              <torusGeometry args={[0.038, 0.005, 6, 16]} />
              <meshStandardMaterial color="#1c1a17" metalness={0.4} roughness={0.4} />
            </mesh>
          ))}
          <mesh position={[0, 0, 0]}>
            <boxGeometry args={[0.024, 0.006, 0.006]} />
            <meshStandardMaterial color="#1c1a17" />
          </mesh>
        </group>
      ) : null}

      {look.accessory === "headphones" ? (
        <group>
          <mesh position={[0, 0.01, 0]} rotation={[0, 0, 0]}>
            <torusGeometry args={[0.142, 0.012, 8, 24, Math.PI]} />
            {accentMaterial}
          </mesh>
          {[-0.135, 0.135].map((x) => (
            <mesh key={x} position={[x, -0.005, 0]} rotation={[0, 0, Math.PI / 2]}>
              <cylinderGeometry args={[0.04, 0.04, 0.028, 16]} />
              <meshStandardMaterial color="#26221d" roughness={0.6} />
            </mesh>
          ))}
        </group>
      ) : null}

      {look.accessory === "beanie" ? (
        <group>
          <mesh position={[0, 0.035, 0.012]}>
            <sphereGeometry args={[0.136, 22, 16, 0, Math.PI * 2, 0, Math.PI * 0.56]} />
            <meshStandardMaterial color="#6d5b48" roughness={0.95} />
          </mesh>
          <mesh position={[0, 0.02, 0.008]} rotation={[Math.PI / 2, 0, 0]}>
            <torusGeometry args={[0.128, 0.018, 8, 24]} />
            <meshStandardMaterial color="#5d4d3d" roughness={0.95} />
          </mesh>
        </group>
      ) : null}

      {look.accessory === "cap" ? (
        <group>
          <mesh position={[0, 0.03, 0.01]}>
            <sphereGeometry args={[0.137, 22, 16, 0, Math.PI * 2, 0, Math.PI * 0.55]} />
            <meshStandardMaterial color="#4a4640" roughness={0.95} />
          </mesh>
          <mesh position={[0, 0.02, -0.1]} rotation={[0.18, 0, 0]}>
            <boxGeometry args={[0.2, 0.012, 0.11]} />
            <meshStandardMaterial color="#3d3934" roughness={0.95} />
          </mesh>
        </group>
      ) : null}
    </group>
  );

  const torsoHeight = pose === "standing" ? 0.62 : 0.58;
  const baseY = pose === "standing" ? 0.86 : 0.55;

  return (
    <group position={[0, 0, 0]}>
      <group ref={torsoRef} position={[0, baseY, 0]} rotation={[0.06, 0, 0]}>
        <mesh position={[0, torsoHeight * 0.42, 0]} castShadow>
          <capsuleGeometry args={[0.155, torsoHeight * 0.48, 8, 18]} />
          <meshStandardMaterial color={look.outfit} roughness={0.88} />
        </mesh>

        <mesh position={[0, 0.5, -0.015]}>
          <cylinderGeometry args={[0.058, 0.07, 0.08, 14]} />
          {skin}
        </mesh>

        <mesh position={[0, torsoHeight * 0.72, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.088, 0.022, 8, 20]} />
          {accentMaterial}
        </mesh>

        {head}

        {[
          { side: -1, armRef: armLRef, elbowRef: elbowLRef, handRef: handLRef },
          { side: 1, armRef: armRRef, elbowRef: elbowRRef, handRef: handRRef },
        ].map(({ side, armRef, elbowRef, handRef }) => (
          <group
            key={side}
            ref={armRef}
            position={[side * 0.195, torsoHeight * 0.72, 0]}
            rotation={[1.2, 0, side * 0.08]}
          >
            <mesh position={[0, -0.13, 0]} castShadow>
              <capsuleGeometry args={[0.052, 0.2, 6, 14]} />
              <meshStandardMaterial color={look.sleeve} roughness={0.9} />
            </mesh>
            <group ref={elbowRef} position={[0, -0.27, 0]} rotation={[0.42, 0, 0]}>
              <mesh position={[0, -0.1, 0]}>
                <capsuleGeometry args={[0.045, 0.16, 6, 14]} />
                <meshStandardMaterial color={look.sleeve} roughness={0.9} />
              </mesh>
              <mesh ref={handRef} position={[0, -0.235, 0]}>
                <sphereGeometry args={[0.056, 14, 12]} />
                {skin}
              </mesh>
            </group>
          </group>
        ))}
      </group>

      {pose === "seated" ? (
        <>
          <mesh position={[0, 0.48, 0.02]} castShadow>
            <boxGeometry args={[0.32, 0.16, 0.28]} />
            <meshStandardMaterial color={look.sleeve} roughness={0.92} />
          </mesh>
          {[-0.095, 0.095].map((x) => (
            <group key={x}>
              <mesh position={[x, 0.43, -0.16]} rotation={[Math.PI / 2, 0, 0]}>
                <capsuleGeometry args={[0.073, 0.2, 6, 14]} />
                <meshStandardMaterial color={look.outfit} roughness={0.92} />
              </mesh>
              <mesh position={[x, 0.17, -0.32]}>
                <capsuleGeometry args={[0.062, 0.28, 6, 14]} />
                <meshStandardMaterial color={look.outfit} roughness={0.92} />
              </mesh>
              <mesh position={[x, 0.035, -0.37]} rotation={[0.1, 0, 0]}>
                <boxGeometry args={[0.11, 0.07, 0.2]} />
                <meshStandardMaterial color="#24211c" roughness={0.85} />
              </mesh>
            </group>
          ))}
        </>
      ) : (
        <>
          <mesh position={[0, 0.8, 0]} castShadow>
            <boxGeometry args={[0.31, 0.17, 0.25]} />
            <meshStandardMaterial color={look.sleeve} roughness={0.92} />
          </mesh>
          {[-0.095, 0.095].map((x) => (
            <group key={x}>
              <mesh position={[x, 0.42, 0]}>
                <capsuleGeometry args={[0.072, 0.58, 6, 14]} />
                <meshStandardMaterial color={look.outfit} roughness={0.92} />
              </mesh>
              <mesh position={[x, 0.035, -0.05]} rotation={[0, 0, 0]}>
                <boxGeometry args={[0.12, 0.07, 0.24]} />
                <meshStandardMaterial color="#24211c" roughness={0.85} />
              </mesh>
            </group>
          ))}
        </>
      )}
    </group>
  );
}
