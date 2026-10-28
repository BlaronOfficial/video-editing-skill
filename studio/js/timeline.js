// Multi-track timeline. Items are absolutely placed divs (fast enough for a few thousand items).
// Drag a graphic/sound/text to move it (anchored items change their offset, so they keep following their
// word), drag a clip edge to trim, click the ruler or empty track to seek. Every change is an op.

import { h, clamp, tc } from "./util.js";
import { clipDur, clipEnd } from "./bake.js";

const TRACKS = [
  { id: "main", label: "V1", name: "Picture" },
  { id: "broll", label: "V2", name: "B-roll" },
  { id: "overlays", label: "G", name: "Graphics" },
  { id: "texts", label: "T", name: "Text" },
  { id: "captions", label: "C", name: "Captions" },
  { id: "music", label: "A2", name: "Music" },
  { id: "sfx", label: "A3", name: "SFX + VO" },
];

export class Timeline {
  constructor(root, { onSeek, onOp, onSelect }) {
    this.root = root;
    this.onSeek = onSeek;
    this.onOp = onOp;
    this.onSelect = onSelect;
    this.pps = 40;                       // pixels per second
    this.sel = null;
    this.peaks = new Map();
    this.head = h("div", { class: "tl-head" });
    this.zoom = h("input", { type: "range", id: "tl-zoom", min: "4", max: "240", value: "40", "aria-label": "Timeline zoom" });
    this.zoom.addEventListener("input", () => { this.pps = +this.zoom.value; this.render(); });
    this.time = h("span", { class: "tl-time tnum" }, "0:00.00");
    this.head.append(this.time, h("label", { class: "tl-zoom", for: "tl-zoom" }, "Zoom"), this.zoom);
    this.scroller = h("div", { class: "tl-scroll" });
    this.body = h("div", { class: "tl-body" });
    this.ruler = h("div", { class: "tl-ruler" });
    this.lanes = h("div", { class: "tl-lanes" });
    this.playhead = h("div", { class: "tl-playhead", "aria-hidden": "true" });
    this.body.append(this.ruler, this.lanes, this.playhead);
    this.scroller.append(this.body);
    this.labels = h("div", { class: "tl-labels" }, ...TRACKS.map((t) => h("div", { class: "tl-label", title: t.name }, h("b", {}, t.label), h("span", {}, t.name))));
    root.append(this.head, h("div", { class: "tl-frame" }, this.labels, this.scroller));
    this.ruler.addEventListener("pointerdown", (e) => this.scrub(e));
    this.lanes.addEventListener("pointerdown", (e) => { if (e.target.classList.contains("tl-lane")) this.scrub(e); });
  }

