#!/usr/bin/env node
// Frame-accurate HTML -> video renderer with real alpha.
//
// Composition contract (HyperFrames-compatible, plus two extras):
//   * GSAP timelines created { paused: true } and registered on window.__timelines[id]
//   * OR window.__seek = async (t) => {...} for Canvas / Three.js / custom engines
//   * CSS / WAAPI animations are also driven (document.getAnimations())
//   * Duration: --duration, else root [data-duration], else window.__duration
//   * Data: window.__VEDIT_DATA__ (from --data JSON), available before any script runs
// Served paths: /__vendor/gsap.min.js, /__vendor/gsap/<Plugin>.min.js, /__vendor/three.module.js,
//               /__vendor/lottie.min.js, /__fonts/<file>, /__mg/<file> (mg/lib)
//
// Usage: node render.mjs --input comp.html --out out.mov [--formats prores,key] [--width 1080 --height 1920]
//                         [--fps 30] [--duration 4] [--data data.json] [--chrome path] [--still 1.2]
// Extra passes (each can run alone, without --out):
//   --stills 0.5,2,3.75 --still-dir dir    one PNG per time (still_<ms>.png)
//   --board out.png                        the page's own storyboard (window.renderBoard(), animated pieces)
//   --audio stem [--audio-parts mix,music,sfx]   the page's score: window.renderAudioAll() -> stem_mix/music/sfx.wav
//                                          (only the parts asked for), or window.renderAudioWav() -> stem_mix.wav
//   --probe-text out.json [--probe-every 6] every string drawn (canvas fillText/strokeText) or shown (DOM text)
//                                          on sampled frames, in screen pixels, for the QA text check
//   --hash-frames 0,12,48                  render those frames forward, then backward, and compare (determinism)
//   --info                                 just the page's size, duration, TIMELINE (animated pieces) and GPU
// The printed JSON always carries `gpu`: the WebGL renderer string and whether it is a real GPU.

import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MG = path.resolve(HERE, "..");
const ROOT = path.resolve(MG, "..");
const NM = path.join(HERE, "node_modules");

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) continue;
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith("--")) out[key] = true;
    else { out[key] = next; i++; }
  }
  return out;
}

const args = parseArgs(process.argv);
const extraPass = args.info || args.stills || args.board || args.audio || args["probe-text"] || args["hash-frames"];
if (!args.input || (!args.out && args.still === undefined && !extraPass)) {
  console.error("usage: render.mjs --input comp.html --out out.mov [--formats prores,key,webm,mp4,png] " +
    "| --still t | --stills a,b --still-dir d | --board png | --audio stem | --probe-text json | --hash-frames a,b");
  process.exit(2);
}

const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
  ".webp": "image/webp", ".gif": "image/gif", ".ttf": "font/ttf", ".otf": "font/otf", ".woff2": "font/woff2",
  ".woff": "font/woff", ".mp4": "video/mp4", ".webm": "video/webm", ".mp3": "audio/mpeg", ".wav": "audio/wav" };

const inputPath = path.resolve(args.input);
const compDir = path.dirname(inputPath);
const fontsDir = path.join(ROOT, ".cache", "fonts");
const vendor = {
  "/__vendor/gsap.min.js": path.join(NM, "gsap", "dist", "gsap.min.js"),
  "/__vendor/three.module.js": path.join(NM, "three", "build", "three.module.js"),
  "/__vendor/lottie.min.js": path.join(NM, "lottie-web", "build", "player", "lottie.min.js"),
};

function resolveUrl(urlPath) {
  const p = decodeURIComponent(urlPath.split("?")[0]);
  if (vendor[p]) return vendor[p];
  if (p.startsWith("/__vendor/gsap/")) return path.join(NM, "gsap", "dist", path.basename(p));
  if (p.startsWith("/__vendor/three/")) return path.join(NM, "three", p.slice("/__vendor/three/".length));
  if (p.startsWith("/__fonts/")) return path.join(fontsDir, path.basename(p));
  if (p.startsWith("/__mg/")) return path.join(MG, "lib", p.slice("/__mg/".length));
  if (p.startsWith("/__abs/")) return p.slice("/__abs/".length);   // absolute local file (assets)
  return path.join(compDir, p);
}

