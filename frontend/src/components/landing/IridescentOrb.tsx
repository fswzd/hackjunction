import { useEffect, useRef, useState } from "react";
import * as THREE from "three";

/**
 * A single full-screen fragment shader. The orb is procedural: no model files,
 * no textures, no network requests. Scroll drives the camera, the pointer adds
 * parallax, and the warm palette follows the workbench theme (ivory / champagne
 * / sage / rose) instead of the reference site's purple.
 */
const FRAGMENT = `
uniform vec2 res;
uniform vec2 mouse;
uniform float time;
uniform float progress;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

// Analytic studio environment: a broad warm softbox, a tall strip light and a
// cool bounce. Reflecting this instead of a rainbow palette is what reads as
// polished metal rather than plastic.
vec3 studio(vec3 r) {
  float el = asin(clamp(r.y, -1.0, 1.0));
  float az = atan(r.x, r.z);
  float up = smoothstep(-0.55, 0.95, el);

  vec3 c = mix(vec3(0.020, 0.018, 0.015), vec3(0.26, 0.232, 0.185), up);

  c += vec3(1.85, 1.58, 1.18) *
       exp(-pow((az + 0.95) / 0.62, 2.0) - pow((el - 0.42) / 0.46, 2.0));

  c += vec3(1.05, 0.96, 0.80) *
       exp(-pow((az - 1.24) / 0.16, 2.0)) *
       smoothstep(-0.55, 0.20, el) * smoothstep(0.95, 0.30, el);

  c += vec3(0.72, 0.57, 0.39) *
       exp(-pow((az + 1.90) / 0.085, 2.0)) *
       smoothstep(-0.40, 0.28, el) * smoothstep(0.90, 0.20, el);

  c += vec3(0.055, 0.085, 0.072) *
       exp(-pow((az - 0.50) / 0.90, 2.0)) * smoothstep(0.20, -0.80, el);

  c += vec3(0.22, 0.155, 0.085) * smoothstep(-0.08, -1.0, el);
  return c;
}

void main() {
  vec2 uv = (gl_FragCoord.xy * 2.0 - res) / res.y;
  float t = time * 0.10;

  vec3 ro = vec3(0.0, 0.0, 4.9 - progress * 2.6);
  vec3 rd = normalize(vec3(uv, -2.6));
  vec3 center = vec3(mouse * 0.14 + vec2(sin(t) * 0.04, cos(t * 0.9) * 0.045), 0.0);

  vec2 projected = center.xy * (2.6 / ro.z);
  float radius = 1.05 * 2.6 / ro.z;

  vec3 bg = vec3(0.028, 0.026, 0.022);
  bg += vec3(0.075, 0.060, 0.042) * pow(0.5 + 0.5 * sin(uv.x * 1.7 + sin(uv.y * 2.1 + t)), 3.0);
  bg += vec3(0.020, 0.018, 0.014) * exp(-1.2 * length(uv - vec2(-0.7, -0.75)));
  bg += vec3(0.24, 0.18, 0.12) * exp(-3.6 * length(uv - vec2(0.72, 0.42)));

  float halo = exp(-max(0.0, length(uv - projected) - radius) * 5.5);
  bg += vec3(0.22, 0.18, 0.13) * halo * 0.32;
  bg += vec3(0.50, 0.42, 0.30) * exp(-abs(length(uv - projected) - radius) * 70.0) * 0.12;

  float dust = smoothstep(0.9983, 1.0, hash(floor(uv * 340.0)));
  bg += vec3(0.32, 0.29, 0.23) * dust * 0.40;

  vec3 col = bg;
  vec3 oc = ro - center;
  float b = dot(oc, rd);
  float c = dot(oc, oc) - 1.05 * 1.05;
  float h = b * b - c;

  if (h > 0.0) {
    float dist = -b - sqrt(h);
    vec3 p = ro + rd * dist;
    vec3 n = normalize(p - center);

    // A barely-there wobble keeps the reflections from looking CG-perfect.
    float ripple = sin(n.x * 7.0 + t * 1.3) * sin(n.y * 5.5 - t * 0.9) * sin(n.z * 6.0 + t * 0.7);
    n = normalize(n + 0.016 * vec3(
      sin(n.y * 9.0 + t * 1.1),
      sin(n.z * 8.0 - t * 0.8),
      ripple
    ));

    vec3 viewDir = normalize(ro - p);
    float ndv = max(dot(n, viewDir), 0.0);
    float fresnel = pow(1.0 - ndv, 5.0);

    vec3 refl = reflect(rd, n);
    vec3 env = studio(refl);
    vec3 f0 = vec3(0.76, 0.68, 0.55);
    vec3 f = f0 + (1.0 - f0) * fresnel;
    col = env * f;

    // Thin-film tint, strongest at the grazing edge.
    float film = fresnel * 2.6 + 0.35 * sin(n.x * 3.0 + n.y * 2.0 + t * 0.6);
    vec3 irid = 0.5 + 0.5 * cos(6.28318 * (vec3(0.02, 0.31, 0.62) + film));
    col += irid * vec3(0.10, 0.072, 0.048) * (0.22 + 0.78 * fresnel);

    vec3 lightA = normalize(vec3(-0.55, 0.82, 0.62));
    col += vec3(1.0, 0.92, 0.78) * pow(max(dot(refl, lightA), 0.0), 46.0) * 0.55;

    vec3 lightB = normalize(vec3(0.85, 0.25, 0.45));
    col += vec3(0.76, 0.84, 0.80) * pow(max(dot(refl, lightB), 0.0), 22.0) * 0.22;

    col *= vec3(1.04, 0.985, 0.915);
    col += vec3(0.95, 0.78, 0.52) * pow(fresnel, 2.2) * 0.36;
    col += vec3(0.05, 0.09, 0.11) * pow(fresnel, 1.3) * 0.28;
    col *= 1.0 - 0.20 * smoothstep(0.10, -0.90, n.y);
  } else {
    // Soft contact shadow on an implied floor: this is what grounds the sphere.
    if (rd.y < 0.0) {
      float tp = (-1.34 - ro.y) / rd.y;
      if (tp > 0.0) {
        vec3 hit = ro + rd * tp;
        float d = length(hit.xz - center.xz);
        col *= 1.0 - exp(-d * d * 0.50) * 0.82;
        col += vec3(0.30, 0.23, 0.15) * exp(-d * d * 0.90) * 0.10;
      }
    }
  }

  col = pow(max(col, 0.0), vec3(0.92));
  col *= 1.0 - 0.22 * length(uv * vec2(0.72, 0.62));

  float dither = (hash(gl_FragCoord.xy + fract(time * 0.7)) - 0.5) * 0.012;
  gl_FragColor = vec4(col + dither, 1.0);
}
`;

