import type {
  CreateTaskInput,
  Decision,
  DecisionOptions,
  Profile,
  TaskContinuation,
  WorkspaceSnapshot,
} from "@/domain/types";

export interface WorkspaceAdapter {
  readonly mode: "demo" | "api";
  load(): Promise<WorkspaceSnapshot>;
  saveProfile(profile: Profile): Promise<WorkspaceSnapshot>;
  createTask(input: CreateTaskInput): Promise<{ taskId: string; snapshot: WorkspaceSnapshot }>;
  advanceTask(taskId: string): Promise<WorkspaceSnapshot>;
  decideTask(
    taskId: string,
    decision: Decision,
    options?: DecisionOptions,
  ): Promise<WorkspaceSnapshot>;
  continueTask?(taskId: string, action: TaskContinuation): Promise<WorkspaceSnapshot>;
  reset?(): Promise<WorkspaceSnapshot>;
}
