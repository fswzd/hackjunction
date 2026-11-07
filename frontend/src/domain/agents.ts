import type {
  AgentId,
  AgentStatus,
  AgentVM,
  BackendStep,
  BackendTaskState,
  TaskStage,
  TaskStatus,
  TaskVM,
} from "./types";

export interface AgentMeta {
  id: AgentId;
  name: string;
  role: string;
  /** Backend action(s) from `backend/workflow/five_agent/registry.py`. */
  actions: string[];
  description: string;
  accent: string;
  /** Isometric office position. The operations officer sits at the centre. */
  position: [number, number, number];
  capabilities: string[];
}

/**
 * UI order, not the registry dictionary order. The operations officer leads,
 * then the optional PR intake, the optional topic scout, and the required
 * draft → review pipeline. Preview and diagnosis close the loop.
 */
export const AGENT_ORDER: AgentId[] = [
  "operations_officer",
  "pr_analyst",
  "traffic_scout",
  "content_creator",
  "editorial_reviewer",
  "simulated_audience",
  "data_analyst",
];

export const AGENT_META: Record<AgentId, AgentMeta> = {
  operations_officer: {
    id: "operations_officer",
    name: "运营官",
    role: "Operations Officer",
    actions: ["prepare_brief"],
    description:
      "接住创作者目标，整理成待确认的 Brief，按确定性路由协调其余六个角色，并在任务书确认与最终验收两个节点等待人工决定。",
    accent: "#83B8FF",
    position: [0, 0, 0],
    capabilities: ["Brief 生成", "路由规划", "人工确认节点", "团队调度"],
  },
  pr_analyst: {
    id: "pr_analyst",
    name: "商单需求分析员",
    role: "PR Analyst",
    actions: ["analyze_request"],
    description:
      "在运营官之前整理品牌、产品、目标、受众、平台、风格、预算与截止时间，输出可追溯的商单分析，不自动接受任务书。",
    accent: "#B49CFF",
    position: [-3.35, 0, -1.9],
    capabilities: ["客户简报提取", "条件与冲突标注", "待问问题", "运营官交接"],
  },
  traffic_scout: {
    id: "traffic_scout",
    name: "流量捕捉者",
    role: "Traffic Scout",
    actions: ["capture_opportunities"],
    description:
      "只分析创作者明确提供的经验、读者问题与来源正文，给出带材料编号的选题机会；不联网抓取，也不预测流量。",
    accent: "#78E3DE",
    position: [0, 0, -3.8],
    capabilities: ["选题机会", "来源依据", "账号适配", "待验证假设"],
  },
  content_creator: {
    id: "content_creator",
    name: "内容主创",
    role: "Content Creator",
    actions: ["draft", "revise"],
    description:
      "依据已确认的 Brief 与冻结规则产出标题、封面文案和正文候选；修订时只改授权段落，并输出完整新稿与 change_log。",
    accent: "#6FA8FF",
    position: [3.35, 0, -1.9],
    capabilities: ["新稿创作", "定向修订", "段落编号", "来源引用"],
  },
  editorial_reviewer: {
    id: "editorial_reviewer",
    name: "审稿员",
    role: "Editorial Reviewer",
    actions: ["assess_content"],
    description:
      "用独立上下文检查结构、要求与事实依据，给出行级修改意见；不改稿、不自动接受、不发布。",
    accent: "#F0B36E",
    position: [3.35, 0, 1.9],
    capabilities: ["结构校验", "要求核对", "事实依据", "独立审稿"],
  },
  simulated_audience: {
    id: "simulated_audience",
    name: "模拟观众",
    role: "Simulated Audience",
    actions: ["read_segment"],
    description:
      "让一至六个 persona 按封面、正文顺序逐段阅读，记录继续、退出与互动事件；模拟结果不是人类样本。",
    accent: "#D0A6FF",
    position: [0, 0, 3.8],
    capabilities: ["Persona 阅读", "逐段事件", "退出位置", "预算与调用上限"],
  },
  data_analyst: {
    id: "data_analyst",
    name: "数据分析师",
    role: "Data Analyst",
    actions: ["diagnose_preview"],
    description:
      "先校验模拟观众冻结版本、事件与用量，再用程序计算覆盖率、完成率和分段退出率，模型只解释观察，不替换统计。",
    accent: "#6FD6C4",
    position: [-3.35, 0, 1.9],
    capabilities: ["覆盖率统计", "分段退出率", "统计校验", "编辑试验建议"],
  },
};

