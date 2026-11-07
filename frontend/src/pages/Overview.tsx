import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  FolderKanban,
  Plus,
  Sparkles,
  Users,
} from "lucide-react";
import {
  AGENT_META,
  TASK_STATUS_META,
  agentForTask,
  progressForTask,
  stageLabelForTask,
} from "@/domain/agents";
import type { AgentVM, TaskVM } from "@/domain/types";
import { cn, formatDay, formatRelative } from "@/lib/format";
import { useWorkspace } from "@/store/workspace";
import { Headquarters3D } from "@/components/headquarters/Headquarters3D";
import { AgentStatusBadge, TaskStatusBadge } from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { SectionHeader } from "@/components/ui/SectionHeader";

function Stat({
  icon,
  label,
  value,
  hint,
  color,
}: {
  icon: ReactNode;
  label: string;
  value: number | string;
  hint: string;
  color: string;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] text-muted">{label}</p>
          <p className="mt-2 text-2xl font-semibold tracking-tight">{value}</p>
          <p className="mt-1 text-[10px] text-muted">{hint}</p>
        </div>
        <span
          className="flex h-8 w-8 items-center justify-center rounded-lg border"
          style={{
            color,
            borderColor: `color-mix(in srgb, ${color} 30%, transparent)`,
            backgroundColor: `color-mix(in srgb, ${color} 10%, transparent)`,
          }}
        >
          {icon}
        </span>
      </div>
    </Card>
  );
}

