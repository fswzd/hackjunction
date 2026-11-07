import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  Copy,
  Download,
  FileText,
  FolderOpen,
  Search,
} from "lucide-react";
import type { AssetKind, AssetVM } from "@/domain/types";
import { cn, formatRelative } from "@/lib/format";
import { useWorkspace } from "@/store/workspace";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Modal } from "@/components/ui/Modal";
import { SectionHeader } from "@/components/ui/SectionHeader";

const KIND_META: Record<
  AssetKind,
  { label: string; color: string; description: string }
> = {
  script: { label: "脚本", color: "#83B8FF", description: "已批准可交付的内容" },
  topic: { label: "选题", color: "#B49CFF", description: "选题方向与依据" },
  research: { label: "研究", color: "#78E3DE", description: "资料与事实笔记" },
  brief: { label: "任务书", color: "#F0B36E", description: "结构化的创作 Brief" },
};

const KINDS: ("all" | AssetKind)[] = ["all", "script", "topic", "research", "brief"];

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

function safeFilename(name: string): string {
  return name.replace(/[\\/:*?"<>|]/g, "-").slice(0, 60);
}

function AssetCard({
  asset,
  projectName,
  onOpen,
}: {
  asset: AssetVM;
  projectName: string;
  onOpen: () => void;
}) {
  const meta = KIND_META[asset.kind];
  return (
    <Card className="group flex flex-col p-4 transition hover:border-[#43506a]">
      <div className="flex items-start justify-between gap-2">
        <span
          className="flex h-8 w-8 items-center justify-center rounded-lg border"
          style={{
            color: meta.color,
            borderColor: `color-mix(in srgb, ${meta.color} 30%, transparent)`,
            backgroundColor: `color-mix(in srgb, ${meta.color} 10%, transparent)`,
          }}
        >
          <FileText size={14} />
        </span>
        <Badge color={meta.color}>{meta.label}</Badge>
      </div>
      <button
        type="button"
        onClick={onOpen}
        className="mt-3 line-clamp-2 text-left text-[13px] font-medium leading-5 text-text transition hover:text-blue"
      >
        {asset.name}
      </button>
      <p className="mt-2 line-clamp-2 flex-1 text-[10px] leading-5 text-muted">
        {asset.body}
      </p>
      <div className="mt-3 flex items-center justify-between border-t border-line/60 pt-3 text-[10px] text-muted">
        <span className="flex items-center gap-1 truncate">
          <FolderOpen size={11} />
          {projectName}
        </span>
        <span className="shrink-0">{formatRelative(asset.createdAt)}</span>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={onOpen}
          className="flex-1 rounded-lg border border-line bg-raised py-1.5 text-[10px] text-text transition hover:border-[#43506a]"
        >
          预览内容
        </button>
        <Link
          to={`/workspace/tasks/${asset.taskId}`}
          className="rounded-lg p-1.5 text-muted transition hover:bg-white/5 hover:text-text"
          aria-label="查看来源任务"
        >
          <ArrowUpRight size={14} />
        </Link>
      </div>
    </Card>
  );
}

export function Assets() {
  const snapshot = useWorkspace((state) => state.snapshot);
  const showToast = useWorkspace((state) => state.showToast);
  const [kind, setKind] = useState<"all" | AssetKind>("all");
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);

  const assets = useMemo(() => {
    return (snapshot?.assets ?? [])
      .filter((asset) => (kind === "all" ? true : asset.kind === kind))
      .filter((asset) =>
        query.trim()
          ? `${asset.name} ${asset.body}`
              .toLowerCase()
              .includes(query.trim().toLowerCase())
          : true,
      )
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }, [snapshot, kind, query]);

  if (!snapshot) return null;

  const active = snapshot.assets.find((asset) => asset.id === activeId) ?? null;
  const activeProject = active
    ? snapshot.projects.find((project) => project.id === active.projectId)
    : null;

  const copyActive = async () => {
    if (!active) return;
    try {
      await navigator.clipboard.writeText(active.body);
      showToast("内容已复制到剪贴板。", "success");
    } catch {
      showToast("复制失败，请在预览中手动选择文本。", "error");
    }
  };

  return (
    <div className="space-y-5">
      <SectionHeader
        eyebrow="资产"
        title="素材库"
        description="所有被批准的内容与已产出的过程材料。演示模式下保存在本地浏览器。"
      />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-1.5">
          {KINDS.map((item) => {
            const label = item === "all" ? "全部" : KIND_META[item].label;
            const count =
              item === "all"
                ? snapshot.assets.length
                : snapshot.assets.filter((asset) => asset.kind === item).length;
            return (
              <button
                key={item}
                type="button"
                onClick={() => setKind(item)}
                aria-pressed={kind === item}
                className={cn(
                  "rounded-lg border px-3 py-1.5 text-[11px] transition",
                  kind === item
                    ? "border-blue/45 bg-blue/10 text-blue"
                    : "border-line bg-raised text-muted hover:text-text",
                )}
              >
                {label}
                <span className="ml-1.5 opacity-60">{count}</span>
              </button>
            );
          })}
        </div>
        <label className="relative w-full lg:w-64">
          <Search
            size={14}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted"
          />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索素材内容"
            aria-label="搜索素材内容"
            className="h-9 w-full rounded-lg border border-line bg-raised pl-9 pr-3 text-xs text-text placeholder:text-muted/60 focus:border-blue/60 focus:outline-none"
          />
        </label>
      </div>

      {assets.length ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {assets.map((asset) => (
            <AssetCard
              key={asset.id}
              asset={asset}
              projectName={
                snapshot.projects.find(
                  (project) => project.id === asset.projectId,
                )?.name ?? "未归档"
              }
              onOpen={() => setActiveId(asset.id)}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={<FileText size={18} />}
          title={query ? "没有匹配的素材" : "还没有素材"}
          description={
            query
              ? "换一个关键词，或切换素材类型。"
              : "批准一份内容后，它会作为可下载资产出现在这里。"
          }
        />
      )}

      <Modal
        open={Boolean(active)}
        onClose={() => setActiveId(null)}
        title={active?.name ?? "素材预览"}
        description={
          active
            ? `${KIND_META[active.kind].label} · ${activeProject?.name ?? "未归档"} · ${formatRelative(active.createdAt)}`
            : undefined
        }
        size="lg"
        footer={
          active ? (
            <>
              <Link
                to={`/workspace/tasks/${active.taskId}`}
                className="mr-auto text-[11px] text-muted transition hover:text-text"
              >
                查看来源任务 ↗
              </Link>
              <Button
                variant="ghost"
                icon={<Copy size={13} />}
                onClick={() => void copyActive()}
              >
                复制
              </Button>
              <Button
                variant="primary"
                icon={<Download size={13} />}
                onClick={() =>
                  downloadText(`${safeFilename(active.name)}.md`, active.body)
                }
              >
                下载 Markdown
              </Button>
            </>
          ) : null
        }
      >
        {active ? (
          <div className="rounded-xl border border-line bg-ink/50 p-4">
            <pre className="whitespace-pre-wrap break-words font-sans text-[13px] leading-7 text-text/90">
              {active.body}
            </pre>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
