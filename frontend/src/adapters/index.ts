import { ApiWorkspaceAdapter } from "./api";
import { MockWorkspaceAdapter } from "./mock";
import type { WorkspaceAdapter } from "./types";

export const MODE_KEY = "creator-os.mode.v2";

export function getStoredMode(): "demo" | "api" {
  try {
    const mode = window.localStorage.getItem(MODE_KEY);
    if (mode === "api" || mode === "demo") return mode;
  } catch {
    /* use the startup default when browser storage is unavailable */
  }
  return import.meta.env.VITE_DATA_MODE === "api" ? "api" : "demo";
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