function TaskRow({ task }: { task: TaskVM }) {
  const agent = AGENT_META[agentForTask(task)];
  const progress = progressForTask(task);
  return (
    <Link
      to={`/workspace/tasks/${task.id}`}
      className="group flex items-start gap-3 rounded-xl px-3 py-3 transition hover:bg-white/[0.03]"
    >
      <span
        className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border text-[10px] font-semibold"
        style={{
          color: agent.accent,
          borderColor: `color-mix(in srgb, ${agent.accent} 30%, transparent)`,
          backgroundColor: `color-mix(in srgb, ${agent.accent} 10%, transparent)`,
        }}
      >
        {agent.name.slice(0, 1)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-[13px] font-medium text-text">
            {task.title}
          </p>
          <TaskStatusBadge status={task.status} />
        </div>
        <p className="mt-1 text-[11px] text-muted">
          {stageLabelForTask(task)} · {agent.name} ·{" "}
          {formatRelative(task.updatedAt)}
        </p>
        <ProgressBar
          value={task.status === "waiting_approval" ? 100 : progress}
          color={agent.accent}
          className="mt-2 max-w-[220px]"
          label={`${task.title} 阶段进度`}
        />
      </div>
      <ArrowUpRight
        size={14}
        className="mt-1 shrink-0 text-muted opacity-0 transition group-hover:opacity-100"
      />
    </Link>
  );
}

function AgentRow({ agent }: { agent: AgentVM }) {
  const meta = AGENT_META[agent.id];
  const selectAgent = useWorkspace((state) => state.selectAgent);
  return (
    <button
      type="button"
      onClick={() => selectAgent(agent.id)}
      className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition hover:bg-white/[0.03]"
    >
      <span
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold"
        style={{
          color: meta.accent,
          borderColor: `color-mix(in srgb, ${meta.accent} 30%, transparent)`,
          backgroundColor: `color-mix(in srgb, ${meta.accent} 10%, transparent)`,
        }}
      >
        {agent.name.slice(0, 1)}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium">{agent.name}</p>
        <p className="truncate text-[10px] text-muted">
          {agent.activeTaskTitle ?? meta.capabilities[0]}
        </p>
      </div>
      <AgentStatusBadge status={agent.status} />
    </button>
  );
}

export function Overview() {
  const snapshot = useWorkspace((state) => state.snapshot);
  const selectedAgentId = useWorkspace((state) => state.selectedAgentId);
  const selectAgent = useWorkspace((state) => state.selectAgent);
  const setImmersive = useWorkspace((state) => state.setImmersive);
  const openNewTask = useWorkspace((state) => state.openNewTask);

  if (!snapshot) return null;
  const profile = snapshot.profile;
  const running = snapshot.tasks.filter(
    (task) => task.status === "running" || task.status === "queued",
  );
  const approvals = snapshot.tasks.filter(
    (task) => task.status === "waiting_approval",
  );
  const completed = snapshot.tasks
    .filter((task) => task.status === "completed")
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  const activeAgents = snapshot.agents.filter(
    (agent) => agent.status === "working" || agent.status === "review",
  ).length;
  const hour = new Date().getHours();
  const greeting = hour < 11 ? "早上好" : hour < 18 ? "下午好" : "晚上好";

  return (
    <div className="space-y-6">
      <SectionHeader
        className="studio-intro"
        eyebrow={`${formatDay(new Date().toISOString())} · 工作台`}
        title={`${greeting}，${profile?.creatorName ?? "创作者"}`}
        description={`这里是「${
          profile?.workspaceName ?? "我的内容工作室"
        }」。把需求交清楚，把稿件做完整，把修改留得住。`}
        action={
          <Button
            variant="primary"
            icon={<Plus size={15} />}
            onClick={() => openNewTask(true)}
          >
            发起创作任务
          </Button>
        }
      />

      {approvals.length > 0 ? (
        <div className="flex flex-col gap-3 rounded-sm border-l-2 border-line bg-surface p-4 sm:flex-row sm:items-center">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-violet/30 bg-violet/10 text-violet">
            <CheckCircle2 size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-text">
              {approvals.length} 项内容等待你的决定
            </p>
            <p className="mt-0.5 truncate text-[11px] text-muted">
              {approvals[0].pendingAction === "confirm_brief"
                ? `《${approvals[0].title}》的 Brief 已整理完成，确认后才会进入内容生成。`
                : `《${approvals[0].title}》已完成自动步骤，验收后会保存到项目资产。`}
            </p>
          </div>
          <Link
            to={`/workspace/tasks/${approvals[0].id}`}
            className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-violet/40 bg-violet/10 px-3 text-[11px] font-medium text-violet transition hover:bg-violet/15"
          >
            去审批
            <ArrowRight size={13} />
          </Link>
        </div>
      ) : null}

      <section className="overflow-hidden rounded-sm border border-line bg-surface">
        <Headquarters3D
          agents={snapshot.agents}
          selectedAgentId={selectedAgentId}
          onSelectAgent={selectAgent}
          onToggleImmersive={() => setImmersive(true)}
          className="h-[400px] w-full sm:h-[500px] lg:h-[560px]"
        />
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-3">
          <p className="text-[10px] leading-5 text-muted">
            点击工位查看角色 · 拖拽可旋转 · 滚轮可缩放 · 双击复位
          </p>
          <button
            type="button"
            onClick={() => setImmersive(true)}
            className="text-[10px] font-medium text-blue transition hover:text-text"
          >
            走进协作现场 ↗
          </button>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          icon={<Users size={15} />}
          label="在线员工"
          value={`${activeAgents} / ${snapshot.agents.length}`}
          hint="工作中或等待审批"
          color="#78E3DE"
        />
        <Stat
          icon={<Clock3 size={15} />}
          label="进行中的任务"
          value={running.length}
          hint="包含排队中的任务"
          color="#83B8FF"
        />
        <Stat
          icon={<Sparkles size={15} />}
          label="待你审批"
          value={approvals.length}
          hint="需要人工决定"
          color="#B49CFF"
        />
        <Stat
          icon={<CheckCircle2 size={15} />}
          label="已完成"
          value={completed.length}
          hint="已进入项目资产"
          color="#8FD6A8"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card>
            <CardHeader>
              <div>
                <h2 className="text-sm font-semibold">正在创作</h2>
                <p className="mt-0.5 text-[11px] text-muted">
                  团队正在推进的内容任务
                </p>
              </div>
              <Link
                to="/workspace/tasks"
                className="text-[11px] text-muted transition hover:text-text"
              >
                全部任务 ↗
              </Link>
            </CardHeader>
            <CardBody className="p-2">
              {running.length ? (
                <div className="divide-y divide-line/50">
                  {running.map((task) => (
                    <TaskRow key={task.id} task={task} />
                  ))}
                </div>
              ) : (
                <EmptyState
                  title="当前没有进行中的任务"
                  description="发起一个创作任务，运营官会先整理 Brief，确认后才进入生成。"
                  action={
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={<Plus size={13} />}
                      onClick={() => openNewTask(true)}
                    >
                      新建任务
                    </Button>
                  }
                />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <h2 className="text-sm font-semibold">最近成果</h2>
                <p className="mt-0.5 text-[11px] text-muted">
                  已批准并进入项目的内容
                </p>
              </div>
              <Link
                to="/workspace/assets"
                className="text-[11px] text-muted transition hover:text-text"
              >
                素材库 ↗
              </Link>
            </CardHeader>
            <CardBody>
              {completed.length ? (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {completed.slice(0, 4).map((task) => {
                    const status = TASK_STATUS_META[task.status];
                    return (
                      <Link
                        key={task.id}
                        to={`/workspace/tasks/${task.id}`}
                        className="group rounded-xl border border-line bg-raised/40 p-3 transition hover:border-[#43506a]"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[10px] text-muted">
                            {formatRelative(task.updatedAt)}
                          </span>
                          <span
                            className="h-1.5 w-1.5 rounded-full"
                            style={{ backgroundColor: status.color }}
                          />
                        </div>
                        <p className="mt-2 line-clamp-2 text-xs font-medium leading-5 text-text">
                          {task.title}
                        </p>
                        <p className="mt-1 text-[10px] text-muted">
                          {task.brief.format} · {task.brief.duration}
                        </p>
                      </Link>
                    );
                  })}
                </div>
              ) : (
                <EmptyState
                  title="还没有已批准的成果"
                  description="完成一次审批后，内容会出现在这里和素材库。"
                />
              )}
            </CardBody>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div>
                <h2 className="text-sm font-semibold">协作团队</h2>
                <p className="mt-0.5 text-[11px] text-muted">
                  点击查看当前任务与详情
                </p>
              </div>
              <Link
                to="/workspace/workforce"
                className="text-[11px] text-muted transition hover:text-text"
              >
                全部 ↗
              </Link>
            </CardHeader>
            <CardBody className="space-y-0.5 p-2">
              {snapshot.agents.map((agent) => (
                <AgentRow key={agent.id} agent={agent} />
              ))}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <h2 className="text-sm font-semibold">内容项目</h2>
                <p className="mt-0.5 text-[11px] text-muted">持续创作的主题</p>
              </div>
              <FolderKanban size={14} className="text-muted" />
            </CardHeader>
            <CardBody className="space-y-0.5 p-2">
              {snapshot.projects.slice(0, 4).map((project) => {
                const count = snapshot.tasks.filter(
                  (task) => task.projectId === project.id,
                ).length;
                return (
                  <Link
                    key={project.id}
                    to="/workspace/projects"
                    className="flex items-center gap-3 rounded-xl px-3 py-2.5 transition hover:bg-white/[0.03]"
                  >
                    <span
                      className="h-6 w-1 rounded-full"
                      style={{ backgroundColor: project.accent }}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium">
                        {project.name}
                      </p>
                      <p className="text-[10px] text-muted">{count} 个任务</p>
                    </div>
                    <span className="text-[10px] text-muted">
                      {formatRelative(project.updatedAt)}
                    </span>
                  </Link>
                );
              })}
            </CardBody>
          </Card>

          <div
            className={cn(
              "rounded-2xl border border-line bg-raised/40 p-4",
              "text-[10px] leading-5 text-muted",
            )}
          >
            当前为<b className="text-amber">演示模式</b>：任务由本地适配层按阶段推进，
            2D 与 3D 读取同一份状态。真实后端切换入口在「设置」。
          </div>
        </div>
      </div>
    </div>
  );
}
