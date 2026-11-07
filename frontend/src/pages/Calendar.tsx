import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CalendarDays, ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { AGENT_META, TASK_STATUS_META, agentForTask } from "@/domain/agents";
import type { TaskVM } from "@/domain/types";
import { cn, formatDay, formatTime } from "@/lib/format";
import { useWorkspace } from "@/store/workspace";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { SectionHeader } from "@/components/ui/SectionHeader";

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

function dateKey(value: string | Date): string {
  const date = typeof value === "string" ? new Date(value) : value;
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function monthLabel(date: Date): string {
  return date.toLocaleDateString("zh-CN", { year: "numeric", month: "long" });
}

function buildCells(cursor: Date): { date: Date; key: string; inMonth: boolean }[] {
  const year = cursor.getFullYear();
  const month = cursor.getMonth();
  const first = new Date(year, month, 1);
  const offset = (first.getDay() + 6) % 7;
  const start = new Date(year, month, 1 - offset);
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return {
      date,
      key: dateKey(date),
      inMonth: date.getMonth() === month,
    };
  });
}

function DayTask({ task }: { task: TaskVM }) {
  const status = TASK_STATUS_META[task.status];
  const agent = AGENT_META[agentForTask(task)];
  return (
    <Link
      to={`/workspace/tasks/${task.id}`}
      className="flex items-start gap-2.5 rounded-xl border border-line bg-raised/40 p-3 transition hover:border-[#43506a]"
    >
      <span
        className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: status.color }}
      />
      <div className="min-w-0 flex-1">
        <p className="line-clamp-2 text-[11px] font-medium leading-5 text-text">
          {task.title}
        </p>
        <p className="mt-1 text-[10px] text-muted">
          {status.label} · {agent.name} · {formatTime(task.updatedAt)}
        </p>
      </div>
    </Link>
  );
}

