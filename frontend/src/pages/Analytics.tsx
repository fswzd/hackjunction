import { useMemo, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  CheckCircle2,
  Clock3,
  FileText,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import {
  AGENT_META,
  AGENT_ORDER,
  PIPELINE,
  TASK_STATUS_META,
  agentForTask,
} from "@/domain/agents";
import type { AgentId, TaskStatus } from "@/domain/types";
import { formatDay } from "@/lib/format";
import { useWorkspace } from "@/store/workspace";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { SectionHeader } from "@/components/ui/SectionHeader";

function ratio(part: number, total: number): number {
  return total ? Math.round((part / total) * 100) : 0;
}

function Stat({
  label,
  value,
  hint,
  accent,
  icon,
}: {
  label: string;
  value: string;
  hint: string;
  accent: string;
  icon: ReactNode;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] text-muted">{label}</p>
          <p className="mt-2 text-2xl font-semibold tracking-tight">{value}</p>
          <p className="mt-1 text-[10px] leading-4 text-muted">{hint}</p>
        </div>
        <span
          className="flex h-8 w-8 items-center justify-center rounded-lg border"
          style={{
            color: accent,
            borderColor: `color-mix(in srgb, ${accent} 30%, transparent)`,
            backgroundColor: `color-mix(in srgb, ${accent} 10%, transparent)`,
          }}
        >
          {icon}
        </span>
      </div>
    </Card>
  );
}

function BarRow({
  label,
  value,
  max,
  color,
  caption,
}: {
  label: string;
  value: number;
  max: number;
  color: string;
  caption?: string;
}) {
  const width = max ? Math.max((value / max) * 100, value > 0 ? 6 : 0) : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="w-24 shrink-0 text-right">
        <p className="truncate text-[11px] text-text">{label}</p>
        {caption ? (
          <p className="truncate text-[9px] text-muted">{caption}</p>
        ) : null}
      </div>
      <div
        className="relative h-5 flex-1 overflow-hidden rounded-md bg-line/25"
        role="img"
        aria-label={`${label}：${value}`}
        title={`${label}：${value}`}
      >
        <div
          className="h-full rounded-md transition-[width] duration-500"
          style={{ width: `${width}%`, backgroundColor: color }}
        />
      </div>
      <span className="w-7 shrink-0 text-right text-[11px] tabular-nums text-text">
        {value}
      </span>
    </div>
  );
}

