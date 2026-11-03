// Live preview compositor. Plays the baked edit from proxy chunks with two ping-pong <video> elements
// (gapless cuts, crossfades across transitions), and draws reframe/zoom keys, fit modes, b-roll, overlays
// (live HTML graphics or rendered files), texts, captions, effects, the look, and platform safe zones.
// The final render is FFmpeg's; this is a faithful, fast approximation for judging the edit.

import { Emitter, clamp, ease, h } from "./util.js";
import { clipDur, clipEnd } from "./bake.js";
import { CaptionLayer, fontFor } from "./captions.js";
import { MGHost, fadeOpacity } from "./mghost.js";
import { AudioMix, speechIntervals } from "./audio.js";

const GRADES = {
  warm_cinematic: { contrast: 1.06, saturate: 1.08, sepia: 0.12, brightness: 0.99 },
  moody: { contrast: 1.12, saturate: 0.8, brightness: 0.95, hue: 6, vignette: 0.45 },
  clean: { contrast: 1.04, saturate: 1.05, brightness: 1.01 },
  teal_orange: { contrast: 1.06, saturate: 1.1, hue: -8, sepia: 0.05 },
  bw: { grayscale: 1, contrast: 1.15 },
  vintage: { sepia: 0.35, contrast: 0.95, saturate: 0.85 },
  pastel: { saturate: 0.85, brightness: 1.04, contrast: 0.95 },
  vibrant: { saturate: 1.25, contrast: 1.08 },
  cool: { saturate: 0.95, hue: 10, brightness: 1.0 },
  golden: { sepia: 0.2, saturate: 1.1, brightness: 1.02 },
  matte: { contrast: 0.9, saturate: 0.92, brightness: 1.03 },
  punchy: { contrast: 1.14, saturate: 1.15 },
};

const SAFE_ZONES = {
  tiktok: [[0, 0, 1, 0.08], [0.84, 0.36, 1, 0.86], [0, 0.8, 0.84, 1]],
  reels: [[0, 0, 1, 0.07], [0.85, 0.45, 1, 0.9], [0, 0.78, 0.85, 1]],
  shorts: [[0, 0, 1, 0.07], [0.84, 0.5, 1, 0.9], [0, 0.8, 0.84, 1]],
  youtube: [[0, 0, 1, 0.09], [0, 0.9, 1, 1]],
};

function gradeFilter(color) {
  const g = GRADES[color?.preset];
  if (!g) return "";
  const k = color.intensity ?? 1;
  const mix = (v, neutral) => neutral + (v - neutral) * k;
  const parts = [];
  if (g.contrast !== undefined) parts.push(`contrast(${mix(g.contrast, 1)})`);
  if (g.saturate !== undefined) parts.push(`saturate(${mix(g.saturate, 1)})`);
  if (g.brightness !== undefined) parts.push(`brightness(${mix(g.brightness, 1)})`);
  if (g.sepia !== undefined) parts.push(`sepia(${mix(g.sepia, 0)})`);
  if (g.grayscale !== undefined) parts.push(`grayscale(${mix(g.grayscale, 0)})`);
  if (g.hue !== undefined) parts.push(`hue-rotate(${mix(g.hue, 0)}deg)`);
  return parts.join(" ");
}

function interpKeys(keys, t, field, dflt) {
  if (!keys?.length) return dflt;
  if (t <= keys[0].t) return keys[0][field] ?? dflt;
  for (let i = 0; i + 1 < keys.length; i++) {
    const a = keys[i], b = keys[i + 1];
    if (t <= b.t) return (a[field] ?? dflt) + ((b[field] ?? dflt) - (a[field] ?? dflt)) * ((t - a.t) / Math.max(1e-6, b.t - a.t));
  }
  return keys[keys.length - 1][field] ?? dflt;
}

