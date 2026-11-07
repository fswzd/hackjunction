import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowUpRight,
  LayoutGrid,
  List,
  Plus,
  Search,
  X,
} from "lucide-react";
import { AGENT_META, agentForTask, stageLabelForTask } from "@/domain/agents";
import type { TaskVM } from "@/domain/types";
import { cn, formatRelative } from "@/lib/format";
import { useWorkspace } from "@/store/workspace";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { TaskStatusBadge } from "@/components/ui/StatusBadge";

type Filter = "all" | "active" | "approval" | "completed" | "closed";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "active", label: "执行中" },
  { key: "approval", label: "待审批" },
  { key: "completed", label: "已完成" },
  { key: "closed", label: "已结束" },
];

function matchesFilter(task: TaskVM, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "active") return task.status === "running" || task.status === "queued";
  if (filter === "approval") return task.status === "waiting_approval";
  if (filter === "completed") return task.status === "completed";
  return task.status === "failed" || task.status === "cancelled";
}

function TaskCard({ task }: { task: TaskVM }) {
  const agent = AGENT_META[agentForTask(task)];
  return (
    <Link
      to={`/workspace/tasks/${task.id}`}
      className="group block rounded-xl border border-line bg-surface p-4 transition hover:border-[#43506a]"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="line-clamp-2 text-sm font-medium leading-5 text-text">
          {task.title}
        </p>
        <TaskStatusBadge status={task.status} />
      </div>
      <p className="mt-2 text-[11px] text-muted">
        {agent.name} · {stageLabelForTask(task)}
      </p>
      <div className="mt-3 flex items-center justify-between text-[10px] text-muted">
        <span>{task.brief.format} · {task.brief.duration}</span>
        <span>{formatRelative(task.updatedAt)}</span>
      </div>
      {task.status === "waiting_approval" ? (
        <p className="mt-3 rounded-lg border border-violet/25 bg-violet/8 px-2.5 py-1.5 text-[10px] text-violet">
          {task.pendingAction === "confirm_brief"
            ? "Brief 已整理，等待你确认任务书"
            : "自动步骤已完成，等待你验收内容"}
        </p>
      ) : null}
    </Link>
  );
}

