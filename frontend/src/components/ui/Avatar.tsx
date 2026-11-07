import { cn, initials } from "@/lib/format";

export function Avatar({
  name,
  size = 36,
  accent = "#83B8FF",
  className,
}: {
  name: string;
  size?: number;
  accent?: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full border font-semibold",
        className,
      )}
      style={{
        width: size,
        height: size,
        fontSize: Math.max(12, size * 0.34),
        color: accent,
        borderColor: `color-mix(in srgb, ${accent} 35%, transparent)`,
        backgroundColor: `color-mix(in srgb, ${accent} 12%, transparent)`,
      }}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}
