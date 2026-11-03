// Shared helpers for Three.js motion-graphics templates (ES module).
//
//   <script type="importmap">{"imports": {"three": "/__vendor/three/build/three.module.js",
//                                         "three/addons/": "/__vendor/three/examples/jsm/"}}</script>
//   <script type="module"> import { THREE, D, stage, run, ... } from "/__mg/three-kit.js"; ... </script>
//
// Contract with the renderer: draw synchronously inside window.__seek(t) (may return a promise when a
// video texture has to seek). Everything is a function of t, never of the previous frame, so any frame
// renders the same in the renderer, the Studio and a browser preview.
// Text is drawn with the browser's own shaping (canvas 2D), so Bangla conjuncts are correct; Latin
// titles can use real extruded glyphs (TTF) where the font file is reachable (renderer: /__fonts/).

import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

export { THREE };

export const D = (defaults = {}) => Object.assign({}, defaults, window.__VEDIT_DATA__ || {});
export const isBangla = (s) => /[ঀ-৿]/.test(s || "");
export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, t) => a + (b - a) * t;
export const seg = (t, a, b) => clamp((t - a) / Math.max(1e-6, b - a));
export const ease = {
  linear: (p) => p,
  in: (p) => p * p * p,
  out: (p) => 1 - Math.pow(1 - p, 3),
  inOut: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
  expo: (p) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p)),
  back: (p, s = 1.7) => 1 + (s + 1) * Math.pow(p - 1, 3) + s * Math.pow(p - 1, 2),
  sine: (p) => 0.5 - 0.5 * Math.cos(Math.PI * p),
};
// seeded random (deterministic per seed): rand(7)() -> 0..1
export const rand = (seed = 1) => () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;

export function color(c, fallback = "#ffffff") {
  return new THREE.Color(c || fallback);
}

// Renderer + scene + camera filling the page, transparent background, studio reflections.
export function stage({ fov = 35, env = true, exposure = 1.0, bg = null } = {}) {
  const W = innerWidth, H = innerHeight;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true,
                                             powerPreference: "high-performance" });
  renderer.setPixelRatio(1);
  renderer.setSize(W, H);
  renderer.setClearColor(0x000000, bg ? 1 : 0);
  if (bg) renderer.setClearColor(new THREE.Color(bg), 1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping ?? THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = exposure;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  Object.assign(renderer.domElement.style, { position: "fixed", inset: "0", width: "100%", height: "100%" });
  document.body.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(fov, W / H, 0.1, 400);
  camera.position.set(0, 0, 10);
  if (env) {
    const pm = new THREE.PMREMGenerator(renderer);
    scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture;
  }
  return { renderer, scene, camera, W, H, aspect: W / H };
}

// Visible width/height of the plane `dist` in front of a perspective camera.
export function view(camera, dist) {
  const h = 2 * dist * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
  return { w: h * camera.aspect, h };
}

// Studio-style lights (the environment gives reflections; these give shape and a rim).
export function lights(scene, { key = 2.2, rim = "#ffffff", rimIntensity = 2.5, shadow = false } = {}) {
  const k = new THREE.DirectionalLight(0xffffff, key);
  k.position.set(4, 6, 8);
  if (shadow) {
    k.castShadow = true;
    k.shadow.mapSize.set(2048, 2048);
    Object.assign(k.shadow.camera, { left: -6, right: 6, top: 6, bottom: -6, near: 0.5, far: 40 });
    k.shadow.radius = 6;
  }
  const r = new THREE.DirectionalLight(new THREE.Color(rim), rimIntensity);
  r.position.set(-6, 3, -6);
  const a = new THREE.AmbientLight(0xffffff, 0.35);
  scene.add(k, r, a);
  return { key: k, rim: r, ambient: a };
}