export function Tasks() {
  const snapshot = useWorkspace((state) => state.snapshot);
  const openNewTask = useWorkspace((state) => state.openNewTask);
  const [params, setParams] = useSearchParams();
  const projectId = params.get("project");
  const [filter, setFilter] = useState<Filter>("all");
  const [view, setView] = useState<"list" | "board">("list");
  const [query, setQuery] = useState("");

  const tasks = useMemo(() => {
    if (!snapshot) return [];
    return snapshot.tasks
      .filter((task) => (projectId ? task.projectId === projectId : true))
      .filter((task) => matchesFilter(task, filter))
      .filter((task) =>
        query.trim()
          ? task.title.toLowerCase().includes(query.trim().toLowerCase())
          : true,
      )
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  }, [snapshot, projectId, filter, query]);

  if (!snapshot) return null;
  const project = snapshot.projects.find((item) => item.id === projectId);

  const counts = {
    all: snapshot.tasks.filter((task) => (projectId ? task.projectId === projectId : true)).length,
    active: snapshot.tasks.filter(
      (task) =>
        (!projectId || task.projectId === projectId) &&
        matchesFilter(task, "active"),
    ).length,
    approval: snapshot.tasks.filter(
      (task) =>
        (!projectId || task.projectId === projectId) &&
        matchesFilter(task, "approval"),
    ).length,
    completed: snapshot.tasks.filter(
      (task) =>
        (!projectId || task.projectId === projectId) &&
        matchesFilter(task, "completed"),
    ).length,
    closed: snapshot.tasks.filter(
      (task) =>
        (!projectId || task.projectId === projectId) &&
        matchesFilter(task, "closed"),
    ).length,
  };

  const board = [
    {
      key: "approval",
      label: "待审批",
      color: "#B49CFF",
      tasks: snapshot.tasks.filter(
        (task) =>
          (!projectId || task.projectId === projectId) &&
          task.status === "waiting_approval",
      ),
    },
    {
      key: "active",
      label: "执行中",
      color: "#78E3DE",
      tasks: snapshot.tasks.filter(
        (task) =>
          (!projectId || task.projectId === projectId) &&
          (task.status === "running" || task.status === "queued"),
      ),
    },
    {
      key: "completed",
      label: "已完成",
      color: "#8FD6A8",
      tasks: snapshot.tasks.filter(
        (task) =>
          (!projectId || task.projectId === projectId) &&
          task.status === "completed",
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <SectionHeader
        eyebrow="Tasks"
        title="任务中心"
        description="从发起到审批的完整闭环。状态来自适配层，不因动画自动完成。"
        action={
          <Button
            variant="primary"
            icon={<Plus size={15} />}
            onClick={() => openNewTask(true)}
          >
            新建任务
          </Button>
        }
      />

      {project ? (
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-2 rounded-full border border-line bg-raised px-3 py-1 text-[11px] text-text">
            项目：{project.name}
            <button
              type="button"
              aria-label="清除项目筛选"
              onClick={() => {
                const next = new URLSearchParams(params);
                next.delete("project");
                setParams(next, { replace: true });
              }}
              className="text-muted hover:text-text"
            >
              <X size={12} />
            </button>
          </span>
        </div>
      ) : null}

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setFilter(item.key)}
              aria-pressed={filter === item.key}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-[11px] transition",
                filter === item.key
                  ? "border-blue/45 bg-blue/10 text-blue"
                  : "border-line bg-raised text-muted hover:text-text",
              )}
            >
              {item.label}
              <span className="ml-1.5 opacity-60">{counts[item.key]}</span>
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <label className="relative flex-1 lg:w-56">
            <Search
              size={14}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted"
            />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索任务"
              aria-label="搜索任务"
              className="h-9 w-full rounded-lg border border-line bg-raised pl-9 pr-3 text-xs text-text placeholder:text-muted/60 focus:border-blue/60 focus:outline-none"
            />
          </label>
          <div className="flex rounded-lg border border-line bg-raised p-0.5">
            <button
              type="button"
              onClick={() => setView("list")}
              aria-label="列表视图"
              aria-pressed={view === "list"}
              className={cn(
                "rounded-md p-1.5 transition",
                view === "list" ? "bg-surface text-text" : "text-muted hover:text-text",
              )}
            >
              <List size={14} />
            </button>
            <button
              type="button"
              onClick={() => setView("board")}
              aria-label="看板视图"
              aria-pressed={view === "board"}
              className={cn(
                "rounded-md p-1.5 transition",
                view === "board" ? "bg-surface text-text" : "text-muted hover:text-text",
              )}
            >
              <LayoutGrid size={14} />
            </button>
          </div>
        </div>
      </div>

      {view === "board" ? (
        <div className="grid gap-4 lg:grid-cols-3">
          {board.map((column) => (
            <section key={column.key} className="rounded-2xl border border-line bg-surface/60 p-3">
              <header className="mb-3 flex items-center gap-2 px-1">
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ backgroundColor: column.color }}
                />
                <h2 className="text-xs font-medium">{column.label}</h2>
                <span className="ml-auto text-[10px] text-muted">
                  {column.tasks.length}
                </span>
              </header>
              <div className="space-y-2">
                {column.tasks.map((task) => (
                  <TaskCard key={task.id} task={task} />
                ))}
                {column.tasks.length === 0 ? (
                  <p className="rounded-xl border border-dashed border-line px-3 py-8 text-center text-[11px] text-muted">
                    暂无任务
                  </p>
                ) : null}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <Card className="overflow-hidden">
          {tasks.length ? (
            <ul className="divide-y divide-line/60">
              {tasks.map((task) => {
                const agent = AGENT_META[agentForTask(task)];
                const project = snapshot.projects.find(
                  (item) => item.id === task.projectId,
                );
                return (
                  <li key={task.id}>
                    <Link
                      to={`/workspace/tasks/${task.id}`}
                      className="group flex items-center gap-4 px-4 py-3.5 transition hover:bg-white/[0.03]"
                    >
                      <span
                        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border text-[10px] font-semibold"
                        style={{
                          color: agent.accent,
                          borderColor: `color-mix(in srgb, ${agent.accent} 30%, transparent)`,
                          backgroundColor: `color-mix(in srgb, ${agent.accent} 10%, transparent)`,
                        }}
                      >
                        {agent.name.slice(0, 1)}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px] font-medium text-text">
                          {task.title}
                        </p>
                        <p className="mt-0.5 truncate text-[10px] text-muted">
                          {project?.name ?? "未归档"} · {agent.name} ·{" "}
                          {stageLabelForTask(task)}
                        </p>
                      </div>
                      <span className="hidden text-[10px] text-muted sm:block">
                        {formatRelative(task.updatedAt)}
                      </span>
                      <TaskStatusBadge status={task.status} />
                      <ArrowUpRight
                        size={14}
                        className="shrink-0 text-muted opacity-0 transition group-hover:opacity-100"
                      />
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState
              title="没有匹配的任务"
              description="调整筛选条件，或发起一个新的创作任务。"
            />
          )}
        </Card>
      )}
    </div>
  );
}