export function Analytics() {
  const snapshot = useWorkspace((state) => state.snapshot);
  const mode = useWorkspace((state) => state.mode);

  const activity = useMemo(() => {
    const days = Array.from({ length: 7 }, (_, index) => {
      const date = new Date();
      date.setHours(0, 0, 0, 0);
      date.setDate(date.getDate() - (6 - index));
      return {
        key: date.toISOString().slice(0, 10),
        date,
        count: 0,
      };
    });
    const byKey = new Map(days.map((day) => [day.key, day]));
    for (const task of snapshot?.tasks ?? []) {
      for (const event of task.events) {
        const date = new Date(event.at);
        date.setHours(0, 0, 0, 0);
        const day = byKey.get(date.toISOString().slice(0, 10));
        if (day) day.count += 1;
      }
    }
    return days;
  }, [snapshot]);

  if (!snapshot) return null;

  const tasks = snapshot.tasks;
  const completed = tasks.filter((task) => task.status === "completed").length;
  const waiting = tasks.filter(
    (task) => task.status === "waiting_approval",
  ).length;
  const failed = tasks.filter((task) => task.status === "failed").length;
  const cancelled = tasks.filter((task) => task.status === "cancelled").length;
  const running = tasks.filter(
    (task) => task.status === "running" || task.status === "queued",
  ).length;
  const revisions = tasks.reduce((total, task) => total + task.revisionCount, 0);

  const stageCounts = PIPELINE.map((stage) => ({
    label: stage.label,
    agentId: stage.agentId,
    count: tasks.filter(
      (task) =>
        task.status === "running" &&
        task.stages[task.stageIndex]?.backendStep === stage.backendStep,
    ).length,
  }));
  const stageMax = Math.max(
    1,
    ...stageCounts.map((item) => item.count),
    completed,
    running,
  );

  const statusOrder: TaskStatus[] = [
    "running",
    "waiting_approval",
    "completed",
    "queued",
    "failed",
    "cancelled",
  ];
  const statusCounts = statusOrder
    .map((status) => ({
      status,
      count: tasks.filter((task) => task.status === status).length,
    }))
    .filter((item) => item.count > 0);

  const agentLoad = AGENT_ORDER.map((id: AgentId) => {
    const agent = snapshot.agents.find((item) => item.id === id)!;
    const assigned = tasks.filter(
      (task) =>
        task.status !== "completed" &&
        task.status !== "cancelled" &&
        agentForTask(task) === id,
    ).length;
    return { id, agent, assigned };
  });
  const loadMax = Math.max(1, ...agentLoad.map((item) => item.assigned));
  const activityMax = Math.max(1, ...activity.map((day) => day.count));

  return (
    <div className="space-y-5">
      <SectionHeader
        eyebrow="复盘"
        title="数据分析"
        description="所有指标由当前工作空间实时计算，不使用占位数字。演示数据的样本量较小，仅用于验证闭环。"
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="任务总数"
          value={String(tasks.length)}
          hint={`${running} 个执行中 · ${waiting} 个待审批`}
          accent="#83B8FF"
          icon={<FileText size={15} />}
        />
        <Stat
          label="完成率"
          value={`${ratio(completed, tasks.length)}%`}
          hint={`${completed} 个已批准归档`}
          accent="#8FD6A8"
          icon={<CheckCircle2 size={15} />}
        />
        <Stat
          label="待你审批"
          value={String(waiting)}
          hint={waiting ? "审批是唯一的人工闭环" : "当前没有待处理内容"}
          accent="#B49CFF"
          icon={<Sparkles size={15} />}
        />
        <Stat
          label="人工修订"
          value={String(revisions)}
          hint={`${failed} 个失败 · ${cancelled} 个取消`}
          accent="#F0B36E"
          icon={<Clock3 size={15} />}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <h2 className="text-sm font-semibold">任务分布</h2>
              <p className="mt-0.5 text-[11px] text-muted">
                执行中的任务按当前阶段归类，单系列计数
              </p>
            </div>
            <TrendingUp size={14} className="text-muted" />
          </CardHeader>
          <CardBody className="space-y-3">
            {stageCounts.map((item) => (
              <BarRow
                key={item.label}
                label={item.label}
                caption={AGENT_META[item.agentId].name}
                value={item.count}
                max={stageMax}
                color="#83B8FF"
              />
            ))}
            <div className="my-1 border-t border-line/60" />
            <BarRow
              label="已完成"
              caption="已归档"
              value={completed}
              max={stageMax}
              color="#83B8FF"
            />
            <BarRow
              label="失败 / 取消"
              caption="已停止"
              value={failed + cancelled}
              max={stageMax}
              color="#83B8FF"
            />
            {tasks.length === 0 ? (
              <p className="pt-2 text-[11px] text-muted">
                还没有任务数据。发起一次创作后这里会自动更新。
              </p>
            ) : null}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <h2 className="text-sm font-semibold">近 7 天状态更新</h2>
              <p className="mt-0.5 text-[11px] text-muted">
                按任务事件发生时间统计，单系列计数
              </p>
            </div>
            <span className="text-[10px] text-muted">
              合计 {activity.reduce((total, day) => total + day.count, 0)} 次
            </span>
          </CardHeader>
          <CardBody>
            <div className="flex h-44 items-end gap-2">
              {activity.map((day) => {
                const height = day.count
                  ? Math.max((day.count / activityMax) * 100, 8)
                  : 2;
                return (
                  <div
                    key={day.key}
                    className="flex h-full flex-1 flex-col items-center justify-end gap-2"
                    title={`${formatDay(day.date.toISOString())}：${day.count} 次`}
                  >
                    <span className="text-[10px] tabular-nums text-text">
                      {day.count || ""}
                    </span>
                    <div
                      className="w-full max-w-9 rounded-t-[4px] bg-cyan/80 transition-[height] duration-500"
                      style={{ height: `${height}%` }}
                      role="img"
                      aria-label={`${formatDay(day.date.toISOString())}：${day.count} 次状态更新`}
                    />
                    <span className="text-[9px] text-muted">
                      {day.date.toLocaleDateString("zh-CN", {
                        weekday: "short",
                      })}
                    </span>
                  </div>
                );
              })}
            </div>
            <p className="mt-3 border-t border-line/60 pt-3 text-[10px] text-muted">
              柱高以 7 日内最大值归一，数值直接标注在柱顶。
            </p>
          </CardBody>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <h2 className="text-sm font-semibold">员工负载</h2>
              <p className="mt-0.5 text-[11px] text-muted">
                当前未结束任务在各阶段的归属
              </p>
            </div>
          </CardHeader>
          <CardBody className="space-y-3">
            {agentLoad.map(({ id, agent, assigned }) => (
              <div key={id} className="flex items-center gap-3">
                <span className="flex w-24 shrink-0 items-center gap-1.5 text-[11px] text-text">
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: AGENT_META[id].accent }}
                  />
                  <span className="truncate">{agent.name}</span>
                </span>
                <div
                  className="h-2 flex-1 overflow-hidden rounded-full bg-line/30"
                  role="img"
                  aria-label={`${agent.name}：${assigned} 个任务`}
                >
                  <div
                    className="h-full rounded-full transition-[width] duration-500"
                    style={{
                      width: `${(assigned / loadMax) * 100}%`,
                      backgroundColor: AGENT_META[id].accent,
                    }}
                  />
                </div>
                <span className="w-8 text-right text-[11px] tabular-nums text-text">
                  {assigned}
                </span>
                <span className="w-16 shrink-0 text-right text-[9px] text-muted">
                  {agent.status === "idle"
                    ? "空闲"
                    : agent.status === "review"
                      ? "待审批"
                      : agent.status === "error"
                        ? "异常"
                        : "执行中"}
                </span>
              </div>
            ))}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <h2 className="text-sm font-semibold">状态构成</h2>
              <p className="mt-0.5 text-[11px] text-muted">
                当前任务状态分布，颜色均附带文字标签
              </p>
            </div>
          </CardHeader>
          <CardBody>
            {statusCounts.length ? (
              <ul className="space-y-2.5">
                {statusCounts.map(({ status, count }) => (
                  <li key={status} className="flex items-center gap-3">
                    <span
                      className="h-2 w-2 rounded-full"
                      style={{ backgroundColor: TASK_STATUS_META[status].color }}
                    />
                    <span className="flex-1 text-[11px] text-text">
                      {TASK_STATUS_META[status].label}
                    </span>
                    <span className="text-[11px] tabular-nums text-muted">
                      {count}
                    </span>
                    <span className="w-10 text-right text-[9px] text-muted">
                      {ratio(count, tasks.length)}%
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[11px] text-muted">还没有任务数据。</p>
            )}
            <div className="mt-4 border-t border-line/60 pt-3">
              <Link
                to="/workspace/tasks"
                className="text-[11px] text-blue transition hover:text-text"
              >
                查看任务明细 ↗
              </Link>
            </div>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardBody className="flex flex-col gap-2 text-[10px] leading-5 text-muted sm:flex-row sm:items-center sm:justify-between">
          <span>
            {mode === "demo"
              ? "数据来源：本地演示适配器（localStorage），指标随任务推进实时变化。"
              : "数据来源：后端 /api/v1/tasks。审批、修订与用量接口尚未接入，相关指标暂不可用。"}
          </span>
          <span className="shrink-0 text-muted/70">
            统计口径：任务数按状态去重 · 事件按发生时间归日
          </span>
        </CardBody>
      </Card>
    </div>
  );
}
