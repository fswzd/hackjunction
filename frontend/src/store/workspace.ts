import { create } from "zustand";
import {
  createAdapter,
  getStoredMode,
  setStoredMode,
  type WorkspaceAdapter,
} from "@/adapters";
import { ApiNotWiredError } from "@/domain/types";
import type {
  AgentId,
  CreateTaskInput,
  Decision,
  DecisionOptions,
  Profile,
  WorkspaceSnapshot,
} from "@/domain/types";

const AUTOPLAY_KEY = "creator-os.autoplay.v1";

type ToastTone = "info" | "success" | "error";

interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
}

interface WorkspaceState {
  status: "loading" | "ready" | "error";
  error: string | null;
  snapshot: WorkspaceSnapshot | null;
  mode: "demo" | "api";
  autoplay: boolean;
  selectedAgentId: AgentId | null;
  panelOpen: boolean;
  newTaskOpen: boolean;
  immersive: boolean;
  toast: Toast | null;
  init: () => Promise<void>;
  reload: () => Promise<void>;
  /** Silent API-mode refresh: keeps the last good snapshot on transient errors. */
  refresh: () => Promise<void>;
  setMode: (mode: "demo" | "api") => Promise<void>;
  completeOnboarding: (profile: Profile) => Promise<void>;
  createTask: (input: CreateTaskInput) => Promise<void>;
  advanceTask: (taskId: string) => Promise<void>;
  advanceOldest: () => Promise<void>;
  decideTask: (
    taskId: string,
    decision: Decision,
    options?: DecisionOptions,
  ) => Promise<void>;
  selectAgent: (agentId: AgentId | null) => void;
  openNewTask: (open: boolean) => void;
  setImmersive: (open: boolean) => void;
  setAutoplay: (enabled: boolean) => void;
  resetDemo: () => Promise<void>;
  showToast: (message: string, tone?: ToastTone) => void;
  dismissToast: () => void;
}

let adapter: WorkspaceAdapter = createAdapter(getStoredMode());
let initPromise: Promise<void> | null = null;
let toastSeq = 0;

function readAutoplay(): boolean {
  try {
    const raw = window.localStorage.getItem(AUTOPLAY_KEY);
    return raw === null ? true : raw === "true";
  } catch {
    return true;
  }
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiNotWiredError) return error.message;
  if (error instanceof Error) return error.message;
  return "发生未知错误，请重试。";
}

export const useWorkspace = create<WorkspaceState>((set, get) => ({
  status: "loading",
  error: null,
  snapshot: null,
  mode: getStoredMode(),
  autoplay: readAutoplay(),
  selectedAgentId: null,
  panelOpen: false,
  newTaskOpen: false,
  immersive: false,
  toast: null,

  init: async () => {
    if (initPromise) return initPromise;
    initPromise = (async () => {
      set({ status: "loading", error: null });
      const mode = getStoredMode();
      adapter = createAdapter(mode);
      try {
        const snapshot = await adapter.load();
        set({ status: "ready", snapshot, mode });
      } catch (error) {
        set({ status: "error", error: errorMessage(error), mode });
      }
    })();
    return initPromise;
  },

  reload: async () => {
    try {
      const snapshot = await adapter.load();
      set({ status: "ready", snapshot, error: null });
    } catch (error) {
      set({ status: "error", error: errorMessage(error) });
    }
  },

  refresh: async () => {
    if (get().mode !== "api") return;
    try {
      const snapshot = await adapter.load();
      set({ snapshot });
    } catch {
      /* polling must not replace a usable workspace with an error screen */
    }
  },

  setMode: async (mode) => {
    if (mode === get().mode) return;
    setStoredMode(mode);
    adapter = createAdapter(mode);
    set({ status: "loading", mode, error: null, selectedAgentId: null });
    try {
      const snapshot = await adapter.load();
      set({
        status: "ready",
        snapshot,
        toast: {
          id: ++toastSeq,
          message:
            mode === "demo"
              ? "已切换到演示模式，所有数据仅保存在本地浏览器。"
              : "已切换到真实接口模式：读取/创建任务，Brief 确认、内容验收、取消与修订意见均已接后端。",
          tone: "info",
        },
      });
    } catch (error) {
      set({ status: "error", error: errorMessage(error) });
    }
  },

  completeOnboarding: async (profile) => {
    const snapshot = await adapter.saveProfile(profile);
    set({ snapshot, status: "ready" });
  },

  createTask: async (input) => {
    try {
      const snapshot = await adapter.createTask(input);
      set({
        snapshot,
        toast: {
          id: ++toastSeq,
          message: "任务已创建，AI 团队开始协作。",
          tone: "success",
        },
      });
    } catch (error) {
      get().showToast(errorMessage(error), "error");
    }
  },

  advanceTask: async (taskId) => {
    try {
      const snapshot = await adapter.advanceTask(taskId);
      set({ snapshot });
    } catch (error) {
      get().showToast(errorMessage(error), "error");
    }
  },

  advanceOldest: async () => {
    if (get().mode !== "demo") return;
    const running = get()
      .snapshot?.tasks.filter((task) => task.status === "running")
      .sort((a, b) => a.updatedAt.localeCompare(b.updatedAt));
    const task = running?.[0];
    if (!task) return;
    try {
      const snapshot = await adapter.advanceTask(task.id);
      set({ snapshot });
    } catch {
      /* autoplay failures are silent; the manual controls surface errors */
    }
  },

  decideTask: async (taskId, decision, options) => {
    const pendingAction = get().snapshot?.tasks.find(
      (task) => task.id === taskId,
    )?.pendingAction;
    const apiMode = get().mode === "api";
    try {
      const snapshot = await adapter.decideTask(taskId, decision, options);
      const briefGate = pendingAction === "confirm_brief";
      set({
        snapshot,
        toast: {
          id: ++toastSeq,
          message:
            decision === "approve"
              ? briefGate
                ? "Brief 已确认，任务已进入队列。"
                : "已验收，内容已保存到项目资产。"
              : decision === "revise"
                ? briefGate
                  ? apiMode
                    ? "已保存新的 Brief 版本，请再次确认或继续修改。"
                    : "已退回运营官，重新规划 Brief。"
                  : apiMode
                    ? "修订意见已记录为 feedback（edit_request）；后端修订运行尚未接入，任务仍保持待验收。"
                    : "已退回内容主创，进行定向修订。"
                : briefGate
                  ? "已取消本次任务。"
                  : "已拒绝并取消本次任务。",
          tone: decision === "approve" ? "success" : "info",
        },
      });
    } catch (error) {
      get().showToast(errorMessage(error), "error");
    }
  },

  selectAgent: (agentId) =>
    set({ selectedAgentId: agentId, panelOpen: Boolean(agentId) }),

  openNewTask: (open) => set({ newTaskOpen: open }),

  setImmersive: (open) => set({ immersive: open }),

  setAutoplay: (enabled) => {
    try {
      window.localStorage.setItem(AUTOPLAY_KEY, String(enabled));
    } catch {
      /* best-effort */
    }
    set({ autoplay: enabled });
  },

  resetDemo: async () => {
    if (!adapter.reset) return;
    const snapshot = await adapter.reset();
    set({
      snapshot,
      selectedAgentId: null,
      panelOpen: false,
      toast: {
        id: ++toastSeq,
        message: "演示数据已重置。",
        tone: "info",
      },
    });
  },

  showToast: (message, tone = "info") =>
    set({ toast: { id: ++toastSeq, message, tone } }),

  dismissToast: () => set({ toast: null }),
}));
