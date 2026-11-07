import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/format";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  color?: string;
  dot?: boolean;
  icon?: ReactNode;
}

export function Badge({
  color = "#83B8FF",
  dot = false,
  icon,
  className,
  children,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium leading-none",
        className,
      )}
      style={{
        color,
        borderColor: `color-mix(in srgb, ${color} 34%, transparent)`,
        backgroundColor: `color-mix(in srgb, ${color} 10%, transparent)`,
      }}
      {...props}
    >
      {dot ? (
        <span
          aria-hidden
          className="h-1.5 w-1.5 rounded-full"
          style={{ backgroundColor: color }}
        />
      ) : null}
      {icon}
      {children}
    </span>
  );
}
