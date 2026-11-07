import { Link } from "react-router-dom";
import { ArrowRight, ArrowUpRight, CornerDownRight } from "lucide-react";
import { AGENT_META, AGENT_ORDER, STATUS_META } from "@/domain/agents";
import { formatRelative } from "@/lib/format";
import { useWorkspace } from "@/store/workspace";
import { AgentStatusBadge } from "@/components/ui/StatusBadge";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { SectionHeader } from "@/components/ui/SectionHeader";

export function Workforce() {
  const snapshot = useWorkspace((state) => state.snapshot);
  const selectAgent = useWorkspace((state) => state.selectAgent);
  const openNewTask = useWorkspace((state) => state.openNewTask);

  if (!snapshot) return null;
  const operator = snapshot.agents.find(
    (agent) => agent.id === "operations_officer",
  )!;
  const staff = AGENT_ORDER.filter((id) => id !== "operations_officer").map(
    (id) => snapshot.agents.find((agent) => agent.id === id)!,
  );

  return (
    <div className="space-y-6">
      <SectionHeader
        eyebrow="AI Workforce"
        title="你的 协作团队"
        description="一位运营官与六位专业员工，对应后端 seven-agent.v0.1 的七个业务角色。每个角色都有清楚的职责、真实的任务状态和可追溯的交付物。"
        action={
          <Button
            variant="primary"
            icon={<ArrowRight size={15} />}
            onClick={() => openNewTask(true)}
          >
            发起任务
          </Button>
        }
      />

      <Card
        className="overflow-hidden"
        style={{
          background:
            "radial-gradient(ellipse at 10% 0%, rgba(131,184,255,0.10), transparent 55%), #171B25",
        }}
      >
        <div className="flex flex-col gap-5 p-5 sm:flex-row sm:items-center">
          <span
            className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border text-lg font-semibold"
            style={{
              color: AGENT_META.operations_officer.accent,
              borderColor: `color-mix(in srgb, ${AGENT_META.operations_officer.accent} 35%, transparent)`,
              backgroundColor: `color-mix(in srgb, ${AGENT_META.operations_officer.accent} 12%, transparent)`,
            }}
          >
            运
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold">{operator.name}</h2>
              <Badge color={AGENT_META.operations_officer.accent}>总协调</Badge>
              <AgentStatusBadge status={operator.status} />
            </div>
            <p className="mt-1.5 max-w-2xl text-xs leading-6 text-muted">
              {operator.description}
            </p>
            <p className="mt-1 font-mono text-[9px] text-muted/70">
              operations_officer · prepare_brief
            </p>
            <p className="mt-1 text-[10px] text-muted">
              {operator.activeTaskTitle
                ? `当前：${operator.activeTaskTitle}`
                : "当前没有正在执行的任务"}
              {" · "}
              更新于 {formatRelative(operator.lastUpdatedAt)}
            </p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => selectAgent("operations_officer")}
          >
            查看详情
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-line bg-raised/40 px-5 py-3 text-[10px] text-muted">
          <CornerDownRight size={12} />
          运营官负责接住你的目标、拆成 Brief，并按后端确定性路由协调下面六位员工。
          模型输出不参与调度；Brief 确认与内容验收是两个独立的人工节点。
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {staff.map((agent) => {
          const meta = AGENT_META[agent.id];
          const status = STATUS_META[agent.status];
          const task = agent.activeTaskId
            ? snapshot.tasks.find((item) => item.id === agent.activeTaskId)
            : undefined;
          return (
            <Card
              key={agent.id}
              className="flex flex-col p-5 transition hover:border-[#43506a]"
            >
              <div className="flex items-start justify-between gap-2">
                <span
                  className="flex h-10 w-10 items-center justify-center rounded-xl border text-sm font-semibold"
                  style={{
                    color: meta.accent,
                    borderColor: `color-mix(in srgb, ${meta.accent} 35%, transparent)`,
                    backgroundColor: `color-mix(in srgb, ${meta.accent} 12%, transparent)`,
                  }}
                >
                  {agent.name.slice(0, 1)}
                </span>
                <AgentStatusBadge status={agent.status} />
              </div>
              <h3 className="mt-4 text-sm font-semibold">{agent.name}</h3>
              <p className="text-[10px] uppercase tracking-[0.14em] text-muted">
                {agent.role}
              </p>
              <p className="mt-1 font-mono text-[9px] text-muted/70">
                {agent.id} · {meta.actions.join(" / ")}
              </p>
              <p className="mt-3 line-clamp-3 flex-1 text-[11px] leading-5 text-muted">
                {agent.description}
              </p>

              <div className="mt-4 rounded-xl border border-line bg-raised/50 p-3">
                <p className="text-[10px] uppercase tracking-[0.14em] text-muted">
                  当前任务
                </p>
                {task ? (
                  <Link
                    to={`/workspace/tasks/${task.id}`}
                    className="mt-1.5 flex items-start justify-between gap-2 text-[11px] font-medium leading-5 text-text hover:text-blue"
                  >
                    <span className="line-clamp-2">{task.title}</span>
                    <ArrowUpRight size={12} className="mt-0.5 shrink-0" />
                  </Link>
                ) : (
                  <p className="mt-1.5 text-[11px] text-muted">
                    {agent.status === "error"
                      ? agent.errorMessage
                      : "当前没有正在执行的任务。"}
                  </p>
                )}
                <p className="mt-1.5 flex items-center gap-1.5 text-[10px] text-muted">
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: status.color }}
                  />
                  {status.label} · {formatRelative(agent.lastUpdatedAt)}
                </p>
              </div>

              <div className="mt-3 flex flex-wrap gap-1">
                {meta.capabilities.slice(0, 3).map((capability) => (
                  <span
                    key={capability}
                    className="rounded border border-line px-1.5 py-0.5 text-[9px] text-muted"
                  >
                    {capability}
                  </span>
                ))}
              </div>

              <Button
                variant="ghost"
                size="sm"
                className="mt-3 justify-between"
                onClick={() => selectAgent(agent.id)}
              >
                查看员工详情
                <ArrowRight size={13} />
              </Button>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
