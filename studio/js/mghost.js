// Motion graphics, live: the same template HTML the renderer uses, run in iframes and seeked to the
// playhead (GSAP timelines on window.__timelines, or window.__seek for canvas/three.js work).
// Renderer paths (/__vendor, /__mg, /__fonts) are rewritten to the CDN and the artifact's own files.

import { h } from "./util.js";

const GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.13.0/dist";
const THREE = "https://cdn.jsdelivr.net/npm/three@0.177.0";
const LOTTIE = "https://cdn.jsdelivr.net/npm/lottie-web@5.12.2/build/player/lottie.min.js";
const FONTS = "https://fonts.googleapis.com/css2?family=Anton&family=Archivo+Black&family=Atma:wght@700&family=Bangers&family=Bebas+Neue&family=Caveat+Brush&family=DM+Serif+Display:ital@0;1&family=Galada&family=Hind+Siliguri:wght@500;600;700&family=Instrument+Serif:ital@0;1&family=Luckiest+Guy&family=Permanent+Marker&family=Poppins:wght@500;600;700;800;900&family=Rubik+Mono+One&family=Tiro+Bangla&display=swap";

export class MGHost {
  // getHTML(ov) -> Promise<string|null>: template or composition HTML for an overlay
  constructor(layer, getHTML, assetUrl) {
    this.layer = layer;
    this.getHTML = getHTML;
    this.assetUrl = assetUrl || ((p) => p);
    this.frames = new Map();     // overlay id -> {wrap, iframe, key, lastSeen}
    this.creating = new Map();   // overlay id -> Promise while its HTML loads (frames render concurrently)
    this.base = new URL(".", document.baseURI).href;
  }

  rewrite(html, data) {
    const mgBase = new URL("mg/lib/", this.base).href;
    let out = html
      .replaceAll('src="/__vendor/gsap.min.js"', `src="${GSAP}/gsap.min.js"`)
      .replace(/(["'])\/__vendor\/gsap\/([^"']+)\1/g, (_, q, f) => `${q}${GSAP}/${f}${q}`)
      .replaceAll("/__vendor/three.module.js", `${THREE}/build/three.module.js`)
      .replace(/(["'])\/__vendor\/three\/([^"']+)\1/g, (_, q, f) => `${q}${THREE}/${f}${q}`)
      .replaceAll("/__vendor/lottie.min.js", LOTTIE)
      .replace(/(["'])\/__mg\/([^"']+)\1/g, (_, q, f) => `${q}${mgBase}${f}${q}`)
      .replace(/(["'])\/__abs\/([^"']+)\1/g, (_, q, f) => `${q}${this.assetUrl(f)}${q}`);
    const boot = `<script>window.__VEDIT_DATA__=${JSON.stringify(data).replace(/</g, "\\u003c")};` +
      `window.__VEDIT_RENDERING__=true;</script><link rel="stylesheet" href="${FONTS}">` +
      `<style>:root{color-scheme:normal}html,body{background:transparent!important;margin:0;overflow:hidden}</style>`;
    return /<head[^>]*>/i.test(out) ? out.replace(/<head[^>]*>/i, (m) => m + boot) : boot + out;
  }

  async ensure(ov, canvas) {
    const key = JSON.stringify([ov.mg, ov.duration]);
    const have = this.frames.get(ov.id);
    if (have && have.key === key) return have;
    const busy = this.creating.get(ov.id);
    if (busy && busy.key === key) return busy.promise;
    const promise = this.create(ov, canvas, key);
    this.creating.set(ov.id, { key, promise });
    try { return await promise; } finally { if (this.creating.get(ov.id)?.promise === promise) this.creating.delete(ov.id); }
  }

  async create(ov, canvas, key) {
    const html = await this.getHTML(ov);
    if (this.frames.has(ov.id)) this.drop(ov.id);
    if (!html) return null;
    const W = ov.mg?.width || canvas.width, H = ov.mg?.height || canvas.height;
    const iframe = h("iframe", { class: "mg-frame", title: ov.label || ov.id, tabindex: "-1", "aria-hidden": "true",
                                 width: W, height: H, sandbox: "allow-scripts allow-same-origin" });
    iframe.srcdoc = this.rewrite(html, { ...(ov.mg?.data || {}), duration: ov.duration });
    const wrap = h("div", { class: "mg-wrap" }, iframe);
    wrap.style.width = `${W}px`;
    wrap.style.height = `${H}px`;
    this.layer.append(wrap);
    const entry = { wrap, iframe, key, W, H, lastSeen: performance.now(), ready: false, lastLocal: 0 };
    // A paused player seeks once; if the frame was still loading then, apply that time when it is ready.
    iframe.addEventListener("load", () => { entry.ready = true; this.seek(entry, entry.lastLocal); });
    this.frames.set(ov.id, entry);
    return entry;
  }

  seek(entry, t) {
    if (!entry?.ready) return;
    try {
      const win = entry.iframe.contentWindow;
      if (typeof win.__seek === "function") win.__seek(t);
      for (const tl of Object.values(win.__timelines || {})) {
        if (tl && tl.seek) { tl.pause(); tl.seek(t, false); }
      }
    } catch { /* a composition error must not stop playback */ }
  }

  // overlays visible at t: [{ov, local}], canvas {width,height}, scale (stage px per canvas px)
  async update(visible, canvas, scale) {
    const now = performance.now();
    const seen = new Set();
    for (const { ov, local } of visible) {
      if (!ov.mg) continue;
      seen.add(ov.id);
      const entry = await this.ensure(ov, canvas);
      if (!entry) continue;
      entry.lastSeen = now;
      const tr = ov.transform || {};
      const tx = (tr.x || 0) * (canvas.width / 2) * scale;
      const ty = -(tr.y || 0) * (canvas.height / 2) * scale;
      const s = (tr.scale ?? 1) * scale;
      const left = (canvas.width * scale - entry.W * s) / 2 + tx;     // scaled around the centre, like the renderer
      const top = (canvas.height * scale - entry.H * s) / 2 + ty;
      entry.wrap.style.transform = `translate(${left}px, ${top}px) scale(${s})`;
      entry.wrap.style.opacity = String(fadeOpacity(ov, local) * (tr.opacity ?? 1));
      entry.wrap.style.zIndex = String(10 + (ov.layer || 0));
      entry.wrap.hidden = false;
      entry.lastLocal = local;
      this.seek(entry, local);
    }
    for (const [id, entry] of this.frames) {
      if (!seen.has(id)) {
        entry.wrap.hidden = true;
        if (now - entry.lastSeen > 8000) this.drop(id);
      }
    }
  }

  drop(id) {
    const entry = this.frames.get(id);
    if (entry) entry.wrap.remove();
    this.frames.delete(id);
  }

  clear() {
    for (const id of [...this.frames.keys()]) this.drop(id);
  }
}

export function fadeOpacity(item, local) {
  let a = 1;
  if (item.fade_in) a = Math.min(a, local / item.fade_in);
  if (item.fade_out) a = Math.min(a, (item.duration - local) / item.fade_out);
  return Math.max(0, Math.min(1, a));
}