export class Player extends Emitter {
  constructor(root, { getHTML, assetUrl } = {}) {
    super();
    this.root = root;
    this.t = 0;
    this.playing = false;
    this.baked = null;
    this.media = null;
    this.scale = 0.3;
    this.audio = new AudioMix();
    this.stage = h("div", { class: "stage", tabindex: "0", "aria-label": "Preview" });
    this.bg = h("canvas", { class: "stage-bg", width: 96, height: 170, "aria-hidden": "true" });
    this.vlayer = h("div", { class: "layer video-layer" });
    this.blayer = h("div", { class: "layer broll-layer" });
    this.olayer = h("div", { class: "layer overlay-layer" });
    this.tlayer = h("div", { class: "layer text-layer" });
    this.clayer = h("div", { class: "layer caption-layer" });
    this.fxlayer = h("div", { class: "layer fx-layer" });
    this.safe = h("div", { class: "layer safe-layer" });
    this.empty = h("div", { class: "stage-empty" }, "No preview yet");
    this.slots = [0, 1].map((i) => {
      const el = h("video", { class: "main-video", playsinline: true, preload: "auto", muted: false, "data-slot": i });
      el.crossOrigin = "anonymous";
      this.vlayer.append(el);
      return { el, url: null };
    });
    this.stage.append(this.bg, this.vlayer, this.blayer, this.olayer, this.tlayer, this.clayer, this.fxlayer, this.safe, this.empty);
    root.append(this.stage);
    this.captions = new CaptionLayer(this.clayer);
    this.mg = new MGHost(this.olayer, getHTML || (async () => null), assetUrl);
    this.pool = new Map();          // b-roll / rendered overlay elements by id
    this.textEls = new Map();
    new ResizeObserver(() => this.fit()).observe(root);
    this._loop = this._loop.bind(this);
  }

  get duration() { return this.baked?._duration || 0; }

  fit() {
    if (!this.baked) return;
    const { width: W, height: H } = this.baked.canvas;
    const box = this.root.getBoundingClientRect();
    const scale = Math.max(0.05, Math.min(box.width / W, box.height / H));
    this.scale = scale;
    this.stage.style.width = `${W * scale}px`;
    this.stage.style.height = `${H * scale}px`;
    this.captions.key = null;
    this.renderAt(this.t, true);
  }

  setEdit(baked, media) {
    this.baked = baked;
    this.media = media || this.media;
    this.speech = speechIntervals(baked.captions?.chunks);
    this.empty.hidden = (baked.main || []).length > 0;
    this.t = clamp(this.t, 0, Math.max(0, this.duration - 0.001));
    this.fit();
    this.audio.preload(baked, this.media);
    if (this.playing) this.audio.play(this.baked, this.media, this.t, this.speech);
  }

  play() {
    if (!this.baked || this.playing) return;
    if (this.t >= this.duration - 0.05) this.t = 0;
    this.audio.ensure();
    for (const s of this.slots) this.audio.attachVideo(s.el);
    this.playing = true;
    this.clock = { t0: this.t, wall: performance.now() };
    this.audio.play(this.baked, this.media, this.t, this.speech);
    this.emit("play");
    requestAnimationFrame(this._loop);
  }

  pause() {
    if (!this.playing) return;
    this.playing = false;
    this.audio.stop();
    for (const s of this.slots) s.el.pause();
    for (const el of this.pool.values()) if (el.pause) el.pause();
    this.emit("pause");
    this.renderAt(this.t, true);
  }

  toggle() { this.playing ? this.pause() : this.play(); }

