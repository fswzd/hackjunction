import { Canvas } from "@react-three/fiber";
import type { AgentId, AgentVM } from "@/domain/types";
import HeadquartersScene from "./HeadquartersScene";

export interface HeadquartersCanvasProps {
  agents: AgentVM[];
  selectedAgentId: AgentId | null;
  onSelectAgent: (id: AgentId | null) => void;
  immersive: boolean;
  reducedMotion: boolean;
  userZoom: number;
  onReady: () => void;
}

/**
 * The WebGL canvas is kept in its own module so three.js and R3F only load
 * when a capable browser actually mounts the 3D scene.
 */
export function HeadquartersCanvas({
  agents,
  selectedAgentId,
  onSelectAgent,
  immersive,
  reducedMotion,
  userZoom,
  onReady,
}: HeadquartersCanvasProps) {
  return (
    <Canvas
      orthographic
      camera={{
        position: [10.2, 11.2, 10.2],
        zoom: 52,
        near: -100,
        far: 200,
      }}
      dpr={[1, 2]}
      gl={{
        antialias: true,
        powerPreference: "default",
        alpha: false,
      }}
      onCreated={({ gl }) => {
        gl.setClearColor("#1c1915");
        gl.toneMappingExposure = 1.12;
        onReady();
      }}
      onPointerMissed={() => onSelectAgent(null)}
      className="!absolute inset-0"
    >
      <HeadquartersScene
        agents={agents}
        selectedAgentId={selectedAgentId}
        onSelectAgent={onSelectAgent}
        immersive={immersive}
        reducedMotion={reducedMotion}
        userZoom={userZoom}
      />
    </Canvas>
  );
}

export default HeadquartersCanvas;