// Register the frame function: window.__seek for the renderer / Studio, a looping preview otherwise.
export function run(st, draw, duration) {
  const frame = (t) => {
    const r = draw(t);
    if (r && typeof r.then === "function") return r.then(() => st.renderer.render(st.scene, st.camera));
    st.renderer.render(st.scene, st.camera);
  };
  window.__seek = (t) => frame(t);
  window.__duration = duration;
  if (!window.__VEDIT_RENDERING__) {
    const t0 = performance.now();
    const loop = () => { frame(((performance.now() - t0) / 1000) % duration); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  } else {
    frame(0);
  }
}

// ------------------------------------------------------------------ text

const FAMILY_FILES = {
  "Poppins": { 500: "Poppins-Medium.ttf", 600: "Poppins-SemiBold.ttf", 700: "Poppins-Bold.ttf", 800: "Poppins-ExtraBold.ttf", 900: "Poppins-Black.ttf" },
  "Anton": "Anton-Regular.ttf", "Bebas Neue": "BebasNeue-Regular.ttf", "Archivo Black": "ArchivoBlack-Regular.ttf",
  "Luckiest Guy": "LuckiestGuy-Regular.ttf", "Bangers": "Bangers-Regular.ttf", "Rubik Mono One": "RubikMonoOne-Regular.ttf",
  "DM Serif Display": "DMSerifDisplay-Regular.ttf", "Instrument Serif": "InstrumentSerif-Regular.ttf",
  "Permanent Marker": "PermanentMarker-Regular.ttf",
};

export function fontFile(family, weight = 900) {
  const f = FAMILY_FILES[family];
  if (!f) return null;
  if (typeof f === "string") return f;
  const ws = Object.keys(f).map(Number).sort((a, b) => Math.abs(a - weight) - Math.abs(b - weight));
  return f[ws[0]];
}

export async function fontsReady(specs) {
  try { await Promise.all(specs.map((s) => document.fonts.load(s))); } catch { /* fall back to what loaded */ }
}

// Text drawn to a canvas with the browser's shaping. Returns {canvas, w, h} (pixels).
export function textCanvas(text, { family = "Poppins", weight = 900, size = 220, color = "#ffffff", stroke = 0,
                                   strokeColor = "#000000", padding = 0.18, lineHeight = 1.08, align = "center",
                                   shadow = null } = {}) {
  const fam = isBangla(text) ? `"Hind Siliguri", "${family}", sans-serif` : `"${family}", "Hind Siliguri", sans-serif`;
  const font = `${weight} ${size}px ${fam}`;
  const c = document.createElement("canvas");
  const ctx = c.getContext("2d");
  ctx.font = font;
  const lines = String(text).split("\n");
  const widths = lines.map((l) => ctx.measureText(l).width);
  const pad = size * padding;
  c.width = Math.ceil(Math.max(...widths) + pad * 2 + stroke * 2);
  c.height = Math.ceil(lines.length * size * lineHeight + pad * 2 + stroke * 2);
  ctx.font = font;
  ctx.textBaseline = "middle";
  ctx.textAlign = align;
  ctx.lineJoin = "round";
  const x = align === "center" ? c.width / 2 : pad + stroke;
  lines.forEach((l, i) => {
    const y = pad + stroke + size * lineHeight * (i + 0.5);
    if (shadow) { ctx.shadowColor = shadow.color || "rgba(0,0,0,.5)"; ctx.shadowBlur = shadow.blur ?? size * 0.12; }
    if (stroke) { ctx.lineWidth = stroke * 2; ctx.strokeStyle = strokeColor; ctx.strokeText(l, x, y); }
    ctx.shadowColor = "transparent";
    ctx.fillStyle = color;
    ctx.fillText(l, x, y);
  });
  return { canvas: c, w: c.width, h: c.height };
}

export function canvasTexture(canvas, renderer) {
  const t = new THREE.CanvasTexture(canvas);
  t.colorSpace = THREE.SRGBColorSpace;
  if (renderer) t.anisotropy = renderer.capabilities.getMaxAnisotropy();
  t.needsUpdate = true;
  return t;
}

// "Slab" 3D text for any script: the shaped glyphs as a front face plus stacked slices for the depth.
// height = world height of the text block; depth = world thickness.
export function slabText(text, { height = 1, depth = 0.25, slices = 28, color: front = "#ffffff", side = null,
                                  family = "Poppins", weight = 900, metal = 0.2, rough = 0.35, renderer } = {}) {
  const tc = textCanvas(text, { family, weight, color: "#ffffff" });
  const tex = canvasTexture(tc.canvas, renderer);
  const w = height * tc.w / tc.h;
  const geo = new THREE.PlaneGeometry(w, height);
  const g = new THREE.Group();
  const frontMat = new THREE.MeshStandardMaterial({ map: tex, color: color(front), transparent: true, alphaTest: 0.35,
                                                    metalness: metal, roughness: rough });
  const sideCol = color(side || new THREE.Color(front).multiplyScalar(0.42).getStyle());
  for (let i = slices; i >= 1; i--) {
    const k = i / slices;
    const m = new THREE.MeshStandardMaterial({ map: tex, color: sideCol.clone().multiplyScalar(0.75 + 0.25 * (1 - k)),
                                               transparent: true, alphaTest: 0.35, metalness: metal + 0.2, roughness: 0.4 });
    const p = new THREE.Mesh(geo, m);
    p.position.z = -depth * k;
    g.add(p);
  }
  const f = new THREE.Mesh(geo, frontMat);
  f.position.z = 0.001;
  g.add(f);
  g.userData = { width: w, height, kind: "slab" };
  return g;
}

// Real extruded glyphs from a TTF (Latin). Resolves null when the font file is not reachable.
export async function ttfText(text, { family = "Poppins", weight = 900, size = 1, depth = 0.25, bevel = 0.02,
                                      color: front = "#ffffff", side = null, metal = 0.25, rough = 0.3 } = {}) {
  const file = fontFile(family, weight);
  if (!file || isBangla(text)) return null;
  try {
    const [{ TTFLoader }, { Font }, { TextGeometry }] = await Promise.all([
      import("three/addons/loaders/TTFLoader.js"), import("three/addons/loaders/FontLoader.js"),
      import("three/addons/geometries/TextGeometry.js")]);
    const json = await new TTFLoader().loadAsync(`/__fonts/${file}`);
    const font = new Font(json);
    const geo = new TextGeometry(String(text), { font, size, depth, curveSegments: 10, bevelEnabled: bevel > 0,
                                                bevelThickness: bevel, bevelSize: bevel * 0.8, bevelSegments: 4 });
    geo.computeBoundingBox();
    const bb = geo.boundingBox;
    geo.translate(-(bb.max.x + bb.min.x) / 2, -(bb.max.y + bb.min.y) / 2, -depth / 2);
    const mats = [
      new THREE.MeshStandardMaterial({ color: color(front), metalness: metal, roughness: rough }),
      new THREE.MeshStandardMaterial({ color: color(side || new THREE.Color(front).multiplyScalar(0.45).getStyle()),
                                       metalness: Math.min(1, metal + 0.35), roughness: 0.22 }),
    ];
    const mesh = new THREE.Mesh(geo, mats);
    mesh.userData = { width: bb.max.x - bb.min.x, height: bb.max.y - bb.min.y, kind: "ttf" };
    return mesh;
  } catch (e) {
    console.warn("ttfText fallback:", e?.message || e);
    return null;
  }
}

// Text label as a camera-facing plane (charts, pins). Width follows the text.
export function label(text, { height = 0.3, color: c = "#ffffff", family = "Poppins", weight = 700, renderer, bg = null } = {}) {
  const tc = textCanvas(text, { family, weight, size: 120, color: c, padding: 0.25 });
  if (bg) {
    const ctx = tc.canvas.getContext("2d");
    ctx.globalCompositeOperation = "destination-over";
    ctx.fillStyle = bg;
    const r = tc.h * 0.3;
    ctx.beginPath();
    ctx.roundRect(0, 0, tc.w, tc.h, r);
    ctx.fill();
  }
  const tex = canvasTexture(tc.canvas, renderer);
  const m = new THREE.Mesh(new THREE.PlaneGeometry(height * tc.w / tc.h, height),
                           new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }));
  m.userData.width = height * tc.w / tc.h;
  return m;
}

