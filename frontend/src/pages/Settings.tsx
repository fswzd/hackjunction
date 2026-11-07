import { useEffect, useState } from "react";
import {
  Boxes,
  CheckCircle2,
  Database,
  MonitorCog,
  RotateCcw,
  Save,
  Server,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import type { Profile } from "@/domain/types";
import { CREATOR_STAGES, creatorStageMeta } from "@/domain/profile";
import { cn } from "@/lib/format";
import { useWorkspace } from "@/store/workspace";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { SectionHeader } from "@/components/ui/SectionHeader";

function Switch({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  description: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0">
        <p className="text-xs font-medium text-text">{label}</p>
        <p className="mt-0.5 text-[10px] leading-5 text-muted">{description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors",
          checked
            ? "border-blue/50 bg-blue/70"
            : "border-line bg-raised",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-3.5 w-3.5 rounded-full bg-surface transition-all",
            checked ? "left-[18px] bg-ink" : "left-0.5 bg-muted",
          )}
        />
      </button>
    </div>
  );
}

function Row({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-line/50 py-2.5 last:border-0">
      <span className="text-[11px] text-muted">{label}</span>
      <span
        className="max-w-[60%] truncate text-right text-[11px]"
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </span>
    </div>
  );
}

const EMPTY: Profile = {
  creatorName: "",
  workspaceName: "",
  creatorStage: "starting",
  industry: "",
  niche: "",
  audience: "",
  formats: [],
  tone: [],
  goals: [],
  completedAt: "",
};

