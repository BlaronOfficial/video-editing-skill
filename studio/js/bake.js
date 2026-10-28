// Bake: the effective edit every output uses (knobs applied, anchors resolved, captions rebuilt).
// Mirrors scripts/vedit/knobs.py bake() + timeline.py layout() + captions.py build_chunks/chunk_words.

import { clone, isBangla } from "./util.js";

const PAUSE_NATURAL = 1.2;
const PAUSE_TIGHT = 0.18;
const PAD_IN = 0.06;
const PAD_OUT = 0.12;
const MIN_PIECE = 0.12;
const PUNCT_END = /[.!?।…]$/;
const PUNCT_SOFT = /[,;:—–-]$/;
const r3 = (v) => Math.round(v * 1000) / 1000;

export const clipDur = (c) => Math.max(0, (c.src_out - c.src_in) / Math.max(c.speed || 1, 1e-6));
export const clipEnd = (c) => (c.start || 0) + clipDur(c);

export function maxPause(pace) {
  pace = Math.min(1, Math.max(0, +pace));
  return r3(PAUSE_NATURAL + (PAUSE_TIGHT - PAUSE_NATURAL) * pace);
}

export function sourceToTimeline(d, sid, t) {
  for (const c of d.main || []) {
    if (c.source === sid && c.src_in <= t && t <= c.src_out) return (c.start || 0) + (t - c.src_in) / (c.speed || 1);
  }
  return null;
}

export function timelineToSource(d, t) {
  for (const c of d.main || []) {
    if (c.start != null && c.start <= t && t < clipEnd(c)) return [c.source, c.src_in + (t - c.start) * (c.speed || 1), c];
  }
  return null;
}

function nearestKept(d, sid, t) {
  let best = null;
  for (const c of d.main || []) {
    if (c.source !== sid) continue;
    for (const [st, tl] of [[c.src_in, c.start || 0], [c.src_out, clipEnd(c)]]) {
      const dist = Math.abs(st - t);
      if (!best || dist < best[0]) best = [dist, tl];
    }
  }
  return best ? best[1] : null;
}

export function layout(d) {
  let t = 0;
  for (const c of d.main || []) {
    c.start = Math.round(t * 1e6) / 1e6;
    t = c.start + clipDur(c);
  }
  if (!(d.main || []).length) return d;
  for (const list of ["overlays", "texts", "audio", "effects", "custom_fx"]) {
    for (const item of d[list] || []) {
      const a = item.anchor;
      if (!a) continue;
      let at = sourceToTimeline(d, a.source, a.t);
      if (at === null && (a.policy || "nearest") === "nearest") at = nearestKept(d, a.source, a.t);
      if (at === null) {
        if (a.policy === "drop") item.enabled = false;
        continue;
      }
      item.start = Math.round(Math.max(0, at + (a.offset || 0)) * 1e4) / 1e4;
      if (a.policy === "drop") item.enabled = true;
    }
  }
  return d;
}

export function duration(d) {
  const ends = [...(d.main || []).map(clipEnd), ...(d.broll || []).filter((c) => c.start != null).map(clipEnd)];
  if (ends.length) return Math.max(...ends);
  const others = [...(d.overlays || []), ...(d.texts || [])].map((o) => o.start + o.duration);
  return others.length ? Math.max(...others) : 0;
}

function paceSplit(d, words, limit) {
  const out = [];
  for (const c of d.main || []) {
    const src = d.sources[c.source] || {};
    const ws = words[c.source];
    if (!src.transcript || !ws || (c.speed || 1) !== 1) { out.push(c); continue; }
    const inside = ws.filter((w) => c.src_in <= (w[0] + w[1]) / 2 && (w[0] + w[1]) / 2 <= c.src_out);
    const pieces = [];
    let start = c.src_in;
    for (let i = 0; i + 1 < inside.length; i++) {
      const a = inside[i], b = inside[i + 1];
      const gap = b[0] - a[1];
      if (gap > limit) {
        pieces.push([start, Math.min(a[1] + PAD_OUT, a[1] + gap / 2)]);
        start = Math.max(b[0] - PAD_IN, b[0] - gap / 2);
      }
    }
    pieces.push([start, c.src_out]);
    const kept = pieces.filter(([s, e]) => e - s >= MIN_PIECE);
    if (kept.length <= 1) { out.push(c); continue; }
    kept.forEach(([s, e], n) => {
      const p = clone(c);
      p.id = n === 0 ? c.id : `${c.id}.p${n}`;
      p.src_in = r3(s);
      p.src_out = r3(e);
      if (n) { delete p.transition_in; p.fade_in = 0; }
      if (n < kept.length - 1) p.fade_out = 0;
      out.push(p);
    });
  }
  return out;
}

