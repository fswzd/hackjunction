import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Clock3,
  Copy,
  Download,
  FileText,
  RefreshCw,
  RotateCcw,
  Sparkles,
  XCircle,
} from "lucide-react";
import {
  AGENT_META,
  BACKEND_STATE_META,
  TASK_STATUS_META,
  agentForTask,
  progressForTask,
} from "@/domain/agents";
import type { DecisionOptions, TaskEvent, TaskVM } from "@/domain/types";
import { cn, formatDate, formatRelative, formatTime } from "@/lib/format";
import { useWorkspace } from "@/store/workspace";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Modal } from "@/components/ui/Modal";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { TaskStatusBadge } from "@/components/ui/StatusBadge";
import { TaskInputPanel, TaskRecoveryButton } from "@/components/tasks/TaskRecovery";

const STATUS_COPY: Record<
  TaskVM["status"],
  { title: string; description: string; color: string; surface: string; border: string }
> = {
  pending: {
    title: "等待处理",
    description: "运营官正在整理这份任务书，稍后会派发给第一位员工。",
    color: "#A1A9BB",
    surface: "bg-white/[0.03]",
    border: "border-line",
  },
  queued: {
    title: "排队中",
    description: "有可用执行位时，系统会自动开始下一步。",
    color: "#F0B36E",
    surface: "bg-amber/[0.07]",
    border: "border-amber/30",
  },
  running: {
    title: "AI 团队正在协作",
    description: "完成当前阶段后会自动交接。需要你处理时，任务会停在确认环节。",
    color: "#78E3DE",
    surface: "bg-cyan/[0.06]",
    border: "border-cyan/25",
  },
  waiting_approval: {
    title: "内容已准备好，等你决定",
    description: "确认后会保存到项目资产；也可以退回内容主创做定向修改。",
    color: "#B49CFF",
    surface: "bg-violet/[0.08]",
    border: "border-violet/30",
  },
  completed: {
    title: "已完成并归档",
    description: "你的批准已记录下来，内容可以在素材库中查看和下载。",
    color: "#8FD6A8",
    surface: "bg-green/[0.07]",
    border: "border-green/25",
  },
  failed: {
    title: "任务执行失败",
    description: "任务已停止，没有生成未经验证的内容。请查看事件记录中的失败原因。",
    color: "#F08A8A",
    surface: "bg-red/[0.07]",
    border: "border-red/25",
  },
  cancelled: {
    title: "任务已取消",
    description: "这次创作没有继续。你可以调整 Brief 后重新发起任务。",
    color: "#7C869B",
    surface: "bg-white/[0.03]",
    border: "border-line",
  },
};

function statusCopyFor(task: TaskVM): (typeof STATUS_COPY)[TaskVM["status"]] {
  const base = STATUS_COPY[task.status];
  if (task.status === "waiting_approval" && task.pendingAction === "confirm_brief") {
    return {
      ...base,
      title: "Brief 已整理，等你确认",
      description:
        "确认任务书后，后端才会把任务移入队列并开始生成；也可以退回运营官重新规划。",
    };
  }
  if (task.backendState === "WAITING_INPUT") {
    return {
      ...base,
      title: "等待补充输入",
      description:
        "回答下方的问题后，团队会继续整理任务书。",
    };
  }
  if (task.backendState === "NEEDS_REVIEW") {
    return {
      ...base,
      title: "需要人工审阅",
      description:
        "请查看稿件和审稿意见，再决定批准或退回修改。",
    };
  }
  if (task.backendState === "INTERRUPTED") {
    return {
      ...base,
      title: "任务已中断",
      description:
        "已保存的进度可以在调用结果明确后继续使用。",
    };
  }
  return base;
}

function eventLabel(event: TaskEvent): string {
  if (event.agentId) return AGENT_META[event.agentId].name;
  return "系统";
}

