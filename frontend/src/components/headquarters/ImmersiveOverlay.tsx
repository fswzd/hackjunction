import { useEffect } from "react";
import { X } from "lucide-react";
import { useWorkspace } from "@/store/workspace";
import { Headquarters3D } from "./Headquarters3D";
import { AgentDetailsPanel } from "@/components/agents/AgentDetailsPanel";

export function ImmersiveOverlay() {
  const immersive = useWorkspace((state) => state.immersive);
  const setImmersive = useWorkspace((state) => state.setImmersive);
  const snapshot = useWorkspace((state) => state.snapshot);
  const selectedAgentId = useWorkspace((state) => state.selectedAgentId);
  const selectAgent = useWorkspace((state) => state.selectAgent);

  useEffect(() => {
    if (!immersive) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setImmersive(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previous;
    };
  }, [immersive, setImmersive]);

  if (!immersive || !snapshot) return null;

  return (
    <div className="fixed inset-0 z-[60] bg-[#0b0e15]">
      <Headquarters3D
        agents={snapshot.agents}
        selectedAgentId={selectedAgentId}
        onSelectAgent={selectAgent}
        immersive
        showHeader={false}
        className="h-full w-full"
      />
      <div className="pointer-events-none absolute inset-x-0 top-0 z-40 flex items-start justify-between p-5">
        <div>
          <p className="text-[10px] uppercase tracking-[0.24em] text-muted">
            众幕 AI · Immersive Headquarters
          </p>
          <h2 className="mt-1 text-balance text-xl font-semibold tracking-tight text-text">
            {snapshot.profile?.workspaceName || "我的内容工作室"}
          </h2>
          <p className="mt-1 max-w-md text-[11px] leading-5 text-muted">
            这是一个可点击的展示、观察与导航空间。内容编辑、审批和排期仍在 2D 工作台完成。
          </p>
        </div>
        <button
          type="button"
          onClick={() => setImmersive(false)}
          aria-label="退出沉浸模式"
          className="pointer-events-auto flex items-center gap-1.5 rounded-lg border border-line bg-surface/85 px-3 py-2 text-[11px] text-text backdrop-blur transition hover:text-blue"
        >
          <X size={14} />
          退出沉浸模式
        </button>
      </div>

      {selectedAgentId ? (
        <div className="absolute right-4 top-24 z-40">
          <AgentDetailsPanel floating />
        </div>
      ) : null}
    </div>
  );
}
