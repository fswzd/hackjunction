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
  TaskContinuation,
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
  refreshFailed: boolean;
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
  createTask: (input: CreateTaskInput) => Promise<{ taskId: string } | { error: string }>;
  advanceTask: (taskId: string) => Promise<void>;
  advanceOldest: () => Promise<void>;
  decideTask: (
    taskId: string,
    decision: Decision,
    options?: DecisionOptions,
  ) => Promise<string | null>;
  continueTask: (taskId: string, action: TaskContinuation) => Promise<string | null>;
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
// 快照世代号：写操作/模式切换开始时递增；任何在途读取落地前校验世代未变，
// 否则丢弃过期快照（修复：10s 轮询旧快照覆盖刚写入的结果、模式切换后旧
// Promise 回填串扰——两处同根）。
let snapshotEpoch = 0;

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
  refreshFailed: false,
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
      const epoch = snapshotEpoch;
      try {
        const snapshot = await adapter.load();
        if (epoch === snapshotEpoch) set({ status: "ready", snapshot, mode });
      } catch (error) {
        if (epoch === snapshotEpoch) set({ status: "error", error: errorMessage(error), mode });
      }
    })();
    return initPromise;
  },

  reload: async () => {
    const epoch = snapshotEpoch;
    try {
      const snapshot = await adapter.load();
      if (epoch === snapshotEpoch) set({ status: "ready", snapshot, error: null, refreshFailed: false });
    } catch (error) {
      if (epoch === snapshotEpoch) set({ status: "error", error: errorMessage(error) });
    }
  },

  refresh: async () => {
    if (get().mode !== "api" || get().status !== "ready") return;
    const epoch = snapshotEpoch;
    try {
      const snapshot = await adapter.load();
      if (epoch === snapshotEpoch) set({ snapshot, refreshFailed: false });
    } catch {
      if (epoch === snapshotEpoch) set({ refreshFailed: true });
    }
  },

  setMode: async (mode) => {
    if (mode === get().mode) return;
    snapshotEpoch += 1; // 旧模式在途读取全部作废
    const epoch = snapshotEpoch;
    setStoredMode(mode);
    adapter = createAdapter(mode);
    set({ status: "loading", mode, error: null, refreshFailed: false, selectedAgentId: null });
    try {
      const snapshot = await adapter.load();
      if (epoch !== snapshotEpoch) return;
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
      if (epoch === snapshotEpoch) set({ status: "error", error: errorMessage(error) });
    }
  },

  completeOnboarding: async (profile) => {
    snapshotEpoch += 1;
    const epoch = snapshotEpoch;
    const snapshot = await adapter.saveProfile(profile);
    if (epoch === snapshotEpoch) {
      snapshotEpoch += 1;
      set({ snapshot, status: "ready", refreshFailed: false });
    }
  },

  createTask: async (input) => {
    snapshotEpoch += 1;
    const epoch = snapshotEpoch;
    try {
      const { snapshot, taskId } = await adapter.createTask(input);
      if (epoch !== snapshotEpoch) return { error: "工作台状态已变化，请刷新任务列表核对。" };
      snapshotEpoch += 1;
      set({
        snapshot,
        toast: {
          id: ++toastSeq,
          message: "任务已创建，AI 团队开始协作。",
          tone: "success",
        },
      });
      return { taskId };
    } catch (error) {
      void get().refresh();
      return { error: errorMessage(error) };
    }
  },

  advanceTask: async (taskId) => {
    snapshotEpoch += 1;
    const epoch = snapshotEpoch;
    try {
      const snapshot = await adapter.advanceTask(taskId);
      if (epoch === snapshotEpoch) set({ snapshot });
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
    snapshotEpoch += 1;
    const epoch = snapshotEpoch;
    try {
      const snapshot = await adapter.advanceTask(task.id);
      if (epoch === snapshotEpoch) set({ snapshot });
    } catch {
      /* autoplay failures are silent; the manual controls surface errors */
    }
  },

  decideTask: async (taskId, decision, options) => {
    const pendingAction = get().snapshot?.tasks.find(
      (task) => task.id === taskId,
    )?.pendingAction;
    const apiMode = get().mode === "api";
    snapshotEpoch += 1;
    const epoch = snapshotEpoch;
    try {
      const snapshot = await adapter.decideTask(taskId, decision, options);
      if (epoch !== snapshotEpoch) return "工作台状态已变化，请查看任务当前状态。";
      snapshotEpoch += 1;
      const briefGate = pendingAction === "confirm_brief";
      set({
        snapshot,
        refreshFailed: false,
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
                    ? "已退回内容主创：后端已启动定向修订运行，请等待新版本。"
                    : "已退回内容主创，进行定向修订。"
                : briefGate
                  ? "已取消本次任务。"
                  : "已拒绝并取消本次任务。",
          tone: decision === "approve" ? "success" : "info",
        },
      });
      return null;
    } catch (error) {
      void get().refresh();
      return errorMessage(error);
    }
  },

  continueTask: async (taskId, action) => {
    const activeAdapter = adapter;
    if (!activeAdapter.continueTask) return "请在连接后端的工作台中操作。";
    const epoch = ++snapshotEpoch;
    try {
      const snapshot = await activeAdapter.continueTask(taskId, action);
      if (epoch !== snapshotEpoch) return "工作台状态已变化，请查看任务当前状态。";
      snapshotEpoch += 1;
      set({ snapshot, refreshFailed: false });
      get().showToast(action.type === "supply_input" ? "资料已提交，任务已排队。" : "已从保存的进度继续。", "success");
      return null;
    } catch (error) {
      void get().refresh();
      return errorMessage(error);
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
    snapshotEpoch += 1;
    const epoch = snapshotEpoch;
    const snapshot = await adapter.reset();
    if (epoch !== snapshotEpoch) return;
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
