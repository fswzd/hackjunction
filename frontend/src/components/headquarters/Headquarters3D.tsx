import {
  Component,
  Suspense,
  lazy,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { Expand, Loader2, RotateCcw } from "lucide-react";
import type { AgentId, AgentVM } from "@/domain/types";
import { AGENT_META, STATUS_META } from "@/domain/agents";
import { cn } from "@/lib/format";
import { HeadquartersFallback } from "./HeadquartersFallback";

const HeadquartersCanvas = lazy(() => import("./HeadquartersCanvas"));

function detectWebGL(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const canvas = document.createElement("canvas");
    return Boolean(
      window.WebGLRenderingContext &&
        (canvas.getContext("webgl") || canvas.getContext("experimental-webgl")),
    );
  } catch {
    return false;
  }
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return reduced;
}

class SceneErrorBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error("3D headquarters failed to load:", error);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export interface Headquarters3DProps {
  agents: AgentVM[];
  selectedAgentId: AgentId | null;
  onSelectAgent: (id: AgentId | null) => void;
  immersive?: boolean;
  onToggleImmersive?: () => void;
  className?: string;
  showHeader?: boolean;
}

export function Headquarters3D({
  agents,
  selectedAgentId,
  onSelectAgent,
  immersive = false,
  onToggleImmersive,
  className,
  showHeader = true,
}: Headquarters3DProps) {
  const [webgl] = useState(detectWebGL);
  const [ready, setReady] = useState(false);
  const reducedMotion = usePrefersReducedMotion();
  const fallback = (
    <HeadquartersFallback
      agents={agents}
      selectedAgentId={selectedAgentId}
      onSelectAgent={onSelectAgent}
      compact={immersive}
    />
  );

  if (!webgl) return <div className={className}>{fallback}</div>;

  return (
    <div
      className={cn(
        "relative isolate overflow-hidden bg-[#0b0e15]",
        className,
      )}
    >
      {showHeader && !immersive ? (
        <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-start justify-between gap-3 bg-gradient-to-b from-[#0b0e15]/90 to-transparent p-4">
          <div className="min-w-0">
            <p className="hidden text-[10px] uppercase tracking-[0.22em] text-muted sm:block">
              ZHONGMU / COLLECTIVE
            </p>
            <p className="mt-1 text-xs font-medium text-text">
              {immersive ? "沉浸式协作现场" : (
                <>
                  协作现场
                  <span className="hidden sm:inline"> · 七个角色 · 围绕同一份任务书</span>
                </>
              )}
            </p>
          </div>
        </div>
      ) : null}

      {!immersive ? (
        <div className="absolute right-3 top-3 z-30 flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => onSelectAgent(null)}
            aria-label="重置镜头到工作室全景"
            title="重置镜头"
            className="rounded-lg border border-line bg-surface/80 p-2 text-muted backdrop-blur transition hover:text-text"
          >
            <RotateCcw size={14} />
          </button>
          {onToggleImmersive ? (
            <button
              type="button"
              onClick={onToggleImmersive}
              aria-label="走进协作现场"
              className="flex items-center gap-1.5 rounded-lg border border-line bg-surface/90 px-2.5 py-2 text-[11px] font-medium text-text backdrop-blur transition hover:border-blue/40 hover:text-blue"
            >
              <Expand size={14} />
              走进协作现场
            </button>
          ) : null}
        </div>
      ) : null}

      {!ready ? (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
          <div className="flex items-center gap-2 rounded-full border border-line bg-surface/80 px-4 py-2 text-[11px] text-muted backdrop-blur">
            <Loader2 size={14} className="animate-spin" />
            正在打开协作现场…
          </div>
        </div>
      ) : null}

      <SceneErrorBoundary fallback={fallback}>
        <Suspense fallback={null}>
          <HeadquartersCanvas
            agents={agents}
            selectedAgentId={selectedAgentId}
            onSelectAgent={onSelectAgent}
            immersive={immersive}
            reducedMotion={reducedMotion}
            onReady={() => setReady(true)}
          />
        </Suspense>
      </SceneErrorBoundary>

      {/* Keyboard-accessible equivalent of the 3D hotspots */}
      <div className="absolute inset-x-0 bottom-0 z-20 bg-gradient-to-t from-[#0b0e15] via-[#0b0e15]/85 to-transparent px-3 pb-3 pt-8">
        <div className="flex gap-1.5 overflow-x-auto pb-0.5">
          {agents.map((agent) => {
            const meta = AGENT_META[agent.id];
            const status = STATUS_META[agent.status];
            return (
              <button
                key={agent.id}
                type="button"
                onClick={() => onSelectAgent(agent.id)}
                aria-pressed={selectedAgentId === agent.id}
                className={cn(
                  "flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-medium backdrop-blur transition",
                  selectedAgentId === agent.id
                    ? "border-blue/50 bg-blue/15 text-text"
                    : "border-line bg-surface/75 text-muted hover:text-text",
                )}
              >
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ backgroundColor: status.color }}
                />
                {meta.name}
                <span className="text-[9px] opacity-70">{status.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