export function CalendarPage() {
  const snapshot = useWorkspace((state) => state.snapshot);
  const openNewTask = useWorkspace((state) => state.openNewTask);
  const today = new Date();
  const [cursor, setCursor] = useState(
    () => new Date(today.getFullYear(), today.getMonth(), 1),
  );
  const [selectedKey, setSelectedKey] = useState(() => dateKey(today));

  const tasksByDay = useMemo(() => {
    const map = new Map<string, TaskVM[]>();
    for (const task of snapshot?.tasks ?? []) {
      const key = dateKey(task.updatedAt);
      const list = map.get(key) ?? [];
      list.push(task);
      map.set(key, list);
    }
    return map;
  }, [snapshot]);

  if (!snapshot) return null;

  const cells = buildCells(cursor);
  const selectedTasks = (tasksByDay.get(selectedKey) ?? []).sort((a, b) =>
    b.updatedAt.localeCompare(a.updatedAt),
  );
  const monthPrefix = `${cursor.getFullYear()}-${String(
    cursor.getMonth() + 1,
  ).padStart(2, "0")}`;
  const monthTasks = snapshot.tasks.filter((task) =>
    dateKey(task.updatedAt).startsWith(monthPrefix),
  );
  const todayKey = dateKey(today);
  const selectedDate = new Date(`${selectedKey}T12:00:00`);

  const moveMonth = (delta: number) => {
    const next = new Date(cursor.getFullYear(), cursor.getMonth() + delta, 1);
    setCursor(next);
    const nextPrefix = `${next.getFullYear()}-${String(
      next.getMonth() + 1,
    ).padStart(2, "0")}`;
    setSelectedKey(
      selectedKey.startsWith(nextPrefix) ? selectedKey : dateKey(next),
    );
  };

  return (
    <div className="space-y-5">
      <SectionHeader
        eyebrow="Calendar"
        title="内容日历"
        description="按任务最近一次状态变更聚合，帮助你看清哪一天发生了什么。排期能力将在接入后端后启用。"
        action={
          <Button
            variant="primary"
            icon={<Plus size={15} />}
            onClick={() => openNewTask(true)}
          >
            发起创作
          </Button>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="overflow-hidden">
          <CardHeader>
            <div className="flex items-center gap-2">
              <CalendarDays size={15} className="text-blue" />
              <h2 className="text-sm font-semibold">{monthLabel(cursor)}</h2>
              <span className="rounded border border-line px-1.5 py-0.5 text-[9px] text-muted">
                本月 {monthTasks.length} 次状态更新
              </span>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                aria-label="上一月"
                onClick={() => moveMonth(-1)}
                className="rounded-lg p-1.5 text-muted transition hover:bg-white/5 hover:text-text"
              >
                <ChevronLeft size={15} />
              </button>
              <button
                type="button"
                onClick={() => {
                  const now = new Date();
                  setCursor(new Date(now.getFullYear(), now.getMonth(), 1));
                  setSelectedKey(dateKey(now));
                }}
                className="rounded-lg px-2 py-1 text-[10px] text-muted transition hover:bg-white/5 hover:text-text"
              >
                今天
              </button>
              <button
                type="button"
                aria-label="下一月"
                onClick={() => moveMonth(1)}
                className="rounded-lg p-1.5 text-muted transition hover:bg-white/5 hover:text-text"
              >
                <ChevronRight size={15} />
              </button>
            </div>
          </CardHeader>
          <CardBody className="p-3 sm:p-4">
            <div className="grid grid-cols-7 gap-1">
              {WEEKDAYS.map((day) => (
                <div
                  key={day}
                  className="pb-2 text-center text-[9px] uppercase tracking-[0.14em] text-muted"
                >
                  {day}
                </div>
              ))}
              {cells.map((cell) => {
                const items = tasksByDay.get(cell.key) ?? [];
                const isToday = cell.key === todayKey;
                const isSelected = cell.key === selectedKey;
                return (
                  <button
                    key={cell.key}
                    type="button"
                    onClick={() => setSelectedKey(cell.key)}
                    aria-pressed={isSelected}
                    aria-label={`${cell.key}，${items.length} 条任务更新`}
                    className={cn(
                      "relative flex min-h-[72px] flex-col rounded-lg border p-1.5 text-left transition sm:min-h-[92px]",
                      isSelected
                        ? "border-blue/50 bg-blue/[0.08]"
                        : "border-transparent hover:border-line hover:bg-white/[0.02]",
                      !cell.inMonth && "opacity-35",
                    )}
                  >
                    <span
                      className={cn(
                        "flex h-5 w-5 items-center justify-center rounded-full text-[10px]",
                        isToday
                          ? "bg-blue text-ink font-semibold"
                          : "text-muted",
                      )}
                    >
                      {cell.date.getDate()}
                    </span>
                    <div className="mt-1 flex flex-1 flex-col gap-0.5 overflow-hidden">
                      {items.slice(0, 2).map((task) => (
                        <span
                          key={task.id}
                          className="flex items-center gap-1 truncate rounded bg-white/[0.04] px-1 py-0.5 text-[8px] leading-4 text-muted"
                        >
                          <span
                            className="h-1 w-1 shrink-0 rounded-full"
                            style={{
                              backgroundColor:
                                TASK_STATUS_META[task.status].color,
                            }}
                          />
                          <span className="truncate">{task.title}</span>
                        </span>
                      ))}
                      {items.length > 2 ? (
                        <span className="px-1 text-[8px] text-muted">
                          +{items.length - 2} 条
                        </span>
                      ) : null}
                    </div>
                  </button>
                );
              })}
            </div>
          </CardBody>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div>
                <h2 className="text-sm font-semibold">
                  {formatDay(selectedDate.toISOString())}
                </h2>
                <p className="mt-0.5 text-[11px] text-muted">
                  {selectedTasks.length
                    ? `${selectedTasks.length} 条任务状态更新`
                    : "这一天没有状态更新"}
                </p>
              </div>
            </CardHeader>
            <CardBody className="space-y-2">
              {selectedTasks.length ? (
                selectedTasks.map((task) => (
                  <DayTask key={task.id} task={task} />
                ))
              ) : (
                <EmptyState
                  className="px-3 py-8"
                  title="没有记录"
                  description="选择其他日期，或在这一天发起新的创作任务。"
                />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <h2 className="text-sm font-semibold">需要你处理</h2>
            </CardHeader>
            <CardBody className="space-y-2">
              {snapshot.tasks.filter(
                (task) => task.status === "waiting_approval",
              ).length ? (
                snapshot.tasks
                  .filter((task) => task.status === "waiting_approval")
                  .map((task) => <DayTask key={task.id} task={task} />)
              ) : (
                <p className="rounded-xl border border-dashed border-line px-3 py-6 text-center text-[11px] text-muted">
                  目前没有等待审批的内容。
                </p>
              )}
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
