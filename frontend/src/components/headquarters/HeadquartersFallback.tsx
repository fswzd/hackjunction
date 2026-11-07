import { AGENT_META, STATUS_META } from "@/domain/agents";
import type { AgentId, AgentVM } from "@/domain/types";
import { cn } from "@/lib/format";
import { AgentStatusBadge } from "@/components/ui/StatusBadge";

export function HeadquartersFallback({
  agents,
  selectedAgentId,
  onSelectAgent,
  reason = "当前浏览器无法加载 3D 场景，已切换为 2D 员工视图。",
  compact = false,
}: {
  agents: AgentVM[];
  selectedAgentId: AgentId | null;
  onSelectAgent: (id: AgentId) => void;
  reason?: string;
  compact?: boolean;
}) {
  return (
    <div className="flex h-full flex-col bg-ink/60 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-[11px] leading-5 text-muted">{reason}</p>
        <span className="shrink-0 rounded-full border border-line px-2 py-0.5 text-[10px] text-muted">
          2D 降级
        </span>
      </div>
      <div
        className={cn(
          "grid flex-1 gap-2 overflow-y-auto",
          compact ? "grid-cols-1" : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
        )}
      >
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
                "flex flex-col rounded-xl border p-3 text-left transition",
                selectedAgentId === agent.id
                  ? "border-blue/50 bg-blue/8"
                  : "border-line bg-surface hover:border-[#43506a]",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold text-text">
                  {agent.name}
                </span>
                <AgentStatusBadge status={agent.status} />
              </div>
              <p className="mt-1 text-[10px] tracking-[0.1em] text-muted">
                {meta.capabilities.slice(0, 2).join(" · ")}
              </p>
              <p className="mt-2 line-clamp-2 text-[11px] leading-5 text-muted">
                {agent.activeTaskTitle ?? status.description}
              </p>
              <span className="mt-2 flex items-center gap-1.5 text-[10px] text-muted">
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ backgroundColor: status.color }}
                />
                {status.label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
