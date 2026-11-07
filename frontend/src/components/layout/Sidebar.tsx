import { NavLink } from "react-router-dom";
import { ChevronsLeft, ChevronsRight, X } from "lucide-react";
import { cn } from "@/lib/format";
import { useWorkspace } from "@/store/workspace";
import { NAV_ITEMS } from "./nav";

function BrandMark() {
  return (
    <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-blue/30 bg-blue/10">
      <span className="text-[15px] font-bold tracking-tight text-blue">C</span>
      <span className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-cyan" />
    </span>
  );
}

export function Sidebar({
  collapsed,
  mobileOpen,
  onToggleCollapse,
  onCloseMobile,
}: {
  collapsed: boolean;
  mobileOpen: boolean;
  onToggleCollapse: () => void;
  onCloseMobile: () => void;
}) {
  const profile = useWorkspace((state) => state.snapshot?.profile);
  const mode = useWorkspace((state) => state.mode);

  return (
    <>
      <button
        type="button"
        aria-label="关闭导航"
        onClick={onCloseMobile}
        className={cn(
          "fixed inset-0 z-40 bg-ink/70 backdrop-blur-sm transition-opacity lg:hidden",
          mobileOpen ? "opacity-100" : "pointer-events-none opacity-0",
        )}
      />
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-[248px] flex-col border-r border-line bg-surface/95 transition-transform duration-300 lg:static lg:z-auto lg:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          collapsed ? "lg:w-[76px]" : "lg:w-[248px]",
        )}
      >
        <div
          className={cn(
            "flex h-16 items-center gap-3 border-b border-line/70 px-5",
            collapsed && "lg:justify-center lg:px-2",
          )}
        >
          <BrandMark />
          {!collapsed ? (
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold tracking-tight">
                Creator OS
              </p>
              <p className="truncate text-[10px] uppercase tracking-[0.18em] text-muted">
                One Creator. One AI Company.
              </p>
            </div>
          ) : null}
          <button
            type="button"
            onClick={onCloseMobile}
            aria-label="关闭导航"
            className="ml-auto rounded-lg p-1.5 text-muted hover:bg-white/5 hover:text-text lg:hidden"
          >
            <X size={18} />
          </button>
        </div>

        <nav aria-label="主导航" className="flex-1 overflow-y-auto px-3 py-4">
          <ul className="space-y-1">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    onClick={onCloseMobile}
                    title={collapsed ? item.label : undefined}
                    className={({ isActive }) =>
                      cn(
                        "group flex h-10 items-center gap-3 rounded-xl px-3 text-[13px] transition-colors",
                        collapsed && "lg:justify-center lg:px-0",
                        isActive
                          ? "bg-blue/10 text-text"
                          : "text-muted hover:bg-white/[0.04] hover:text-text",
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <Icon
                          size={17}
                          strokeWidth={1.8}
                          className={cn(
                            "shrink-0",
                            isActive ? "text-blue" : "text-muted group-hover:text-text",
                          )}
                        />
                        {!collapsed ? (
                          <span className="truncate">{item.label}</span>
                        ) : null}
                        {!collapsed && isActive ? (
                          <span className="ml-auto h-1 w-1 rounded-full bg-blue" />
                        ) : null}
                      </>
                    )}
                  </NavLink>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="border-t border-line/70 p-3">
          {!collapsed ? (
            <div className="mb-3 rounded-xl border border-line bg-raised/60 p-3">
              <p className="text-[11px] font-medium text-text">
                黑客松演示工作区
              </p>
              <p className="mt-1 text-[10px] leading-4 text-muted">
                {mode === "demo"
                  ? "演示数据 · 本地持久化 · 未连接模型"
                  : "真实接口模式 · 仅读取任务列表"}
              </p>
            </div>
          ) : null}
          <div
            className={cn(
              "flex items-center gap-2.5 rounded-xl px-2 py-1.5",
              collapsed && "lg:justify-center",
            )}
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-line bg-raised text-xs font-semibold text-blue">
              {profile?.creatorName?.slice(0, 1) || "C"}
            </span>
            {!collapsed ? (
              <div className="min-w-0">
                <p className="truncate text-xs font-medium">
                  {profile?.workspaceName || "我的 AI 公司"}
                </p>
                <p className="truncate text-[10px] text-muted">
                  {profile?.creatorName || "创作者"}
                </p>
              </div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onToggleCollapse}
            aria-label={collapsed ? "展开导航" : "折叠导航"}
            className={cn(
              "mt-2 hidden h-9 w-full items-center gap-2 rounded-lg px-2 text-[11px] text-muted transition hover:bg-white/[0.04] hover:text-text lg:flex",
              collapsed && "justify-center",
            )}
          >
            {collapsed ? <ChevronsRight size={15} /> : <ChevronsLeft size={15} />}
            {!collapsed ? <span>折叠导航</span> : null}
          </button>
        </div>
      </aside>
    </>
  );
}
