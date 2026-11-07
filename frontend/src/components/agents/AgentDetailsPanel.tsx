import { Link } from "react-router-dom";
import { ArrowUpRight, Plus, X } from "lucide-react";
import {
  AGENT_META,
  BACKEND_STATE_META,
  STATUS_META,
  currentStage,
  progressForTask,
} from "@/domain/agents";
import { cn, formatRelative } from "@/lib/format";
import { useWorkspace } from "@/store/workspace";
import { AgentStatusBadge } from "@/components/ui/StatusBadge";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ProgressBar } from "@/components/ui/ProgressBar";

export function AgentDetailsPanel({
  floating = false,
}: {
  floating?: boolean;
}) {
  const selectedAgentId = useWorkspace((state) => state.selectedAgentId);
  const panelOpen = useWorkspace((state) => state.panelOpen);
  const snapshot = useWorkspace((state) => state.snapshot);
  const selectAgent = useWorkspace((state) => state.selectAgent);
  const openNewTask = useWorkspace((state) => state.openNewTask);

  if (!selectedAgentId) return null;
  const agent = snapshot?.agents.find((item) => item.id === selectedAgentId);
  if (!agent) return null;
  const meta = AGENT_META[agent.id];
  const statusMeta = STATUS_META[agent.status];
  const task = agent.activeTaskId
    ? snapshot?.tasks.find((item) => item.id === agent.activeTaskId)
    : undefined;
  const stageProgress = task ? progressForTask(task) : 0;
  const stage = task ? currentStage(task) : undefined;

  return (
    <>
      {panelOpen && !floating ? (
        <button
          type="button"
          aria-label="关闭员工详情"
          onClick={() => selectAgent(null)}
          className="fixed inset-0 z-40 bg-ink/60 backdrop-blur-sm lg:hidden"
        />
      ) : null}
      <aside
        aria-label={`${agent.name} 详情`}
        className={cn(
          "flex w-full flex-col overflow-hidden border-line bg-surface",
          floating
            ? "relative max-h-[calc(100vh-9rem)] w-[min(92vw,380px)] rounded-2xl border shadow-[0_30px_100px_-20px_rgba(0,0,0,0.9)]"
            : cn(
                "fixed inset-y-0 right-0 z-50 border-l transition-transform duration-300 lg:static lg:z-auto lg:w-[380px] lg:shrink-0",
                panelOpen
                  ? "translate-x-0"
                  : "translate-x-full lg:hidden",
              ),
        )}
      >
        <header className="flex items-start gap-3 border-b border-line px-5 py-5">
          <span
            className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border text-sm font-semibold"
            style={{
              color: meta.accent,
              borderColor: `color-mix(in srgb, ${meta.accent} 35%, transparent)`,
              backgroundColor: `color-mix(in srgb, ${meta.accent} 12%, transparent)`,
            }}
          >
            {agent.name.slice(0, 1)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-base font-semibold">{agent.name}</h2>
              <AgentStatusBadge status={agent.status} />
            </div>
            <p className="mt-0.5 text-[11px] tracking-[0.1em] text-muted">
              {meta.capabilities.slice(0, 2).join(" · ")}
            </p>
          </div>
          <button
            type="button"
            onClick={() => selectAgent(null)}
            aria-label="关闭详情"
            className="rounded-lg p-1.5 text-muted hover:bg-white/5 hover:text-text"
          >
            <X size={18} />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <p className="text-sm leading-6 text-muted">{agent.description}</p>

          <section className="mt-5">
            <h3 className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted">
              能力范围
            </h3>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {meta.capabilities.map((capability) => (
                <span
                  key={capability}
                  className="rounded-md border border-line bg-raised/60 px-2 py-1 text-[11px] text-muted"
                >
                  {capability}
                </span>
              ))}
            </div>
          </section>

          <section className="mt-6">
            <h3 className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted">
              当前任务
            </h3>
            {task ? (
              <div className="mt-2 rounded-xl border border-line bg-raised/50 p-4">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium leading-5">{task.title}</p>
                  <Badge color={statusMeta.color}>{statusMeta.label}</Badge>
                </div>
                <p className="mt-2 text-[11px] leading-5 text-muted">
                  {task.pendingAction === "confirm_brief"
                    ? "Brief 已整理，等待你确认任务书"
                    : task.pendingAction === "accept_content"
                      ? "自动步骤已完成，等待你验收内容"
                      : stage?.label ?? "已提交审批"}
                  {task.status !== "waiting_approval" ? " · 进行中" : ""}
                </p>
                <ProgressBar
                  value={task.status === "waiting_approval" ? 100 : stageProgress}
                  color={meta.accent}
                  className="mt-3"
                  label="任务阶段进度"
                />
                <div className="mt-3 flex items-center justify-between text-[10px] text-muted">
                  <span>更新于 {formatRelative(task.updatedAt)}</span>
                  <span>
                    阶段 {Math.min(task.stageIndex + 1, task.stages.length)} /{" "}
                    {task.stages.length}
                  </span>
                </div>
                {task.status === "waiting_approval" ? (
                  <Link
                    to={`/workspace/tasks/${task.id}`}
                    onClick={() => selectAgent(null)}
                    className="mt-3 flex items-center justify-center gap-1.5 rounded-lg border border-violet/30 bg-violet/10 px-3 py-2 text-[11px] font-medium text-violet transition hover:bg-violet/15"
                  >
                    进入审批
                    <ArrowUpRight size={13} />
                  </Link>
                ) : null}
              </div>
            ) : (
              <div className="mt-2 rounded-xl border border-dashed border-line p-4 text-center">
                <p className="text-xs text-muted">当前没有正在执行的任务。</p>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Plus size={13} />}
                  className="mt-3"
                  onClick={() => {
                    selectAgent(null);
                    openNewTask(true);
                  }}
                >
                  创建新任务
                </Button>
              </div>
            )}
          </section>

          {agent.errorMessage ? (
            <section className="mt-6 rounded-xl border border-red/25 bg-red/8 p-4">
              <h3 className="text-[11px] font-medium uppercase tracking-[0.16em] text-red">
                异常信息
              </h3>
              <p className="mt-1.5 text-xs leading-5 text-muted">
                {agent.errorMessage}
              </p>
            </section>
          ) : null}

          <p className="mt-6 text-[10px] leading-5 text-muted">
            角色 ID 与动作来自后端 seven-agent.v0.1 契约。演示模式下由本地任务事件驱动；
            真实模式下由 `/api/v1/tasks` 与任务事件派生，不会因动画自动变更。
          </p>
          {task?.backendState ? (
            <p className="mt-2 text-[10px] text-muted/70">
              后端状态：
              <span style={{ color: BACKEND_STATE_META[task.backendState].color }}>
                {BACKEND_STATE_META[task.backendState].label}
              </span>
            </p>
          ) : null}
        </div>

        {task ? (
          <footer className="border-t border-line px-5 py-4">
            <Link
              to={`/workspace/tasks/${task.id}`}
              onClick={() => selectAgent(null)}
              className="flex h-10 items-center justify-center gap-1.5 rounded-xl border border-line bg-raised text-xs font-medium text-text transition hover:border-[#43506a]"
            >
              查看任务详情
              <ArrowUpRight size={14} />
            </Link>
          </footer>
        ) : null}
      </aside>
    </>
  );
}