// Caption style = shipped preset (already resolved by the engine) + edit overrides, like resolve_style().
export function resolveStyle(library, name, overrides = {}) {
  const base = (library?.caption_styles || {})[name] || Object.values(library?.caption_styles || {})[0] || {};
  const style = { ...clone(base), capcut: { ...(base.capcut || {}) } };
  for (const [k, v] of Object.entries(overrides || {})) {
    if (k === "capcut" && v && typeof v === "object") Object.assign(style.capcut, v);
    else style[k] = v;
  }
  if (style.size_scale) { style.size = r3(style.size * +style.size_scale); delete style.size_scale; }
  if (style.y_delta) {
    const dlt = +style.y_delta;
    delete style.y_delta;
    style.y = r3(style.y + dlt);
    style.y_landscape = r3((style.y_landscape ?? style.y) + dlt);
  }
  return style;
}

export function chunkWords(words, maxWords = 3, maxChars = 22, mode = "karaoke", pauseBreak = 0.35) {
  if (mode === "word") { maxWords = 1; maxChars = 999; }
  else if (mode === "sentence") { maxWords = Math.max(maxWords, 10); maxChars = Math.max(maxChars, 60); }
  const chunks = [];
  let cur = [];
  const flush = () => {
    if (cur.length) {
      chunks.push({ start: cur[0].s, end: cur[cur.length - 1].e, text: cur.map((w) => w.w).join(" "), words: cur });
      cur = [];
    }
  };
  for (const word of words) {
    if (cur.length) {
      const gap = word.s - cur[cur.length - 1].e;
      const length = cur.map((w) => w.w).join(" ").length + 1 + word.w.length;
      if (gap > pauseBreak || cur.length >= maxWords || length > maxChars) flush();
    }
    cur.push(word);
    if (PUNCT_END.test(word.w) || (mode !== "word" && PUNCT_SOFT.test(word.w) && cur.length >= 2)) flush();
  }
  flush();
  for (let i = 0; i + 1 < chunks.length; i++) {
    const a = chunks[i], b = chunks[i + 1];
    a.end = b.start - a.end < 0.6 ? Math.min(b.start, a.end + 0.6) : a.end + 0.25;
  }
  if (chunks.length) chunks[chunks.length - 1].end += 0.3;
  return chunks;
}

export const wordKey = (sid, s) => `${sid}@${s.toFixed(2)}`;

export function buildChunks(d, words, style) {
  const cap = d.captions || {};
  const fixes = cap.word_fixes || {};
  const timed = [];
  for (const c of d.main || []) {
    const src = d.sources[c.source] || {};
    const ws = words[c.source];
    if (!src.transcript || !ws || c.mute) continue;
    for (const w of ws) {
      const mid = (w[0] + w[1]) / 2;
      if (c.src_in <= mid && mid <= c.src_out) {
        const key = w[4] || wordKey(c.source, w[0]);
        const text = key in fixes ? fixes[key] : w[2];
        if (!String(text).trim()) continue;
        const s = (c.start || 0) + (Math.max(w[0], c.src_in) - c.src_in) / (c.speed || 1);
        const e = (c.start || 0) + (Math.min(w[1], c.src_out) - c.src_in) / (c.speed || 1);
        timed.push({ w: String(text).trim(), s: r3(s), e: r3(Math.max(e, s + 0.05)), k: key });
      }
    }
  }
  timed.sort((a, b) => a.s - b.s);
  const chunks = chunkWords(timed, cap.max_words || style.max_words || 3, cap.max_chars || style.max_chars || 22, style.mode || "karaoke");
  const total = duration(d);
  const emph = new Set(cap.emphasis_keys || []);
  const emoji = cap.emoji_keys || {};
  for (const ch of chunks) {
    ch.end = r3(Math.min(ch.end, total));
    ch.emphasis = ch.words.map((w, i) => (emph.has(w.k) ? i : -1)).filter((i) => i >= 0);
    ch.emoji = ch.words.map((w) => emoji[w.k]).find(Boolean) || null;
  }
  return chunks.filter((ch) => ch.end - ch.start > 0.05);
}

