import {
  AGENT_META,
  AGENT_ORDER,
  agentStatusForTask,
  agentVM,
  routeSteps,
  stateForBackendStep,
  type StageDefinition,
} from "@/domain/agents";
import type {
  AgentId,
  AgentStatus,
  AgentVM,
  AssetVM,
  BackendStep,
  BackendTaskState,
  CreateTaskInput,
  Decision,
  DecisionOptions,
  PendingAction,
  Profile,
  ProjectVM,
  TaskEvent,
  TaskStage,
  TaskStatus,
  TaskVM,
  WorkspaceSnapshot,
} from "@/domain/types";
import type { WorkspaceAdapter } from "./types";

/** v3 invalidates snapshots produced by the old four-role model. */
const SNAPSHOT_KEY = "creator-os.snapshot.v3";

function iso(offsetMinutes = 0): string {
  return new Date(Date.now() + offsetMinutes * 60_000).toISOString();
}

function makeId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 6)}`;
}

function routeToStages(route: StageDefinition[]): TaskStage[] {
  return route.map((step) => ({
    agentId: step.agentId,
    label: step.label,
    backendStep: step.backendStep,
    optional: step.optional,
    state: "todo",
  }));
}

function markStages(
  stages: TaskStage[],
  stageIndex: number,
  status: TaskStatus,
): TaskStage[] {
  return stages.map((stage, index) => ({
    ...stage,
    state:
      status === "completed"
        ? "done"
        : index < stageIndex
          ? "done"
          : index === stageIndex
            ? status === "queued" || status === "pending"
              ? "todo"
              : "active"
            : "todo",
  }));
}

function event(
  kind: TaskEvent["kind"],
  message: string,
  agentId?: AgentId,
  at = iso(),
): TaskEvent {
  return { id: makeId("ev"), at, kind, message, agentId };
}

function buildOutput(task: TaskVM): TaskVM["output"] {
  const { idea, audience, format, duration } = task.brief;
  const body = [
    `【标题】${task.title}`,
    "",
    "【开场 0–5s】",
    `${audience || "正在刷到这条内容的人"}，先别急着划走——${idea || "这件事可能和你有关系"}。`,
    "",
    "【主体 5–45s】",
    "第一，先把问题说清楚：读者真正卡住的地方是什么，而不是我们最想讲的地方。",
    `第二，给出一个今天就能试的具体动作，让内容与「${audience || "目标受众"}」建立关系。`,
    "第三，用一个真实的限制条件收束，避免把结果说得比事实更满。",
    "",
    `【收尾 45–${duration.replace(/[^0-9]/g, "") || "60"}s】`,
    "如果你也遇到类似的问题，先试一次，再把结果带回来。下一次，我们沿着你的反馈继续改。",
    "",
    `—— 由众幕 AI · ${AGENT_META.content_creator.name}生成的 ${format || "内容"}候选稿`,
  ].join("\n");
  return {
    version: task.output?.version ?? 1,
    title: task.title,
    body,
    updatedAt: iso(),
  };
}

/**
 * Employee status is a projection of backend-shaped tasks. Only one task per
 * employee is surfaced; errors and human gates outrank ordinary work.
 */
function derivedAgents(tasks: TaskVM[], previous?: AgentVM[]): AgentVM[] {
  const previousById = new Map(previous?.map((agent) => [agent.id, agent]));
  const priority: Record<AgentStatus, number> = {
    error: 5,
    review: 4,
    working: 3,
    waiting: 2,
    completed: 1,
    idle: 0,
  };
  const assigned = new Map<
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
    const current = assigned.get(assignment.agentId);
    if (
      !current ||
      score > current.score ||
      (score === current.score && task.updatedAt > current.task.updatedAt)
    ) {
      assigned.set(assignment.agentId, {
        task,
        status: assignment.status,
        score,
      });
    }
  }

  // The operations officer is always aware of the queue, even when another
  // employee owns the current step.
  const waiting = tasks
    .filter((task) => task.status === "waiting_approval")
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  const running = tasks
    .filter((task) => task.status === "running")
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  const queued = tasks
    .filter((task) => task.status === "queued")
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  if (waiting.length) {
    assigned.set("operations_officer", {
      task: waiting[0],
      status: "review",
      score: priority.review,
    });
  } else if (running.length) {
    assigned.set("operations_officer", {
      task: running[0],
      status: "working",
      score: priority.working,
    });
  } else if (queued.length) {
    assigned.set("operations_officer", {
      task: queued[0],
      status: "waiting",
      score: priority.waiting,
    });
  }

  return AGENT_ORDER.map((id) => {
    const current = assigned.get(id);
    if (current) return agentVM(id, current.status, current.task);
    const meta = AGENT_META[id];
    return {
      id,
      name: meta.name,
      role: meta.role,
      description: meta.description,
      status: "idle" as const,
      activeTaskId: null,
      activeTaskTitle: null,
      lastUpdatedAt: previousById.get(id)?.lastUpdatedAt ?? iso(),
      errorMessage: null,
    };
  });
}

interface TaskSeed {
  id: string;
  title: string;
  projectId: string;
  route: StageDefinition[];
  stageIndex: number;
  status: TaskStatus;
  backendState: BackendTaskState | null;
  pendingAction?: PendingAction;
  briefConfirmed: boolean;
  previewRequested?: boolean;
  output?: TaskVM["output"];
  outputId?: string;
  events: TaskEvent[];
  brief: TaskVM["brief"];
  createdAt: string;
  updatedAt: string;
  revisionCount?: number;
  agentId?: AgentId;
  backendError?: string | null;
}

function makeTask(seed: TaskSeed): TaskVM {
  const agentId =
    seed.agentId ??
    (seed.pendingAction === "confirm_brief" ||
    seed.pendingAction === "accept_content"
      ? "operations_officer"
      : seed.route[seed.stageIndex]?.agentId ?? "operations_officer");
  return {
    id: seed.id,
    title: seed.title,
    projectId: seed.projectId,
    agentId,
    status: seed.status,
    stageIndex: seed.stageIndex,
    stages: markStages(
      routeToStages(seed.route),
      seed.stageIndex,
      seed.status,
    ),
    progress: null,
    outputId: seed.outputId ?? null,
    output: seed.output ?? null,
    brief: seed.brief,
    events: seed.events,
    revisionCount: seed.revisionCount ?? 0,
    createdAt: seed.createdAt,
    updatedAt: seed.updatedAt,
    demo: true,
    backendState: seed.backendState,
    pendingAction: seed.pendingAction ?? null,
    queuePosition: null,
    briefConfirmed: seed.briefConfirmed,
    previewRequested: seed.previewRequested ?? false,
    usage: null,
    backendError: seed.backendError ?? null,
  };
}

function seedProjects(): ProjectVM[] {
  return [
    {
      id: "p-ai-tools",
      name: "AI 工具科普",
      description: "面向大学生的 60 秒 AI 工具测评系列，每周两条。",
      status: "active",
      taskIds: [],
      updatedAt: iso(-12),
      accent: "#83B8FF",
    },
    {
      id: "p-portrait",
      name: "人像摄影随笔",
      description: "把拍摄经验讲给第一次拿起相机的人。",
      status: "active",
      taskIds: [],
      updatedAt: iso(-38),
      accent: "#B49CFF",
    },
    {
      id: "p-fashion",
      name: "秋季穿搭灵感",
      description: "轻量图文系列，强调可复用的搭配思路。",
      status: "active",
      taskIds: [],
      updatedAt: iso(-140),
      accent: "#78E3DE",
    },
  ];
}

function seedTasks(): TaskVM[] {
  const standardRoute = routeSteps();
  const commercialRoute = routeSteps({ commercial: true });
  const previewRoute = routeSteps({ preview: true });
  const commercialDirectRoute = routeSteps({ commercial: true, scout: false });

  const t1 = makeTask({
    id: "t-ai-tools",
    title: "5 款 AI 效率工具，大学生 60 秒看懂",
    projectId: "p-ai-tools",
    route: commercialRoute,
    stageIndex: 3,
    status: "running",
    backendState: "GENERATING",
    briefConfirmed: true,
    brief: {
      idea: "介绍 2026 年最值得大学生使用的 5 款 AI 效率工具，强调真实使用场景。",
      audience: "大学生与刚入职场的年轻人",
      format: "短视频",
      duration: "60 秒",
      tone: ["清晰", "有信息密度", "不说教"],
    },
    events: [
      event(
        "created",
        "任务已创建，商单需求分析员开始提取客户需求。",
        "pr_analyst",
        iso(-130),
      ),
      event(
        "stage",
        "商单需求分析完成，目标、受众与限制条件已整理。",
        "pr_analyst",
        iso(-120),
      ),
      event(
        "approval",
        "运营官完成 Brief，创作者已确认任务书。",
        "operations_officer",
        iso(-110),
      ),
      event(
        "stage",
        "流量捕捉者提交 3 个带材料编号的选题机会。",
        "traffic_scout",
        iso(-70),
      ),
      event(
        "stage",
        "内容主创正在按已确认 Brief 组织候选稿。",
        "content_creator",
        iso(-20),
      ),
    ],
    createdAt: iso(-130),
    updatedAt: iso(-20),
  });

  const t2 = makeTask({
    id: "t-portrait",
    title: "自然光人像的三个动作",
    projectId: "p-portrait",
    route: standardRoute,
    stageIndex: 3,
    status: "waiting_approval",
    backendState: "READY",
    pendingAction: "accept_content",
    briefConfirmed: true,
    output: {
      version: 2,
      title: "自然光人像，先学会这三个动作",
      body: [
        "【标题】自然光人像，先学会这三个动作",
        "",
        "【开场】",
        "如果你也总觉得人像拍得「像证件照」，问题可能不在器材。",
        "",
        "【主体】",
        "动作一：让光从侧前方来。先观察窗户，再决定人站在哪里。",
        "动作二：先看表情，再举起相机。把注意力从参数移回眼前的人。",
        "动作三：让手有事可做。扶帽檐、整理袖口，都比僵直站立更自然。",
        "",
        "【收尾】",
        "今天就找一个窗边，试一次。拍完再回来看，哪一步最像你。",
        "",
        "—— 众幕 AI · 内容主创 V2",
      ].join("\n"),
      updatedAt: iso(-20),
    },
    outputId: "a-portrait-script",
    brief: {
      idea: "用三个不依赖昂贵器材的动作，讲清楚怎样拍出自然的人像。",
      audience: "第一次拍人像的摄影爱好者",
      format: "图文",
      duration: "800 字",
      tone: ["温和", "具体", "有画面感"],
    },
    events: [
      event("created", "任务已创建，运营官开始整理 Brief。", "operations_officer", iso(-220)),
      event("approval", "创作者已确认 Brief。", "operations_officer", iso(-210)),
      event("stage", "流量捕捉完成，确定「先放下镜头」的叙事切口。", "traffic_scout", iso(-180)),
      event("stage", "内容主创完成初稿 V1。", "content_creator", iso(-120)),
      event("stage", "审稿员完成独立审稿，提出两处定位到段落的修改。", "editorial_reviewer", iso(-60)),
      event("stage", "内容主创完成修订 V2。", "content_creator", iso(-40)),
      event("approval", "程序校验与独立审稿通过，等待创作者验收。", "operations_officer", iso(-20)),
    ],
    createdAt: iso(-220),
    updatedAt: iso(-20),
    revisionCount: 1,
  });

  const t3 = makeTask({
    id: "t-fashion",
    title: "秋季通勤穿搭：三件单品",
    projectId: "p-fashion",
    route: previewRoute,
    stageIndex: 5,
    status: "completed",
    backendState: "ACCEPTED",
    briefConfirmed: true,
    previewRequested: true,
    output: {
      version: 1,
      title: "秋季通勤，只需要这三件单品",
      body: [
        "【标题】秋季通勤，只需要这三件单品",
        "",
        "不是买得更多，而是让每一件都能被重复使用。",
        "",
        "一、挺括的薄外套：决定整体轮廓。",
        "二、低饱和内搭：把视觉重点留给外套与配饰。",
        "三、有结构的通勤包：让整套搭配有一个明确的落点。",
        "",
        "—— 众幕 AI · 已由创作者验收",
      ].join("\n"),
      updatedAt: iso(-150),
    },
    outputId: "a-fashion-script",
    brief: {
      idea: "用三件可复用的单品，讲清楚秋季通勤穿搭的搭配逻辑。",
      audience: "刚进入职场、想提升通勤质感的女生",
      format: "图文",
      duration: "600 字",
      tone: ["克制", "实用", "有质感"],
    },
    events: [
      event("created", "任务已创建，运营官开始整理 Brief。", "operations_officer", iso(-330)),
      event("approval", "创作者已确认 Brief。", "operations_officer", iso(-320)),
      event("stage", "流量捕捉完成。", "traffic_scout", iso(-300)),
      event("stage", "内容主创完成候选稿。", "content_creator", iso(-240)),
      event("stage", "审稿员通过结构、要求与事实依据检查。", "editorial_reviewer", iso(-210)),
      event("stage", "模拟观众完成 4 个 persona 的逐段阅读。", "simulated_audience", iso(-190)),
      event("stage", "数据分析师完成程序统计与诊断建议。", "data_analyst", iso(-175)),
      event("completed", "创作者已验收，内容归档到「秋季穿搭灵感」项目。", "operations_officer", iso(-150)),
    ],
    createdAt: iso(-330),
    updatedAt: iso(-150),
  });

  const t4 = makeTask({
    id: "t-notes",
    title: "AI 笔记工具横评：谁更适合课堂",
    projectId: "p-ai-tools",
    route: standardRoute,
    stageIndex: 0,
    status: "queued",
    backendState: "QUEUED",
    briefConfirmed: false,
    brief: {
      idea: "对比三款 AI 笔记工具在课堂记录、课后整理和复习场景中的表现。",
      audience: "需要长时间记笔记的大学生",
      format: "短视频",
      duration: "90 秒",
      tone: ["直接", "有对比"],
    },
    events: [
      event(
        "created",
        "任务已受理，等待运营官规划 Brief。",
        "operations_officer",
        iso(-3),
      ),
    ],
    createdAt: iso(-3),
    updatedAt: iso(-3),
  });

  const t5 = makeTask({
    id: "t-failed",
    title: "美妆选题测试：早八妆容",
    projectId: "p-fashion",
    route: standardRoute,
    stageIndex: 1,
    status: "failed",
    backendState: "FAILED",
    briefConfirmed: true,
    agentId: "traffic_scout",
    backendError: "流量捕捉失败：缺少可核实的材料，任务已停止。",
    brief: {
      idea: "测试一个早八妆容选题，验证受众匹配度。",
      audience: "早起通勤的年轻女性",
      format: "短视频",
      duration: "45 秒",
      tone: ["轻快"],
    },
    events: [
      event("created", "任务已创建。", "operations_officer", iso(-430)),
      event("approval", "创作者已确认 Brief。", "operations_officer", iso(-425)),
      event(
        "failed",
        "流量捕捉失败：缺少可核实的材料，任务已停止。",
        "traffic_scout",
        iso(-400),
      ),
    ],
    createdAt: iso(-430),
    updatedAt: iso(-400),
  });

  const t6 = makeTask({
    id: "t-brief",
    title: "品牌联名咖啡：春季上新图文",
    projectId: "p-fashion",
    route: commercialDirectRoute,
    stageIndex: 1,
    status: "waiting_approval",
    backendState: "WAITING_CONFIRMATION",
    pendingAction: "confirm_brief",
    briefConfirmed: false,
    brief: {
      idea: "为品牌联名咖啡整理春季上新图文，突出限定口味与门店活动。",
      audience: "一二线城市 20–30 岁咖啡消费者",
      format: "图文",
      duration: "600 字",
      tone: ["克制", "有质感"],
    },
    events: [
      event(
        "created",
        "商单任务已创建，商单需求分析员开始整理客户资料。",
        "pr_analyst",
        iso(-50),
      ),
      event(
        "stage",
        "商单需求分析完成，已生成运营官待确认输入。",
        "pr_analyst",
        iso(-40),
      ),
      event(
        "approval",
        "运营官已整理 Brief，等待你确认任务书。",
        "operations_officer",
        iso(-10),
      ),
    ],
    createdAt: iso(-50),
    updatedAt: iso(-10),
  });

  return [t1, t2, t3, t4, t5, t6];
}

function seedSnapshot(): WorkspaceSnapshot {
  const tasks = seedTasks();
  const projects = seedProjects().map((project) => ({
    ...project,
    taskIds: tasks.filter((task) => task.projectId === project.id).map((task) => task.id),
  }));
  const assets: AssetVM[] = [
    {
      id: "a-fashion-script",
      name: "秋季通勤穿搭：三件单品 · 内容候选",
      kind: "script",
      projectId: "p-fashion",
      taskId: "t-fashion",
      createdAt: iso(-150),
      body: "秋季通勤，只需要这三件单品……",
    },
    {
      id: "a-portrait-script",
      name: "自然光人像 · 待验收候选 V2",
      kind: "script",
      projectId: "p-portrait",
      taskId: "t-portrait",
      createdAt: iso(-20),
      body: "自然光人像，先学会这三个动作……",
    },
    {
      id: "a-portrait-topic",
      name: "自然光人像 · 选题机会",
      kind: "topic",
      projectId: "p-portrait",
      taskId: "t-portrait",
      createdAt: iso(-180),
      body: "切口：先放下镜头，再谈器材。目标受众：第一次拍人像的摄影爱好者。",
    },
    {
      id: "a-brief",
      name: "品牌联名咖啡 · 待确认 Brief",
      kind: "brief",
      projectId: "p-fashion",
      taskId: "t-brief",
      createdAt: iso(-10),
      body: "商单已整理为待确认 Brief，等待创作者确认后才能进入内容生成。",
    },
  ];

  return {
    mode: "demo",
    agents: derivedAgents(tasks),
    tasks,
    projects,
    assets,
    profile: null,
    updatedAt: iso(),
  };
}

function readSnapshot(): WorkspaceSnapshot {
  if (typeof window === "undefined") return seedSnapshot();
  try {
    const raw = window.localStorage.getItem(SNAPSHOT_KEY);
    if (!raw) return seedSnapshot();
    const parsed = JSON.parse(raw) as WorkspaceSnapshot;
    if (!parsed?.tasks || !parsed?.agents) return seedSnapshot();
    return {
      ...parsed,
      agents: derivedAgents(parsed.tasks, parsed.agents),
    };
  } catch {
    return seedSnapshot();
  }
}

function writeSnapshot(snapshot: WorkspaceSnapshot): WorkspaceSnapshot {
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(snapshot));
    } catch {
      /* demo persistence is best-effort */
    }
  }
  return snapshot;
}

function syncProjects(tasks: TaskVM[], projects: ProjectVM[]): ProjectVM[] {
  return projects.map((project) => ({
    ...project,
    taskIds: tasks
      .filter((task) => task.projectId === project.id)
      .map((task) => task.id),
    updatedAt:
      tasks
        .filter((task) => task.projectId === project.id)
        .map((task) => task.updatedAt)
        .sort()
        .at(-1) ?? project.updatedAt,
  }));
}

function stateForStep(step: BackendStep): BackendTaskState | null {
  return stateForBackendStep(step);
}

export class MockWorkspaceAdapter implements WorkspaceAdapter {
  readonly mode = "demo" as const;

  async load(): Promise<WorkspaceSnapshot> {
    return readSnapshot();
  }

  async saveProfile(profile: Profile): Promise<WorkspaceSnapshot> {
    const snapshot = readSnapshot();
    return writeSnapshot({
      ...snapshot,
      profile,
      updatedAt: iso(),
    });
  }

  async createTask(input: CreateTaskInput): Promise<WorkspaceSnapshot> {
    const snapshot = readSnapshot();
    const now = iso();
    const route = routeSteps({ preview: input.previewRequested });
    const task = makeTask({
      id: makeId("t"),
      title: input.title.trim(),
      projectId: input.projectId || snapshot.projects[0]?.id || "p-ai-tools",
      route,
      stageIndex: 0,
      status: "running",
      backendState: "PLANNING",
      briefConfirmed: false,
      previewRequested: input.previewRequested,
      brief: {
        idea: input.idea.trim(),
        audience: input.audience.trim(),
        format: input.format,
        duration: input.duration,
        tone: input.tone,
      },
      events: [
        event("created", "任务已创建，运营官开始整理 Brief。", "operations_officer", now),
        event("stage", "Brief 规划进行中。", "operations_officer", now),
      ],
      createdAt: now,
      updatedAt: now,
    });
    const tasks = [task, ...snapshot.tasks];
    const projects = syncProjects(tasks, snapshot.projects);
    return writeSnapshot({
      ...snapshot,
      tasks,
      projects,
      agents: derivedAgents(tasks, snapshot.agents),
      updatedAt: now,
    });
  }

  async advanceTask(taskId: string): Promise<WorkspaceSnapshot> {
    const snapshot = readSnapshot();
    const tasks = snapshot.tasks.map((task) => ({ ...task }));
    const task = tasks.find((item) => item.id === taskId);
    if (!task || task.status !== "running") return snapshot;

    const now = iso();
    const current = task.stages[task.stageIndex];
    if (!current) return snapshot;

    // Backend gate 1: the content run cannot start until a human confirms Brief.
    if (current.backendStep === "planning" && !task.briefConfirmed) {
      task.status = "waiting_approval";
      task.pendingAction = "confirm_brief";
      task.backendState = "WAITING_CONFIRMATION";
      task.agentId = "operations_officer";
      task.stages = markStages(task.stages, task.stageIndex, task.status);
      task.updatedAt = now;
      task.events.push(
        event(
          "approval",
          "运营官已完成 Brief，等待你确认任务书。",
          "operations_officer",
          now,
        ),
      );
    } else if (task.stageIndex < task.stages.length - 1) {
      // Draft output exists before review / preview, matching the backend run.
      if (current.backendStep === "draft" && !task.output) {
        task.output = buildOutput(task);
        task.outputId = task.outputId ?? makeId("a");
        task.events.push(
          event(
            "stage",
            "内容主创完成候选稿 V1，交给独立审稿。",
            "content_creator",
            now,
          ),
        );
      }
      const next = task.stages[task.stageIndex + 1];
      task.stageIndex += 1;
      task.agentId = next.agentId;
      task.status = "running";
      task.backendState = stateForStep(next.backendStep);
      task.stages = markStages(task.stages, task.stageIndex, task.status);
      task.updatedAt = now;
      task.events.push(
        event(
          "stage",
          `${AGENT_META[current.agentId].name}完成「${current.label}」，交接给${AGENT_META[next.agentId].name}。`,
          current.agentId,
          now,
        ),
        event("stage", `${next.label}阶段开始。`, next.agentId, now),
      );
    } else {
      // Backend gate 2: READY → human accept.
      if (!task.output) {
        task.output = buildOutput(task);
        task.outputId = task.outputId ?? makeId("a");
      }
      task.status = "waiting_approval";
      task.pendingAction = "accept_content";
      task.backendState = "READY";
      task.agentId = "operations_officer";
      task.stages = markStages(task.stages, task.stageIndex, task.status);
      task.updatedAt = now;
      task.events.push(
        event(
          "approval",
          "全部自动步骤已完成，等待你验收内容。",
          "operations_officer",
          now,
        ),
      );
    }

    const projects = syncProjects(tasks, snapshot.projects);
    return writeSnapshot({
      ...snapshot,
      tasks,
      projects,
      agents: derivedAgents(tasks, snapshot.agents),
      updatedAt: now,
    });
  }

  async decideTask(
    taskId: string,
    decision: Decision,
    options: DecisionOptions = {},
  ): Promise<WorkspaceSnapshot> {
    const snapshot = readSnapshot();
    const tasks = snapshot.tasks.map((task) => ({ ...task }));
    const task = tasks.find((item) => item.id === taskId);
    if (!task || task.status !== "waiting_approval") return snapshot;

    const now = iso();
    const pending: PendingAction = task.pendingAction ?? "accept_content";
    let assets = snapshot.assets;

    if (pending === "confirm_brief") {
      if (decision === "approve") {
        task.briefConfirmed = true;
        task.pendingAction = null;
        task.backendState = "QUEUED";
        if (task.stageIndex < task.stages.length - 1) {
          const next = task.stages[task.stageIndex + 1];
          task.stageIndex += 1;
          task.agentId = next.agentId;
          task.status = "running";
          task.backendState = stateForStep(next.backendStep);
          task.stages = markStages(task.stages, task.stageIndex, task.status);
          task.events.push(
            event(
              "approval",
              `创作者已确认 Brief，任务进入队列并交给${AGENT_META[next.agentId].name}。`,
              "operations_officer",
              now,
            ),
          );
        } else {
          task.status = "running";
          task.stages = markStages(task.stages, task.stageIndex, task.status);
        }
        task.updatedAt = now;
      } else if (decision === "revise") {
        task.briefConfirmed = false;
        task.pendingAction = null;
        task.status = "running";
        task.backendState = "PLANNING";
        if (options.note?.trim()) {
          task.brief.idea = `${task.brief.idea}\n修改要求：${options.note.trim()}`;
        }
        task.stages = markStages(task.stages, task.stageIndex, task.status);
        task.updatedAt = now;
        task.events.push(
          event(
            "revision",
            options.note?.trim()
              ? `创作者要求修改 Brief：${options.note.trim()}`
              : "创作者要求修改 Brief，运营官重新规划。",
            "operations_officer",
            now,
          ),
        );
      } else {
        task.status = "cancelled";
        task.backendState = "CANCELLED";
        task.pendingAction = null;
        task.updatedAt = now;
        task.events.push(
          event(
            "cancelled",
            options.note?.trim()
              ? `创作者拒绝了任务书：${options.note.trim()}`
              : "创作者拒绝了本次任务书。",
            "operations_officer",
            now,
          ),
        );
      }
    } else if (decision === "approve") {
      const body = options.editedBody?.trim() || task.output?.body || "";
      task.output = {
        version: (task.output?.version ?? 1) + 1,
        title: task.output?.title ?? task.title,
        body,
        updatedAt: now,
      };
      task.outputId = task.outputId ?? makeId("a");
      task.status = "completed";
      task.pendingAction = null;
      task.backendState = "ACCEPTED";
      task.agentId = "operations_officer";
      task.stages = markStages(task.stages, task.stageIndex, "completed");
      task.updatedAt = now;
      task.events.push(
        event(
          "completed",
          "创作者已验收，内容归档为可下载资产。",
          "operations_officer",
          now,
        ),
      );
      const asset: AssetVM = {
        id: makeId("asset"),
        name: `${task.title} · 已验收内容`,
        kind: "script",
        projectId: task.projectId,
        taskId: task.id,
        createdAt: now,
        body,
      };
      assets = [asset, ...snapshot.assets];
    } else if (decision === "revise") {
      const draftIndex = Math.max(
        0,
        task.stages.findIndex((stage) => stage.backendStep === "draft"),
      );
      task.status = "running";
      task.stageIndex = draftIndex;
      task.agentId = "content_creator";
      task.backendState = "REVISING";
      task.pendingAction = null;
      task.briefConfirmed = true;
      task.stages = markStages(task.stages, task.stageIndex, task.status);
      task.revisionCount += 1;
      task.updatedAt = now;
      if (options.editedBody?.trim() && task.output) {
        task.output = {
          ...task.output,
          body: options.editedBody.trim(),
          updatedAt: now,
        };
      }
      task.events.push(
        event(
          "revision",
          options.note?.trim()
            ? `创作者要求修改：${options.note.trim()}`
            : "创作者要求修改，内容主创进入定向修订。",
          "content_creator",
          now,
        ),
      );
    } else {
      task.status = "cancelled";
      task.backendState = "CANCELLED";
      task.pendingAction = null;
      task.updatedAt = now;
      task.events.push(
        event(
          "cancelled",
          options.note?.trim()
            ? `创作者拒绝并取消：${options.note.trim()}`
            : "创作者拒绝了本次成果。",
          "operations_officer",
          now,
        ),
      );
    }

    const projects = syncProjects(tasks, snapshot.projects);
    return writeSnapshot({
      ...snapshot,
      tasks,
      projects,
      assets,
      agents: derivedAgents(tasks, snapshot.agents),
      updatedAt: now,
    });
  }

  async reset(): Promise<WorkspaceSnapshot> {
    if (typeof window === "undefined") return seedSnapshot();
    const previous = readSnapshot();
    window.localStorage.removeItem(SNAPSHOT_KEY);
    const fresh = readSnapshot();
    // The settings dialog promises that the workspace profile survives a demo
    // reset — only tasks, approvals and assets are rebuilt.
    return previous.profile
      ? writeSnapshot({ ...fresh, profile: previous.profile })
      : fresh;
  }
}

export const MOCK_STORAGE_KEY = SNAPSHOT_KEY;
