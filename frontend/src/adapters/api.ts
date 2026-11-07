import {
  AGENT_META,
  AGENT_ORDER,
  agentStatusForTask,
  agentVM,
  routeSteps,
  stepMeta,
  type StageDefinition,
} from "@/domain/agents";
import type {
  AgentId,
  AgentStatus,
  AgentVM,
  BackendStep,
  BackendTaskState,
  CreateTaskInput,
  CreatorStage,
  Decision,
  DecisionOptions,
  PendingAction,
  Profile,
  TaskBrief,
  TaskEvent,
  TaskEventKind,
  TaskOutput,
  TaskStage,
  TaskStatus,
  TaskVM,
  WorkspaceSnapshot,
} from "@/domain/types";
import { ApiNotWiredError } from "@/domain/types";
import {
  creatorStageMeta,
  normalizeCreatorStage,
  normalizeProfile,
} from "@/domain/profile";
import type { WorkspaceAdapter } from "./types";

const PROFILE_KEY = "creator-os.profile.v2";
const TITLE_CACHE_KEY = "creator-os.api-titles.v1";

interface BackendUsage {
  calls_reserved?: number;
  calls_completed?: number;
  total_tokens?: number | null;
  unknown_calls?: number;
  cost_status?: string;
}

interface BackendError {
  code?: string;
  cause_hint?: string;
  next_action?: string;
}

interface BackendTaskSummary {
  task_id?: string;
  account_id?: string;
  state?: BackendTaskState;
  row_version?: number;
  current_run_id?: string;
  brief_version?: number | null;
  head_version_id?: string | null;
  ready_version_id?: string | null;
  accepted_version_id?: string | null;
  pending_action?: string | null;
  queue_position?: number | null;
  mode?: "mock" | "live";
  usage?: BackendUsage;
  error?: BackendError | null;
}

interface BackendRequirement {
  id?: string;
  text?: string;
}

interface BackendBriefBody {
  input_mode?: string;
  objective?: string;
  audience?: string;
  platform?: string;
  format?: string;
  core_promise?: string;
  requirements?: BackendRequirement[];
  length_rule?: { minimum?: number | null; maximum?: number | null };
  route?: string[];
}

interface BackendBriefRead {
  task_id?: string;
  brief_version?: number;
  brief_hash?: string;
  confirmed?: boolean;
  brief?: BackendBriefBody;
}

interface BackendContent {
  titles?: string[];
  cover_copy?: string | null;
  segments?: { segment_id?: string; kind?: string; text?: string }[];
}

interface BackendVersion {
  version_id?: string;
  task_id?: string;
  ordinal?: number;
  parent_version_id?: string | null;
  brief_hash?: string;
  content_hash?: string;
  content?: BackendContent;
  rule_report?: unknown;
  editorial_review?: unknown;
  validation?: string;
}

interface BackendEvent {
  event_id?: string;
  seq?: number;
  run_id?: string;
  type?: string;
  step?: string;
  state?: BackendTaskState;
  summary?: string;
  created_at?: string;
}

interface SessionInfo {
  session_id: string;
  csrf_token: string;
  capabilities: string[];
}

interface Account {
  account_id: string;
  name: string;
  creator_stage: CreatorStage;
  row_version: number;
}

const BACKEND_STATES: BackendTaskState[] = [
  "DRAFT",
  "PLANNING",
  "WAITING_CONFIRMATION",
  "QUEUED",
  "GENERATING",
  "VALIDATING",
  "REVISING",
  "EXPORTING",
  "READY",
  "ACCEPTED",
  "WAITING_INPUT",
  "NEEDS_REVIEW",
  "FAILED",
  "INTERRUPTED",
  "CANCELLED",
];

function readProfile(): Profile | null {
  try {
    const raw = window.localStorage.getItem(PROFILE_KEY);
    return raw ? normalizeProfile(JSON.parse(raw) as Profile) : null;
  } catch {
    return null;
  }
}

function writeProfile(profile: Profile): void {
  try {
    window.localStorage.setItem(
      PROFILE_KEY,
      JSON.stringify(normalizeProfile(profile)),
    );
  } catch {
    /* profile persistence is best-effort */
  }
}

