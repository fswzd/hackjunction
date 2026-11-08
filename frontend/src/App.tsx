import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AlertTriangle, Loader2 } from "lucide-react";
import { useWorkspace } from "@/store/workspace";
import { Button } from "@/components/ui/Button";
import { AppShell } from "@/components/layout/AppShell";
import { Landing } from "@/pages/Landing";
import { Onboarding } from "@/pages/Onboarding";
import { NotFound } from "@/pages/NotFound";

const Overview = lazy(() => import("@/pages/Overview").then((m) => ({ default: m.Overview })));
const Workforce = lazy(() => import("@/pages/Workforce").then((m) => ({ default: m.Workforce })));
const Projects = lazy(() => import("@/pages/Projects").then((m) => ({ default: m.Projects })));
const Tasks = lazy(() => import("@/pages/Tasks").then((m) => ({ default: m.Tasks })));
const TaskDetail = lazy(() => import("@/pages/TaskDetail").then((m) => ({ default: m.TaskDetail })));
const CalendarPage = lazy(() => import("@/pages/Calendar").then((m) => ({ default: m.CalendarPage })));
const Assets = lazy(() => import("@/pages/Assets").then((m) => ({ default: m.Assets })));
const Analytics = lazy(() => import("@/pages/Analytics").then((m) => ({ default: m.Analytics })));
const Settings = lazy(() => import("@/pages/Settings").then((m) => ({ default: m.Settings })));

function Splash() {
  return (
    <div className="inner-grid flex min-h-screen flex-col items-center justify-center gap-4 bg-ink">
      <div className="relative flex h-12 w-12 items-center justify-center rounded-2xl border border-blue/30 bg-blue/10">
        <span className="text-lg font-bold text-blue">幕</span>
        <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-cyan" />
      </div>
      <div className="flex items-center gap-2 text-xs text-muted">
        <Loader2 size={14} className="animate-spin" />
        正在打开你的内容工作室…
      </div>
    </div>
  );
}

function ErrorScreen() {
  const error = useWorkspace((state) => state.error);
  const reload = useWorkspace((state) => state.reload);
  const setMode = useWorkspace((state) => state.setMode);

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink p-6">
      <div className="w-full max-w-lg rounded-2xl border border-line bg-surface p-6">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-red/30 bg-red/10 text-red">
            <AlertTriangle size={18} />
          </span>
          <div>
            <h1 className="text-base font-semibold">数据没有加载成功</h1>
            <p className="text-[11px] text-muted">众幕 AI · workspace</p>
          </div>
        </div>
        <p className="mt-4 rounded-xl border border-line bg-raised p-3 text-xs leading-6 text-muted">
          {error ?? "未知错误"}
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => void reload()}>
            重试
          </Button>
          <Button variant="primary" onClick={() => void setMode("demo")}>
            切换到演示模式
          </Button>
        </div>
        <p className="mt-4 text-[10px] leading-5 text-muted">
          演示模式不依赖后端，所有状态保存在浏览器本地，并在界面上明确标注。
        </p>
      </div>
    </div>
  );
}

export default function App() {
  const status = useWorkspace((state) => state.status);
  const init = useWorkspace((state) => state.init);
  const location = useLocation();

  useEffect(() => {
    void init();
  }, [init]);

  // The public landing page stays available even when the optional local API
  // is unreachable; only the workspace routes need workspace data.
  if (location.pathname === "/") return <Landing />;

  if (status === "loading") return <Splash />;
  if (status === "error") return <ErrorScreen />;

  return (
    <Suspense fallback={<Splash />}>
    <Routes>
      <Route path="/onboarding" element={<Onboarding />} />
      <Route path="/workspace" element={<AppShell />}>
        <Route index element={<Navigate to="overview" replace />} />
        <Route path="overview" element={<Overview />} />
        <Route path="workforce" element={<Workforce />} />
        <Route path="projects" element={<Projects />} />
        <Route path="tasks" element={<Tasks />} />
        <Route path="tasks/:taskId" element={<TaskDetail />} />
        <Route path="calendar" element={<CalendarPage />} />
        <Route path="assets" element={<Assets />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
    </Suspense>
  );
}
