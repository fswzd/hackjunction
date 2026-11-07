import { ApiWorkspaceAdapter } from "./api";
import { MockWorkspaceAdapter } from "./mock";
import type { WorkspaceAdapter } from "./types";

export const MODE_KEY = "creator-os.mode.v2";

export function getStoredMode(): "demo" | "api" {
  if (import.meta.env.VITE_DATA_MODE === "api") return "api";
  if (import.meta.env.VITE_DATA_MODE === "demo") return "demo";
  try {
    return window.localStorage.getItem(MODE_KEY) === "api" ? "api" : "demo";
  } catch {
    return "demo";
  }
}

export function setStoredMode(mode: "demo" | "api"): void {
  try {
    window.localStorage.setItem(MODE_KEY, mode);
  } catch {
    /* best-effort */
  }
}

export function createAdapter(mode: "demo" | "api"): WorkspaceAdapter {
  return mode === "api" ? new ApiWorkspaceAdapter() : new MockWorkspaceAdapter();
}

export type { WorkspaceAdapter };