function readTitleCache(): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(TITLE_CACHE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function writeTitleCache(cache: Record<string, string>): void {
  try {
    window.localStorage.setItem(TITLE_CACHE_KEY, JSON.stringify(cache));
  } catch {
    /* best-effort */
  }
}

function dataOf(payload: unknown): unknown {
  if (payload && typeof payload === "object" && "data" in payload) {
    return (payload as { data: unknown }).data;
  }
  return payload;
}

function backendState(value: unknown): BackendTaskState {
  return BACKEND_STATES.includes(value as BackendTaskState)
    ? (value as BackendTaskState)
    : "DRAFT";
}

function planForState(state: BackendTaskState): {
  status: TaskStatus;
  step: BackendStep;
  pendingAction: PendingAction;
} {
  switch (state) {
    case "DRAFT":
      return { status: "pending", step: "planning", pendingAction: null };
    case "PLANNING":
      return { status: "running", step: "planning", pendingAction: null };
    case "WAITING_CONFIRMATION":
      return {
        status: "waiting_approval",
        step: "planning",
        pendingAction: "confirm_brief",
      };
    case "WAITING_INPUT":
      return { status: "pending", step: "planning", pendingAction: null };
    case "QUEUED":
      return { status: "queued", step: "planning", pendingAction: null };
    case "GENERATING":
      return { status: "running", step: "draft", pendingAction: null };
    case "VALIDATING":
      return { status: "running", step: "review", pendingAction: null };
    case "REVISING":
      return { status: "running", step: "repair", pendingAction: null };
    case "EXPORTING":
      return { status: "running", step: "export", pendingAction: null };
    case "READY":
      return {
        status: "waiting_approval",
        step: "export",
        pendingAction: "accept_content",
      };
    case "ACCEPTED":
      return { status: "completed", step: "export", pendingAction: null };
    case "NEEDS_REVIEW":
      return {
        status: "waiting_approval",
        step: "review",
        pendingAction: "accept_content",
      };
    case "FAILED":
    case "INTERRUPTED":
      return { status: "failed", step: "planning", pendingAction: null };
    case "CANCELLED":
      return { status: "cancelled", step: "planning", pendingAction: null };
  }
}

const EVENT_AGENT: Record<string, AgentId> = {
  pr_intake: "pr_analyst",
  planning: "operations_officer",
  operator: "operations_officer",
  scout: "traffic_scout",
  draft: "content_creator",
  repair: "content_creator",
  rule: "editorial_reviewer",
  review: "editorial_reviewer",
  preview: "simulated_audience",
  audience: "simulated_audience",
  analysis: "data_analyst",
  export: "operations_officer",
};

const SUMMARY_ZH: Record<string, string> = {
  "Task accepted": "任务已受理",
  "Worker claimed run": "工作进程已接管当前步骤",
  "Brief confirmed": "任务书已确认",
  "Run released: SUCCEEDED": "步骤已完成",
  "Run released: WAITING": "步骤完成，等待下一步",
  "Run released: FAILED": "步骤失败",
  "Worker lease expired": "工作进程租约过期",
};

function eventKind(event: BackendEvent): TaskEventKind {
  const type = event.type ?? "";
  const state = event.state;
  if (
    state === "FAILED" ||
    state === "INTERRUPTED" ||
    type.includes("fail") ||
    type.includes("error") ||
    type === "lease_expired"
  ) {
    return "failed";
  }
  if (state === "CANCELLED" || type.includes("cancel")) return "cancelled";
  if (state === "ACCEPTED" || type === "accept") return "completed";
  if (type === "task_created") return "created";
  if (type === "confirm" || type.includes("approval")) return "approval";
  if (type.includes("revis") || type.includes("repair") || event.step === "repair") {
    return "revision";
  }
  if (type === "run_released") return "system";
  return "stage";
}

function eventMessage(event: BackendEvent): string {
  const summary = event.summary?.trim();
  if (!summary) return stepMeta((event.step ?? "planning") as BackendStep).label;
  if (/[一-龥]/.test(summary)) return summary;
  return (
    SUMMARY_ZH[summary] ??
    `${stepMeta((event.step ?? "planning") as BackendStep).label} · ${summary}`
  );
}

function mapEvent(event: BackendEvent, index: number): TaskEvent {
  const at = event.created_at ?? new Date().toISOString();
  return {
    id: event.event_id ?? `ev-${event.seq ?? index}`,
    at,
    agentId: EVENT_AGENT[event.step ?? ""],
    kind: eventKind(event),
    message: eventMessage(event),
  };
}

function routeForEvents(events: BackendEvent[]): StageDefinition[] {
  const steps = new Set(events.map((event) => event.step));
  return routeSteps({
    commercial: steps.has("pr_intake"),
    scout: steps.has("scout"),
    preview:
      steps.has("preview") ||
      steps.has("audience") ||
      steps.has("analysis"),
  });
}

function stageIndexFor(
  state: BackendTaskState,
  step: BackendStep,
  latestStep: string | undefined,
  route: StageDefinition[],
): number {
  if (state === "READY" || state === "ACCEPTED" || step === "export") {
    return Math.max(0, route.length - 1);
  }
  const source =
    (state === "FAILED" || state === "INTERRUPTED") && latestStep
      ? latestStep
      : step;
  const normalized =
    source === "repair" ? "draft" : source === "rule" ? "review" : source;
  const index = route.findIndex((item) => item.backendStep === normalized);
  return index >= 0 ? index : 0;
}

function stageState(
  index: number,
  stageIndex: number,
  status: TaskStatus,
): TaskStage["state"] {
  if (status === "completed") return "done";
  if (index < stageIndex) return "done";
  if (index === stageIndex) {
    return status === "queued" || status === "pending" ? "todo" : "active";
  }
  return "todo";
}

function briefToVM(body: BackendBriefBody): TaskBrief {
  const minimum = body.length_rule?.minimum;
  const maximum = body.length_rule?.maximum;
  const duration =
    minimum != null || maximum != null
      ? `${minimum ?? "不限"}–${maximum ?? "不限"} 字`
      : "";
  return {
    idea: body.objective ?? "",
    audience: body.audience ?? "",
    format: body.format === "text" ? "文本" : (body.format ?? ""),
    duration,
    tone: [],
  };
}

function versionBody(version: BackendVersion): string {
  return (version.content?.segments ?? [])
    .map((segment) => segment.text?.trim() ?? "")
    .filter(Boolean)
    .join("\n\n");
}

function versionToOutput(
  version: BackendVersion,
  fallbackTitle: string,
  updatedAt: string,
): TaskOutput {
  return {
    version: version.ordinal ?? 1,
    title: version.content?.titles?.[0] ?? fallbackTitle,
    body: versionBody(version),
    updatedAt,
  };
}

function mapTask(
  item: BackendTaskSummary,
  events: BackendEvent[],
  titles: Record<string, string>,
): TaskVM {
  const state = backendState(item.state);
  const plan = planForState(state);
  const route = routeForEvents(events);
  const latestStep = [...events].reverse().find((event) => event.step)?.step;
  const stageIndex = stageIndexFor(state, plan.step, latestStep, route);
  const mappedEvents = events.map(mapEvent);
  const createdAt =
    mappedEvents[0]?.at ??
    new Date().toISOString();
  const updatedAt =
    mappedEvents[mappedEvents.length - 1]?.at ??
    createdAt;
  const id = String(item.task_id ?? "");
  const title = titles[id] ?? `任务 ${id.slice(0, 10) || "未命名"}`;

  const stages: TaskStage[] = route.map((step, index) => ({
    agentId: step.agentId,
    label: step.label,
    backendStep: step.backendStep,
    optional: step.optional,
    state: stageState(index, stageIndex, plan.status),
  }));

  return {
    id,
    title,
    projectId: "p-backend",
    agentId:
      plan.pendingAction === "confirm_brief" ||
      plan.pendingAction === "accept_content"
        ? "operations_officer"
        : route[stageIndex]?.agentId ?? "operations_officer",
    status: plan.status,
    stageIndex,
    stages,
    progress: null,
    outputId: item.head_version_id ?? null,
    output: null,
    brief: {
      idea: "",
      audience: "",
      format: "",
      duration: "",
      tone: [],
    },
    events: mappedEvents,
    revisionCount: mappedEvents.filter((event) => event.kind === "revision").length,
    createdAt,
    updatedAt,
    demo: false,
    backendState: state,
    rowVersion: item.row_version,
    briefVersion: item.brief_version ?? null,
    headVersionId: item.head_version_id ?? null,
    readyVersionId: item.ready_version_id ?? null,
    acceptedVersionId: item.accepted_version_id ?? null,
    pendingAction: plan.pendingAction,
    queuePosition: item.queue_position ?? null,
    briefConfirmed:
      state !== "DRAFT" &&
      state !== "PLANNING" &&
      state !== "WAITING_CONFIRMATION" &&
      state !== "WAITING_INPUT",
    previewRequested: route.some(
      (step) => step.backendStep === "preview" || step.backendStep === "analysis",
    ),
    usage: item.usage
      ? {
          callsReserved: item.usage.calls_reserved ?? 0,
          callsCompleted: item.usage.calls_completed ?? 0,
          totalTokens: item.usage.total_tokens ?? null,
          unknownCalls: item.usage.unknown_calls ?? 0,
          costStatus: item.usage.cost_status ?? "unpriced",
        }
      : null,
    backendError: item.error?.cause_hint ?? null,
  };
}

function deriveAgents(tasks: TaskVM[]): AgentVM[] {
  const priority: Record<AgentStatus, number> = {
    error: 5,
    review: 4,
    working: 3,
    waiting: 2,
    completed: 1,
    idle: 0,
  };
  const chosen = new Map<
    AgentId,
    { task: TaskVM; status: AgentStatus; score: number }
  >();

  for (const task of tasks) {
    const assignment = agentStatusForTask(task);
    if (!assignment) continue;
    if (
      assignment.status === "completed" &&
      Date.now() - new Date(task.updatedAt).getTime() > 60_000
    ) {
      continue;
    }
    const score = priority[assignment.status];
    const current = chosen.get(assignment.agentId);
    if (
      !current ||
      score > current.score ||
      (score === current.score && task.updatedAt > current.task.updatedAt)
    ) {
      chosen.set(assignment.agentId, {
        task,
        status: assignment.status,
        score,
      });
    }
  }

  const waiting = tasks.find((task) => task.status === "waiting_approval");
  const running = tasks.find((task) => task.status === "running");
  const queued = tasks.find((task) => task.status === "queued");
  const operatorTask = waiting ?? running ?? queued;
  if (operatorTask) {
    chosen.set("operations_officer", {
      task: operatorTask,
      status: waiting ? "review" : running ? "working" : "waiting",
      score: waiting ? priority.review : running ? priority.working : priority.waiting,
    });
  }

  return AGENT_ORDER.map((id) => {
    const current = chosen.get(id);
    return current
      ? agentVM(id, current.status, current.task)
      : agentVM(id);
  });
}

function randomKey(): string {
  return `creator-os-${crypto.randomUUID()}`;
}

export class ApiWorkspaceAdapter implements WorkspaceAdapter {
  readonly mode = "api" as const;
  private readonly base = import.meta.env.VITE_API_BASE ?? "";
  private session: SessionInfo | null = null;
  private sessionPromise: Promise<SessionInfo> | null = null;

  private async request<T>(
    path: string,
    init: RequestInit = {},
  ): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    const response = await fetch(`${this.base}${path}`, {
      ...init,
      credentials: "include",
      headers,
    });
    if (!response.ok) {
      let message = `后端返回 ${response.status}`;
      try {
        const body = (await response.json()) as {
          error?: { code?: string; cause_hint?: string; next_action?: string };
        };
        message =
          body.error?.cause_hint ??
          body.error?.code ??
          body.error?.next_action ??
          message;
      } catch {
        /* keep the status message */
      }
      throw new Error(message);
    }
    return (await response.json()) as T;
  }

  private async ensureSession(): Promise<SessionInfo> {
    if (this.session) return this.session;
    if (!this.sessionPromise) {
      this.sessionPromise = this.request<{ data: SessionInfo }>(
        "/api/v1/session",
      ).then((payload) => {
        this.session = payload.data;
        return payload.data;
      });
    }
    return this.sessionPromise;
  }

  private writeHeaders(): HeadersInit {
    return {
      "Content-Type": "application/json",
      "X-CSRF-Token": this.session?.csrf_token ?? "",
      "Idempotency-Key": randomKey(),
    };
  }

  private async ensureAccount(): Promise<Account> {
    await this.ensureSession();
    const payload = await this.request<{ data: Account[] }>(
      "/api/v1/accounts",
    );
    const existing = payload.data?.[0];
    if (existing) return existing;
    const created = await this.request<{ data: Account }>(
      "/api/v1/accounts",
      {
        method: "POST",
        headers: this.writeHeaders(),
        body: JSON.stringify({
          name: readProfile()?.workspaceName ?? "本地创作者",
          creator_stage: readProfile()?.creatorStage ?? "starting",
        }),
      },
    );
    return created.data;
  }

  async load(): Promise<WorkspaceSnapshot> {
    let tasks: TaskVM[] = [];
    let account: Account | undefined;
    try {
      await this.ensureSession();
      const accounts = await this.request<{ data: Account[] }>(
        "/api/v1/accounts",
      );
      account = accounts.data?.[0];
      if (account) {
        const titleCache = readTitleCache();
        const list = await this.request<{ data: BackendTaskSummary[] }>(
          `/api/v1/tasks?account_id=${encodeURIComponent(account.account_id)}&limit=100`,
        );
        const summaries = list.data ?? [];
        tasks = await Promise.all(
          summaries.map(async (item) => {
            const id = String(item.task_id ?? "");
            let events: BackendEvent[] = [];
            if (id) {
              try {
                const page = await this.request<{
                  data: { items?: BackendEvent[] };
                }>(`/api/v1/tasks/${encodeURIComponent(id)}/events?limit=100`);
                events = page.data?.items ?? [];
              } catch {
                /* event history is optional for rendering the task row */
              }
            }
            return mapTask(item, events, titleCache);
          }),
        );
        tasks = await Promise.all(tasks.map((task) => this.enrichTask(task)));
      }
    } catch (error) {
      throw new Error(
        `无法连接本地后端（${this.base || window.location.origin}）：${
          error instanceof Error ? error.message : "未知错误"
        }。请确认 Flask 服务与 Vite 代理已启动，或在设置中切回演示模式。`,
      );
    }

    const now = new Date().toISOString();
    const localProfile = readProfile();
    // The account stage is backend-owned; hydrate it so a second browser or a
    // cleared localStorage does not silently fall back to "starting".
    const profile =
      localProfile && account
        ? {
            ...localProfile,
            creatorStage: normalizeCreatorStage(
              account.creator_stage ?? localProfile.creatorStage,
            ),
          }
        : localProfile;
    if (
      profile &&
      localProfile &&
      profile.creatorStage !== localProfile.creatorStage
    ) {
      writeProfile(profile);
    }
    return {
      mode: "api",
      agents: deriveAgents(tasks),
      tasks,
      projects: [
        {
          id: "p-backend",
          name: "后端任务",
          description:
            "来自 /api/v1/tasks 的任务。项目、Brief 正文与版本内容尚未由后端摘要接口暴露。",
          status: "active",
          taskIds: tasks.map((task) => task.id),
          updatedAt: now,
          accent: "#83B8FF",
        },
      ],
      assets: [],
      profile,
      updatedAt: now,
    };
  }

  async saveProfile(profile: Profile): Promise<WorkspaceSnapshot> {
    const normalized = normalizeProfile(profile) ?? profile;
    writeProfile(normalized);
    try {
      await this.ensureSession();
      const accounts = await this.request<{ data: Account[] }>(
        "/api/v1/accounts",
      );
      const existing = accounts.data?.[0];
      if (existing) {
        await this.request(
          `/api/v1/accounts/${encodeURIComponent(existing.account_id)}`,
          {
            method: "PUT",
            headers: this.writeHeaders(),
            body: JSON.stringify({
              name: normalized.workspaceName || existing.name,
              creator_stage: normalized.creatorStage,
              expected_row_version: existing.row_version,
            }),
          },
        );
      } else {
        await this.request("/api/v1/accounts", {
          method: "POST",
          headers: this.writeHeaders(),
          body: JSON.stringify({
            name: normalized.workspaceName || "本地创作者",
            creator_stage: normalized.creatorStage,
          }),
        });
      }
    } catch (error) {
      throw new Error(
        `画像已保存在本地，但同步到后端失败：${
          error instanceof Error ? error.message : "未知错误"
        }`,
      );
    }
    return this.load();
  }

  async createTask(input: CreateTaskInput): Promise<WorkspaceSnapshot> {
    try {
      await this.ensureSession();
      const account = await this.ensureAccount();
      const title = input.title.trim();
      const objective = `${title}：${input.idea.trim()}`.slice(0, 1000);
      const stage = creatorStageMeta(readProfile()?.creatorStage);
      // CreateTask has no duration/format fields (format is fixed to "text"),
      // so carry them as explicit creative constraints in requirements.
      const requirementText = [
        input.idea.trim(),
        `账号阶段：${stage.label}`,
        input.format ? `内容形式：${input.format}` : "",
        input.duration ? `目标时长 / 篇幅：${input.duration}` : "",
      ]
        .filter(Boolean)
        .join("；")
        .slice(0, 1000);
      const payload = {
        account_id: account.account_id,
        input_mode: "idea",
        objective,
        audience: input.audience.trim(),
        platform: "generic",
        format: "text",
        style: (input.tone.join("、") || "清晰").slice(0, 1000),
        requirements: [
          {
            id: "r1",
            text: requirementText || objective,
          },
        ],
        materials: [],
        preview_requested: input.previewRequested,
        length_rule: { minimum: null, maximum: 20000 },
      };
      const created = await this.request<{ data: BackendTaskSummary }>(
        "/api/v1/tasks",
        {
          method: "POST",
          headers: this.writeHeaders(),
          body: JSON.stringify(payload),
        },
      );
      const id = String(created.data?.task_id ?? "");
      if (id) {
        const cache = readTitleCache();
        cache[id] = title;
        writeTitleCache(cache);
      }
      return this.load();
    } catch (error) {
      throw new Error(
        `真实后端创建任务失败：${
          error instanceof Error ? error.message : "未知错误"
        }`,
      );
    }
  }

  private async enrichTask(task: TaskVM): Promise<TaskVM> {
    let next = task;
    if (task.briefVersion != null) {
      try {
        const payload = await this.request<{ data: BackendBriefRead }>(
          `/api/v1/tasks/${encodeURIComponent(task.id)}/brief`,
        );
        if (payload.data?.brief) {
          next = {
            ...next,
            brief: briefToVM(payload.data.brief),
            briefConfirmed: Boolean(payload.data.confirmed),
          };
        }
      } catch {
        /* Brief body is optional for rendering the task row */
      }
    }
    const versionId =
      task.headVersionId ?? task.readyVersionId ?? task.acceptedVersionId;
    if (versionId) {
      try {
        const payload = await this.request<{ data: BackendVersion }>(
          `/api/v1/tasks/${encodeURIComponent(task.id)}/versions/${encodeURIComponent(versionId)}`,
        );
        if (payload.data) {
          next = {
            ...next,
            outputId: payload.data.version_id ?? next.outputId,
            output: versionToOutput(payload.data, next.title, next.updatedAt),
          };
        }
      } catch {
        /* Version body is optional for rendering the task row */
      }
    }
    return next;
  }

  private async refreshTask(taskId: string): Promise<BackendTaskSummary> {
    const payload = await this.request<{ data: BackendTaskSummary }>(
      `/api/v1/tasks/${encodeURIComponent(taskId)}`,
    );
    return payload.data;
  }

  private async readBrief(taskId: string): Promise<BackendBriefRead> {
    const payload = await this.request<{ data: BackendBriefRead }>(
      `/api/v1/tasks/${encodeURIComponent(taskId)}/brief`,
    );
    return payload.data;
  }

  private async readVersion(
    taskId: string,
    versionId: string,
  ): Promise<BackendVersion> {
    const payload = await this.request<{ data: BackendVersion }>(
      `/api/v1/tasks/${encodeURIComponent(taskId)}/versions/${encodeURIComponent(versionId)}`,
    );
    return payload.data;
  }

  private writeRequest<T>(
    path: string,
    method: "POST" | "PUT",
    body: unknown,
  ): Promise<T> {
    return this.request<T>(path, {
      method,
      headers: this.writeHeaders(),
      body: JSON.stringify(body),
    });
  }

  private async confirmBrief(
    taskId: string,
    rowVersion: number,
  ): Promise<void> {
    const brief = await this.readBrief(taskId);
    if (!brief.brief_version || !brief.brief_hash) {
      throw new Error("后端未返回 Brief 版本与哈希，无法确认。");
    }
    await this.writeRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/confirm`, "POST", {
      expected_row_version: rowVersion,
      expected_brief_version: brief.brief_version,
      brief_hash: brief.brief_hash,
    });
  }

  private async editBrief(
    taskId: string,
    rowVersion: number,
    briefVersion: number | null | undefined,
    note?: string,
  ): Promise<void> {
    const text = note?.trim();
    if (!text) {
      throw new Error("请填写修改意见后再退回 Brief。");
    }
    const brief = await this.readBrief(taskId);
    const version = brief.brief_version ?? briefVersion;
    if (!version || !brief.brief) {
      throw new Error("后端未返回可编辑的 Brief。");
    }
    const requirements = [...(brief.brief.requirements ?? [])];
    if (requirements.length >= 30) {
      throw new Error("Brief 需求条目已达上限（30），请先精简后再提交修改。");
    }
    requirements.push({ id: `rev-${version + 1}`, text: text.slice(0, 1000) });
    await this.writeRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/brief`, "PUT", {
      expected_row_version: rowVersion,
      expected_brief_version: version,
      brief: { ...brief.brief, requirements },
    });
  }

  private async acceptContent(
    taskId: string,
    rowVersion: number,
    task: BackendTaskSummary,
    editedBody?: string,
  ): Promise<void> {
    const versionId = task.ready_version_id ?? task.head_version_id;
    if (!versionId) {
      throw new Error("后端尚未提供可验收的内容版本。");
    }
    const version = await this.readVersion(taskId, versionId);
    if (!version.content_hash) {
      throw new Error("后端未返回内容哈希，无法验收。");
    }
    const draft = editedBody?.trim();
    if (draft && draft !== versionBody(version).trim()) {
      throw new ApiNotWiredError(
        "后端验收接口只接受冻结版本，不能把界面里的改写直接写入。请先用“退回修改”记录修订意见。",
      );
    }
    await this.writeRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/accept`, "POST", {
      expected_row_version: rowVersion,
      version_id: versionId,
      content_hash: version.content_hash,
    });
  }

  private async submitRevisionNote(
    taskId: string,
    task: BackendTaskSummary,
    options: DecisionOptions,
  ): Promise<void> {
    const versionId = task.ready_version_id ?? task.head_version_id;
    if (!versionId) {
      throw new Error("后端尚未提供可修订的内容版本。");
    }
    const text = [
      options.note?.trim(),
      options.editedBody?.trim()
        ? "创作者在审核界面提交了修改稿，请据此修订。"
        : "",
    ]
      .filter(Boolean)
      .join(" ")
      .slice(0, 1000);
    if (!text) {
      throw new Error("请填写修改意见后再退回内容主创。");
    }
    await this.writeRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/feedback`, "POST", {
      version_id: versionId,
      kind: "edit_request",
      text,
      platform: null,
      window_start: null,
      window_end: null,
      metrics: {},
      source_ref: null,
    });
  }

  private async cancelTask(taskId: string, rowVersion: number): Promise<void> {
    await this.writeRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/cancel`, "POST", {
      expected_row_version: rowVersion,
    });
  }

  async advanceTask(_taskId: string): Promise<WorkspaceSnapshot> {
    throw new ApiNotWiredError(
      "真实任务由后端 worker 按 QUEUED → GENERATING → VALIDATING 等状态推进，前端不能手动推进。",
    );
  }

  async decideTask(
    taskId: string,
    decision: Decision,
    options: DecisionOptions = {},
  ): Promise<WorkspaceSnapshot> {
    try {
      await this.ensureSession();
      const task = await this.refreshTask(taskId);
      const rowVersion = task.row_version;
      if (typeof rowVersion !== "number") {
        throw new Error("后端未返回任务版本号，无法执行审批。");
      }
      if (task.state === "WAITING_CONFIRMATION") {
        if (decision === "approve") {
          await this.confirmBrief(taskId, rowVersion);
        } else if (decision === "revise") {
          await this.editBrief(taskId, rowVersion, task.brief_version, options.note);
        } else {
          await this.cancelTask(taskId, rowVersion);
        }
      } else if (task.state === "READY") {
        if (decision === "approve") {
          await this.acceptContent(taskId, rowVersion, task, options.editedBody);
        } else if (decision === "revise") {
          await this.submitRevisionNote(taskId, task, options);
        } else {
          await this.cancelTask(taskId, rowVersion);
        }
      } else if (decision === "reject") {
        await this.cancelTask(taskId, rowVersion);
      } else {
        throw new Error(`任务当前状态为 ${task.state}，不在等待人工处理。`);
      }
      return this.load();
    } catch (error) {
      if (error instanceof ApiNotWiredError) throw error;
      throw new Error(
        `真实后端审批失败：${
          error instanceof Error ? error.message : "未知错误"
        }`,
      );
    }
  }
}

/** Re-exported for the settings copy and future API feature checks. */
export const API_ROLES = AGENT_ORDER.map((id) => ({
  id,
  name: AGENT_META[id].name,
  actions: AGENT_META[id].actions,
}));