  scrub(e) {
    const rect = this.body.getBoundingClientRect();
    const move = (ev) => this.onSeek(clamp((ev.clientX - rect.left) / this.pps, 0, this.duration));
    move(e);
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  setPeaks(sid, data) { this.peaks.set(sid, data); this.render(); }

  set(baked, media, fps) {
    this.baked = baked;
    this.media = media;
    this.fps = fps || 30;
    this.duration = baked._duration || 0;
    if (!this._fitted && this.duration) {
      const w = this.scroller.clientWidth || 800;
      this.pps = clamp((w - 40) / this.duration, 4, 240);
      this.zoom.value = String(Math.round(this.pps));
      this._fitted = true;
    }
    this.render();
  }

  setTime(t) {
    this.time.textContent = tc(t, this.fps);
    this.playhead.style.transform = `translateX(${t * this.pps}px)`;
    const x = t * this.pps;
    const view = this.scroller;
    if (x < view.scrollLeft || x > view.scrollLeft + view.clientWidth - 30) view.scrollLeft = Math.max(0, x - 60);
  }

  select(kind, id) {
    this.sel = id ? { kind, id } : null;
    for (const el of this.lanes.querySelectorAll(".tl-item")) el.classList.toggle("sel", el.dataset.id === id);
    this.onSelect?.(this.sel);
  }

  render() {
    const b = this.baked;
    if (!b) return;
    const W = Math.max(this.scroller.clientWidth, (this.duration + 2) * this.pps);
    this.body.style.width = `${W}px`;
    this.ruler.replaceChildren(...this.ticks());
    const lanes = Object.fromEntries(TRACKS.map((t) => [t.id, h("div", { class: `tl-lane lane-${t.id}` })]));
    for (const c of b.main || []) lanes.main.append(this.clipItem(c, "main"));
    for (const c of b.broll || []) if (c.start != null) lanes.broll.append(this.clipItem(c, "broll"));
    const pack = (lane, rows) => {          // overlapping items stack in rows instead of covering each other
      const ends = [];
      for (const [item, list, label] of rows.sort((a, b) => a[0].start - b[0].start)) {
        let r = ends.findIndex((e) => e <= item.start + 1e-3);
        if (r < 0) { r = ends.length; ends.push(0); }
        ends[r] = item.start + Math.max(item.duration || 0.5, 0.5);
        lane.append(this.spanItem(item, list, label, r));
      }
      lane.style.height = `${Math.max(30, ends.length * 24 + 6)}px`;
      return ends.length;
    };
    pack(lanes.overlays, (b.overlays || []).map((o) => [o, "overlays", o.label || o.mg?.template || o.id]));
    pack(lanes.texts, (b.texts || []).map((x) => [x, "texts", x.text]));
    for (const ch of b.captions?.enabled ? b.captions.chunks || [] : []) {
      lanes.captions.append(h("div", { class: "tl-cap", title: ch.text, style: { left: `${ch.start * this.pps}px`, width: `${Math.max(2, (ch.end - ch.start) * this.pps - 1)}px` } }, ch.text));
    }
    const isMusic = (a) => ["music", "ambience"].includes(a.role || "music");
    const rows = { music: [], sfx: [] };
    for (const a of b.audio || []) rows[isMusic(a) ? "music" : "sfx"].push([{ ...a, duration: this.audioDur(a) }, "audio", a.label || a.source]);
    pack(lanes.music, rows.music);
    pack(lanes.sfx, rows.sfx);
    this.lanes.replaceChildren(...TRACKS.map((t) => lanes[t.id]));
    for (const t of TRACKS) {                 // keep the track labels level with their lanes
      const label = this.labels.children[TRACKS.indexOf(t)];
      if (label) label.style.height = lanes[t.id].style.height || "";
    }
    if (this.sel) this.select(this.sel.kind, this.sel.id);
  }

  audioDur(a) {
    const src = this.baked.sources?.[a.source];
    const full = (a.src_out ?? src?.duration ?? 1) - (a.src_in || 0);
    return ["music", "ambience"].includes(a.role || "music") || a.loop ? Math.min(a.loop ? Infinity : full, this.duration - a.start) : full;
  }

  ticks() {
    const step = this.pps > 120 ? 0.5 : this.pps > 40 ? 1 : this.pps > 15 ? 5 : this.pps > 6 ? 10 : 30;
    const out = [];
    for (let t = 0; t <= this.duration + step; t += step) {
      out.push(h("div", { class: "tl-tick", style: { left: `${t * this.pps}px` } }, Number.isInteger(t / (step * 2)) ? tc(t, this.fps).replace(/\.\d+$/, "") : ""));
    }
    return out;
  }

  clipItem(c, list) {
    const left = (c.start || 0) * this.pps;
    const width = Math.max(3, clipDur(c) * this.pps - 1);
    const el = h("div", { class: `tl-item clip ${list}`, dataset: { id: c.id, kind: list }, title: `${c.label || c.id} · ${tc(clipDur(c))}`,
                          style: { left: `${left}px`, width: `${width}px` } });
    const src = this.media?.sources?.[c.source];
    const sheet = src?.sprites?.[0];
    if (sheet?.url && width > 24) {
      const thumbs = Math.max(1, Math.floor(width / (sheet.tile_w || 50)));
      for (let i = 0; i < thumbs; i++) {
        const st = c.src_in + (i / thumbs) * (c.src_out - c.src_in);
        const sh = (src.sprites || []).find((s) => st >= s.start && st < s.start + s.cols * s.rows * s.interval) || sheet;
        const n = Math.max(0, Math.min(sh.count - 1, Math.floor((st - sh.start) / sh.interval)));
        const col = n % sh.cols, row = Math.floor(n / sh.cols);
        const f = 40 / sh.tile_h;                  // lane height in px over tile height
        el.append(h("span", { class: "thumb", style: {
          backgroundImage: `url(${sh.url})`, backgroundSize: `${sh.cols * sh.tile_w * f}px ${sh.rows * sh.tile_h * f}px`,
          backgroundPosition: `-${col * sh.tile_w * f}px -${row * sh.tile_h * f}px`, width: `${sh.tile_w * f}px`, height: "40px" } }));
      }
    }
    if (list === "main") {
      const peaks = this.peaks.get(c.source);
      if (peaks && width > 8) el.append(this.wave(peaks, c, width));
    }
    el.append(h("span", { class: "tl-name" }, c.label || c.id));
    if (c.transition_in) el.append(h("span", { class: "tl-tr", title: `transition: ${c.transition_in.type}` }));
    for (const side of ["l", "r"]) {
      const grip = h("span", { class: `grip ${side}`, "aria-label": side === "l" ? "Trim start" : "Trim end" });
      grip.addEventListener("pointerdown", (e) => this.trimDrag(e, c, side, el, list));
      el.append(grip);
    }
    el.addEventListener("pointerdown", (e) => { if (!e.target.classList.contains("grip")) { this.select(list, c.id); this.onSeek(Math.max(c.start || 0, Math.min(clipEnd(c) - 0.01, (e.clientX - this.body.getBoundingClientRect().left) / this.pps))); } });
    return el;
  }

  wave(peaks, c, width) {
    const cv = h("canvas", { class: "wave", width: Math.round(width), height: 28 });
    const ctx = cv.getContext("2d");
    const rate = peaks.rate || 50;
    const color = getComputedStyle(this.root).getPropertyValue("--wave").trim() || "#8aa";
    ctx.fillStyle = color;
    for (let x = 0; x < width; x++) {
      const st = c.src_in + (x / width) * (c.src_out - c.src_in);
      const v = (peaks.peaks[Math.floor(st * rate)] || 0) / 127;
      const hgt = Math.max(1, v * 26);
      ctx.fillRect(x, 14 - hgt / 2, 1, hgt);
    }
    return cv;
  }

  spanItem(it, list, label, row = 0) {
    const dur = it.duration || 0.5;
    const el = h("div", { class: `tl-item span ${list}${it.anchor ? " anchored" : ""}`, dataset: { id: it.id, kind: list },
                          title: `${label} · ${tc(it.start)}${it.anchor ? " · follows its word" : ""}`,
                          style: { left: `${it.start * this.pps}px`, top: `${3 + row * 24}px`,
                                   width: `${Math.max(4, Math.min(dur, this.duration + 5) * this.pps - 1)}px` } },
                   h("span", { class: "tl-name" }, label));
    el.addEventListener("pointerdown", (e) => {
      if (e.target.classList.contains("grip")) return;
      this.select(list, it.id);
      this.moveDrag(e, it, list, el);
    });
    if (list !== "audio") {
      const grip = h("span", { class: "grip r", "aria-label": "Change length" });
      grip.addEventListener("pointerdown", (e) => this.lengthDrag(e, it, list, el));
      el.append(grip);
    }
    return el;
  }

  moveDrag(e, it, list, el) {
    e.preventDefault();
    const x0 = e.clientX;
    const left0 = it.start * this.pps;
    let dt = 0;
    const move = (ev) => {
      dt = (ev.clientX - x0) / this.pps;
      el.style.left = `${Math.max(0, left0 + dt * this.pps)}px`;
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (Math.abs(dt) < 1 / this.fps) return;
      const fields = it.anchor ? { anchor: { offset: Math.round(((it.anchor.offset || 0) + dt) * 1000) / 1000 } }
                               : { start: Math.round(Math.max(0, it.start + dt) * 1000) / 1000 };
      this.onOp({ op: "update", list, id: it.id, fields });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  lengthDrag(e, it, list, el) {
    e.preventDefault();
    e.stopPropagation();
    const x0 = e.clientX;
    const w0 = it.duration * this.pps;
    let dd = 0;
    const move = (ev) => { dd = (ev.clientX - x0) / this.pps; el.style.width = `${Math.max(4, w0 + dd * this.pps)}px`; };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (Math.abs(dd) < 1 / this.fps) return;
      this.onOp({ op: "update", list, id: it.id, fields: { duration: Math.round(Math.max(0.1, it.duration + dd) * 1000) / 1000 } });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  trimDrag(e, c, side, el, list) {
    e.preventDefault();
    e.stopPropagation();
    const x0 = e.clientX;
    const left0 = parseFloat(el.style.left), w0 = parseFloat(el.style.width);
    let dt = 0;
    const move = (ev) => {
      dt = (ev.clientX - x0) / this.pps;
      if (side === "l") { el.style.left = `${left0 + dt * this.pps}px`; el.style.width = `${Math.max(3, w0 - dt * this.pps)}px`; }
      else el.style.width = `${Math.max(3, w0 + dt * this.pps)}px`;
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (Math.abs(dt) < 1 / this.fps) return;
      const d = dt * (c.speed || 1);
      const src = this.baked.sources?.[c.source];
      const op = side === "l" ? { op: "trim", clip: c.id.split(".p")[0], src_in: Math.max(0, Math.round((c.src_in + d) * 1000) / 1000) }
                              : { op: "trim", clip: c.id.split(".p")[0], src_out: Math.min(src?.duration || 1e9, Math.round((c.src_out + d) * 1000) / 1000) };
      this.onOp(op);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }
}