// ------------------------------------------------------------------ media

// Absolute local paths in data are served by the renderer under /__abs/ (the Studio maps them too).
export const mediaUrl = (p) => (!p ? p : /^(https?:|data:|blob:|\/__)/.test(p) ? p : "/__abs/" + String(p).replace(/\\/g, "/"));

export function loadTexture(path, renderer) {
  return new Promise((res, rej) => new THREE.TextureLoader().load(mediaUrl(path), (t) => {
    t.colorSpace = THREE.SRGBColorSpace;
    if (renderer) t.anisotropy = renderer.capabilities.getMaxAnisotropy();
    res(t);
  }, undefined, rej));
}

// Video texture that seeks exactly: await vt.seek(t) inside the frame function.
export async function loadVideo(path) {
  const v = document.createElement("video");
  v.src = mediaUrl(path);
  v.muted = true;
  v.playsInline = true;
  v.crossOrigin = "anonymous";
  v.preload = "auto";
  await new Promise((res, rej) => { v.onloadeddata = res; v.onerror = rej; });
  const tex = new THREE.VideoTexture(v);
  tex.colorSpace = THREE.SRGBColorSpace;
  return {
    texture: tex, video: v, aspect: v.videoWidth / v.videoHeight,
    seek: (t) => new Promise((res) => {
      const target = v.duration ? t % v.duration : t;
      if (Math.abs(v.currentTime - target) < 0.004) { tex.needsUpdate = true; return res(); }
      v.onseeked = () => { tex.needsUpdate = true; res(); };
      v.currentTime = target;
    }),
  };
}

export const isVideo = (p) => /\.(mp4|webm|mov|m4v)$/i.test(p || "");

// Rounded-rectangle shape (device bodies, cards).
export function roundedRect(w, h, r) {
  const s = new THREE.Shape();
  const x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y);
  s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  return s;
}

// Soft radial shadow / glow sprite under objects.
export function softDisc(radius, { color: c = "#000000", opacity = 0.45 } = {}) {
  const cv = document.createElement("canvas");
  cv.width = cv.height = 256;
  const ctx = cv.getContext("2d");
  const g = ctx.createRadialGradient(128, 128, 0, 128, 128, 128);
  const col = new THREE.Color(c);
  const rgb = `${Math.round(col.r * 255)},${Math.round(col.g * 255)},${Math.round(col.b * 255)}`;
  g.addColorStop(0, `rgba(${rgb},1)`);
  g.addColorStop(1, `rgba(${rgb},0)`);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 256, 256);
  const m = new THREE.Mesh(new THREE.PlaneGeometry(radius * 2, radius * 2),
                           new THREE.MeshBasicMaterial({ map: canvasTexture(cv), transparent: true, opacity, depthWrite: false }));
  return m;
}

// Assets ready: templates assign window.__ready = setup() so the renderer waits for fonts / textures.
export function ready(promise) {
  window.__ready = promise.catch((e) => { console.error("composition setup failed:", e?.message || e); });
  return window.__ready;
}