const server = http.createServer((req, res) => {
  if (req.url === "/favicon.ico") { res.writeHead(204); res.end(); return; }
  const file = resolveUrl(req.url);
  fs.readFile(file, (err, buf) => {
    if (err) { res.writeHead(404); res.end("not found"); return; }
    res.writeHead(200, { "Content-Type": MIME[path.extname(file).toLowerCase()] || "application/octet-stream",
      "Access-Control-Allow-Origin": "*" });
    res.end(buf);
  });
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const port = server.address().port;

function findChrome() {
  if (args.chrome && fs.existsSync(args.chrome)) return args.chrome;
  if (process.env.VEDIT_CHROME && fs.existsSync(process.env.VEDIT_CHROME)) return process.env.VEDIT_CHROME;
  const pf = process.env["ProgramFiles"] || "C:\\Program Files";
  const pf86 = process.env["ProgramFiles(x86)"] || "C:\\Program Files (x86)";
  const local = process.env.LOCALAPPDATA || "";
  const cands = [
    path.join(pf, "Google/Chrome/Application/chrome.exe"), path.join(pf86, "Google/Chrome/Application/chrome.exe"),
    path.join(local, "Google/Chrome/Application/chrome.exe"), path.join(pf86, "Microsoft/Edge/Application/msedge.exe"),
    path.join(pf, "Microsoft/Edge/Application/msedge.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  ];
  return cands.find((c) => fs.existsSync(c));
}

const data = args.data ? JSON.parse(fs.readFileSync(path.resolve(args.data), "utf8")) : {};
const executablePath = findChrome();
if (!executablePath) { console.error("No Chrome/Edge found; set VEDIT_CHROME"); process.exit(3); }

// One browser per worker: a second tab in the same headless browser is "hidden" and never produces
// frames, so its screenshots would hang.
// GPU raster is far faster for blur/backdrop-filter/shadows than SwiftShader; --gpu off forces software.
const useGpu = String(args.gpu ?? process.env.VEDIT_MG_GPU ?? "on") !== "off";
const gpuArgs = useGpu
  ? ["--enable-gpu-rasterization", "--ignore-gpu-blocklist", "--enable-zero-copy",
     process.platform === "win32" ? "--use-angle=d3d11" : process.platform === "darwin" ? "--use-angle=metal" : "--use-angle=default"]
  : ["--disable-gpu", "--enable-unsafe-swiftshader"];
const launch = () => puppeteer.launch({
  executablePath, headless: true,
  args: ["--hide-scrollbars", "--mute-audio", "--force-device-scale-factor=1", "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows", "--run-all-compositor-stages-before-draw",
    "--font-render-hinting=none", "--allow-file-access-from-files", ...gpuArgs],
});
const browsers = [await launch()];

let exitCode = 0;
const compUrl = `http://127.0.0.1:${port}/${encodeURIComponent(path.basename(inputPath))}`;

// Text probe: record every string a canvas draws (in screen pixels, through the context's transform), so the QA
// text check sees labels cut off by the frame, overlapping, or under the platform UI. Adapted from animate's
// tools/textcheck.mjs (MIT, (c) 2026 cth9191). Installed before the page's own scripts run.
const PROBE_INIT = () => {
  window.__textlog = [];
  const P = CanvasRenderingContext2D.prototype;
  for (const name of ["fillText", "strokeText"]) {
    const orig = P[name];
    P[name] = function (str, x, y, maxW) {
      try {
        const s = String(str), cv = this.canvas, root = document.querySelector("canvas");
        // only the visible canvas, or a full-size layer composited onto it at identity (same size)
        if (s.trim() && cv && root && cv.width === root.width && cv.height === root.height && this.globalAlpha > 0.05) {
          const m = this.measureText(s), w = maxW != null ? Math.min(m.width, maxW) : m.width;
          const al = this.textAlign, x0 = al === "center" ? x - w / 2 : al === "right" || al === "end" ? x - w : x;
          const asc = m.actualBoundingBoxAscent || 0, desc = m.actualBoundingBoxDescent || 0;
          const tf = this.getTransform();
          const pts = [[x0, y - asc], [x0 + w, y - asc], [x0 + w, y + desc], [x0, y + desc]]
            .map(([px, py]) => [tf.a * px + tf.c * py + tf.e, tf.b * px + tf.d * py + tf.f]);
          // canvas pixels -> CSS pixels of the page (the canvas may be scaled to the viewport)
          const r = root.getBoundingClientRect(), kx = r.width / root.width, ky = r.height / root.height;
          const q = pts.map(([px, py]) => [r.left + px * kx, r.top + py * ky]);
          const xs = q.map((p) => p[0]), ys = q.map((p) => p[1]);
          window.__textlog.push({ s, kind: "canvas", x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) });
        }
      } catch (e) { /* the probe never breaks a render */ }
      return orig.apply(this, arguments);
    };
  }
};
const domText = () => {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const vis = (el) => {
    let a = 1;
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === "none" || cs.visibility === "hidden") return 0;
      a *= Number(cs.opacity);
    }
    return a;
  };
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const s = n.textContent.replace(/\s+/g, " ").trim();
    const el = n.parentElement;
    if (!s || !el || ["SCRIPT", "STYLE", "NOSCRIPT"].includes(el.tagName) || vis(el) < 0.05) continue;
    const rg = document.createRange(); rg.selectNodeContents(n);
    const rects = [...rg.getClientRects()].filter((r) => r.width > 0.5 && r.height > 0.5);
    if (!rects.length) continue;
    out.push({ s, kind: "dom", x0: Math.min(...rects.map((r) => r.left)), y0: Math.min(...rects.map((r) => r.top)),
      x1: Math.max(...rects.map((r) => r.right)), y1: Math.max(...rects.map((r) => r.bottom)), lines: rects.length });
  }
  return out;
};