export interface StageDefinition {
  backendStep: BackendStep;
  agentId: AgentId;
  label: string;
  optional: boolean;
  description: string;
}

/**
 * Canonical backend route. The content run itself is planning → draft → rule /
 * review → export; scout, preview and diagnosis are separate optional runs.
 */
export const PIPELINE: StageDefinition[] = [
  {
    backendStep: "pr_intake",
    agentId: "pr_analyst",
    label: "商单需求分析",
    optional: true,
    description: "商单或 PR 任务先提取客户需求，再交给运营官。",
  },
  {
    backendStep: "planning",
    agentId: "operations_officer",
    label: "Brief 规划",
    optional: false,
    description: "运营官整理 Brief，等待创作者确认后才能进入生成。",
  },
  {
    backendStep: "scout",
    agentId: "traffic_scout",
    label: "选题捕捉",
    optional: true,
    description: "有材料需要分析时，由流量捕捉者给出选题机会；固定选题可跳过。",
  },
  {
    backendStep: "draft",
    agentId: "content_creator",
    label: "内容创作",
    optional: false,
    description: "内容主创依据已确认的 Brief 与冻结规则产出候选稿。",
  },
  {
    backendStep: "review",
    agentId: "editorial_reviewer",
    label: "独立审稿",
    optional: false,
    description: "审稿员独立检查结构、要求与事实依据，不能自签通过。",
  },
  {
    backendStep: "preview",
    agentId: "simulated_audience",
    label: "模拟观众试映",
    optional: true,
    description: "按 persona 逐段模拟阅读，记录事件与退出位置。",
  },
  {
    backendStep: "analysis",
    agentId: "data_analyst",
    label: "数据诊断",
    optional: true,
    description: "程序统计加模型解释，给出可选择的编辑试验建议。",
  },
];

export const STAGE_DEFINITION = PIPELINE;

const STEP_BY_ID = new Map(PIPELINE.map((step) => [step.backendStep, step]));

export interface RouteOptions {
  commercial?: boolean;
  scout?: boolean;
  preview?: boolean;
}

/** Build the visible task route; optional runs are only added when requested. */
export function routeSteps({
  commercial = false,
  scout = true,
  preview = false,
}: RouteOptions = {}): StageDefinition[] {
  const route: StageDefinition[] = [];
  if (commercial) route.push(STEP_BY_ID.get("pr_intake")!);
  route.push(STEP_BY_ID.get("planning")!);
  if (scout) route.push(STEP_BY_ID.get("scout")!);
  route.push(STEP_BY_ID.get("draft")!, STEP_BY_ID.get("review")!);
  if (preview) route.push(STEP_BY_ID.get("preview")!, STEP_BY_ID.get("analysis")!);
  return route;
}

export function stepMeta(step: BackendStep): StageDefinition {
  return STEP_BY_ID.get(step) ?? STEP_BY_ID.get("planning")!;
}

/**
 * Map a content-run step to the persisted TaskState it runs under. PR intake,
 * scout, preview and analysis are separate runs, so they do not have a single
 * task state of their own.
 */
export function stateForBackendStep(
  step: BackendStep,
): BackendTaskState | null {
  switch (step) {
    case "planning":
      return "PLANNING";
    case "draft":
      return "GENERATING";
    case "rule":
    case "review":
      return "VALIDATING";
    case "repair":
      return "REVISING";
    case "export":
      return "EXPORTING";
    default:
      return null;
  }
}

export const BACKEND_STATE_META: Record<
  BackendTaskState,
  { label: string; color: string }
> = {
  DRAFT: { label: "草稿", color: "#7C869B" },
  PLANNING: { label: "Brief 规划", color: "#83B8FF" },
  WAITING_CONFIRMATION: { label: "待确认任务书", color: "#B49CFF" },
  WAITING_INPUT: { label: "待补充输入", color: "#F0B36E" },
  QUEUED: { label: "排队中", color: "#A1A9BB" },
  GENERATING: { label: "内容生成", color: "#78E3DE" },
  VALIDATING: { label: "校验与审稿", color: "#F0B36E" },
  REVISING: { label: "修订中", color: "#78E3DE" },
  EXPORTING: { label: "导出中", color: "#83B8FF" },
  READY: { label: "待人工验收", color: "#B49CFF" },
  ACCEPTED: { label: "已验收", color: "#8FD6A8" },
  NEEDS_REVIEW: { label: "需人工审阅", color: "#F0B36E" },
  FAILED: { label: "失败", color: "#F08A8A" },
  INTERRUPTED: { label: "中断", color: "#F08A8A" },
  CANCELLED: { label: "已取消", color: "#7C869B" },
};

