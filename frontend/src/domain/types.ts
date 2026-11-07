/**
 * The frontend mirrors the backend's seven-agent.v0.1 contract:
 * `pr_analyst`, `operations_officer`, `traffic_scout`, `content_creator`,
 * `editorial_reviewer`, `simulated_audience`, `data_analyst`.
 *
 * These IDs are backend role IDs, not UI-only labels. Do not add a frontend
 * role that does not exist in `backend/workflow/five_agent/registry.py`.
 */
export type AgentId =
  | "pr_analyst"
  | "operations_officer"
  | "traffic_scout"
  | "content_creator"
  | "editorial_reviewer"
  | "simulated_audience"
  | "data_analyst";

/** Persisted task states exposed by `birthco-local/backend/domain/states.py`. */
export type BackendTaskState =
  | "DRAFT"
  | "PLANNING"
  | "WAITING_CONFIRMATION"
  | "QUEUED"
  | "GENERATING"
  | "VALIDATING"
  | "REVISING"
  | "EXPORTING"
  | "READY"
  | "ACCEPTED"
  | "WAITING_INPUT"
  | "NEEDS_REVIEW"
  | "FAILED"
  | "INTERRUPTED"
  | "CANCELLED";

/**
 * Backend steps. `rule` and `review` both belong to the editorial reviewer;
 * `repair` is the content creator's revision loop. `preview` and `analysis`
 * are the optional audience/diagnosis run.
 */
export type BackendStep =
  | "pr_intake"
  | "planning"
  | "scout"
  | "draft"
  | "rule"
  | "review"
  | "repair"
  | "preview"
  | "analysis"
  | "export";

export type PendingAction = "confirm_brief" | "accept_content" | null;

export type AgentStatus =
  | "idle"
  | "working"
  | "waiting"
  | "review"
  | "completed"
  | "error";

export interface AgentVM {
  id: AgentId;
  name: string;
  role: string;
  description: string;
  status: AgentStatus;
  activeTaskId: string | null;
  activeTaskTitle: string | null;
  lastUpdatedAt: string;
  errorMessage: string | null;
}

export type TaskStatus =
  | "pending"
  | "queued"
  | "running"
  | "waiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

export type StageState = "done" | "active" | "todo" | "skipped";

export interface TaskStage {
  agentId: AgentId;
  label: string;
  state: StageState;
  backendStep: BackendStep;
  optional: boolean;
}

export type Decision = "approve" | "revise" | "reject";

export interface TaskOutput {
  version: number;
  title: string;
  body: string;
  updatedAt: string;
}

export type TaskEventKind =
  | "created"
  | "stage"
  | "approval"
  | "revision"
  | "completed"
  | "failed"
  | "cancelled"
  | "system";

export interface TaskEvent {
  id: string;
  at: string;
  agentId?: AgentId;
  kind: TaskEventKind;
  message: string;
}

export interface TaskBrief {
  idea: string;
  audience: string;
  format: string;
  duration: string;
  tone: string[];
}

export interface BackendUsage {
  callsReserved: number;
  callsCompleted: number;
  totalTokens: number | null;
  unknownCalls: number;
  costStatus: string;
}

export interface TaskVM {
  id: string;
  title: string;
  projectId: string;
  agentId: AgentId;
  status: TaskStatus;
  stageIndex: number;
  stages: TaskStage[];
  progress: number | null;
  outputId: string | null;
  output: TaskOutput | null;
  brief: TaskBrief;
  events: TaskEvent[];
  revisionCount: number;
  createdAt: string;
  updatedAt: string;
  demo: boolean;
  /** Raw backend state when the task came from `/api/v1/tasks`. */
  backendState: BackendTaskState | null;
  /** Backend CAS token required by confirm / accept / cancel / edit. */
  rowVersion?: number;
  briefVersion?: number | null;
  headVersionId?: string | null;
  readyVersionId?: string | null;
  acceptedVersionId?: string | null;
  pendingAction: PendingAction;
  queuePosition: number | null;
  briefConfirmed: boolean;
  previewRequested: boolean;
  usage: BackendUsage | null;
  backendError: string | null;
}

export interface ProjectVM {
  id: string;
  name: string;
  description: string;
  status: "active" | "paused" | "archived";
  taskIds: string[];
  updatedAt: string;
  accent: string;
}

export type AssetKind = "script" | "topic" | "research" | "brief";

export interface AssetVM {
  id: string;
  name: string;
  kind: AssetKind;
  projectId: string;
  taskId: string;
  createdAt: string;
  body: string;
}

export interface Profile {
  creatorName: string;
  workspaceName: string;
  industry: string;
  niche: string;
  audience: string;
  formats: string[];
  tone: string[];
  goals: string[];
  completedAt: string;
}

export interface WorkspaceSnapshot {
  mode: "demo" | "api";
  agents: AgentVM[];
  tasks: TaskVM[];
  projects: ProjectVM[];
  assets: AssetVM[];
  profile: Profile | null;
  updatedAt: string;
}

export interface CreateTaskInput {
  title: string;
  idea: string;
  audience: string;
  format: string;
  duration: string;
  tone: string[];
  projectId: string;
  /** Backend `CreateTask.preview_requested`: run the audience/diagnosis preview. */
  previewRequested: boolean;
}

export interface DecisionOptions {
  note?: string;
  editedBody?: string;
}

export class ApiNotWiredError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiNotWiredError";
  }
}
