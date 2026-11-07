import { useEffect, useState } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { useWorkspace } from "@/store/workspace";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { Toast } from "./Toast";
import { AgentDetailsPanel } from "@/components/agents/AgentDetailsPanel";
import { NewTaskDialog } from "@/components/tasks/NewTaskDialog";
import { ImmersiveOverlay } from "@/components/headquarters/ImmersiveOverlay";

export function AppShell() {
  const status = useWorkspace((state) => state.status);
  const snapshot = useWorkspace((state) => state.snapshot);
  const mode = useWorkspace((state) => state.mode);
  const autoplay = useWorkspace((state) => state.autoplay);
  const advanceOldest = useWorkspace((state) => state.advanceOldest);
  const refresh = useWorkspace((state) => state.refresh);
  const selectedAgentId = useWorkspace((state) => state.selectedAgentId);
  const immersive = useWorkspace((state) => state.immersive);

  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    if (mode !== "demo" || !autoplay) return;
    const timer = window.setInterval(() => {
      void advanceOldest();
    }, 4200);
    return () => window.clearInterval(timer);
  }, [mode, autoplay, advanceOldest]);

  // Real backend tasks advance in a worker; poll while the tab is visible so
  // the 2D pages, agent statuses and the 3D headquarters stay in sync.
  useEffect(() => {
    if (mode !== "api") return;
    let disposed = false;
    let inFlight = false;
    const tick = async () => {
      if (disposed || inFlight || document.visibilityState !== "visible") return;
      inFlight = true;
      try {
        await refresh();
      } finally {
        inFlight = false;
      }
    };
    const timer = window.setInterval(() => void tick(), 10_000);
    const onFocus = () => void tick();
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [mode, refresh]);

  if (status === "ready" && snapshot && !snapshot.profile) {
    return <Navigate to="/onboarding" replace />;
  }

  if (!snapshot) return null;

  return (
    <div className="flex min-h-screen bg-ink">
      <Sidebar
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onToggleCollapse={() => setCollapsed((value) => !value)}
        onCloseMobile={() => setMobileOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenMobile={() => setMobileOpen(true)} />
        <main className="inner-grid flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-[1320px]">
            <Outlet />
          </div>
        </main>
      </div>
      {selectedAgentId && !immersive ? <AgentDetailsPanel /> : null}
      <NewTaskDialog />
      <Toast />
      <ImmersiveOverlay />
    </div>
  );
}