const VERTEX = "void main() { gl_Position = vec4(position, 1.0); }";

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

export function IridescentOrb() {
  const host = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = host.current;
    if (!el) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: false,
        alpha: false,
        powerPreference: "low-power",
      });
    } catch {
      setFailed(true);
      return;
    }
    setFailed(false);

    const canvas = renderer.domElement;
    canvas.style.display = "block";
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    el.appendChild(canvas);

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");

    const uniforms = {
      res: { value: new THREE.Vector2() },
      mouse: { value: new THREE.Vector2() },
      time: { value: 0 },
      progress: { value: 0 },
    };

    const geometry = new THREE.PlaneGeometry(2, 2);
    const material = new THREE.ShaderMaterial({
      uniforms,
      vertexShader: VERTEX,
      fragmentShader: FRAGMENT,
      depthTest: false,
      depthWrite: false,
    });
    const scene = new THREE.Scene();
    scene.add(new THREE.Mesh(geometry, material));
    const camera = new THREE.Camera();

    let dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    let raf = 0;
    let last = 0;
    let slowFrames = 0;
    let lastOpacity = 1;
    const pointer = new THREE.Vector2();

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, reduce.matches ? 1 : 1.5);
      renderer.setPixelRatio(dpr);
      renderer.setSize(window.innerWidth, window.innerHeight);
      renderer.getDrawingBufferSize(uniforms.res.value);
    };
    resize();

    const onPointerMove = (event: PointerEvent) => {
      pointer.set(
        (event.clientX / window.innerWidth) * 2 - 1,
        1 - (event.clientY / window.innerHeight) * 2,
      );
    };

    const onContextLost = (event: Event) => {
      event.preventDefault();
      cancelAnimationFrame(raf);
      setFailed(true);
    };

    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      const dt = last ? Math.min((now - last) / 1000, 0.1) : 0.016;
      last = now;
      if (document.hidden) return;

      if (!reduce.matches) uniforms.time.value += dt;
      uniforms.mouse.value.lerp(pointer, reduce.matches ? 1 : 0.045);

      const target = clamp(
        window.scrollY / Math.max(window.innerHeight * 1.15, 1),
        0,
        1,
      );
      uniforms.progress.value +=
        (target - uniforms.progress.value) * (reduce.matches ? 1 : 0.075);

      // The orb recedes once the editorial sections take over. Rendering stops
      // completely after it is invisible, which keeps long-page scrolling cheap.
      const fade = 1 - clamp(
        (window.scrollY - window.innerHeight * 0.9) /
          Math.max(window.innerHeight * 1.5, 1),
        0,
        1,
      );
      if (Math.abs(fade - lastOpacity) > 0.002) {
        el.style.opacity = fade.toFixed(3);
        lastOpacity = fade;
      }
      if (fade <= 0.002) return;

      if (dt > 0.034 && !reduce.matches) {
        slowFrames += 1;
        if (slowFrames > 90 && dpr > 0.75) {
          dpr = 0.75;
          renderer.setPixelRatio(dpr);
          renderer.setSize(window.innerWidth, window.innerHeight);
          renderer.getDrawingBufferSize(uniforms.res.value);
        }
      }

      renderer.render(scene, camera);
    };

    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    canvas.addEventListener("webglcontextlost", onContextLost);
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("webglcontextlost", onContextLost);
      geometry.dispose();
      material.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
    };
  }, []);

  return (
    <div className="landing-orb" ref={host} aria-hidden="true">
      {failed ? <div className="landing-orb-fallback" /> : null}
    </div>
  );
}
