import type {
  CreateTaskInput,
  Decision,
  DecisionOptions,
  Profile,
  WorkspaceSnapshot,
} from "@/domain/types";

export interface WorkspaceAdapter {
  readonly mode: "demo" | "api";
  load(): Promise<WorkspaceSnapshot>;
  saveProfile(profile: Profile): Promise<WorkspaceSnapshot>;
  createTask(input: CreateTaskInput): Promise<WorkspaceSnapshot>;
  advanceTask(taskId: string): Promise<WorkspaceSnapshot>;
  decideTask(
    taskId: string,
    decision: Decision,
    options?: DecisionOptions,
  ): Promise<WorkspaceSnapshot>;
  reset?(): Promise<WorkspaceSnapshot>;
}
