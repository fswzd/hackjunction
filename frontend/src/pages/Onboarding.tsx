import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, Sparkles } from "lucide-react";
import type { Profile } from "@/domain/types";
import {
  CREATOR_STAGES,
  creatorStageMeta,
  normalizeCreatorStage,
} from "@/domain/profile";
import { useWorkspace } from "@/store/workspace";
import { Button } from "@/components/ui/Button";
import { BrandMark } from "@/components/brand/BrandMark";
import { AccountConnect } from "@/components/accounts/AccountConnect";
import { cn } from "@/lib/format";

const INDUSTRIES = [
  "内容创作者 / 自媒体",
  "电商与零售",
  "教育与培训",
  "科技与 SaaS",
  "生活方式",
  "娱乐与媒体",
  "健康与健身",
  "其他",
];

const FORMATS = ["短视频", "图文", "长视频", "播客", "直播"];

const TONES = [
  "温和真诚",
  "清晰直接",
  "克制专业",
  "幽默轻松",
  "有画面感",
  "高信息密度",
];

const GOALS = [
  "稳定更新",
  "提升选题命中率",
  "打磨内容质量",
  "建立个人品牌",
  "提高制作效率",
];

const STEPS = [
  { title: "你的身份", en: "Identity" },
  { title: "创作领域", en: "Niche" },
  { title: "你的读者", en: "Audience" },
  { title: "语气与目标", en: "Voice & Goals" },
];

const EMPTY: Profile = {
  creatorName: "",
  workspaceName: "",
  creatorStage: "starting",
  industry: INDUSTRIES[0],
  niche: "",
  audience: "",
  formats: [FORMATS[0]],
  tone: [TONES[0]],
  goals: [GOALS[0]],
  completedAt: "",
};

function toggleValue(
  list: string[],
  value: string,
  fallback: string,
): string[] {
  if (list.includes(value)) {
    const next = list.filter((item) => item !== value);
    return next.length ? next : [fallback];
  }
  return [...list, value];
}