// words: {sourceId: [[s, e, text, flags, key], ...]}; library: the engine's library doc.
export function bake(edit, words = {}, library = {}) {
  const k = edit.knobs || {};
  const d = clone(edit);
  d.sources ||= {};
  if (k.pace !== undefined && k.pace !== null) d.main = paceSplit(d, words, maxPause(k.pace));
  if (k.transitions && k.transitions !== "keep") {
    (d.main || []).forEach((c, n) => {
      if (k.transitions === "none" || n === 0) delete c.transition_in;
      else c.transition_in = { type: k.transitions, duration: 0.25 };
    });
  }
  layout(d);
  if (k.zoom_strength !== undefined && k.zoom_strength !== null) {
    for (const c of [...(d.main || []), ...(d.broll || [])]) {
      if (c.zoom) {
        c.zoom.start_scale = 1 + ((c.zoom.start_scale ?? 1) - 1) * k.zoom_strength;
        c.zoom.end_scale = 1 + ((c.zoom.end_scale ?? 1.12) - 1) * k.zoom_strength;
      }
    }
  }
  if (k.voice_level != null) for (const c of d.main || []) c.volume = (c.volume ?? 1) * k.voice_level;
  for (const [knob, roles] of [["music_level", ["music", "ambience"]], ["sfx_level", ["sfx"]]]) {
    if (k[knob] != null) for (const a of d.audio || []) if (roles.includes(a.role || "music")) a.volume = (a.volume ?? 1) * k[knob];
  }
  d.output ||= {};
  d.output.audio ||= {};
  if (k.duck_db != null) d.output.audio.duck_db = +k.duck_db;
  d.color ||= {};
  if (k.grade_preset != null) d.color.preset = k.grade_preset === "none" ? null : k.grade_preset;
  if (k.grade_intensity != null) d.color.intensity = +k.grade_intensity;
  if (k.graphics_on === false) { d.overlays = []; d.texts = []; }
  const cap = (d.captions ||= {});
  cap.enabled = cap.enabled !== false;
  if (k.captions_on != null) cap.enabled = !!k.captions_on;
  if (k.caption_style) cap.style = k.caption_style;
  cap.overrides ||= {};
  if (k.caption_size != null) cap.overrides = { ...cap.overrides, size_scale: +k.caption_size * +(cap.overrides.size_scale || 1) };
  if (k.caption_y != null) cap.overrides = { ...cap.overrides, y: +k.caption_y, y_landscape: +k.caption_y };
  if (k.caption_words != null) cap.max_words = k.caption_words | 0;
  const style = resolveStyle(library, cap.style || "karaoke_pop", cap.overrides);
  if (cap.uppercase !== undefined && cap.uppercase !== null) style.uppercase = cap.uppercase;
  d._style = style;
  if (cap.enabled && cap.from_words !== false) cap.chunks = buildChunks(d, words, style);
  for (const list of ["overlays", "texts", "audio", "effects", "custom_fx"]) {
    d[list] = (d[list] || []).filter((x) => x.enabled !== false);
  }
  d._duration = duration(d);
  return d;
}

export function chunkAt(chunks, t) {
  for (const c of chunks || []) if (c.start <= t && t < c.end) return c;
  return null;
}

export { isBangla };