export function Settings() {
  const snapshot = useWorkspace((state) => state.snapshot);
  const mode = useWorkspace((state) => state.mode);
  const autoplay = useWorkspace((state) => state.autoplay);
  const setAutoplay = useWorkspace((state) => state.setAutoplay);
  const setMode = useWorkspace((state) => state.setMode);
  const setImmersive = useWorkspace((state) => state.setImmersive);
  const completeOnboarding = useWorkspace((state) => state.completeOnboarding);
  const resetDemo = useWorkspace((state) => state.resetDemo);
  const showToast = useWorkspace((state) => state.showToast);

  const [form, setForm] = useState<Profile>(snapshot?.profile ?? EMPTY);
  const [saving, setSaving] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    if (snapshot?.profile) setForm(snapshot.profile);
  }, [snapshot?.profile]);

  if (!snapshot) return null;
  const apiBase =
    import.meta.env.VITE_API_BASE || "同源 /api 代理 → http://127.0.0.1:5001";

  const update = (patch: Partial<Profile>) =>
    setForm((current) => ({ ...current, ...patch }));

  const save = async () => {
    if (!form.creatorName.trim() || !form.workspaceName.trim()) {
      showToast("名字与工作空间名称不能为空。", "error");
      return;
    }
    setSaving(true);
    try {
      await completeOnboarding({
        ...form,
        completedAt: form.completedAt || new Date().toISOString(),
      });
      showToast("工作空间信息已保存。", "success");
    } catch {
      showToast("保存失败，请重试。", "error");
    } finally {
      setSaving(false);
    }
  };

  const switchMode = async (next: "demo" | "api") => {
    if (next === mode || switching) return;
    setSwitching(true);
    await setMode(next);
    setSwitching(false);
  };

  const confirmReset = async () => {
    setResetting(true);
    try {
      await resetDemo();
      setResetOpen(false);
    } catch {
      showToast("重置失败，请重试。", "error");
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="space-y-5">
      <SectionHeader
        eyebrow="设置"
        title="设置"
        description="工作空间画像、数据来源与体验偏好。所有演示数据只保存在这台设备的浏览器里。"
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div>
                <h2 className="text-sm font-semibold">工作空间信息</h2>
                <p className="mt-0.5 text-[11px] text-muted">
                  这些字段会进入任务 Brief 的默认称呼与研究方向
                </p>
              </div>
              <Sparkles size={14} className="text-violet" />
            </CardHeader>
            <CardBody className="space-y-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-1.5 block text-[11px] font-medium">
                    创作者名字
                  </span>
                  <input
                    value={form.creatorName}
                    onChange={(event) =>
                      update({ creatorName: event.target.value })
                    }
                    maxLength={40}
                    className="h-10 w-full rounded-xl border border-line bg-raised px-3 text-xs text-text focus:border-blue/60 focus:outline-none"
                  />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-[11px] font-medium">
                    工作空间名称
                  </span>
                  <input
                    value={form.workspaceName}
                    onChange={(event) =>
                      update({ workspaceName: event.target.value })
                    }
                    maxLength={60}
                    className="h-10 w-full rounded-xl border border-line bg-raised px-3 text-xs text-text focus:border-blue/60 focus:outline-none"
                  />
                </label>
              </div>
              <fieldset>
                <legend className="mb-1.5 block text-[11px] font-medium">
                  账号阶段
                </legend>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  {CREATOR_STAGES.map((stage) => (
                    <button
                      key={stage.id}
                      type="button"
                      onClick={() => update({ creatorStage: stage.id })}
                      aria-pressed={form.creatorStage === stage.id}
                      className={cn(
                        "rounded-xl border p-3 text-left transition",
                        form.creatorStage === stage.id
                          ? "border-blue/50 bg-blue/10 text-text"
                          : "border-line bg-raised text-muted hover:border-[#43506a] hover:text-text",
                      )}
                    >
                      <span className="block text-xs font-medium">
                        {stage.label}
                      </span>
                      <span className="mt-1 block text-[10px] leading-5">
                        {stage.description}
                      </span>
                    </button>
                  ))}
                </div>
                <p className="mt-2 text-[10px] leading-5 text-muted">
                  {creatorStageMeta(form.creatorStage).hint}
                </p>
              </fieldset>
              <label className="block">
                <span className="mb-1.5 block text-[11px] font-medium">
                  创作领域
                </span>
                <input
                  value={form.industry}
                  onChange={(event) => update({ industry: event.target.value })}
                  maxLength={60}
                  className="h-10 w-full rounded-xl border border-line bg-raised px-3 text-xs text-text focus:border-blue/60 focus:outline-none"
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-[11px] font-medium">
                  具体方向
                </span>
                <input
                  value={form.niche}
                  onChange={(event) => update({ niche: event.target.value })}
                  maxLength={80}
                  className="h-10 w-full rounded-xl border border-line bg-raised px-3 text-xs text-text focus:border-blue/60 focus:outline-none"
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-[11px] font-medium">
                  目标读者
                </span>
                <textarea
                  value={form.audience}
                  onChange={(event) => update({ audience: event.target.value })}
                  rows={3}
                  maxLength={200}
                  className="w-full resize-y rounded-xl border border-line bg-raised px-3 py-2.5 text-xs leading-6 text-text focus:border-blue/60 focus:outline-none"
                />
              </label>
              <div className="flex items-center justify-between gap-3">
                <p className="text-[10px] leading-5 text-muted">
                  {mode === "demo"
                    ? "当前保存到 localStorage；演示模式不会写后端。"
                    : "真实接口模式：名字、工作空间与账号阶段会写入后端 accounts 表；其他画像字段仍保存在本地。"}
                </p>
                <Button
                  variant="primary"
                  icon={<Save size={14} />}
                  onClick={() => void save()}
                  disabled={saving}
                >
                  {saving ? "保存中…" : "保存"}
                </Button>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <h2 className="text-sm font-semibold">数据与连接</h2>
                <p className="mt-0.5 text-[11px] text-muted">
                  真实业务闭环优先：先看后端已提供的读写能力
                </p>
              </div>
              <Database size={14} className="text-cyan" />
            </CardHeader>
            <CardBody className="space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => void switchMode("demo")}
                  aria-pressed={mode === "demo"}
                  className={cn(
                    "rounded-xl border p-4 text-left transition",
                    mode === "demo"
                      ? "border-blue/45 bg-blue/[0.08]"
                      : "border-line bg-raised/40 hover:border-[#43506a]",
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-xs font-medium">
                      <MonitorCog size={14} className="text-blue" />
                      演示模式
                    </span>
                    {mode === "demo" ? (
                      <CheckCircle2 size={14} className="text-blue" />
                    ) : null}
                  </div>
                  <p className="mt-2 text-[10px] leading-5 text-muted">
                    本地适配器按阶段推进任务，可手动推进、审批与修订。
                    数据保存在浏览器，刷新不丢失。
                  </p>
                </button>
                <button
                  type="button"
                  onClick={() => void switchMode("api")}
                  aria-pressed={mode === "api"}
                  className={cn(
                    "rounded-xl border p-4 text-left transition",
                    mode === "api"
                      ? "border-cyan/45 bg-cyan/[0.08]"
                      : "border-line bg-raised/40 hover:border-[#43506a]",
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-xs font-medium">
                      <Server size={14} className="text-cyan" />
                      真实接口
                    </span>
                    {mode === "api" ? (
                      <CheckCircle2 size={14} className="text-cyan" />
                    ) : null}
                  </div>
                  <p className="mt-2 text-[10px] leading-5 text-muted">
                    接入 session / accounts / tasks / events / brief / versions。
                    可创建任务、确认 Brief、验收内容、取消任务，并以 feedback 记录修订意见。
                  </p>
                </button>
              </div>
              <div className="rounded-xl border border-line bg-raised/40 px-3 py-1">
                <Row label="API Base" value={apiBase} />
                <Row
                  label="读取任务与事件"
                  value="GET /api/v1/tasks + /events · 已接入"
                  accent="#8FD6A8"
                />
                <Row
                  label="创建任务"
                  value="POST /api/v1/tasks · 已接入"
                  accent="#8FD6A8"
                />
                <Row
                  label="Brief 确认 / 内容验收 / 取消"
                  value="POST confirm · accept · cancel / PUT brief · 已接入"
                  accent="#8FD6A8"
                />
                <Row
                  label="修订意见"
                  value="POST /feedback (edit_request) · 已接入"
                  accent="#8FD6A8"
                />
                <Row
                  label="修订运行"
                  value="需后端 worker 消费 feedback · 未接入"
                  accent="#F0B36E"
                />
                <Row
                  label="产物下载"
                  value="/api/v1/artifacts/{id}/download · 未接入"
                  accent="#F0B36E"
                />
                <Row
                  label="工作空间画像"
                  value="后端未提供 · 本地持久化"
                  accent="#F0B36E"
                />
              </div>
              {mode === "api" ? (
                <div className="flex items-start gap-2 rounded-xl border border-amber/25 bg-amber/[0.06] p-3">
                  <TriangleAlert
                    size={14}
                    className="mt-0.5 shrink-0 text-amber"
                  />
                  <p className="text-[10px] leading-5 text-muted">
                    切换前请确认 Flask 后端已运行在 <code>{apiBase}</code>。
                    连接失败会进入可恢复的错误页，可直接切回演示模式。
                  </p>
                </div>
              ) : null}
            </CardBody>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <h2 className="text-sm font-semibold">体验偏好</h2>
            </CardHeader>
            <CardBody className="divide-y divide-line/50 py-0">
              <Switch
                label="自动推进演示任务"
                description="仅演示模式生效，每 4.2 秒推进最早的任务，到达审批节点后停止。"
                checked={autoplay}
                onChange={setAutoplay}
              />
              <div className="py-3">
                <Button
                  variant="secondary"
                  className="w-full"
                  icon={<Boxes size={14} />}
                  onClick={() => setImmersive(true)}
                >
                  进入沉浸式 AI 公司
                </Button>
                <p className="mt-1.5 text-[9px] leading-4 text-muted">
                  WebGL 不可用时会自动显示 2D 降级视图；系统中开启「减少动态效果」时动画会被关闭。
                </p>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <h2 className="text-sm font-semibold">工作空间</h2>
            </CardHeader>
            <CardBody className="py-1">
              <Row label="模式" value={mode === "demo" ? "演示" : "真实接口"} />
              <Row
                label="账号阶段"
                value={creatorStageMeta(snapshot.profile?.creatorStage).label}
              />
              <Row label="员工" value={`${snapshot.agents.length} 位`} />
              <Row label="任务" value={`${snapshot.tasks.length} 个`} />
              <Row label="资产" value={`${snapshot.assets.length} 份`} />
              <Row
                label="画像状态"
                value={snapshot.profile?.completedAt ? "已完成引导" : "未完成"}
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <h2 className="text-sm font-semibold">数据管理</h2>
            </CardHeader>
            <CardBody className="space-y-3">
              <p className="text-[10px] leading-5 text-muted">
                重置会清除本地演示任务、资产与审批记录，恢复为初始示例数据。
                不会影响后端数据库。
              </p>
              <Button
                variant="danger"
                size="sm"
                className="w-full"
                icon={<RotateCcw size={13} />}
                onClick={() => setResetOpen(true)}
              >
                重置演示数据
              </Button>
            </CardBody>
          </Card>

          <div className="rounded-2xl border border-line bg-raised/40 p-4 text-[10px] leading-5 text-muted">
            <p className="font-medium text-text">Creator OS · 前端原型</p>
            <p className="mt-1">
              React 19 · Vite · TypeScript · Tailwind v4 · R3F。3D 场景为本地程序化几何，无外部模型与网络请求。
            </p>
            <p className="mt-1 text-muted/70">
              后端契约 seven-agent.v0.1：pr_analyst / operations_officer / traffic_scout /
              content_creator / editorial_reviewer / simulated_audience / data_analyst。
              前端仅做状态投影，不修改业务语义。
            </p>
          </div>
        </div>
      </div>

      <Modal
        open={resetOpen}
        onClose={() => setResetOpen(false)}
        title="重置演示数据？"
        description="当前浏览器里的演示任务、审批与资产会被清除，无法撤销。"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setResetOpen(false)}>
              取消
            </Button>
            <Button
              variant="danger"
              onClick={() => void confirmReset()}
              disabled={resetting}
            >
              {resetting ? "正在重置…" : "确认重置"}
            </Button>
          </>
        }
      >
        <p className="text-[11px] leading-6 text-muted">
          工作空间画像会保留。若只想换一种状态看看，也可以直接在任务详情里推进或审批任务。
        </p>
      </Modal>
    </div>
  );
}