export const STATUS_META: Record<
  AgentStatus,
  { label: string; color: string; description: string }
> = {
  idle: { label: "空闲", color: "#7C869B", description: "当前没有正在执行的任务" },
  working: { label: "工作中", color: "#78E3DE", description: "正在处理任务" },
  waiting: { label: "等待依赖", color: "#F0B36E", description: "等待上游交付" },
  review: { label: "待审批", color: "#B49CFF", description: "等待你的决定" },
  completed: { label: "已完成", color: "#8FD6A8", description: "刚刚完成一项任务" },
  error: { label: "异常", color: "#F08A8A", description: "任务执行失败" },
};

export const TASK_STATUS_META: Record<
  TaskStatus,
  { label: string; color: string }
> = {
  pending: { label: "待处理", color: "#7C869B" },
  queued: { label: "排队中", color: "#A1A9BB" },
  running: { label: "执行中", color: "#78E3DE" },
  waiting_approval: { label: "待审批", color: "#B49CFF" },
  completed: { label: "已完成", color: "#8FD6A8" },
  failed: { label: "失败", color: "#F08A8A" },
  cancelled: { label: "已取消", color: "#7C869B" },
};

export function agentById(id: AgentId): AgentMeta {
  return AGENT_META[id];
}

export function currentStage(task: TaskVM): TaskStage | undefined {
  return task.stages[task.stageIndex] ?? task.stages[task.stages.length - 1];
}

/** The agent that owns the current work, including the two human gates. */
export function agentForTask(task: TaskVM): AgentId {
  if (task.pendingAction === "confirm_brief") return "operations_officer";
  if (task.pendingAction === "accept_content") return "operations_officer";
  return currentStage(task)?.agentId ?? task.agentId;
}

export function progressForTask(task: TaskVM): number {
  if (task.status === "completed") return 100;
  if (task.status === "waiting_approval") return 100;
  if (!task.stages.length) return 0;
  return Math.round(((task.stageIndex + 1) / task.stages.length) * 100);
}

/** Human gates happen between stages, so they get explicit labels. */
export function stageLabelForTask(task: TaskVM): string {
  if (task.status === "waiting_approval") {
    return task.pendingAction === "confirm_brief"
      ? "等待确认 Brief"
      : "等待内容验收";
  }
  return currentStage(task)?.label ?? "等待审批";
}

/** Kept for callers that only know a stage list and index. */
export function stageAgent(stages: TaskStage[], stageIndex: number): AgentId {
  return stages[Math.min(stageIndex, stages.length - 1)]?.agentId ?? "operations_officer";
}

/** Used by the mock adapter to keep employee status in sync with one snapshot. */
export function agentStatusForTask(
  task: TaskVM,
): { status: AgentStatus; agentId: AgentId } | null {
  const agentId = agentForTask(task);
  if (task.status === "running") return { status: "working", agentId };
  if (task.status === "queued") return { status: "waiting", agentId };
  if (task.status === "waiting_approval") return { status: "review", agentId };
  if (task.status === "failed") return { status: "error", agentId };
  if (task.status === "completed") return { status: "completed", agentId };
  return null;
}

export function agentVM(
  id: AgentId,
  status: AgentStatus = "idle",
  task?: TaskVM,
): AgentVM {
  const meta = AGENT_META[id];
  return {
    id,
    name: meta.name,
    role: meta.role,
    description: meta.description,
    status,
    activeTaskId: task?.id ?? null,
    activeTaskTitle: task?.title ?? null,
    lastUpdatedAt: task?.updatedAt ?? new Date().toISOString(),
    errorMessage:
      status === "error"
        ? task?.backendError ??
          task?.events.find((event) => event.kind === "failed")?.message ??
          "任务执行失败"
        : null,
  };
}
