import { useEffect, useMemo, useRef, useState } from "react";
import { CircleAlert, Download, FileJson, Loader2, LogIn, RefreshCw } from "lucide-react";
import {
  createExternalAccountsClient,
  PLATFORM_META,
  type ExperienceSummary,
  type ExternalAccount,
  type ExternalAccountsClient,
  type ManualVideo,
  type Platform,
  type SessionStatus,
} from "@/adapters/externalAccounts";
import { useWorkspace } from "@/store/workspace";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/format";

const STATUS_LABEL: Record<SessionStatus, string> = {
  none: "未登录",
  pending_adapter_setup: "待重试",
  logging_in: "登录中…",
  logged_in: "已登录",
  expired: "已过期",
};

const STATUS_TONE: Record<SessionStatus, string> = {
  none: "text-muted",
  pending_adapter_setup: "text-amber",
  logging_in: "text-blue",
  logged_in: "text-green",
  expired: "text-red",
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

interface Message {
  tone: "info" | "success" | "error";
  text: string;
}

export function AccountConnect() {
  const mode = useWorkspace((state) => state.mode);
  const showToast = useWorkspace((state) => state.showToast);
  const client = useMemo<ExternalAccountsClient>(
    () => createExternalAccountsClient(mode),
    [mode],
  );

  const [accounts, setAccounts] = useState<ExternalAccount[]>([]);
  const [platform, setPlatform] = useState<Platform>("douyin");
  const [handle, setHandle] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState<"" | "login" | "manual" | "refresh">("");
  const [message, setMessage] = useState<Message | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [experience, setExperience] = useState<ExperienceSummary | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const polling = useRef(false);

  const refresh = async () => {
    try {
      setAccounts(await client.list());
    } catch {
      /* 列表失败不打断表单；下次操作会再报错 */
    }
  };

  useEffect(() => {
    setAccounts([]);
    setMessage(null);
    setExpandedId(null);
    setExperience(null);
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  const pollUntilDone = async (externalId: string) => {
    polling.current = true;
    const deadline = Date.now() + 210_000;
    try {
      while (Date.now() < deadline && polling.current) {
        await sleep(2000);
        const status = await client.status(externalId);
        setAccounts((current) =>
          current.map((item) =>
            item.external_account_id === externalId
              ? {
                  ...item,
                  session_status: status.session_status,
                  imported_count: status.imported_count,
                  baseline_plays: status.baseline_plays,
                }
              : item,
          ),
        );
        if (status.session_status === "logged_in") return status;
        if (status.login_error) return status;
        if (
          status.session_status !== "logging_in" &&
          status.session_status !== "none"
        ) {
          // pending_adapter_setup / expired：登录线程已结束
          return status;
        }
        // logging_in（等扫码）或刚复位的 none：继续观察至超时
      }
      return await client.status(externalId);
    } finally {
      polling.current = false;
    }
  };

  const connect = async () => {
    const handleValue = handle.trim();
    if (!handleValue) {
      setMessage({ tone: "error", text: `请填写${PLATFORM_META[platform].handleLabel}。` });
      return;
    }
    setBusy("login");
    setMessage({
      tone: "info",
      text:
        mode === "api"
          ? "已启动登录：请在弹出的浏览器窗口中扫码，登录成功后会自动抓取最近作品实绩写入经验库…"
          : "演示模式：正在模拟登录与实绩导入…",
    });
    try {
      const account = await client.register({
        platform,
        handle: handleValue,
        displayName: displayName.trim(),
      });
      await refresh();
      await client.login(account.external_account_id);
      const status = await pollUntilDone(account.external_account_id);
      if (status.session_status === "logged_in") {
        const exp = await client.experience(account.external_account_id);
        setExperience(exp);
        setExpandedId(account.external_account_id);
        const importNote = status.import_error
          ? `实绩抓取未完成（${status.import_error}），可稍后“重新抓取”或手动导入。`
          : `已导入 ${status.imported_count} 条作品实绩，基准播放 ${
              status.baseline_plays ?? "—"
            }，已写入经验库。`;
        setMessage({
          tone: status.import_error ? "info" : "success",
          text: `登录成功。${importNote}`,
        });
        showToast("账号已接入，实绩已入库作为经验库。", "success");
      } else if (status.login_error) {
        setMessage({
          tone: "error",
          text: `登录未完成：${status.login_error}。可重试，或用“手动导入 JSON”补录实绩。`,
        });
      } else {
        setMessage({
          tone: "error",
          text: "登录等待超时。可重新点击登录，或用“手动导入 JSON”补录实绩。",
        });
      }
      await refresh();
    } catch (error) {
      setMessage({
        tone: "error",
        text: error instanceof Error ? error.message : "接入失败，请重试。",
      });
    } finally {
      setBusy("");
    }
  };

  const reImport = async (account: ExternalAccount) => {
    setBusy("refresh");
    setMessage({ tone: "info", text: "正在抓取最近作品实绩…" });
    try {
      const result = await client.importAdapter(account.external_account_id);
      setMessage({
        tone: "success",
        text: `已抓取：新增 ${result.imported} 条（去重 ${
          result.skipped_duplicates ?? 0
        }），基准播放 ${result.baseline_plays ?? "—"}。`,
      });
      if (expandedId === account.external_account_id) {
        setExperience(await client.experience(account.external_account_id));
      }
      await refresh();
    } catch (error) {
      setMessage({
        tone: "error",
        text: `抓取失败：${
          error instanceof Error ? error.message : "未知错误"
        }。会话可能过期，请重新登录，或改用“手动导入 JSON”。`,
      });
    } finally {
      setBusy("");
    }
  };

  const toggleExperience = async (account: ExternalAccount) => {
    if (expandedId === account.external_account_id) {
      setExpandedId(null);
      setExperience(null);
      return;
    }
    try {
      setExperience(await client.experience(account.external_account_id));
      setExpandedId(account.external_account_id);
    } catch (error) {
      setMessage({
        tone: "error",
        text: error instanceof Error ? error.message : "经验库读取失败。",
      });
    }
  };

  const onManualFile = async (file: File) => {
    const handleValue = handle.trim();
    if (!handleValue) {
      setMessage({
        tone: "error",
        text: `手动导入也需要${PLATFORM_META[platform].handleLabel}来绑定账号。`,
      });
      return;
    }
    setBusy("manual");
    try {
      const raw = JSON.parse(await file.text()) as unknown;
      const videos = Array.isArray(raw) ? raw : (raw as { videos?: unknown }).videos;
      if (!Array.isArray(videos) || videos.length === 0) {
        throw new Error("JSON 需为 {\"videos\":[…]} 或作品数组，且不能为空。");
      }
      const account = await client.register({
        platform,
        handle: handleValue,
        displayName: displayName.trim(),
      });
      await refresh();
      const result = await client.importManual(
        account.external_account_id,
        videos as ManualVideo[],
      );
      setMessage({
        tone: "success",
        text: `手动导入完成：新增 ${result.imported} 条（去重 ${
          result.skipped_duplicates ?? 0
        }），基准播放 ${result.baseline_plays ?? "—"}，已写入经验库。`,
      });
      await refresh();
    } catch (error) {
      setMessage({
        tone: "error",
        text: `手动导入失败：${
          error instanceof Error ? error.message : "文件格式不正确"
        }。`,
      });
    } finally {
      setBusy("");
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold">平台账号 · 经验库</h2>
        <p className="mt-1 text-[11px] leading-5 text-muted">
          接入你已有的抖音 / 小红书账号：登录后自动抓取最近作品实绩（播放、点赞、评论、热评），
          写入本地数据库作为<b className="text-text">经验库</b>，为选题、审稿与数据分析提供历史依据。
          只读接入，不会发布或修改任何内容。
        </p>
        <p className="mt-1 text-[10px] leading-5 text-muted">
          {mode === "api"
            ? "真实接口模式：实绩写入本地 SQLite（imported_videos），基准线 baseline_plays 自动派生。"
            : "演示模式：模拟数据仅保存在浏览器；切换真实接口模式后才会连接平台并写入数据库。"}
        </p>
      </div>

      <fieldset>
        <legend className="mb-2 text-[11px] font-medium">选择平台并登录已有账号</legend>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {(Object.keys(PLATFORM_META) as Platform[]).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setPlatform(item)}
              aria-pressed={platform === item}
              className={cn(
                "rounded-xl border p-3 text-left transition",
                platform === item
                  ? "border-blue/50 bg-blue/10 text-text"
                  : "border-line bg-raised text-muted hover:border-[#43506a] hover:text-text",
              )}
            >
              <span className="block text-xs font-medium">
                {PLATFORM_META[item].label}
              </span>
              <span className="mt-1 block text-[10px] leading-5">
                {PLATFORM_META[item].hint}
              </span>
            </button>
          ))}
        </div>
      </fieldset>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1.5 block text-[11px] font-medium">
            {PLATFORM_META[platform].handleLabel}
          </span>
          <input
            value={handle}
            onChange={(event) => setHandle(event.target.value)}
            maxLength={64}
            placeholder={`填写${PLATFORM_META[platform].label}账号标识`}
            className="h-10 w-full rounded-xl border border-line bg-raised px-3 text-xs text-text placeholder:text-muted/60 focus:border-blue/60 focus:outline-none"
          />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-[11px] font-medium">
            备注昵称（可选）
          </span>
          <input
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            maxLength={64}
            placeholder="例如：主号 / 测评小号"
            className="h-10 w-full rounded-xl border border-line bg-raised px-3 text-xs text-text placeholder:text-muted/60 focus:border-blue/60 focus:outline-none"
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          size="sm"
          icon={
            busy === "login" ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <LogIn size={13} />
            )
          }
          onClick={() => void connect()}
          disabled={busy !== ""}
        >
          {busy === "login" ? "登录中…" : "登录并导入实绩"}
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void onManualFile(file);
          }}
        />
        <Button
          variant="secondary"
          size="sm"
          icon={
            busy === "manual" ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <FileJson size={13} />
            )
          }
          onClick={() => fileRef.current?.click()}
          disabled={busy !== ""}
        >
          手动导入 JSON
        </Button>
        <span className="text-[10px] leading-5 text-muted">
          手动导入格式：{"{ \"videos\": [ { \"platform_video_id\": \"…\", \"plays\": 1200, … } ] }"}
        </span>
      </div>

      {message ? (
        <p
          role={message.tone === "error" ? "alert" : undefined}
          className={cn(
            "flex items-start gap-1.5 rounded-xl border px-3 py-2 text-[11px] leading-5",
            message.tone === "error"
              ? "border-red/30 bg-red/[0.06] text-red"
              : message.tone === "success"
                ? "border-green/30 bg-green/[0.06] text-green"
                : "border-line bg-raised/60 text-muted",
          )}
        >
          {message.tone === "error" ? (
            <CircleAlert size={13} className="mt-0.5 shrink-0" />
          ) : null}
          {message.text}
        </p>
      ) : null}

      {accounts.length > 0 ? (
        <div className="rounded-xl border border-line bg-raised/40">
          <p className="border-b border-line/50 px-3 py-2 text-[11px] font-medium">
            已接入账号（经验库）
          </p>
          <ul className="divide-y divide-line/50">
            {accounts.map((account) => (
              <li key={account.external_account_id} className="px-3 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-xs text-text">
                      {PLATFORM_META[account.platform].label}
                      <span className="text-muted"> · {account.handle}</span>
                      {account.display_name ? (
                        <span className="text-muted">（{account.display_name}）</span>
                      ) : null}
                    </p>
                    <p className="mt-1 text-[10px] leading-5 text-muted">
                      <span className={STATUS_TONE[account.session_status]}>
                        {STATUS_LABEL[account.session_status]}
                      </span>
                      {" · 已入库 "}
                      {account.imported_count}
                      {" 条 · 基准播放 "}
                      {account.baseline_plays ?? "—"}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={
                        busy === "refresh" ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <RefreshCw size={12} />
                        )
                      }
                      onClick={() => void reImport(account)}
                      disabled={busy !== "" || account.session_status !== "logged_in"}
                    >
                      重新抓取
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<Download size={12} />}
                      onClick={() => void toggleExperience(account)}
                    >
                      {expandedId === account.external_account_id
                        ? "收起经验库"
                        : "查看经验库"}
                    </Button>
                  </div>
                </div>
                {expandedId === account.external_account_id && experience ? (
                  <div className="mt-2 space-y-2 rounded-lg border border-line/60 bg-ink/40 p-3">
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                      {(
                        [
                          ["总播放", experience.totals.plays],
                          ["点赞", experience.totals.likes],
                          ["评论", experience.totals.comments],
                          ["转发", experience.totals.shares],
                          ["收藏", experience.totals.favorites],
                        ] as const
                      ).map(([label, value]) => (
                        <div key={label}>
                          <p className="text-[9px] text-muted">{label}</p>
                          <p className="text-xs text-text">{value}</p>
                        </div>
                      ))}
                    </div>
                    {experience.top_comments.length > 0 ? (
                      <div>
                        <p className="text-[10px] font-medium text-text">热评（真信号）</p>
                        <ul className="mt-1 space-y-1">
                          {experience.top_comments.slice(0, 5).map((comment, index) => (
                            <li key={index} className="text-[10px] leading-5 text-muted">
                              {comment.text}
                              <span className="text-muted/70">（{comment.likes} 赞）</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    {experience.recent_videos.length > 0 ? (
                      <div>
                        <p className="text-[10px] font-medium text-text">
                          最近作品实绩（{experience.recent_videos.length} 条）
                        </p>
                        <ul className="mt-1 space-y-1">
                          {experience.recent_videos.slice(0, 8).map((video) => (
                            <li
                              key={video.platform_video_id}
                              className="truncate text-[10px] leading-5 text-muted"
                            >
                              {video.title || video.platform_video_id}
                              <span className="text-muted/70">
                                {" · 播放 "}
                                {video.plays ?? "—"}
                                {" · 赞 "}
                                {video.likes ?? "—"}
                                {" · 评 "}
                                {video.comments ?? "—"}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : (
                      <p className="text-[10px] text-muted">
                        还没有实绩数据。点“重新抓取”，或用“手动导入 JSON”补录。
                      </p>
                    )}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="rounded-xl border border-dashed border-line px-3 py-2.5 text-[10px] leading-5 text-muted">
          还没有接入任何平台账号。选择平台、填写账号标识后点“登录并导入实绩”；
          未登录也可用“手动导入 JSON”先补录历史数据。
        </p>
      )}
    </div>
  );
}
