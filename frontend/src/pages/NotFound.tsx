import { Link } from "react-router-dom";
import { ArrowLeft, Compass } from "lucide-react";
import { useWorkspace } from "@/store/workspace";

export function NotFound() {
  const profile = useWorkspace((state) => state.snapshot?.profile);

  return (
    <div className="inner-grid flex min-h-screen flex-col items-center justify-center bg-ink p-6 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-line bg-surface text-muted">
        <Compass size={20} />
      </span>
      <p className="mt-5 text-[11px] uppercase tracking-[0.2em] text-muted">
        404
      </p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight">
        这个页面不存在
      </h1>
      <p className="mt-2 max-w-sm text-xs leading-6 text-muted">
        链接可能已经失效，或者你输入的路径不在工作空间里。
      </p>
      <Link
        to={profile ? "/workspace/overview" : "/onboarding"}
        className="mt-6 inline-flex h-10 items-center gap-2 rounded-xl border border-line bg-raised px-4 text-xs font-medium text-text transition hover:border-[#43506a]"
      >
        <ArrowLeft size={14} />
        {profile ? "回到工作台" : "开始引导"}
      </Link>
    </div>
  );
}
