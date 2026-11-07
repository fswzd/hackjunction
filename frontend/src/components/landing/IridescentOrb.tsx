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

vec3 palette(float t) {
  return 0.55 + 0.45 * cos(6.28318 * (vec3(0.10, 0.21, 0.35) + t));
}

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

void main() {
  vec2 uv = (gl_FragCoord.xy * 2.0 - res) / res.y;
  float t = time * 0.12;

  vec3 bg = vec3(0.030, 0.028, 0.024);
  bg += vec3(0.075, 0.060, 0.042) * pow(0.5 + 0.5 * sin(uv.x * 1.7 + sin(uv.y * 2.1 + t)), 3.0);
  bg += vec3(0.030, 0.026, 0.020) * exp(-1.2 * length(uv - vec2(-0.7, -0.75)));
  bg += vec3(0.22, 0.17, 0.12) * exp(-4.2 * length(uv - vec2(0.68, 0.46)));

  float dust = smoothstep(0.9985, 1.0, hash(floor(uv * 320.0)));
  bg += vec3(0.35, 0.32, 0.26) * dust * 0.35;

  vec3 ro = vec3(0.0, 0.0, 4.8 - progress * 2.55);
  vec3 rd = normalize(vec3(uv, -2.6));
  vec3 center = vec3(mouse * 0.13 + vec2(sin(t) * 0.03, cos(t) * 0.035), 0.0);
  vec3 oc = ro - center;
  float b = dot(oc, rd);
  float c = dot(oc, oc) - 1.06;
  float h = b * b - c;
  vec3 col = bg;

  if (h > 0.0) {
    float dist = -b - sqrt(h);
    vec3 p = ro + rd * dist;
    vec3 n = normalize(p - center);
    float fresnel = pow(1.0 - max(dot(n, -rd), 0.0), 2.4);

    float flow = sin(n.x * 3.0 + t + sin(n.y * 4.2 - t)) * 0.18
               + sin(n.z * 2.6 + t * 0.8) * 0.12
               + sin((n.x + n.y + n.z) * 4.5 - t * 0.5) * 0.06;
    vec3 ir = palette(flow + n.y * 0.12 + fresnel * 0.22);
    vec3 base = mix(vec3(0.20, 0.17, 0.13), ir, 0.58);

    float top = pow(max(dot(n, normalize(vec3(-0.25, 0.85, 0.8))), 0.0), 3.0);
    col = mix(base, bg, 0.22) + vec3(0.10, 0.09, 0.07) * top;

    col += vec3(0.50, 0.43, 0.33) * fresnel * 0.55;
    col += vec3(0.10, 0.22, 0.18) * exp(-16.0 * dot(n.xy - vec2(0.28, -0.55), n.xy - vec2(0.28, -0.55)));

    vec3 refl = reflect(rd, n);
    float spec = pow(max(dot(refl, normalize(vec3(-1.0, 1.5, 1.9))), 0.0), 18.0);
    col += vec3(0.62, 0.55, 0.42) * spec;
    col = mix(col, vec3(0.80, 0.72, 0.60), pow(fresnel, 6.0) * 0.45);
  }

  float vignette = 1.0 - 0.20 * length(uv);
  col *= vignette;
  gl_FragColor = vec4(pow(col, vec3(0.88)), 1.0);
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