function downloadText(filename: string, body: string) {
  const blob = new Blob([body], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function safeFilename(title: string): string {
  return title.replace(/[\\/:*?"<>|]/g, "-").slice(0, 60);
}

export function TaskDetail() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const snapshot = useWorkspace((state) => state.snapshot);
  const mode = useWorkspace((state) => state.mode);
  const advanceTask = useWorkspace((state) => state.advanceTask);
  const decideTask = useWorkspace((state) => state.decideTask);
  const showToast = useWorkspace((state) => state.showToast);

  const [approveOpen, setApproveOpen] = useState(false);
  const [reviseOpen, setReviseOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [bodyDraft, setBodyDraft] = useState("");
  const [reviseNote, setReviseNote] = useState("");
  const [reviseBody, setReviseBody] = useState("");
  const [rejectNote, setRejectNote] = useState("");
  const [copied, setCopied] = useState(false);
  const [pending, setPending] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [decisionTarget, setDecisionTarget] = useState<DecisionOptions>({});

  if (!snapshot) return null;
  const task = snapshot.tasks.find((item) => item.id === taskId);

  if (!task) {
    return (
      <EmptyState
        className="mt-10"
        icon={<FileText size={18} />}
        title="找不到这个任务"
        description="它可能已被重置或删除。回到任务中心查看当前所有任务。"
        action={
          <Button variant="secondary" onClick={() => navigate("/workspace/tasks")}>
            返回任务中心
          </Button>
        }
      />
    );
  }

  const project = snapshot.projects.find((item) => item.id === task.projectId);
  const statusCopy = statusCopyFor(task);
  const currentAgent = AGENT_META[agentForTask(task)];
  const progress = progressForTask(task);
  const isDemo = mode === "demo";
  const isBriefGate = task.pendingAction === "confirm_brief";
  const preview = task.preview;
  const previewPending = preview?.state === "QUEUED" || preview?.state === "RUNNING";
  const canResumeTask = task.canResume && task.rowVersion !== undefined;
  const canAdvance = isDemo && task.status === "running";
  const nextStage = task.stages[task.stageIndex + 1];
  const approvedAsset = snapshot.assets.find((asset) => asset.taskId === task.id && asset.kind === "script");
  const canApprove = isBriefGate
    ? isDemo || task.briefVersion != null
    : Boolean(task.output) && !previewPending;

  const prepareDecision = () => {
    setDecisionError(null);
    setDecisionTarget({
      expectedBriefVersion: isBriefGate ? task.briefVersion ?? undefined : undefined,
      expectedContentVersionId: isBriefGate ? undefined : task.readyVersionId ?? task.headVersionId ?? undefined,
    });
  };
  const targetChanged =
    (decisionTarget.expectedBriefVersion !== undefined &&
      (!isBriefGate || task.briefVersion !== decisionTarget.expectedBriefVersion)) ||
    (decisionTarget.expectedContentVersionId !== undefined &&
      (task.status !== "waiting_approval" ||
       (task.readyVersionId ?? task.headVersionId) !== decisionTarget.expectedContentVersionId));
  const dialogError = targetChanged ? "任务已更新。请关闭窗口，阅读新版本后再提交。" : decisionError;

  const openApprove = () => {
    prepareDecision();
    setBodyDraft(task.output?.body ?? "");
    setApproveOpen(true);
  };

  const openRevise = () => {
    prepareDecision();
    setReviseNote("");
    setReviseBody(task.output?.body ?? "");
    setReviseOpen(true);
  };

  const confirmApprove = async () => {
    setPending(true);
    const error = await decideTask(task.id, "approve", { ...decisionTarget, editedBody: bodyDraft });
    setPending(false);
    setDecisionError(error);
    if (!error) setApproveOpen(false);
  };

  const confirmRevise = async () => {
    setPending(true);
    const error = await decideTask(task.id, "revise", {
      ...decisionTarget,
      note: reviseNote,
      editedBody: reviseBody !== (task.output?.body ?? "") ? reviseBody : undefined,
    });
    setPending(false);
    setDecisionError(error);
    if (!error) setReviseOpen(false);
  };

  const confirmReject = async () => {
    setPending(true);
    const error = await decideTask(task.id, "reject", { ...decisionTarget, note: rejectNote });
    setPending(false);
    setDecisionError(error);
    if (!error) setRejectOpen(false);
  };

  const copyOutput = async () => {
    if (!task.output) return;
    try {
      await navigator.clipboard.writeText(task.output.body);
      setCopied(true);
      showToast("脚本已复制到剪贴板。", "success");
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      showToast("复制失败，请手动选择文本。", "error");
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          to="/workspace/tasks"
          className="inline-flex items-center gap-1.5 text-[11px] text-muted transition hover:text-text"
        >
          <ArrowLeft size={13} />
          任务中心
        </Link>
        <span className="text-[10px] text-muted">/</span>
        <span className="text-[11px] text-muted">{project?.name ?? "未归档"}</span>
        {task.demo ? (
          <span className="rounded border border-amber/25 bg-amber/8 px-1.5 py-0.5 text-[9px] text-amber">
            演示数据
          </span>
        ) : null}
      </div>

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <TaskStatusBadge status={task.status} backendState={task.backendState} />
            <span className="text-[10px] text-muted">
              创建于 {formatDate(task.createdAt)} {formatTime(task.createdAt)}
            </span>
            {task.revisionCount > 0 ? (
              <span className="rounded border border-line px-1.5 py-0.5 text-[9px] text-muted">
                已修订 {task.revisionCount} 次
              </span>
            ) : null}
          </div>
          <h1 className="mt-3 text-balance text-2xl font-semibold tracking-tight sm:text-3xl">
            {task.title}
          </h1>
          <p className="mt-2 text-xs leading-6 text-muted">
            当前由 <b className="text-text">{currentAgent.name}</b> 负责 ·{" "}
            {task.stages[task.stageIndex]?.label ?? "等待审批"} · 更新于{" "}
            {formatRelative(task.updatedAt)}
          </p>
        </div>

        {canAdvance ? (
          <div className="flex shrink-0 flex-col items-start gap-1.5 sm:items-end">
            <Button
              variant="secondary"
              icon={<ArrowRight size={14} />}
              onClick={() => void advanceTask(task.id)}
            >
              模拟推进到{nextStage ? nextStage.label : "审批"}
            </Button>
            <p className="text-[9px] text-muted">
              演示模式手动推进 · 真实接口模式下由后端状态驱动
            </p>
          </div>
        ) : null}
      </div>

      <div
        className={cn(
          "flex flex-col gap-3 rounded-2xl border p-4 sm:flex-row sm:items-center",
          statusCopy.border,
          statusCopy.surface,
        )}
      >
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border"
          style={{
            color: statusCopy.color,
            borderColor: `color-mix(in srgb, ${statusCopy.color} 35%, transparent)`,
            backgroundColor: `color-mix(in srgb, ${statusCopy.color} 12%, transparent)`,
          }}
        >
          {task.status === "waiting_approval" ? (
            <Sparkles size={16} />
          ) : task.status === "completed" ? (
            <CheckCircle2 size={16} />
          ) : task.status === "failed" ? (
            <AlertTriangle size={16} />
          ) : (
            <Clock3 size={16} />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium" style={{ color: statusCopy.color }}>
            {statusCopy.title}
          </p>
          <p className="mt-0.5 text-[11px] leading-5 text-muted">
            {statusCopy.description}
          </p>
        </div>
        {task.status === "waiting_approval" ? (
          <div className="flex shrink-0 flex-wrap gap-2">
            <Button
              variant="ghost"
              size="sm"
              icon={<RotateCcw size={13} />}
              onClick={openRevise}
            >
              {isBriefGate ? "修改 Brief" : "退回修改"}
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={<Check size={14} />}
              onClick={openApprove}
              disabled={!canApprove}
            >
              {isBriefGate ? "确认 Brief" : "审阅并批准"}
            </Button>
          </div>
        ) : null}
      </div>

      {task.backendState === "WAITING_INPUT" ? <TaskInputPanel key={task.id} task={task} /> : null}
      {previewPending && task.status === "waiting_approval" ? (
        <p role="status" className="rounded-xl border border-cyan/25 bg-cyan/[0.05] px-3 py-2 text-xs text-muted">
          你可以先阅读稿件。试映结束后即可批准。
        </p>
      ) : null}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-4">
          {preview ? (
            <Card>
              <CardHeader><h2 className="text-sm font-semibold">模拟试映</h2></CardHeader>
              <CardBody className="space-y-3">
                <p className="text-xs text-muted">
                  {preview.state === "QUEUED" ? "试映已排队。"
                    : preview.state === "RUNNING" ? "模拟观众正在逐段阅读，随后会生成分析。"
                    : preview.state === "COMPLETED"
                      ? `试映完成。${preview.started ?? 0} / ${preview.selected ?? 0} 位模拟观众开始阅读。`
                      : ({ INTERRUPTED: "试映已中断。", INCOMPLETE: "试映只完成了一部分。", FAILED: "试映失败。", CANCELLED: "试映已取消。" } as Record<string, string>)[preview.state] ?? "试映状态待更新。"}
                </p>
                {preview.error ? <p className="text-xs text-amber">{preview.error}</p> : null}
                {preview.nextAction ? <p className="text-xs text-muted">{preview.nextAction}</p> : null}
                {preview.state === "COMPLETED" && preview.analysisStatus !== "succeeded" ? (
                  <p className="text-xs text-muted">阅读记录已保存，本次没有生成完整分析。</p>
                ) : null}
                {preview.findings.length ? (
                  <ul className="space-y-2">
                    {preview.findings.map((finding) => (
                      <li key={finding.id} className="rounded-lg border border-line bg-ink/40 p-3 text-xs leading-5">
                        <p className="text-muted">{finding.interpretation}</p>
                        <p className="mt-1 font-medium text-text">{finding.suggested_edit}</p>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {preview.canResume ? (
                  <TaskRecoveryButton taskId={task.id} label="继续试映" action={{
                    type: "resume_preview", previewId: preview.id, rowVersion: preview.rowVersion,
                  }} />
                ) : null}
              </CardBody>
            </Card>
          ) : null}
          <Card>
            <CardHeader>
              <div>
                <h2 className="text-sm font-semibold">协作阶段</h2>
                <p className="mt-0.5 text-[11px] text-muted">
                  共 {task.stages.length} 个阶段，按后端任务路由动态生成；任一步失败都会停止任务
                </p>
              </div>
              <span className="text-[10px] text-muted">{progress}%</span>
            </CardHeader>
            <CardBody>
              <ol className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {task.stages.map((stage, index) => {
                  const meta = AGENT_META[stage.agentId];
                  const state =
                    task.status === "completed" ? "done" : stage.state;
                  return (
                    <li
                      key={`${stage.agentId}-${index}`}
                      className={cn(
                        "relative rounded-xl border p-3",
                        state === "active"
                          ? "border-cyan/35 bg-cyan/[0.06]"
                          : state === "done"
                            ? "border-green/20 bg-green/[0.04]"
                            : "border-line bg-raised/30",
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1.5 text-[10px] text-muted">
                          <span
                            className={cn(
                              "flex h-5 w-5 items-center justify-center rounded-full border text-[9px]",
                              state === "done"
                                ? "border-green/40 bg-green/10 text-green"
                                : state === "active"
                                  ? "border-cyan/50 bg-cyan/12 text-cyan"
                                  : "border-line text-muted",
                            )}
                          >
                            {state === "done" ? <Check size={10} /> : index + 1}
                          </span>
                          <span>步骤 {index + 1}</span>
                        </span>
                        <span className="flex items-center gap-1.5">
                          {stage.optional ? (
                            <span className="rounded border border-line px-1 py-0.5 text-[10px] text-muted">
                              可选
                            </span>
                          ) : null}
                          {state === "active" ? (
                            <span className="h-1.5 w-1.5 animate-soft-pulse rounded-full bg-cyan" />
                          ) : null}
                        </span>
                      </div>
                      <p className="mt-2 text-xs font-medium">{stage.label}</p>
                      <p className="mt-0.5 text-[10px]" style={{ color: meta.accent }}>
                        {meta.name}
                      </p>
                    </li>
                  );
                })}
              </ol>
              <div className="mt-4">
                <ProgressBar value={progress} color={statusCopy.color} />
              </div>
              {task.status === "failed" ? (
                <div className="mt-4 space-y-2 rounded-xl border border-red/25 bg-red/8 px-3 py-2 text-xs leading-5">
                  <p className="text-red">{task.backendError ??
                    [...task.events].reverse().find((event) => event.kind === "failed")?.message ??
                    "请查看下方事件记录。"}</p>
                  {task.backendNextAction ? <p className="text-muted">{task.backendNextAction}</p> : null}
                  {canResumeTask && task.rowVersion !== undefined ? (
                    <TaskRecoveryButton taskId={task.id} label="从保存进度继续" action={{
                      type: "resume_task", rowVersion: task.rowVersion,
                    }} />
                  ) : null}
                </div>
              ) : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <h2 className="text-sm font-semibold">交付内容</h2>
                <p className="mt-0.5 text-[11px] text-muted">
                  {task.output
                    ? `版本 V${task.output.version} · 更新于 ${formatRelative(
                        task.output.updatedAt,
                      )}`
                    : isBriefGate
                      ? "Brief 确认后，内容主创才会开始创作"
                      : "候选稿会在内容创作完成并进入审稿时出现"}
                </p>
              </div>
              {task.output ? (
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => void copyOutput()}
                    className="rounded-lg p-1.5 text-muted transition hover:bg-white/5 hover:text-text"
                    aria-label="复制脚本"
                  >
                    {copied ? <Check size={14} /> : <Copy size={14} />}
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      downloadText(
                        `${safeFilename(task.title)}.md`,
                        [`# ${task.output!.title}`, task.output!.cover ? `> ${task.output!.cover}` : "", task.output!.body]
                          .filter(Boolean).join("\n\n") + "\n",
                      )
                    }
                    className="rounded-lg p-1.5 text-muted transition hover:bg-white/5 hover:text-text"
                    aria-label="下载脚本"
                  >
                    <Download size={14} />
                  </button>
                </div>
              ) : null}
            </CardHeader>
            <CardBody>
              {task.backendState === "WAITING_INPUT" ? (
                <p className="text-xs text-muted">补充资料后，团队会先整理任务书。</p>
              ) : isBriefGate ? (
                <div className="rounded-xl border border-violet/25 bg-violet/6 p-4">
                  <p className="text-xs font-medium text-violet">任务书待确认</p>
                  <p className="mt-1 text-[11px] leading-5 text-muted">
                    运营官已整理 Brief。确认后任务进入后台队列，内容主创才会开始生成候选稿；
                    退回则重新规划 Brief，不会产生内容。
                  </p>
                  <dl className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {[
                      ["创作想法", task.brief.idea || "未填写"],
                      ["目标读者", task.brief.audience || "未填写"],
                      ["内容形式", task.brief.format],
                      ["时长 / 篇幅", task.brief.duration],
                      ["语气", task.brief.tone.join(" / ") || "未填写"],
                      ["试映", task.previewRequested ? "生成后运行" : "不运行"],
                    ].map(([label, value]) => (
                      <div
                        key={label}
                        className="rounded-lg border border-line bg-ink/40 p-2.5"
                      >
                        <dt className="text-[9px] uppercase tracking-[0.12em] text-muted">
                          {label}
                        </dt>
                        <dd className="mt-1 text-[11px] leading-5 text-text/90">
                          {value}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
                    <Button variant="ghost" size="sm" onClick={openRevise}>
                      修改 Brief
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      icon={<Check size={13} />}
                      onClick={openApprove}
                    >
                      确认并开始创作
                    </Button>
                  </div>
                </div>
              ) : task.output ? (
                <>
                  <div className="rounded-xl border border-line bg-ink/50 p-4">
                    <h3 className="mb-2 break-words text-base font-semibold">{task.output.title}</h3>
                    {task.output.cover ? <p className="mb-3 break-words text-xs text-muted">{task.output.cover}</p> : null}
                    <pre className="whitespace-pre-wrap break-words font-sans text-[13px] leading-7 text-text/90">
                      {task.output.body}
                    </pre>
                  </div>
                  {task.output.ruleIssues?.length ? (
                    <div className="mt-4 space-y-2 rounded-xl border border-amber/25 bg-amber/6 p-3">
                      <h3 className="text-xs font-medium text-amber">规则检查</h3>
                      <ul className="space-y-1 text-xs leading-5 text-text">
                        {task.output.ruleIssues.map((issue, index) => (
                          <li key={`${issue.rule_id}-${index}`}>{issue.reason}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {task.output.review && task.output.review.overall !== "pass" ? (
                    <div className="mt-4 space-y-2 rounded-xl border border-amber/25 bg-amber/6 p-3">
                      <h3 className="text-xs font-medium text-amber">审稿意见</h3>
                      {task.output.review.issues.map((issue, index) => (
                        <div key={index} className="text-xs leading-5">
                          <p className="text-text">{issue.reason}</p>
                          <p className="text-muted">{issue.requested_change}</p>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {task.status === "waiting_approval" ? (
                    <div className="mt-4 flex flex-col gap-2 rounded-xl border border-violet/25 bg-violet/6 p-3 sm:flex-row sm:items-center sm:justify-between">
                      <p className="text-[11px] leading-5 text-muted">
                        批准即保存到项目资产，可随时下载。若只想小改，可直接退回内容主创。
                      </p>
                      <div className="flex shrink-0 gap-2">
                        <Button variant="ghost" size="sm" onClick={openRevise}>
                          退回修改
                        </Button>
                        <Button
                          variant="primary"
                          size="sm"
                          icon={<Check size={13} />}
                          onClick={openApprove}
                          disabled={!canApprove}
                        >
                          批准内容
                        </Button>
                      </div>
                    </div>
                  ) : null}
                  {task.status === "completed" ? (
                    <div className="mt-4 flex flex-wrap items-center gap-3 text-xs">
                      <span className="flex items-center gap-1.5 text-green"><CheckCircle2 size={13} />已批准并归档</span>
                      {approvedAsset ? (
                        <Link className="text-blue underline underline-offset-4" to={`/workspace/assets?asset=${encodeURIComponent(approvedAsset.id)}`}>
                          在素材库查看并下载
                        </Link>
                      ) : null}
                    </div>
                  ) : null}
                </>
              ) : (
                <EmptyState
                  icon={<FileText size={18} />}
                  title={
                    task.status === "failed"
                      ? "本次任务没有生成内容"
                      : "还没有可审阅的内容"
                  }
                  description={
                    task.status === "failed"
                      ? "失败的任务不会输出未经验证的内容。可以调整 Brief 后重新发起。"
                      : isBriefGate
                        ? "当前停在人工确认任务书的环节，确认 Brief 后才会生成内容。"
                        : "当自动阶段完成后，候选稿会出现在这里等待你验收。"
                  }
                />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <h2 className="text-sm font-semibold">事件记录</h2>
                <p className="mt-0.5 text-[11px] text-muted">
                  每次阶段交接与人工决定都会留下记录
                </p>
              </div>
              <span className="text-[10px] text-muted">
                {task.events.length} 条
              </span>
            </CardHeader>
            <CardBody>
              <ol className="relative space-y-4 border-l border-line pl-5">
                {task.events.map((event) => (
                  <li key={event.id} className="relative">
                    <span
                      className="absolute -left-[26px] top-1 h-2.5 w-2.5 rounded-full border-2 border-surface"
                      style={{
                        backgroundColor:
                          event.kind === "failed"
                            ? "#F08A8A"
                            : event.kind === "completed"
                              ? "#8FD6A8"
                              : event.kind === "approval" || event.kind === "revision"
                                ? "#B49CFF"
                                : "#4A556B",
                      }}
                    />
                    <p className="text-[11px] leading-6 text-text">
                      {event.message}
                    </p>
                    <p className="mt-0.5 text-[10px] text-muted">
                      {eventLabel(event)} · {formatRelative(event.at)} ·{" "}
                      {formatTime(event.at)}
                    </p>
                  </li>
                ))}
              </ol>
            </CardBody>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <h2 className="text-sm font-semibold">任务 Brief</h2>
            </CardHeader>
            <CardBody className="space-y-4">
              <div>
                <p className="text-[10px] uppercase tracking-[0.14em] text-muted">
                  创作想法
                </p>
                <p className="mt-1.5 text-[11px] leading-6 text-text/90">
                  {task.brief.idea || "未填写"}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-[0.14em] text-muted">
                  目标读者
                </p>
                <p className="mt-1.5 text-[11px] leading-6 text-text/90">
                  {task.brief.audience || "未填写"}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-line bg-raised/40 p-2.5">
                  <p className="text-[9px] text-muted">形式</p>
                  <p className="mt-1 text-[11px]">{task.brief.format}</p>
                </div>
                <div className="rounded-lg border border-line bg-raised/40 p-2.5">
                  <p className="text-[9px] text-muted">时长 / 篇幅</p>
                  <p className="mt-1 text-[11px]">{task.brief.duration}</p>
                </div>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-[0.14em] text-muted">
                  语气
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {task.brief.tone.map((item) => (
                    <span
                      key={item}
                      className="rounded border border-line px-1.5 py-0.5 text-[9px] text-muted"
                    >
                      {item}
                    </span>
                  ))}
                </div>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <h2 className="text-sm font-semibold">任务信息</h2>
            </CardHeader>
            <CardBody className="space-y-3">
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-muted">所属项目</span>
                <Link
                  to={`/workspace/tasks?project=${task.projectId}`}
                  className="max-w-[180px] truncate text-text hover:text-blue"
                >
                  {project?.name ?? "未归档"}
                </Link>
              </div>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-muted">当前负责人</span>
                <span className="flex items-center gap-1.5 text-text">
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: currentAgent.accent }}
                  />
                  {currentAgent.name}
                </span>
              </div>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-muted">任务状态</span>
                <span style={{ color: TASK_STATUS_META[task.status].color }}>
                  {TASK_STATUS_META[task.status].label}
                </span>
              </div>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-muted">人工修订</span>
                <span className="text-text">{task.revisionCount} 次</span>
              </div>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-muted">数据来源</span>
                <span className="text-text">
                  {task.demo ? "本地演示适配器" : "后端 /api/v1/tasks"}
                </span>
              </div>
              {task.backendState ? (
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-muted">后端状态</span>
                  <span style={{ color: BACKEND_STATE_META[task.backendState].color }}>
                    {task.backendState} · {BACKEND_STATE_META[task.backendState].label}
                  </span>
                </div>
              ) : null}
              {task.queuePosition !== null ? (
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-muted">队列位置</span>
                  <span className="text-text">第 {task.queuePosition} 位</span>
                </div>
              ) : null}
              {task.usage ? (
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-muted">模型用量</span>
                  <span className="tabular-nums text-text">
                    {task.usage.totalTokens !== null
                      ? `${task.usage.totalTokens.toLocaleString()} tokens`
                      : `${task.usage.callsCompleted}/${task.usage.callsReserved} 次调用`}
                  </span>
                </div>
              ) : null}
              <div className="border-t border-line pt-3 text-[10px] leading-5 text-muted">
                后端契约 seven-agent.v0.1 共 7 个角色：pr_analyst / operations_officer /
                traffic_scout / content_creator / editorial_reviewer / simulated_audience /
                data_analyst。前端只投影状态，不改变后端业务语义。
              </div>
            </CardBody>
          </Card>

          {task.status === "waiting_approval" ? (
            <Button
              variant="danger"
              size="sm"
              className="w-full"
              icon={<XCircle size={13} />}
              onClick={() => {
                prepareDecision();
                setRejectNote("");
                setRejectOpen(true);
              }}
            >
              {isBriefGate ? "取消本次任务" : "拒绝本次成果"}
            </Button>
          ) : null}

          {task.status === "cancelled" || task.status === "failed" ? (
            <Button
              variant="secondary"
              className="w-full"
              icon={<RefreshCw size={14} />}
              onClick={() => navigate("/workspace/tasks")}
            >
              回到任务中心
            </Button>
          ) : null}
        </div>
      </div>

      <Modal
        open={approveOpen}
        onClose={() => { if (!pending) setApproveOpen(false); }}
        title={isBriefGate ? "确认任务书" : "审阅并批准"}
        description={
          isBriefGate
            ? "确认后任务进入后端队列，由内容主创依据这份 Brief 开始创作。"
            : isDemo
              ? "批准后内容会保存为项目资产。你可以在批准前直接修改文本。"
              : "批准只作用于后端冻结的 READY 版本；如需改动，请先退回内容主创生成新版本。"
        }
        size="lg"
        footer={
          <>
            <Button variant="ghost" disabled={pending} onClick={() => setApproveOpen(false)}>
              取消
            </Button>
            <Button
              variant="primary"
              icon={<Check size={14} />}
              onClick={() => void confirmApprove()}
              disabled={pending || targetChanged || !canApprove || (!isBriefGate && isDemo && !bodyDraft.trim())}
            >
              {pending
                ? "正在保存…"
                : isBriefGate
                  ? "确认并开始创作"
                  : "确认批准"}
            </Button>
          </>
        }
      >
        {dialogError ? <p role="alert" className="mb-4 text-xs text-red">{dialogError}</p> : null}
        {isBriefGate ? (
          <dl className="space-y-3">
            {[
              ["创作想法", task.brief.idea || "未填写"],
              ["目标读者", task.brief.audience || "未填写"],
              ["内容形式", task.brief.format],
              ["时长 / 篇幅", task.brief.duration],
              ["语气", task.brief.tone.join(" / ") || "未填写"],
              ["模拟观众试映", task.previewRequested ? "生成后运行" : "不运行"],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-line bg-raised/60 p-3">
                <dt className="text-[10px] uppercase tracking-[0.12em] text-muted">
                  {label}
                </dt>
                <dd className="mt-1 text-[13px] leading-6 text-text/90">{value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <label className="block">
            <span className="mb-1.5 flex items-center justify-between text-xs font-medium">
              最终交付文本
              <span className="text-[10px] font-normal text-muted">
                {bodyDraft.length} 字
              </span>
            </span>
            <textarea
              value={bodyDraft}
              onChange={(event) => setBodyDraft(event.target.value)}
              readOnly={!isDemo}
              rows={16}
              className="w-full resize-y rounded-xl border border-line bg-ink/60 px-4 py-3 font-sans text-[13px] leading-7 text-text focus:border-blue/60 focus:outline-none read-only:text-muted"
            />
            {!isDemo ? (
              <span className="mt-1.5 block text-[10px] leading-5 text-muted">
                真实接口模式下此文本只读：验收会按后端版本哈希提交，不会把界面改写写回后端。
              </span>
            ) : null}
          </label>
        )}
      </Modal>

      <Modal
        open={reviseOpen}
        onClose={() => { if (!pending) setReviseOpen(false); }}
        title={isBriefGate ? "退回 Brief 重新规划" : "退回内容主创"}
        description={
          isBriefGate
            ? isDemo ? "运营官会按你的意见重新规划任务书。" : "修改意见会加入新版任务书，保存后请再次确认。"
            : "任务会回到内容创作阶段，由内容主创按你的意见做定向修订。"
        }
        size="lg"
        footer={
          <>
            <Button variant="ghost" disabled={pending} onClick={() => setReviseOpen(false)}>
              取消
            </Button>
            <Button
              variant="primary"
              icon={<RotateCcw size={14} />}
              onClick={() => void confirmRevise()}
              disabled={pending || targetChanged || (!isDemo && !reviseNote.trim())}
            >
              {pending ? "正在退回…" : "确认退回"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {dialogError ? <p role="alert" className="text-xs text-red">{dialogError}</p> : null}
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium">修改意见</span>
            <textarea
              value={reviseNote}
              maxLength={1000}
              onChange={(event) => setReviseNote(event.target.value)}
              rows={4}
              placeholder="例如：开场再具体一点，把「三个动作」提前，删掉最后一段自我表达。"
              className="w-full resize-y rounded-xl border border-line bg-raised px-4 py-3 text-sm leading-6 text-text placeholder:text-muted/60 focus:border-blue/60 focus:outline-none"
            />
          </label>
          {isBriefGate || !isDemo ? null : (
            <label className="block">
              <span className="mb-1.5 block text-xs font-medium">
                或者直接改写脚本（可选）
              </span>
              <textarea
                value={reviseBody}
                onChange={(event) => setReviseBody(event.target.value)}
                rows={10}
                className="w-full resize-y rounded-xl border border-line bg-ink/60 px-4 py-3 font-sans text-[13px] leading-7 text-text focus:border-blue/60 focus:outline-none"
              />
            </label>
          )}
          {!isBriefGate && !isDemo ? (
            <p className="rounded-xl border border-amber/25 bg-amber/[0.06] px-3 py-2 text-[10px] leading-5 text-muted">
              修改意见会交给内容主创。完成后会生成新版本，供你重新验收。
            </p>
          ) : null}
        </div>
      </Modal>

      <Modal
        open={rejectOpen}
        onClose={() => { if (!pending) setRejectOpen(false); }}
        title="拒绝本次成果"
        description="任务会被取消。这个操作不会删除项目或已有资产。"
        size="sm"
        footer={
          <>
            <Button variant="ghost" disabled={pending} onClick={() => setRejectOpen(false)}>
              取消
            </Button>
            <Button
              variant="danger"
              onClick={() => void confirmReject()}
              disabled={pending || targetChanged}
            >
              {pending ? "正在取消…" : "确认拒绝"}
            </Button>
          </>
        }
      >
        {dialogError ? <p role="alert" className="mb-3 text-xs text-red">{dialogError}</p> : null}
        {isDemo ? <label className="block">
          <span className="mb-1.5 block text-xs font-medium">
            原因（可选）
          </span>
          <textarea
            value={rejectNote}
            onChange={(event) => setRejectNote(event.target.value)}
            rows={4}
            placeholder="记录这次没有采用的原因，便于下次调整方向。"
            className="w-full resize-y rounded-xl border border-line bg-raised px-4 py-3 text-sm leading-6 text-text placeholder:text-muted/60 focus:border-blue/60 focus:outline-none"
          />
        </label> : null}
      </Modal>
    </div>
  );
}
