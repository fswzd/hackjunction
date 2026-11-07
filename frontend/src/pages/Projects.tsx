import { Link } from "react-router-dom";
import { ArrowUpRight, FolderKanban, Plus } from "lucide-react";
import { formatRelative } from "@/lib/format";
import { useWorkspace } from "@/store/workspace";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { TaskStatusBadge } from "@/components/ui/StatusBadge";

export function Projects() {
  const snapshot = useWorkspace((state) => state.snapshot);
  const openNewTask = useWorkspace((state) => state.openNewTask);

  if (!snapshot) return null;

  return (
    <div className="space-y-6">
      <SectionHeader
        eyebrow="Projects"
        title="内容项目"
        description="一个项目可以是一个系列、一个账号或一次持续创作。任务与产物都归档在项目下。"
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

      {snapshot.projects.length ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {snapshot.projects.map((project) => {
            const tasks = snapshot.tasks.filter(
              (task) => task.projectId === project.id,
            );
            const completed = tasks.filter(
              (task) => task.status === "completed",
            ).length;
            const progress = tasks.length
              ? Math.round((completed / tasks.length) * 100)
              : 0;
            return (
              <Card key={project.id} className="flex flex-col p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <span
                      className="mt-1 h-9 w-1.5 rounded-full"
                      style={{ backgroundColor: project.accent }}
                    />
                    <div>
                      <h2 className="text-base font-semibold">{project.name}</h2>
                      <p className="mt-1 max-w-md text-[11px] leading-5 text-muted">
                        {project.description}
                      </p>
                    </div>
                  </div>
                  <span className="shrink-0 rounded-full border border-line px-2 py-0.5 text-[10px] text-muted">
                    {project.status === "active" ? "进行中" : project.status}
                  </span>
                </div>

                <div className="mt-4 grid grid-cols-3 gap-2 rounded-xl border border-line bg-raised/40 p-3">
                  <div>
                    <p className="text-[9px] uppercase tracking-[0.14em] text-muted">
                      任务
                    </p>
                    <p className="mt-1 text-lg font-semibold">{tasks.length}</p>
                  </div>
                  <div>
                    <p className="text-[9px] uppercase tracking-[0.14em] text-muted">
                      已完成
                    </p>
                    <p className="mt-1 text-lg font-semibold">{completed}</p>
                  </div>
                  <div>
                    <p className="text-[9px] uppercase tracking-[0.14em] text-muted">
                      最近更新
                    </p>
                    <p className="mt-1 text-[11px] text-muted">
                      {formatRelative(project.updatedAt)}
                    </p>
                  </div>
                </div>

                <div className="mt-4">
                  <div className="mb-1.5 flex justify-between text-[10px] text-muted">
                    <span>项目完成度</span>
                    <span>{progress}%</span>
                  </div>
                  <ProgressBar value={progress} color={project.accent} />
                </div>

                <div className="mt-4 flex-1 space-y-1">
                  {tasks.slice(0, 3).map((task) => (
                    <Link
                      key={task.id}
                      to={`/workspace/tasks/${task.id}`}
                      className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-[11px] transition hover:bg-white/[0.03]"
                    >
                      <span className="min-w-0 flex-1 truncate text-text">
                        {task.title}
                      </span>
                      <TaskStatusBadge status={task.status} />
                    </Link>
                  ))}
                  {tasks.length === 0 ? (
                    <p className="px-2 py-2 text-[11px] text-muted">
                      这个项目还没有任务。
                    </p>
                  ) : null}
                </div>

                <Link
                  to={`/workspace/tasks?project=${project.id}`}
                  className="mt-4 flex h-9 items-center justify-center gap-1.5 rounded-lg border border-line bg-raised text-[11px] font-medium text-text transition hover:border-[#43506a]"
                >
                  进入项目任务
                  <ArrowUpRight size={13} />
                </Link>
              </Card>
            );
          })}
        </div>
      ) : (
        <EmptyState
          icon={<FolderKanban size={18} />}
          title="还没有内容项目"
          description="创建第一个任务后，项目会自动归档任务与产物。"
          action={
            <Button variant="secondary" onClick={() => openNewTask(true)}>
              新建任务
            </Button>
          }
        />
      )}
    </div>
  );
}
