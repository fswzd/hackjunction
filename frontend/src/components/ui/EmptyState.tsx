import type { ReactNode } from "react";
import { cn } from "@/lib/format";

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-2xl border border-dashed border-line px-6 py-12 text-center",
        className,
      )}
    >
      {icon ? (
        <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-line bg-raised text-muted">
          {icon}
        </div>
      ) : null}
      <p className="text-sm font-medium text-text">{title}</p>
      {description ? (
        <p className="mt-1 max-w-sm text-xs leading-5 text-muted">{description}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