async function openPage(width, height, browser = browsers[0]) {
  const page = await browser.newPage();
  page.on("console", (m) => { if (["error", "warning"].includes(m.type())) console.error(`[page ${m.type()}] ${m.text()}`); });
  page.on("pageerror", (e) => console.error(`[page error] ${e.message}`));
  page.on("requestfailed", (r) => console.error(`[missing] ${r.url()}`));
  page.on("response", (r) => { if (r.status() === 404) console.error(`[missing] ${decodeURIComponent(new URL(r.url()).pathname)}`); });
  if (args["probe-text"]) await page.evaluateOnNewDocument(PROBE_INIT);
  await page.evaluateOnNewDocument((d) => { window.__VEDIT_DATA__ = d; window.__VEDIT_RENDERING__ = true; }, data);
  await page.setViewport({ width, height, deviceScaleFactor: 1 });
  await page.goto(compUrl, { waitUntil: "networkidle0", timeout: 60000 });
  await page.evaluate(async () => { await document.fonts.ready; if (window.__ready) await window.__ready; });
  return page;
}

// No requestAnimationFrame here: worker pages are background tabs where rAF never fires. GSAP and
// WAAPI apply state synchronously, and the screenshot itself forces style/layout/paint.
// Canvas / Three.js compositions must draw synchronously inside window.__seek(t).
const seek = async (page, t) => page.evaluate(async (tt) => {
  if (typeof window.__seek === "function") await window.__seek(tt);
  if (window.__timelines) for (const tl of Object.values(window.__timelines)) { if (tl && tl.seek) { tl.pause(); tl.seek(tt, false); } }
  for (const a of document.getAnimations()) { a.pause(); a.currentTime = tt * 1000; }
}, t);

