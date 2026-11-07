import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { useWorkspace } from "@/store/workspace";
import { creatorStageMeta } from "@/domain/profile";
import { cn } from "@/lib/format";

const FORMATS = ["短视频", "图文", "长视频", "播客"];
const DURATIONS = ["30 秒", "60 秒", "90 秒", "3 分钟", "800 字"];
const TONES = ["清晰", "克制", "有信息密度", "温和", "有画面感", "直接", "不说教"];

const EXAMPLE = {
  title: "5 款 AI 效率工具，大学生 60 秒看懂",
  idea: "介绍 2026 年最值得大学生使用的 5 款 AI 效率工具，强调真实使用场景，不做参数堆砌。",
  audience: "大学生与刚入职场的年轻人",
  format: "短视频",
  duration: "60 秒",
  tone: ["清晰", "有信息密度"],
};

export function NewTaskDialog() {
  const open = useWorkspace((state) => state.newTaskOpen);
  const openNewTask = useWorkspace((state) => state.openNewTask);
  const createTask = useWorkspace((state) => state.createTask);
  const projects = useWorkspace((state) => state.snapshot?.projects ?? []);
  const profile = useWorkspace((state) => state.snapshot?.profile);
  const mode = useWorkspace((state) => state.mode);
  const stage = creatorStageMeta(profile?.creatorStage);
  const navigate = useNavigate();

  const [title, setTitle] = useState("");
  const [idea, setIdea] = useState("");
  const [audience, setAudience] = useState("");
  const [format, setFormat] = useState(FORMATS[0]);
  const [duration, setDuration] = useState(DURATIONS[1]);
  const [tone, setTone] = useState<string[]>(["清晰"]);
  const [projectId, setProjectId] = useState("");
  const [previewRequested, setPreviewRequested] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTitle("");
    setIdea("");
    setAudience("");
    setFormat(FORMATS[0]);
    setDuration(DURATIONS[1]);
    setTone(["清晰"]);
    setProjectId(projects[0]?.id ?? "");
    setPreviewRequested(false);
    setError("");
    setSubmitting(false);
  }, [open, projects]);

  const toggleTone = (value: string) => {
    setTone((current) =>
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    );
  };

  const fillExample = () => {
    setTitle(EXAMPLE.title);
    setIdea(EXAMPLE.idea);
    setAudience(EXAMPLE.audience);
    setFormat(EXAMPLE.format);
    setDuration(EXAMPLE.duration);
    setTone(EXAMPLE.tone);
    setError("");
  };

  const submit = async () => {
    if (!title.trim() || !idea.trim() || !audience.trim()) {
      setError("请填写任务标题、创作想法和目标受众。");
      return;
    }
    setSubmitting(true);
    await createTask({
      title,
      idea,
      audience,
      format,
      duration,
      tone,
      projectId,
      previewRequested,
    });
    setSubmitting(false);
    openNewTask(false);
    const newest = useWorkspace.getState().snapshot?.tasks[0];
    if (newest) {
      navigate(`/workspace/tasks/${newest.id}`);
    }
  };

  return (
    <Modal
      open={open}
      onClose={() => openNewTask(false)}
      title="发起一个创作任务"
      description="说明你想表达什么、说给谁听。运营官会先整理 Brief，等你确认后再派发给内容主创。"
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => openNewTask(false)}>
            取消
          </Button>
          <Button variant="primary" onClick={submit} disabled={submitting}>
            {submitting ? "正在创建…" : "创建任务"}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-blue/20 bg-blue/5 px-4 py-3">
          <p className="text-[11px] leading-5 text-muted">
            {mode === "demo" ? (
              <>
                当前为<b className="text-text">演示模式</b>：任务由本地适配层按阶段推进，
                用于展示 2D / 3D 状态联动，不代表真实模型调用。
              </>
            ) : (
              <>
                当前为<b className="text-text">真实接口模式</b>：任务提交到
                <code className="mx-1">POST /api/v1/tasks</code>，由后端推进。
                到达人工节点后，Brief 确认、内容验收与退回会写入本地后端。
              </>
            )}
          </p>
          <Button
            variant="ghost"
            size="sm"
            icon={<Sparkles size={13} />}
            onClick={fillExample}
          >
            填入示例
          </Button>
        </div>

        <div className="flex items-start gap-2 rounded-xl border border-line bg-raised/40 px-3.5 py-2.5">
          <span className="mt-0.5 shrink-0 rounded-full border border-blue/30 bg-blue/10 px-2 py-0.5 text-[10px] font-medium text-blue">
            {stage.label}
          </span>
          <p className="text-[11px] leading-5 text-muted">{stage.hint}</p>
        </div>

        <label className="block">
          <span className="mb-1.5 block text-xs font-medium text-text">
            任务标题
          </span>
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={80}
            placeholder="例如：5 款 AI 效率工具，大学生 60 秒看懂"
            className="h-11 w-full rounded-xl border border-line bg-raised px-3.5 text-sm text-text placeholder:text-muted/60 focus:border-blue/60 focus:outline-none"
          />
        </label>

        <label className="block">
          <span className="mb-1.5 block text-xs font-medium text-text">
            创作想法
          </span>
          <textarea
            value={idea}
            onChange={(event) => setIdea(event.target.value)}
            rows={4}
            maxLength={1200}
            placeholder="你真正想表达什么？有哪些素材、经验或限制条件？"
            className="w-full resize-y rounded-xl border border-line bg-raised px-3.5 py-3 text-sm leading-6 text-text placeholder:text-muted/60 focus:border-blue/60 focus:outline-none"
          />
        </label>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-text">
              目标受众
            </span>
            <input
              value={audience}
              onChange={(event) => setAudience(event.target.value)}
              maxLength={100}
              placeholder="例如：第一次拍人像的摄影爱好者"
              className="h-11 w-full rounded-xl border border-line bg-raised px-3.5 text-sm text-text placeholder:text-muted/60 focus:border-blue/60 focus:outline-none"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-text">
              内容项目
            </span>
            <select
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
              className="h-11 w-full rounded-xl border border-line bg-raised px-3 text-sm text-text focus:border-blue/60 focus:outline-none"
            >
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <fieldset>
            <legend className="mb-1.5 text-xs font-medium text-text">
              内容形式
            </legend>
            <div className="flex flex-wrap gap-1.5">
              {FORMATS.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setFormat(item)}
                  aria-pressed={format === item}
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-[11px] transition",
                    format === item
                      ? "border-blue/50 bg-blue/12 text-blue"
                      : "border-line bg-raised text-muted hover:text-text",
                  )}
                >
                  {item}
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend className="mb-1.5 text-xs font-medium text-text">
              目标时长
            </legend>
            <div className="flex flex-wrap gap-1.5">
              {DURATIONS.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setDuration(item)}
                  aria-pressed={duration === item}
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-[11px] transition",
                    duration === item
                      ? "border-blue/50 bg-blue/12 text-blue"
                      : "border-line bg-raised text-muted hover:text-text",
                  )}
                >
                  {item}
                </button>
              ))}
            </div>
          </fieldset>
        </div>

        {mode === "api" ? (
          <p className="rounded-xl border border-amber/25 bg-amber/[0.06] px-3.5 py-2.5 text-[10px] leading-5 text-muted">
            后端 CreateTask 目前只接受 <code>format: "text"</code>。内容形式与目标时长会写入
            requirements 文本，作为内容主创的创作约束。
          </p>
        ) : null}

        <fieldset>
          <legend className="mb-1.5 text-xs font-medium text-text">
            语气偏好
          </legend>
          <div className="flex flex-wrap gap-1.5">
            {TONES.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => toggleTone(item)}
                aria-pressed={tone.includes(item)}
                className={cn(
                  "rounded-lg border px-3 py-1.5 text-[11px] transition",
                  tone.includes(item)
                    ? "border-violet/50 bg-violet/12 text-violet"
                    : "border-line bg-raised text-muted hover:text-text",
                )}
              >
                {item}
              </button>
            ))}
          </div>
        </fieldset>

        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-raised/50 p-3.5">
          <input
            type="checkbox"
            checked={previewRequested}
            onChange={(event) => setPreviewRequested(event.target.checked)}
            className="mt-0.5 h-4 w-4 accent-[#83B8FF]"
          />
          <span>
            <span className="block text-xs font-medium text-text">
              生成后运行模拟观众试映
            </span>
            <span className="mt-0.5 block text-[10px] leading-5 text-muted">
              对应后端 CreateTask.preview_requested。试映会调用模拟观众与数据分析师，
              在内容验收前补充逐段阅读和诊断建议。
            </span>
          </span>
        </label>

        {error ? (
          <p role="alert" className="text-xs text-red">
            {error}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}
