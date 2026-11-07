import { useId } from "react";

/**
 * 众幕 brand mark — two drawn curtains parted around a single light seam.
 * Pure SVG so it stays crisp in the sidebar, the landing nav and the favicon
 * scale without a raster asset.
 */
export function BrandMark({
  size = 32,
  className,
  title,
}: {
  size?: number;
  className?: string;
  title?: string;
}) {
  const gradientId = `bm-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      className={className}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      <defs>
        <linearGradient
          id={gradientId}
          x1="6"
          y1="3"
          x2="42"
          y2="46"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="#f7edda" />
          <stop offset="0.48" stopColor="#dcc7a8" />
          <stop offset="1" stopColor="#9a7a51" />
        </linearGradient>
      </defs>
      <path
        d="M15.8 4.8C10.1 10.4 7.8 16.6 7.8 24s2.3 13.6 8 19.2c3.7-5.1 5.2-11.3 5.2-19.2S19.5 9.9 15.8 4.8Z"
        fill={`url(#${gradientId})`}
      />
      <path
        d="M32.2 4.8C37.9 10.4 40.2 16.6 40.2 24s-2.3 13.6-8 19.2c-3.7-5.1-5.2-11.3-5.2-19.2s1.5-14.1 5.2-19.2Z"
        fill={`url(#${gradientId})`}
      />
      <path
        d="M24 7.6v32.8"
        stroke="#fff5e4"
        strokeWidth="1.35"
        strokeLinecap="round"
        opacity="0.95"
      />
      <circle cx="24" cy="24" r="2.15" fill="#fff5e4" />
    </svg>
  );
}
