import { useEffect } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { useWorkspace } from "@/store/workspace";
import { cn } from "@/lib/format";

const TONES = {
  info: { icon: Info, color: "text-blue", border: "border-blue/30" },
  success: { icon: CheckCircle2, color: "text-green", border: "border-green/30" },
  error: { icon: AlertCircle, color: "text-red", border: "border-red/30" },
};

export function Toast() {
  const toast = useWorkspace((state) => state.toast);
  const dismiss = useWorkspace((state) => state.dismissToast);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(dismiss, 4600);
    return () => window.clearTimeout(timer);
  }, [toast, dismiss]);

  if (!toast) return null;
  const tone = TONES[toast.tone];
  const Icon = tone.icon;

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "animate-fade-up fixed bottom-6 left-1/2 z-[80] flex w-[min(92vw,520px)] -translate-x-1/2 items-start gap-3 rounded-xl border bg-surface px-4 py-3 shadow-[0_24px_80px_-20px_rgba(0,0,0,0.9)]",
        tone.border,
      )}
    >
      <Icon size={16} className={cn("mt-0.5 shrink-0", tone.color)} />
      <p className="flex-1 text-xs leading-5 text-text">{toast.message}</p>
      <button
        type="button"
        onClick={dismiss}
        aria-label="关闭提示"
        className="rounded p-1 text-muted hover:bg-white/5 hover:text-text"
      >
        <X size={14} />
      </button>
    </div>
  );
}