  // Collect `n` clicks on the picture (canvas 0..1 coordinates), e.g. the corners of a screen to replace.
  // Esc cancels (resolves null). The playhead stays where it is, so the picked moment is this.t.
  pickPoints(n, hint = "") {
    this.pause?.();
    return new Promise((resolve) => {
      const pts = [];
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "pick-svg");
      svg.setAttribute("viewBox", "0 0 1 1");
      svg.setAttribute("preserveAspectRatio", "none");
      const tip = h("div", { class: "pick-tip", role: "status" }, hint || `Click ${n} points on the picture. Esc cancels.`);
      const layer = h("div", { class: "pick-layer", tabindex: "-1" }, svg, tip);
      const done = (val) => { layer.remove(); window.removeEventListener("keydown", onKey, true); resolve(val); };
      const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); done(null); } };
      const draw = () => {
        svg.replaceChildren();
        if (pts.length > 1) {
          const poly = document.createElementNS(svg.namespaceURI, pts.length === n ? "polygon" : "polyline");
          poly.setAttribute("points", pts.map((q) => q.join(",")).join(" "));
          poly.setAttribute("class", "pick-shape");
          svg.append(poly);
        }
        pts.forEach(([x, y], i) => {
          const c = document.createElementNS(svg.namespaceURI, "circle");
          c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", 0.012);
          c.setAttribute("class", "pick-dot");
          svg.append(c);
        });
        tip.textContent = pts.length < n ? `${hint || "Click the corners"}: ${pts.length + 1} of ${n}. Esc cancels.` : "Done";
      };
      layer.addEventListener("pointerdown", (e) => {
        const r = this.stage.getBoundingClientRect();
        pts.push([Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]);
        draw();
        if (pts.length === n) setTimeout(() => done(pts.map((q) => q.map((v) => +v.toFixed(4)))), 250);
      });
      window.addEventListener("keydown", onKey, true);
      this.stage.append(layer);
      layer.focus();
      draw();
    });
  }

  seek(t) {
    this.t = clamp(t, 0, Math.max(0, this.duration - 0.001));
    if (this.playing) {
      this.clock = { t0: this.t, wall: performance.now() };
      this.audio.play(this.baked, this.media, this.t, this.speech);
    }
    this.renderAt(this.t, true);
  }

  _loop(now) {
    if (!this.playing) return;
    const t = this.clock.t0 + (now - this.clock.wall) / 1000;
    if (t >= this.duration) {
      this.t = this.duration;
      this.pause();
      this.emit("ended");
      return;
    }
    this.t = t;
    this.renderAt(t);
    requestAnimationFrame(this._loop);
  }

  // ------------------------------------------------------------ media helpers

  chunk(sid, srcT) {
    const chunks = this.media?.sources?.[sid]?.proxy || [];
    let best = null;
    for (const c of chunks) {
      if (!c.url) continue;
      if (c.start <= srcT && srcT < c.start + c.duration + 0.05) return c;
      if (!best || Math.abs(c.start - srcT) < Math.abs(best.start - srcT)) best = c;
    }
    return best;
  }

  slot(url, avoid) {
    // A crossfade inside one proxy chunk needs the same file in both elements, hence `avoid`.
    let s = this.slots.find((x) => x.url === url && x !== avoid);
    if (s) return s;
    s = this.slots.find((x) => x !== avoid) || this.slots[0];
    s.url = url;
    s.el.src = url;
    return s;
  }

  syncVideo(el, local, rate, fps) {
    if (this.playing) {
      if (el.paused) el.play().catch(() => {});
      const drift = local - el.currentTime;
      if (Math.abs(drift) > 0.25 && !el.seeking) el.currentTime = local;
      else el.playbackRate = clamp(rate * (1 + drift * 0.6), 0.5, 4);
    } else {
      if (!el.paused) el.pause();
      if (Math.abs(local - el.currentTime) > 0.5 / (fps || 30) && !el.seeking) el.currentTime = local;
    }
  }

  place(el, clip, src, tIn, z = 1) {
    const { width: W, height: H } = this.baked.canvas;
    const sw = src?.width || 16, sh = src?.height || 9;
    const fit = clip.fit || "cover";
    let dw, dh;
    if (fit === "stretch") { dw = W; dh = H; }
    else {
      const base = fit === "contain" ? Math.min(W / sw, H / sh) : Math.max(W / sw, H / sh);
      dw = sw * base; dh = sh * base;
    }
    const cx = interpKeys(clip.crop, tIn, "cx", 0.5), cy = interpKeys(clip.crop, tIn, "cy", 0.5);
    let ox = (0.5 - cx) * dw, oy = (0.5 - cy) * dh;
    ox = dw > W ? clamp(ox, -(dw - W) / 2, (dw - W) / 2) : 0;
    oy = dh > H ? clamp(oy, -(dh - H) / 2, (dh - H) / 2) : 0;
    const tr = clip.transform || {};
    const s = z * (tr.scale ?? 1);
    const tx = (tr.x || 0) * (W / 2), ty = -(tr.y || 0) * (H / 2);
    const k = this.scale;
    el.style.width = `${dw * k}px`;
    el.style.height = `${dh * k}px`;
    el.style.transform = `translate(${((W - dw) / 2 + ox * z + tx) * k}px, ${((H - dh) / 2 + oy * z + ty) * k}px) ` +
      `scale(${s}) rotate(${tr.rotation || 0}deg)`;
    return fit;
  }

  zoomAt(clip, tIn) {
    const zm = clip.zoom;
    if (!zm) return 1;
    const p = ease(tIn / Math.max(1e-3, clipDur(clip)), zm.ease || "out");
    return (zm.start_scale ?? 1) + ((zm.end_scale ?? 1.12) - (zm.start_scale ?? 1)) * p;
  }

  // ------------------------------------------------------------ frame

  renderAt(t, force = false) {
    const b = this.baked;
    if (!b) return;
    const fps = b.canvas.fps || 30;
    const main = b.main || [];
    let i = main.findIndex((c) => c.start <= t && t < clipEnd(c));
    if (i < 0 && main.length) i = t >= (main[main.length - 1].start || 0) ? main.length - 1 : 0;
    const visible = [];
    if (i >= 0) {
      const cur = main[i];
      visible.push({ clip: cur, srcT: cur.src_in + (t - cur.start) * (cur.speed || 1), alpha: 1, primary: true });
      const nxt = main[i + 1], prev = main[i - 1];
      const dn = nxt?.transition_in ? Math.max(0.05, nxt.transition_in.duration || 0.3) : 0;
      const dp = cur.transition_in ? Math.max(0.05, cur.transition_in.duration || 0.3) : 0;
      if (nxt && dn && t > nxt.start - dn / 2) {
        const p = (t - (nxt.start - dn / 2)) / dn;
        visible.push({ clip: nxt, srcT: nxt.src_in - (nxt.start - t) * (nxt.speed || 1), alpha: clamp(p, 0, 1), primary: false });
      } else if (prev && dp && t < cur.start + dp / 2) {
        const p = (t - (cur.start - dp / 2)) / dp;
        visible[0].alpha = clamp(p, 0, 1);
        visible.unshift({ clip: prev, srcT: prev.src_out + (t - cur.start) * (prev.speed || 1), alpha: 1, primary: false, under: true });
      }
    }
    const used = new Set();
    let primaryEl = null, primaryFit = "cover";
    for (const v of visible) {
      const ch = this.chunk(v.clip.source, v.srcT);
      if (!ch) continue;
      const other = [...used][0];
      const s = this.slot(ch.url, other);
      used.add(s);
      const el = s.el;
      const local = Math.max(0, v.srcT - ch.start);
      this.syncVideo(el, local, v.clip.speed || 1, fps);
      const tIn = t - (v.clip.start || 0);
      const fit = this.place(el, v.clip, this.media?.sources?.[v.clip.source], tIn, this.zoomAt(v.clip, tIn));
      el.style.opacity = String(v.alpha);
      el.style.zIndex = v.under ? "1" : v.primary ? "2" : "3";
      el.hidden = false;
      const gain = v.clip.mute ? 0 : (v.clip.volume ?? 1) * v.alpha;
      this.audio.setVideoGain(el, gain);
      if (v.primary) { primaryEl = el; primaryFit = fit; }
    }
    for (const s of this.slots) {
      if (!used.has(s)) {
        s.el.hidden = true;
        if (!s.el.paused) s.el.pause();
        this.audio.setVideoGain(s.el, 0);
        // preload the next clip into the idle element
        const nxt = main[i + 1];
        if (nxt && nxt.start - t < 1.5) {
          const ch = this.chunk(nxt.source, nxt.src_in);
          if (ch && s.url !== ch.url) { s.url = ch.url; s.el.src = ch.url; }
          if (ch && s.url === ch.url && Math.abs(s.el.currentTime - (nxt.src_in - ch.start)) > 0.1 && !s.el.seeking) {
            s.el.currentTime = Math.max(0, nxt.src_in - ch.start);
          }
        }
      }
    }
    this.vlayer.style.filter = gradeFilter(b.color);
    this.drawBackdrop(primaryEl, primaryFit);
    this.renderBroll(t, fps);
    this.renderOverlays(t, fps);
    this.renderTexts(t);
    this.captions.render(b, t, this.scale);
    this.renderEffects(t);
    this.renderSafe(b.knobs?.safe_zone);
    this.emit("time", t);
  }

  drawBackdrop(el, fit) {
    const show = el && fit === "contain";
    this.bg.hidden = !show;
    if (!show || el.readyState < 2) return;
    this._bgTick = (this._bgTick || 0) + 1;
    if (this._bgTick % 4 && this.playing) return;
    const ctx = this.bg.getContext("2d");
    const { width: cw, height: ch } = this.bg;
    const s = Math.max(cw / el.videoWidth, ch / el.videoHeight);
    ctx.filter = "blur(6px) brightness(0.7)";
    ctx.drawImage(el, (cw - el.videoWidth * s) / 2, (ch - el.videoHeight * s) / 2, el.videoWidth * s, el.videoHeight * s);
  }

  poolEl(id, kind, url) {
    let el = this.pool.get(id);
    if (el && el.dataset.url !== url) { el.remove(); el = null; }
    if (!el) {
      el = kind === "image" ? h("img", { class: "pool-el", alt: "" }) : h("video", { class: "pool-el", playsinline: true, muted: true, preload: "auto" });
      if (kind !== "image") { el.muted = true; el.crossOrigin = "anonymous"; }
      el.dataset.url = url;
      el.src = url;
      this.pool.set(id, el);
    }
    return el;
  }

  renderBroll(t, fps) {
    const seen = new Set();
    for (const c of this.baked.broll || []) {
      if (c.start == null || t < c.start || t >= clipEnd(c)) continue;
      const src = this.media?.sources?.[c.source];
      const tIn = t - c.start;
      let url, kind = src?.kind || "video", local = 0;
      if (kind === "image") url = src?.still;
      else {
        const ch = this.chunk(c.source, c.src_in + tIn * (c.speed || 1));
        url = ch?.url;
        local = c.src_in + tIn * (c.speed || 1) - (ch?.start || 0);
      }
      if (!url) continue;
      const el = this.poolEl(`b_${c.id}`, kind, url);
      if (el.parentElement !== this.blayer) this.blayer.append(el);
      seen.add(`b_${c.id}`);
      if (kind !== "image") this.syncVideo(el, local, c.speed || 1, fps);
      this.place(el, c, src, tIn, this.zoomAt(c, tIn));
      el.style.opacity = String(Math.min(fadeOpacity({ ...c, duration: clipDur(c) }, tIn), c.transform?.opacity ?? 1));
      el.hidden = false;
    }
    this.hideUnseen(this.blayer, seen);
  }

  hideUnseen(layer, seen) {
    for (const [id, el] of this.pool) {
      if (el.parentElement === layer && !seen.has(id)) { el.hidden = true; if (el.pause && !el.paused) el.pause(); }
    }
  }

  renderOverlays(t, fps) {
    const live = [];
    const seen = new Set();
    const { width: W, height: H } = this.baked.canvas;
    for (const ov of this.baked.overlays || []) {
      if (t < ov.start || t >= ov.start + ov.duration) continue;
      const local = t - ov.start;
      const url = this.media?.overlays?.[ov.id];
      if (ov.mg && !url) { live.push({ ov, local }); continue; }
      if (!url) continue;
      const kind = /\.(png|jpe?g|gif|webp|svg)(\?|$)/i.test(url) ? "image" : "video";
      const el = this.poolEl(`o_${ov.id}`, kind, url);
      if (el.parentElement !== this.olayer) this.olayer.append(el);
      seen.add(`o_${ov.id}`);
      if (kind === "video") this.syncVideo(el, local, 1, fps);
      const tr = ov.transform || {};
      const k = this.scale;
      const fit = ov.fit || "none";
      el.style.width = fit === "none" ? "auto" : `${W * k}px`;
      el.style.height = fit === "none" ? "auto" : `${H * k}px`;
      el.style.objectFit = fit === "none" ? "" : fit;
      if (fit === "none" && el.naturalWidth !== undefined && el.naturalWidth) {
        el.style.width = `${el.naturalWidth * k}px`;
      } else if (fit === "none" && el.videoWidth) {
        el.style.width = `${el.videoWidth * k}px`;
      }
      const ew = parseFloat(el.style.width) || W * k, eh = (el.videoHeight || el.naturalHeight) ? ew * ((el.videoHeight || el.naturalHeight) / (el.videoWidth || el.naturalWidth)) : H * k;
      const s = tr.scale ?? 1;
      el.style.transform = `translate(${(W * k - ew) / 2 + (tr.x || 0) * (W / 2) * k}px, ${(H * k - eh) / 2 - (tr.y || 0) * (H / 2) * k}px) scale(${s})`;
      el.style.opacity = String(fadeOpacity(ov, local) * (tr.opacity ?? 1));
      el.style.zIndex = String(10 + (ov.layer || 0));
      el.hidden = false;
    }
    this.hideUnseen(this.olayer, seen);
    this.mg.update(live, this.baked.canvas, this.scale);
  }

  renderTexts(t) {
    const { width: W, height: H } = this.baked.canvas;
    const k = this.scale;
    const seen = new Set();
    for (const x of this.baked.texts || []) {
      if (t < x.start || t >= x.start + x.duration) continue;
      seen.add(x.id);
      let el = this.textEls.get(x.id);
      const st = x.style || {};
      const key = JSON.stringify([x.text, st, k]);
      if (!el || el.dataset.key !== key) {
        el?.remove();
        const f = fontFor(st.font || "Poppins Bold");
        el = h("div", { class: "text-item" }, x.text);
        el.dataset.key = key;
        const px = (st.size || 0.07) * Math.min(W, H) * k;
        Object.assign(el.style, {
          fontFamily: `"${f.family}", "Hind Siliguri", sans-serif`, fontWeight: String(st.weight || f.weight || 700),
          fontSize: `${px}px`, color: st.color || "#FFFFFF", textAlign: st.align || "center", maxWidth: `${(W - 80) * k}px`,
        });
        if (st.stroke) { el.style.webkitTextStroke = `${(st.stroke_width || 0.08) * px * 2}px ${st.stroke}`; el.style.paintOrder = "stroke fill"; }
        if (st.background) { el.style.background = st.background.color || st.background; el.style.padding = `${px * 0.15}px ${px * 0.35}px`; el.style.borderRadius = `${px * 0.15}px`; }
        this.tlayer.append(el);
        this.textEls.set(x.id, el);
      }
      const tr = x.transform || {};
      el.style.left = `${(W / 2 + (tr.x || 0) * W / 2) * k}px`;
      el.style.top = `${(H / 2 - (tr.y || 0) * H / 2) * k}px`;
      el.style.transform = `translate(-50%, -50%) scale(${tr.scale ?? 1}) rotate(${tr.rotation || 0}deg)`;
      el.style.opacity = String(fadeOpacity(x, t - x.start) * (tr.opacity ?? 1));
      el.hidden = false;
    }
    for (const [id, el] of this.textEls) if (!seen.has(id)) el.hidden = true;
  }

  renderEffects(t) {
    const fx = this.fxlayer;
    let flash = 0, shake = 0, blur = 0, vignette = GRADES[this.baked.color?.preset]?.vignette || 0, pulse = 0, split = 0, grain = 0;
    for (const e of this.baked.effects || []) {
      if (t < e.start || t >= e.start + e.duration) continue;
      const p = (t - e.start) / Math.max(1e-3, e.duration);
      const k = e.intensity ?? 1;
      switch (e.render) {
        case "flash": flash = Math.max(flash, (1 - p) * k); break;
        case "shake": case "glitch": shake = Math.max(shake, k); break;
        case "blur": blur = Math.max(blur, 6 * k); break;
        case "vignette": vignette = Math.max(vignette, 0.6 * k); break;
        case "zoom_pulse": pulse = Math.max(pulse, Math.sin(Math.PI * p) * 0.06 * k); break;
        case "rgb_split": split = Math.max(split, 3 * k); break;
        case "film_grain": grain = Math.max(grain, 0.18 * k); break;
        default: break;
      }
    }
    fx.style.background = vignette ? `radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,${vignette}) 100%)` : "";
    fx.style.boxShadow = flash ? `inset 0 0 0 9999px rgba(255,255,255,${flash})` : "";
    fx.classList.toggle("grain", grain > 0);
    const jitter = shake ? `translate(${(Math.random() - 0.5) * 8 * shake}px, ${(Math.random() - 0.5) * 8 * shake}px)` : "";
    const zoom = pulse ? `scale(${1 + pulse})` : "";
    this.vlayer.style.transform = `${jitter} ${zoom}`.trim();
    const extra = [blur ? `blur(${blur * this.scale}px)` : "", split ? `drop-shadow(${-split}px 0 rgba(255,0,60,.6)) drop-shadow(${split}px 0 rgba(0,220,255,.6))` : ""];
    this.vlayer.style.filter = [gradeFilter(this.baked.color), ...extra].filter(Boolean).join(" ");
  }

  renderSafe(zone) {
    const boxes = SAFE_ZONES[zone];
    if (this._safeKey === zone) return;
    this._safeKey = zone;
    this.safe.replaceChildren();
    if (!boxes) return;
    for (const [x0, y0, x1, y1] of boxes) {
      const b = h("div", { class: "safe-box" });
      Object.assign(b.style, { left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` });
      this.safe.append(b);
    }
    this.safe.append(h("div", { class: "safe-label" }, `${zone} UI`));
  }
}
