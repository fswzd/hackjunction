import { useEffect, useRef } from "react";

interface Thread {
  y: number;
  amp: number;
  amp2: number;
  freq: number;
  speed: number;
  phase: number;
  alpha: number;
  width: number;
  color: [number, number, number];
  beads: number[];
}

const THREADS: Thread[] = [
  { y: 0.24, amp: 0.1, amp2: 0.035, freq: 0.9, speed: 0.11, phase: 0.4, alpha: 0.2, width: 1.1, color: [238, 226, 201], beads: [0.15, 0.62] },
  { y: 0.36, amp: 0.075, amp2: 0.03, freq: 1.25, speed: -0.085, phase: 1.8, alpha: 0.11, width: 0.8, color: [216, 195, 165], beads: [0.4] },
  { y: 0.49, amp: 0.055, amp2: 0.02, freq: 0.7, speed: 0.07, phase: 3.1, alpha: 0.09, width: 1.4, color: [201, 169, 166], beads: [0.76] },
  { y: 0.62, amp: 0.09, amp2: 0.025, freq: 1.05, speed: -0.12, phase: 0.9, alpha: 0.14, width: 0.9, color: [177, 188, 164], beads: [0.22, 0.83] },
  { y: 0.75, amp: 0.07, amp2: 0.03, freq: 0.82, speed: 0.095, phase: 2.35, alpha: 0.1, width: 1.2, color: [238, 226, 201], beads: [0.55] },
  { y: 0.18, amp: 0.045, amp2: 0.018, freq: 1.6, speed: -0.06, phase: 4.4, alpha: 0.07, width: 0.7, color: [216, 195, 165], beads: [0.68] },
  { y: 0.86, amp: 0.05, amp2: 0.02, freq: 1.4, speed: 0.075, phase: 5.2, alpha: 0.08, width: 0.8, color: [201, 169, 166], beads: [0.32] },
];

const pointer = { x: -9999, y: -9999, tx: -9999, ty: -9999 };

function yAt(thread: Thread, x: number, width: number, height: number, time: number) {
  const u = x / width;
  let y =
    height * thread.y +
    Math.sin(u * Math.PI * 2 * thread.freq + time * thread.speed + thread.phase) *
      thread.amp *
      height +
    Math.sin(u * Math.PI * 6.2 - time * thread.speed * 0.7 + thread.phase) *
      thread.amp2 *
      height;

  const dx = pointer.x - x;
  const dy = pointer.y - y;
  const distance = Math.hypot(dx, dy);
  if (distance < 360) {
    const pull = 1 - distance / 360;
    y += dy * pull * pull * 0.5;
  }
  return y;
}

export function FlowLines() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    let width = 0;
    let height = 0;
    let dpr = 1;
    let raf = 0;
    let last = 0;
    let time = 0;

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const drawThread = (thread: Thread) => {
      const step = Math.max(7, width / 110);
      const points: Array<[number, number]> = [];
      for (let x = -60; x <= width + 60; x += step) {
        points.push([x, yAt(thread, x, width, height, time)]);
      }

      const [r, g, b] = thread.color;
      const gradient = ctx.createLinearGradient(0, 0, width, 0);
      gradient.addColorStop(0, `rgba(${r},${g},${b},0)`);
      gradient.addColorStop(0.22, `rgba(${r},${g},${b},${thread.alpha})`);
      gradient.addColorStop(0.78, `rgba(${r},${g},${b},${thread.alpha})`);
      gradient.addColorStop(1, `rgba(${r},${g},${b},0)`);

      ctx.beginPath();
      points.forEach(([x, y], index) => {
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = gradient;
      ctx.lineWidth = thread.width;
      ctx.stroke();

      for (const offset of thread.beads) {
        const t = (time * thread.speed * 0.055 + offset) % 1;
        const normalized = t < 0 ? t + 1 : t;
        const x = normalized * width;
        const y = yAt(thread, x, width, height, time);
        const glow = ctx.createRadialGradient(x, y, 0, x, y, 26);
        glow.addColorStop(0, `rgba(${r},${g},${b},0.5)`);
        glow.addColorStop(0.35, `rgba(${r},${g},${b},0.16)`);
        glow.addColorStop(1, `rgba(${r},${g},${b},0)`);
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(x, y, 26, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = `rgba(252,246,233,0.65)`;
        ctx.beginPath();
        ctx.arc(x, y, 1.5, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      const delta = last ? Math.min((now - last) / 1000, 0.05) : 0.016;
      last = now;
      if (document.hidden) return;
      if (!reduce.matches) time += delta;

      pointer.x += (pointer.tx - pointer.x) * 0.08;
      pointer.y += (pointer.ty - pointer.y) * 0.08;

      ctx.clearRect(0, 0, width, height);
      ctx.globalCompositeOperation = "lighter";

      if (pointer.x > -1000) {
        const glow = ctx.createRadialGradient(
          pointer.x,
          pointer.y,
          0,
          pointer.x,
          pointer.y,
          320,
        );
        glow.addColorStop(0, "rgba(235,216,184,0.06)");
        glow.addColorStop(1, "rgba(235,216,184,0)");
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(pointer.x, pointer.y, 320, 0, Math.PI * 2);
        ctx.fill();
      }

      for (const thread of THREADS) drawThread(thread);
    };

    const onPointerMove = (event: PointerEvent) => {
      pointer.tx = event.clientX;
      pointer.ty = event.clientY;
    };
    const onPointerLeave = () => {
      pointer.tx = -9999;
      pointer.ty = -9999;
    };
    const onVisibility = () => {
      last = 0;
    };

    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    document.addEventListener("pointerleave", onPointerLeave);
    document.addEventListener("visibilitychange", onVisibility);

    if (reduce.matches) {
      time = 4.2;
      pointer.tx = width * 0.62;
      pointer.ty = height * 0.4;
      pointer.x = pointer.tx;
      pointer.y = pointer.ty;
      ctx.globalCompositeOperation = "lighter";
      for (const thread of THREADS) drawThread(thread);
    } else {
      raf = requestAnimationFrame(draw);
    }

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerleave", onPointerLeave);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return <canvas ref={ref} className="landing-threads" aria-hidden="true" />;
}
