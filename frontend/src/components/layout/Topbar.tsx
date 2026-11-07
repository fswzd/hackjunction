import { Link, useLocation } from "react-router-dom";
import { Bell, Menu, Pause, Play, Plus } from "lucide-react";
import { cn } from "@/lib/format";
import { useWorkspace } from "@/store/workspace";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { pageTitle } from "./nav";

export function Topbar({ onOpenMobile }: { onOpenMobile: () => void }) {
  const location = useLocation();
  const title = pageTitle(location.pathname);
  const snapshot = useWorkspace((state) => state.snapshot);
  const mode = useWorkspace((state) => state.mode);
  const autoplay = useWorkspace((state) => state.autoplay);
  const setAutoplay = useWorkspace((state) => state.setAutoplay);
  const openNewTask = useWorkspace((state) => state.openNewTask);

  const approvals =
    snapshot?.tasks.filter((task) => task.status === "waiting_approval").length ??
    0;

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-line bg-ink/85 px-4 backdrop-blur-xl sm:px-6">
      <button
        type="button"
        onClick={onOpenMobile}
        aria-label="打开导航"
        className="rounded-lg p-2 text-muted hover:bg-white/5 hover:text-text lg:hidden"
      >
        <Menu size={18} />
      </button>

      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-text">{title.title}</p>
        <p className="hidden text-[10px] uppercase tracking-[0.18em] text-muted sm:block">
          {title.en}
        </p>
      </div>

      <div className="ml-auto flex items-center gap-2">
        {mode === "demo" ? (
          <span
            className="hidden items-center gap-2 rounded-full border border-amber/25 bg-amber/8 px-3 py-1 text-[10px] font-medium text-amber sm:inline-flex"
            title="演示数据仅保存在浏览器，本地推进不代表真实模型调用"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-amber" />
            演示模式
          </span>
        ) : (
          <span className="hidden items-center gap-2 rounded-full border border-cyan/25 bg-cyan/8 px-3 py-1 text-[10px] font-medium text-cyan sm:inline-flex">
            <span className="h-1.5 w-1.5 rounded-full bg-cyan" />
            真实接口
          </span>
        )}

        {mode === "demo" ? (
          <button
            type="button"
            onClick={() => setAutoplay(!autoplay)}
            aria-pressed={autoplay}
            className={cn(
              "hidden h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] transition md:inline-flex",
              autoplay
                ? "border-cyan/30 bg-cyan/8 text-cyan"
                : "border-line bg-raised text-muted hover:text-text",
            )}
            title={
              autoplay
                ? "演示流程自动推进，遇到审批会暂停等待你操作"
                : "演示流程不会自动推进，请使用任务详情中的“推进演示”按钮"
            }
          >
            {autoplay ? <Pause size={12} /> : <Play size={12} />}
            {autoplay ? "自动推进中" : "已暂停"}
          </button>
        ) : null}

        <Link
          to="/workspace/tasks"
          aria-label={`待审批 ${approvals} 项`}
          className="relative rounded-lg p-2 text-muted transition hover:bg-white/5 hover:text-text"
        >
          <Bell size={17} />
          {approvals > 0 ? (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-violet px-1 text-[9px] font-semibold text-ink">
              {approvals}
            </span>
          ) : null}
        </Link>

        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={14} />}
          onClick={() => openNewTask(true)}
          className="hidden sm:inline-flex"
        >
          新建任务
        </Button>

        <Avatar
          name={snapshot?.profile?.creatorName || "创作者"}
          size={32}
          accent="#B49CFF"
        />
      </div>
    </header>
  );
}
