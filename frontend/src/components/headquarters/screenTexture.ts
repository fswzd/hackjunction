import * as THREE from "three";

export type ScreenVariant =
  | "brief"
  | "review"
  | "scout"
  | "creator"
  | "audience"
  | "data"
  | "ops";

function rounded(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + width, y, x + width, y + height, r);
  ctx.arcTo(x + width, y + height, x, y + height, r);
  ctx.arcTo(x, y + height, x, y, r);
  ctx.arcTo(x, y, x + width, y, r);
  ctx.closePath();
}

function line(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  color: string,
  radius = 3,
) {
  ctx.fillStyle = color;
  rounded(ctx, x, y, width, height, radius);
  ctx.fill();
}

/**
 * A small procedural UI for each monitor. Drawn to a canvas texture so the
 * desks read as working software instead of glowing rectangles, without any
 * bitmap assets or network requests.
 */
export function createScreenTexture({
  name,
  accent,
  statusColor,
  variant,
  statusLabel,
}: {
  name: string;
  accent: string;
  statusColor: string;
  variant: ScreenVariant;
  statusLabel: string;
}) {
  const width = 512;
  const height = 288;
  const scale = 2;
  const canvas = document.createElement("canvas");
  canvas.width = width * scale;
  canvas.height = height * scale;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.scale(scale, scale);

  const bg = ctx.createLinearGradient(0, 0, 0, height);
  bg.addColorStop(0, "#12100d");
  bg.addColorStop(1, "#0a0908");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, width, height);

  // Top window chrome
  ctx.fillStyle = "#181510";
  ctx.fillRect(0, 0, width, 34);
  ["#8a5a4a", "#8a7a4a", "#5a7a5a"].forEach((color, index) => {
    ctx.beginPath();
    ctx.arc(18 + index * 14, 17, 4, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  });

  ctx.textBaseline = "middle";
  ctx.font =
    '600 15px "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif';
  ctx.fillStyle = "#d9d1c0";
  ctx.fillText(name, 74, 18, 220);

  ctx.font =
    '500 10px "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif';
  ctx.fillStyle = "#8a8170";
  ctx.fillText("众幕 AI · 本地工作区", width - 178, 18);

  // Left rail
  ctx.fillStyle = "#14120f";
  ctx.fillRect(0, 34, 58, height - 34);
  for (let index = 0; index < 5; index += 1) {
    ctx.fillStyle = index === 0 ? accent : "#2a261f";
    ctx.globalAlpha = index === 0 ? 0.9 : 0.75;
    rounded(ctx, 18, 58 + index * 34, 22, 22, 6);
    ctx.fill();
  }
  ctx.globalAlpha = 1;

  const left = 76;
  const top = 52;
  const contentWidth = width - left - 24;

  if (variant === "data") {
    line(ctx, left, top, 118, 10, "#4a4438", 5);
    line(ctx, left, top + 22, 74, 6, "#2c2822", 3);

    const chartTop = 112;
    const chartHeight = 106;
    ctx.strokeStyle = "rgba(238,234,222,0.07)";
    ctx.lineWidth = 1;
    for (let index = 0; index <= 4; index += 1) {
      const y = chartTop + (chartHeight / 4) * index;
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(width - 34, y);
      ctx.stroke();
    }
    const bars = [0.38, 0.62, 0.5, 0.86, 0.7, 0.96, 0.58];
    bars.forEach((value, index) => {
      const barWidth = 22;
      const gap = (contentWidth - 4 - bars.length * barWidth) / (bars.length - 1);
      const x = left + 6 + index * (barWidth + gap);
      const barHeight = value * chartHeight;
      ctx.fillStyle = index === 5 ? accent : `${accent}55`;
      rounded(ctx, x, chartTop + chartHeight - barHeight, barWidth, barHeight, 4);
      ctx.fill();
    });
    line(ctx, left, 244, 196, 7, "#3a342b", 3);
    line(ctx, left, 260, 140, 7, "#2a261f", 3);
  } else if (variant === "audience") {
    line(ctx, left, top, 140, 10, "#4a4438", 5);
    line(ctx, left + 170, top, 52, 10, "#2c2822", 5);
    // Video preview
    rounded(ctx, left, 80, 248, 140, 8);
    ctx.fillStyle = "#1a1712";
    ctx.fill();
    ctx.strokeStyle = `${accent}44`;
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(left + 112, 132);
    ctx.lineTo(left + 112, 168);
    ctx.lineTo(left + 140, 150);
    ctx.closePath();
    ctx.fillStyle = `${accent}cc`;
    ctx.fill();
    // Event ticks
    for (let index = 0; index < 12; index += 1) {
      const value = 0.25 + Math.abs(Math.sin(index * 1.7)) * 0.7;
      ctx.fillStyle =
        index === 4 || index === 9 ? "#d18f7d" : `${accent}88`;
      ctx.fillRect(left + 268 + index * 14, 84, 6, value * 132);
    }
    line(ctx, left, 234, 248, 7, "#3a342b", 3);
    line(ctx, left, 250, 160, 7, "#2a261f", 3);
    line(ctx, left + 268, 234, 60, 7, "#2a261f", 3);
  } else if (variant === "scout") {
    line(ctx, left, top, 110, 10, "#4a4438", 5);
    const cards = [
      { x: 0, y: 78, w: 196, h: 74 },
      { x: 210, y: 78, w: 196, h: 74 },
      { x: 0, y: 164, w: 196, h: 74 },
    ];
    cards.forEach((card, index) => {
      rounded(ctx, left + card.x, card.y, card.w, card.h, 7);
      ctx.fillStyle = index === 0 ? "rgba(216,195,165,0.1)" : "#191612";
      ctx.fill();
      ctx.strokeStyle = index === 0 ? `${accent}66` : "rgba(238,234,222,0.08)";
      ctx.stroke();
      line(ctx, left + card.x + 12, card.y + 14, 120, 7, "#ded3be", 3);
      line(ctx, left + card.x + 12, card.y + 30, 156, 5, "#6c6556", 2);
      line(ctx, left + card.x + 12, card.y + 44, 128, 5, "#4a4438", 2);
      line(ctx, left + card.x + 12, card.y + 58, 42, 8, `${accent}88`, 4);
    });
  } else if (variant === "review") {
    line(ctx, left, top, 96, 10, "#4a4438", 5);
    line(ctx, left, 82, contentWidth, 1, "rgba(238,234,222,0.09)", 0.5);
    for (let index = 0; index < 7; index += 1) {
      const y = 98 + index * 20;
      line(ctx, left, y, index % 3 === 0 ? 360 : 250 + (index % 4) * 30, 6, "#5d5648", 3);
    }
    // Editorial marks
    [116, 176, 216].forEach((y, index) => {
      ctx.strokeStyle = index === 1 ? "#d18f7d" : `${accent}bb`;
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(left + 18, y + 4);
      ctx.lineTo(left + 20 + index * 26, y + 4);
      ctx.stroke();
      ctx.fillStyle = index === 1 ? "#d18f7d" : accent;
      ctx.fillRect(left + 26 + index * 26, y - 2, 3, 12);
    });
    line(ctx, left, 246, 150, 7, "#3a342b", 3);
  } else if (variant === "ops") {
    line(ctx, left, top, 128, 10, "#4a4438", 5);
    const columns = [0, 1, 2];
    columns.forEach((column) => {
      const x = left + column * 142;
      rounded(ctx, x, 78, 126, 168, 8);
      ctx.fillStyle = column === 1 ? "rgba(216,195,165,0.09)" : "#191612";
      ctx.fill();
      ctx.strokeStyle = "rgba(238,234,222,0.08)";
      ctx.stroke();
      line(ctx, x + 12, 92, 64, 6, "#8a8170", 3);
      for (let index = 0; index < 5; index += 1) {
        ctx.strokeStyle = "rgba(238,234,222,0.22)";
        ctx.lineWidth = 1;
        rounded(ctx, x + 12, 110 + index * 22, 9, 9, 2);
        ctx.stroke();
        if (index < 3 && column !== 2) {
          ctx.fillStyle = accent;
          ctx.fillRect(x + 14, 112 + index * 22, 5, 5);
        }
        line(ctx, x + 28, 112 + index * 22, 70 + (index % 3) * 12, 5, "#4f493d", 2);
      }
    });
  } else {
    // creator / brief / default: a document being written
    line(ctx, left, top, 132, 10, "#4a4438", 5);
    line(ctx, left + 360, top, 54, 10, `${accent}99`, 5);
    rounded(ctx, left, 76, contentWidth, 158, 8);
    ctx.fillStyle = "#16130f";
    ctx.fill();
    ctx.strokeStyle = "rgba(238,234,222,0.08)";
    ctx.stroke();

    line(ctx, left + 18, 94, 210, 9, "#ded3be", 4);
    line(ctx, left + 18, 112, 120, 6, "#6c6556", 3);
    const widths = [430, 468, 402, 448, 300];
    widths.forEach((w, index) => {
      line(ctx, left + 18, 140 + index * 16, Math.min(w, contentWidth - 36), 5, "#4a4438", 2);
    });
    if (variant === "creator") {
      ctx.fillStyle = `${accent}`;
      ctx.fillRect(left + 18, 222, 46, 3);
      ctx.fillStyle = "rgba(255,255,255,0.7)";
      ctx.fillRect(left + 68, 222, 2, 3);
    }
  }

  // Bottom status bar
  ctx.fillStyle = "rgba(238,234,222,0.045)";
  ctx.fillRect(0, height - 24, width, 24);
  ctx.beginPath();
  ctx.arc(width - 92, height - 12, 3.5, 0, Math.PI * 2);
  ctx.fillStyle = statusColor;
  ctx.fill();
  ctx.font =
    '500 10px "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif';
  ctx.fillStyle = "#a89f8c";
  ctx.fillText(statusLabel, width - 80, height - 12);

  // A quiet accent line under the chrome keeps each desk colour-coded.
  ctx.fillStyle = accent;
  ctx.globalAlpha = 0.55;
  ctx.fillRect(0, 33, width, 1.5);
  ctx.globalAlpha = 1;

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  texture.needsUpdate = true;
  return texture;
}
