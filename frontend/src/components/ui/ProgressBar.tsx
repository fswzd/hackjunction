import { cn } from "@/lib/format";

export function ProgressBar({
  value,
  color = "#83B8FF",
  className,
  label,
}: {
  value: number;
  color?: string;
  className?: string;
  label?: string;
}) {
  const safe = Math.min(100, Math.max(0, value));
  return (
    <div className={className}>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-line/60"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(safe)}
        aria-label={label}
      >
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{ width: `${safe}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}