export function Onboarding() {
  const navigate = useNavigate();
  const existing = useWorkspace((state) => state.snapshot?.profile);
  const mode = useWorkspace((state) => state.mode);
  const completeOnboarding = useWorkspace((state) => state.completeOnboarding);
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<Profile>(existing ?? EMPTY);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [prefilled, setPrefilled] = useState(false);
  // `creatorStage` always has a display value, but we still require one
  // intentional click during onboarding. Returning profiles are already chosen.
  const [stageChosen, setStageChosen] = useState(
    Boolean(existing?.creatorStage),
  );

  useEffect(() => {
    if (existing && !prefilled) {
      setForm({
        ...EMPTY,
        ...existing,
        creatorStage: normalizeCreatorStage(existing.creatorStage),
      });
      setStageChosen(Boolean(existing.creatorStage));
      setPrefilled(true);
    }
  }, [existing, prefilled]);

  const update = (patch: Partial<Profile>) =>
    setForm((current) => ({ ...current, ...patch }));

  const canContinue = useMemo(() => {
    if (step === 0) {
      return Boolean(
        form.creatorName.trim() &&
          form.workspaceName.trim() &&
          stageChosen,
      );
    }
    if (step === 1) return Boolean(form.industry);
    if (step === 2) return Boolean(form.audience.trim() && form.formats.length);
    return form.tone.length > 0 && form.goals.length > 0;
  }, [step, form, stageChosen]);

  const finish = async (profile: Profile = form) => {
    setSaving(true);
    setError("");
    try {
      await completeOnboarding({
        ...profile,
        creatorName: profile.creatorName.trim() || "创作者",
        workspaceName: profile.workspaceName.trim() || "我的内容工作室",
        creatorStage: normalizeCreatorStage(profile.creatorStage),
        completedAt: new Date().toISOString(),
      });
      navigate("/workspace/overview", { replace: true });
    } catch {
      setError("保存失败，请重试。");
      setSaving(false);
    }
  };

  const next = () => {
    if (!canContinue) {
      setError(
        step === 0
          ? "请填写你的名字、工作空间名称，并选择你当前的账号阶段。"
          : step === 2
            ? "请描述你的目标读者，并至少选择一种内容形式。"
            : "请至少选择一项。",
      );
      return;
    }
    setError("");
    if (step < STEPS.length - 1) {
      setStep((value) => value + 1);
    } else {
      void finish();
    }
  };

  const fillExample = () => {
    setForm({
      creatorName: "林知夏",
      workspaceName: "知夏的内容工作室",
      creatorStage: "operating",
      industry: "内容创作者 / 自媒体",
      niche: "人像摄影与轻量创作方法",
      audience: "第一次拿起相机、想拍出自然感的摄影爱好者",
      formats: ["图文", "短视频"],
      tone: ["温和真诚", "有画面感"],
      goals: ["稳定更新", "打磨内容质量"],
      completedAt: "",
    });
    setStageChosen(true);
    setError("");
  };

  return (
    <div className="flex min-h-screen bg-ink">
      <aside className="relative hidden w-[42%] max-w-[560px] flex-col justify-between overflow-hidden border-r border-line bg-surface p-10 lg:flex">
        <div className="inner-grid absolute inset-0 opacity-60" />
        <div className="relative">
          <div className="flex items-center gap-3">
            <BrandMark size={36} />
            <div>
              <p className="studio-brand text-lg">众幕 AI</p>
              <p className="studio-subtitle">一人内容工作室</p>
            </div>
          </div>

          <h1 className="mt-16 text-balance text-4xl font-semibold leading-[1.15] tracking-tight">
            一个人，
            <br />
            也有一支内容团队。
          </h1>
          <p className="mt-5 max-w-sm text-sm leading-7 text-muted">
            先告诉我们你在做什么、说给谁听。
            从任务书到交付稿，让创作、审稿与修改有据可循。
          </p>
        </div>

        <div className="relative mt-12">
          <div className="relative mx-auto h-56 w-56">
            <span className="absolute inset-0 rounded-full border border-blue/25" />
            <span className="absolute inset-5 rounded-full border border-violet/25" />
            <span className="absolute inset-10 rounded-full border border-cyan/20" />
            <span className="absolute inset-0 animate-spin-slow rounded-full border border-dashed border-blue/20" />
            <span className="absolute left-1/2 top-1/2 h-20 w-20 -translate-x-1/2 -translate-y-1/2 rounded-full bg-blue/15 blur-xl" />
            <span className="absolute left-1/2 top-1/2 h-10 w-10 -translate-x-1/2 -translate-y-1/2 rounded-full border border-blue/40 bg-surface" />
          </div>
          <ul className="mt-10 space-y-3">
            {STEPS.map((item, index) => (
              <li key={item.en} className="flex items-center gap-3 text-xs">
                <span
                  className={cn(
                    "flex h-6 w-6 items-center justify-center rounded-full border text-[10px]",
                    index < step
                      ? "border-green/40 bg-green/10 text-green"
                      : index === step
                        ? "border-blue/50 bg-blue/12 text-blue"
                        : "border-line text-muted",
                  )}
                >
                  {index < step ? <Check size={12} /> : index + 1}
                </span>
                <span className={index <= step ? "text-text" : "text-muted"}>
                  {item.title}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-[10px] leading-5 text-muted">
          {mode === "demo"
            ? "演示模式：信息仅保存在本地浏览器，不会上传。"
            : "真实接口模式：名字、工作空间与账号阶段会写入本地后端；其他画像字段保存在浏览器。"}
        </p>
      </aside>

      <main className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-line px-5 py-4 sm:px-8">
          <div className="flex items-center gap-2.5 lg:hidden">
            <BrandMark size={28} />
            <span className="studio-brand text-base">众幕 AI</span>
          </div>
          <div className="hidden items-center gap-2 lg:flex">
            {STEPS.map((item, index) => (
              <span
                key={item.en}
                className={cn(
                  "h-1 w-10 rounded-full transition-colors",
                  index <= step ? "bg-blue" : "bg-line",
                )}
              />
            ))}
          </div>
          <div className="flex items-center gap-2">
            {existing ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => navigate("/workspace/overview")}
              >
                返回工作台
              </Button>
            ) : null}
            <Button
              variant="ghost"
              size="sm"
              icon={<Sparkles size={13} />}
              onClick={fillExample}
            >
              使用示例身份
            </Button>
          </div>
        </header>

        <div className="flex flex-1 items-center justify-center px-5 py-10 sm:px-8">
          <div className="w-full max-w-2xl">
            <p className="text-[11px] tracking-[0.16em] text-muted">
              第 {step + 1} 步 / {STEPS.length} · {STEPS[step].title}
            </p>
            <h2 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">
              {step === 0
                ? "先认识一下你。"
                : step === 1
                  ? "你主要在创作什么？"
                  : step === 2
                    ? "这条内容，说给谁听？"
                    : "你希望团队怎么配合你？"}
            </h2>
            <p className="mt-2 text-sm leading-6 text-muted">
              {step === 0
                ? "这些信息会显示在你的内容工作室里，也用于任务书的默认称呼；账号阶段会同步到本地后端。"
                : step === 1
                  ? "领域会影响选题捕捉与内容创作的默认方向，可以随时在设置里修改。"
                  : step === 2
                    ? "越具体，Brief 与候选稿越能贴近真实读者。"
                    : "语气和目标会写进 Brief，并作为独立审稿的参考。"}
            </p>

            <div className="mt-8">
              {step === 0 ? (
                <div className="space-y-5">
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-medium">
                      你的名字
                    </span>
                    <input
                      value={form.creatorName}
                      onChange={(event) =>
                        update({ creatorName: event.target.value })
                      }
                      maxLength={40}
                      placeholder="例如：林知夏"
                      className="h-12 w-full rounded-xl border border-line bg-raised px-4 text-sm text-text placeholder:text-muted/60 focus:border-blue/60 focus:outline-none"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-medium">
                      工作空间名称
                    </span>
                    <input
                      value={form.workspaceName}
                      onChange={(event) =>
                        update({ workspaceName: event.target.value })
                      }
                      maxLength={60}
                      placeholder="例如：知夏的内容工作室"
                      className="h-12 w-full rounded-xl border border-line bg-raised px-4 text-sm text-text placeholder:text-muted/60 focus:border-blue/60 focus:outline-none"
                    />
                  </label>

                  <fieldset>
                    <legend className="mb-1.5 block text-xs font-medium">
                      你现在的账号阶段
                    </legend>
                    <p className="mb-3 text-[11px] leading-5 text-muted">
                      这会影响团队默认的选题、Brief 与协作节奏，之后可以在设置里修改。
                    </p>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                      {CREATOR_STAGES.map((stage) => {
                        const active = stageChosen && form.creatorStage === stage.id;
                        return (
                          <button
                            key={stage.id}
                            type="button"
                            onClick={() => {
                              update({ creatorStage: stage.id });
                              setStageChosen(true);
                            }}
                            aria-pressed={active}
                            className={cn(
                              "rounded-xl border p-3 text-left transition",
                              active
                                ? "border-blue/50 bg-blue/10 text-text"
                                : "border-line bg-raised text-muted hover:border-[#43506a] hover:text-text",
                            )}
                          >
                            <span className="block text-xs font-medium">
                              {stage.label}
                            </span>
                            <span className="mt-1 block text-[11px] leading-5">
                              {stage.description}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                    <p className="mt-2 text-[11px] leading-5 text-muted">
                      {creatorStageMeta(form.creatorStage).hint}
                    </p>
                  </fieldset>

                  {form.creatorStage !== "starting" ? (
                    <div className="rounded-xl border border-line bg-raised/40 p-4">
                      <AccountConnect />
                    </div>
                  ) : null}
                </div>
              ) : null}

              {step === 1 ? (
                <div className="space-y-5">
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {INDUSTRIES.map((item) => (
                      <button
                        key={item}
                        type="button"
                        onClick={() => update({ industry: item })}
                        aria-pressed={form.industry === item}
                        className={cn(
                          "rounded-xl border px-3 py-3 text-left text-[11px] leading-5 transition",
                          form.industry === item
                            ? "border-blue/50 bg-blue/10 text-text"
                            : "border-line bg-raised text-muted hover:border-[#43506a] hover:text-text",
                        )}
                      >
                        {item}
                      </button>
                    ))}
                  </div>
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-medium">
                      具体方向（可选）
                    </span>
                    <input
                      value={form.niche}
                      onChange={(event) => update({ niche: event.target.value })}
                      maxLength={80}
                      placeholder="例如：人像摄影与轻量创作方法"
                      className="h-12 w-full rounded-xl border border-line bg-raised px-4 text-sm text-text placeholder:text-muted/60 focus:border-blue/60 focus:outline-none"
                    />
                  </label>
                </div>
              ) : null}

              {step === 2 ? (
                <div className="space-y-5">
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-medium">
                      目标读者
                    </span>
                    <textarea
                      value={form.audience}
                      onChange={(event) =>
                        update({ audience: event.target.value })
                      }
                      rows={3}
                      maxLength={200}
                      placeholder="例如：第一次拿起相机、想拍出自然感的摄影爱好者"
                      className="w-full resize-y rounded-xl border border-line bg-raised px-4 py-3 text-sm leading-6 text-text placeholder:text-muted/60 focus:border-blue/60 focus:outline-none"
                    />
                  </label>
                  <fieldset>
                    <legend className="mb-2 text-xs font-medium">
                      常用内容形式
                    </legend>
                    <div className="flex flex-wrap gap-2">
                      {FORMATS.map((item) => (
                        <button
                          key={item}
                          type="button"
                          onClick={() =>
                            update({
                              formats: toggleValue(form.formats, item, FORMATS[0]),
                            })
                          }
                          aria-pressed={form.formats.includes(item)}
                          className={cn(
                            "rounded-lg border px-4 py-2 text-xs transition",
                            form.formats.includes(item)
                              ? "border-cyan/45 bg-cyan/10 text-cyan"
                              : "border-line bg-raised text-muted hover:text-text",
                          )}
                        >
                          {item}
                        </button>
                      ))}
                    </div>
                  </fieldset>
                </div>
              ) : null}

              {step === 3 ? (
                <div className="space-y-6">
                  <fieldset>
                    <legend className="mb-2 text-xs font-medium">
                      语气偏好（可多选）
                    </legend>
                    <div className="flex flex-wrap gap-2">
                      {TONES.map((item) => (
                        <button
                          key={item}
                          type="button"
                          onClick={() =>
                            update({
                              tone: toggleValue(form.tone, item, TONES[0]),
                            })
                          }
                          aria-pressed={form.tone.includes(item)}
                          className={cn(
                            "rounded-lg border px-4 py-2 text-xs transition",
                            form.tone.includes(item)
                              ? "border-violet/45 bg-violet/10 text-violet"
                              : "border-line bg-raised text-muted hover:text-text",
                          )}
                        >
                          {item}
                        </button>
                      ))}
                    </div>
                  </fieldset>
                  <fieldset>
                    <legend className="mb-2 text-xs font-medium">
                      你最想解决什么？（可多选）
                    </legend>
                    <div className="flex flex-wrap gap-2">
                      {GOALS.map((item) => (
                        <button
                          key={item}
                          type="button"
                          onClick={() =>
                            update({
                              goals: toggleValue(form.goals, item, GOALS[0]),
                            })
                          }
                          aria-pressed={form.goals.includes(item)}
                          className={cn(
                            "rounded-lg border px-4 py-2 text-xs transition",
                            form.goals.includes(item)
                              ? "border-blue/45 bg-blue/10 text-blue"
                              : "border-line bg-raised text-muted hover:text-text",
                          )}
                        >
                          {item}
                        </button>
                      ))}
                    </div>
                  </fieldset>
                  <div className="rounded-xl border border-line bg-raised/60 p-4">
                    <p className="text-[11px] font-medium text-text">
                      即将创建的工作空间
                    </p>
                    <p className="mt-1 text-sm">{form.workspaceName}</p>
                    <p className="mt-1 text-[11px] leading-5 text-muted">
                      阶段：{creatorStageMeta(form.creatorStage).label}
                      <br />
                      {form.industry}
                      {form.niche ? ` · ${form.niche}` : ""}
                      <br />
                      读者：{form.audience || "未填写"}
                      <br />
                      形式：{form.formats.join(" / ")} · 语气：
                      {form.tone.join(" / ")}
                    </p>
                  </div>
                </div>
              ) : null}
            </div>

            {error ? (
              <p role="alert" className="mt-4 text-xs text-red">
                {error}
              </p>
            ) : null}

            <div className="mt-8 flex items-center justify-between gap-3">
              <Button
                variant="ghost"
                icon={<ArrowLeft size={14} />}
                onClick={() => setStep((value) => Math.max(0, value - 1))}
                disabled={step === 0}
              >
                上一步
              </Button>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  onClick={() => void finish({ ...form, completedAt: "" })}
                  disabled={saving}
                >
                  跳过
                </Button>
                <Button
                  variant="primary"
                  onClick={next}
                  disabled={saving}
                  icon={step === STEPS.length - 1 ? undefined : <ArrowRight size={14} />}
                >
                  {saving
                    ? "正在保存…"
                    : step === STEPS.length - 1
                      ? "走进协作现场"
                      : "继续"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