try {
  // First page: probe intrinsic size/duration, then reuse it as worker 0.
  let width = Number(args.width) || 0, height = Number(args.height) || 0;
  let page = await openPage(width || 1080, height || 1920);
  const meta = await page.evaluate(() => {
    const root = document.querySelector("[data-composition-id]") || document.body;
    return { w: Number(root.dataset?.width) || 0, h: Number(root.dataset?.height) || 0,
      d: Number(root.dataset?.duration) || window.__duration || 0 };
  });
  if ((!width && meta.w) || (!height && meta.h)) {
    width = width || meta.w; height = height || meta.h;
    await page.close();
    page = await openPage(width, height);
  }
  width = width || 1080;
  height = height || 1920;

  const fps = Number(args.fps) || 30;
  const duration = Number(args.duration) || meta.d;
  const alpha = !args.opaque;
  const shoot = (p) => p.screenshot({ type: "png", omitBackground: alpha, optimizeForSpeed: true,
    clip: { x: 0, y: 0, width, height }, captureBeyondViewport: false });
  // Does WebGL run on the GPU here? (headless Chrome falls back to software rendering: correct but slow)
  const gpu = await page.evaluate(() => {
    try {
      const c = document.createElement("canvas"), gl = c.getContext("webgl2") || c.getContext("webgl");
      if (!gl) return { ok: false, renderer: "no WebGL" };
      const ext = gl.getExtension("WEBGL_debug_renderer_info");
      const renderer = String(ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
      gl.getExtension("WEBGL_lose_context")?.loseContext();
      return { ok: !/swiftshader|llvmpipe|software|basic render/i.test(renderer), renderer };
    } catch (e) { return { ok: false, renderer: String(e) }; }
  });
  if (!gpu.ok && useGpu) console.error(`[gpu] WebGL runs in software (${gpu.renderer}): correct but slower`);
  const result = { width, height, fps, duration, gpu };
  const timeline = await page.evaluate(() => { try { return window.TIMELINE ? JSON.parse(JSON.stringify(window.TIMELINE)) : null; } catch { return null; } });
  if (timeline) result.timeline = timeline;

  if (args.stills) {
    const dir = path.resolve(String(args["still-dir"] || path.join(compDir, "stills")));
    fs.mkdirSync(dir, { recursive: true });
    result.stills = [];
    for (const t of String(args.stills).split(",").map(Number).filter((v) => Number.isFinite(v))) {
      await seek(page, t);
      const f = path.join(dir, `still_${String(Math.round(t * 1000)).padStart(7, "0")}.png`);
      fs.writeFileSync(f, await shoot(page));
      result.stills.push(f);
    }
  }
  if (args.board) {
    const b64 = await page.evaluate(() => (typeof window.renderBoard === "function"
      ? window.renderBoard().toDataURL("image/png").split(",")[1] : null));
    if (!b64) throw new Error("this page has no storyboard (window.renderBoard)");
    result.board = path.resolve(String(args.board));
    fs.writeFileSync(result.board, Buffer.from(b64, "base64"));
  }
  if (args.audio) {
    const stem = path.resolve(String(args.audio));
    const parts = args["audio-parts"] ? String(args["audio-parts"]).split(",").map((s) => s.trim()) : null;
    const res = await page.evaluate(async (pp) => {
      if (typeof window.renderAudioAll === "function") return await window.renderAudioAll(pp || undefined);
      if (typeof window.renderAudioWav === "function") return { mix: await window.renderAudioWav() };
      return null;
    }, parts);
    if (!res) throw new Error("this page has no score (window.renderAudioAll / renderAudioWav)");
    result.audio = {};
    for (const [k, b64] of Object.entries(res)) {
      if (!b64) continue;
      const f = `${stem}_${k}.wav`;
      fs.writeFileSync(f, Buffer.from(b64, "base64"));
      result.audio[k] = f;
    }
  }
  if (args["probe-text"]) {
    const every = Math.max(1, Number(args["probe-every"]) || 6);
    const total = Math.max(1, Math.round((duration || 0) * fps));
    const samples = [];
    for (let f = 0; f < total; f += every) {
      await page.evaluate(() => { window.__textlog = []; });
      await seek(page, f / fps);
      const canvasItems = await page.evaluate(() => window.__textlog || []);
      const domItems = await page.evaluate(domText);
      const anchor = await page.evaluate(() => { try { return typeof window.anchorAt === "function" ? window.anchorAt() : null; } catch { return null; } });
      samples.push({ t: +(f / fps).toFixed(3), items: [...canvasItems, ...domItems], ...(anchor ? { anchor } : {}) });
    }
    result.probe = path.resolve(String(args["probe-text"]));
    fs.writeFileSync(result.probe, JSON.stringify({ width, height, fps, duration, samples, timeline }, null, 0));
  }
  if (args["hash-frames"]) {
    const { createHash } = await import("node:crypto");
    const sha = (b) => createHash("sha1").update(b).digest("hex").slice(0, 16);
    const frs = String(args["hash-frames"]).split(",").map(Number).filter((v) => Number.isFinite(v));
    const first = [];
    for (const f of frs) { await seek(page, f / fps); first.push(sha(await shoot(page))); }
    const bad = [];
    for (let i = frs.length - 1; i >= 0; i--) { await seek(page, frs[i] / fps); if (sha(await shoot(page)) !== first[i]) bad.push(frs[i]); }
    result.hashes = Object.fromEntries(frs.map((f, i) => [f, first[i]]));
    result.deterministic = bad.length === 0;
    if (bad.length) result.nondeterministic_frames = bad;
  }

  if (args.still !== undefined) {
    await seek(page, Number(args.still) || 0);
    const buf = await shoot(page);
    const out = path.resolve(args.out || inputPath.replace(/\.html?$/i, ".png"));
    fs.writeFileSync(out, buf);
    console.log(JSON.stringify({ ...result, still: out }));
  } else if (!args.out) {
    console.log(JSON.stringify(result));
  } else {
    if (!duration) throw new Error("No duration: pass --duration or set data-duration on the composition root");
    const formats = String(args.formats || "prores").split(",").map((s) => s.trim()).filter(Boolean);
    const out = path.resolve(args.out);
    const stem = out.replace(/\.[^.]+$/, "");
    const n = formats.length;
    // One filtergraph: split the captured RGBA stream into one named branch per output format.
    const graph = [n > 1 ? `[0:v]split=${n}${formats.map((_, i) => `[s${i}]`).join("")}` : "[0:v]null[s0]"];
    const outArgs = [];
    const outputs = [];
    formats.forEach((fmt, i) => {
      let label = `[s${i}]`;
      if (fmt === "key") {
        // Green-screen version for editors without alpha support (CapCut chroma key).
        graph.push(`color=c=0x00FF00:s=${width}x${height}:r=${fps}[kg${i}]`,
          `[kg${i}][s${i}]overlay=shortest=1,format=yuv420p[k${i}]`);
        label = `[k${i}]`;
      }
      if (fmt === "prores") {
        outArgs.push("-map", label, "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le", "-vendor", "apl0", `${stem}.mov`);
        outputs.push(`${stem}.mov`);
      } else if (fmt === "webm") {
        // realtime/cpu-used 8 is ~5x faster than "good"; crf 22 keeps graphics edges clean.
        outArgs.push("-map", label, "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-crf", "22", "-b:v", "0", "-row-mt", "1",
          "-deadline", "realtime", "-cpu-used", "8", "-auto-alt-ref", "0", `${stem}.webm`);
        outputs.push(`${stem}.webm`);
      } else if (fmt === "mp4") {
        outArgs.push("-map", label, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-preset", "medium", `${stem}.mp4`);
        outputs.push(`${stem}.mp4`);
      } else if (fmt === "key") {
        outArgs.push("-map", label, "-c:v", "libx264", "-crf", "16", "-preset", "medium", `${stem}_key.mp4`);
        outputs.push(`${stem}_key.mp4`);
      } else if (fmt === "png") {
        const dir = `${stem}_frames`;
        fs.mkdirSync(dir, { recursive: true });
        outArgs.push("-map", label, path.join(dir, "f_%05d.png"));
        outputs.push(dir);
      } else {
        throw new Error(`unknown format ${fmt}`);
      }
    });
    // Capture in parallel pages (each seeks independently), then encode the sequence once.
    const frames = Math.max(1, Math.round(duration * fps));
    // Each worker is a whole headless Chrome (with its GPU process ~0.6-0.9 GB): by default, as many as the CPU
    // and the free memory allow (a 16 GB laptop with the owner's own apps open can't spare four).
    const memCap = Math.max(1, Math.floor((os.freemem() / 1e9 - 1.5) / 0.9));
    const workers = Math.max(1, Math.min(Number(args.workers) || Math.min(4, Math.max(1, Math.floor(os.cpus().length / 4)), memCap), frames));
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "vedit-mg-"));
    const t0 = Date.now();
    const pages = [page];
    const extra = await Promise.all(Array.from({ length: workers - 1 }, async () => {
      const b = await launch();
      browsers.push(b);
      return openPage(width, height, b);
    }));
    pages.push(...extra);
    const tLaunch = (Date.now() - t0) / 1000;
    await Promise.all(pages.map(async (p, w) => {
      for (let f = w; f < frames; f += workers) {
        await seek(p, f / fps);
        fs.writeFileSync(path.join(tmp, `f_${String(f).padStart(5, "0")}.png`), await shoot(p));
      }
    }));
    const tCapture = (Date.now() - t0) / 1000 - tLaunch;
    const ff = ["-y", "-v", "error", "-framerate", String(fps), "-i", path.join(tmp, "f_%05d.png"),
      "-filter_complex", graph.join(";"), ...outArgs];
    const proc = spawn(process.env.VEDIT_FFMPEG || "ffmpeg", ff, { stdio: ["ignore", "inherit", "inherit"] });
    const code = await new Promise((r) => proc.on("close", r));
    fs.rmSync(tmp, { recursive: true, force: true });
    if (code !== 0) throw new Error(`ffmpeg exited with ${code}`);
    const total = (Date.now() - t0) / 1000;
    console.log(JSON.stringify({ ...result, outputs, frames, fps, width, height, duration, workers, seconds: total,
      timing: { launch: tLaunch, capture: tCapture, encode: total - tLaunch - tCapture } }));
  }
} catch (err) {
  console.error(String(err && err.stack || err));
  exitCode = 1;
} finally {
  await Promise.all(browsers.map((b) => b.close().catch(() => {})));
  server.close();
}
process.exit(exitCode);
