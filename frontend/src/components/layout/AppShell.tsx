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
  const selectedAgentId = useWorkspace((state) => state.selectedAgentId);

  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    if (mode !== "demo" || !autoplay) return;
    const timer = window.setInterval(() => {
      void advanceOldest();
    }, 4200);
    return () => window.clearInterval(timer);
  }, [mode, autoplay, advanceOldest]);

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
      {selectedAgentId ? <AgentDetailsPanel /> : null}
      <NewTaskDialog />
      <Toast />
      <ImmersiveOverlay />
    </div>
  );
}
