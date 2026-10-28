// The edit operation language, mirrored from scripts/vedit/ops.py so the live preview matches what the
// engine will do. The engine stays authoritative: after Claude (or the live link) applies ops, the
// Studio replaces its copy with the engine's edit.

import { clone } from "./util.js";

export const LISTS = ["main", "broll", "overlays", "texts", "audio", "effects", "custom_fx"];
const MIN_CLIP = 0.08;
const EPS = 0.02;
const PAD_IN = 0.06;
const PAD_OUT = 0.12;
const CLAUDE_OPS = ["note", "request"];
const r3 = (v) => Math.round(v * 1000) / 1000;

export function wordBounds(words, firstS, lastE) {
  const prev = words.filter((w) => w[1] <= firstS + 1e-3);
  const nxt = words.filter((w) => w[0] >= lastE - 1e-3);
  let lo = prev.length ? (prev[prev.length - 1][1] + firstS) / 2 : Math.max(0, firstS - PAD_IN);
  let hi = nxt.length ? (lastE + nxt[0][0]) / 2 : lastE + PAD_OUT;
  if (prev.length) lo = Math.min(firstS, Math.max(lo, prev[prev.length - 1][1] + 0.02));
  if (nxt.length) hi = Math.max(lastE, Math.min(hi, nxt[0][0] - 0.02));
  return [r3(lo), r3(Math.max(hi, lo + 0.05))];
}

function allIds(d) {
  const ids = new Set();
  for (const name of LISTS) for (const it of d[name] || []) if (it && it.id) ids.add(it.id);
  return ids;
}

function newId(d, base) {
  const ids = allIds(d);
  let n = 2;
  while (ids.has(`${base}.${n}`)) n++;
  return `${base}.${n}`;
}

class OpError extends Error {}

function find(d, list, id) {
  if (!LISTS.includes(list)) throw new OpError(`unknown list '${list}'`);
  d[list] ||= [];
  const i = d[list].findIndex((it) => it.id === id);
  if (i < 0) throw new OpError(`no ${list} item '${id}'`);
  return [d[list], i];
}

function clipRef(d, id) {
  for (const name of ["main", "broll"]) {
    const i = (d[name] || []).findIndex((c) => c.id === id);
    if (i >= 0) return [d[name], i];
  }
  throw new OpError(`no clip '${id}'`);
}

function deepMerge(base, patch) {
  for (const [k, v] of Object.entries(patch || {})) {
    if (v === null) delete base[k];
    else if (v && typeof v === "object" && !Array.isArray(v) && base[k] && typeof base[k] === "object" && !Array.isArray(base[k])) deepMerge(base[k], v);
    else base[k] = clone(v);
  }
  return base;
}

function walkPath(d, path) {
  const parts = path.split(".");
  let node = d;
  for (let i = 0; i < parts.length; i++) {
    const m = /^([A-Za-z_]\w*)(?:\[([^\]]+)\])?$/.exec(parts[i]);
    if (!m) throw new OpError(`bad path segment '${parts[i]}'`);
    const [, key, sel] = m;
    const last = i === parts.length - 1;
    if (sel !== undefined) {
      const items = (node[key] ||= []);
      const match = items.find((it) => String(it.id) === sel);
      if (!match) throw new OpError(`no item '${sel}' in ${key}`);
      if (last) throw new OpError("path must end with a field");
      node = match;
    } else if (last) {
      return [node, key];
    } else {
      node = (node[key] ||= {});
    }
  }
  throw new OpError("empty path");
}

export function cutRange(d, sid, lo, hi) {
  const out = [];
  for (const c of d.main || []) {
    if (c.source !== sid || c.src_out <= lo || c.src_in >= hi) { out.push(c); continue; }
    const left = c.src_in < lo ? [c.src_in, Math.min(c.src_out, lo)] : null;
    const right = c.src_out > hi ? [Math.max(c.src_in, hi), c.src_out] : null;
    const leftOk = left && left[1] - left[0] >= MIN_CLIP;
    if (leftOk) {
      const a = clone(c);
      a.src_out = r3(left[1]);
      if (right) delete a.fade_out;
      out.push(a);
    }
    if (right && right[1] - right[0] >= MIN_CLIP) {
      const b = clone(c);
      b.src_in = r3(right[0]);
      if (leftOk) {
        b.id = newId({ main: [...out, ...(d.main || [])], broll: d.broll || [] }, c.id);
        delete b.transition_in;
        delete b.fade_in;
      }
      out.push(b);
    }
  }
  d.main = out;
}

function subtract(lo, hi, covered) {
  const gaps = [];
  let cur = lo;
  for (const [s, e] of [...covered].sort((a, b) => a[0] - b[0])) {
    if (e <= cur || s >= hi) continue;
    if (s > cur) gaps.push([cur, Math.min(s, hi)]);
    cur = Math.max(cur, e);
  }
  if (cur < hi) gaps.push([cur, hi]);
  return gaps.map(([a, b]) => [r3(a), r3(b)]).filter(([a, b]) => b - a >= MIN_CLIP / 2);
}

function mergeable(a, b) {
  if (b.transition_in) return false;
  return ["speed", "zoom", "transform", "crop", "fit", "volume", "mute", "color"]
    .every((k) => JSON.stringify(a[k]) === JSON.stringify(b[k]));
}

export function restoreRange(d, sid, lo, hi) {
  const main = (d.main ||= []);
  const covered = main.filter((c) => c.source === sid).map((c) => [c.src_in, c.src_out]);
  for (const [g0, g1] of subtract(lo, hi, covered)) {
    const prev = main.find((c) => c.source === sid && Math.abs(c.src_out - g0) < EPS);
    const nxt = main.find((c) => c.source === sid && Math.abs(c.src_in - g1) < EPS);
    if (prev && nxt && main.indexOf(nxt) === main.indexOf(prev) + 1 && mergeable(prev, nxt)) {
      prev.src_out = nxt.src_out;
      main.splice(main.indexOf(nxt), 1);
    } else if (prev) {
      prev.src_out = g1;
    } else if (nxt) {
      nxt.src_in = g0;
    } else {
      const item = { id: newId(d, `r_${sid}`), source: sid, src_in: g0, src_out: g1, label: "restored" };
      const before = main.map((c, i) => (c.source === sid && c.src_out <= g0 + EPS ? i : -1)).filter((i) => i >= 0);
      const after = main.map((c, i) => (c.source === sid && c.src_in >= g1 - EPS ? i : -1)).filter((i) => i >= 0);
      const pos = before.length ? before[before.length - 1] + 1 : after.length ? after[0] : main.length;
      main.splice(pos, 0, item);
    }
  }
}

function apply(d, op, ctx, report, depth = 0) {
  const name = op.op;
  if (depth > 3) throw new OpError("nested accept too deep");
  if (name === "cut_words" || name === "restore_words") {
    const words = ctx.words?.[op.source] || [];
    const [lo, hi] = words.length ? wordBounds(words, +op.from, +op.to) : [+op.from, +op.to];
    (name === "cut_words" ? cutRange : restoreRange)(d, op.source, lo, hi);
    report.captions_dirty = true;
  } else if (name === "cut_range" || name === "restore_range") {
    (name === "cut_range" ? cutRange : restoreRange)(d, op.source, +op.from, +op.to);
    report.captions_dirty = true;
  } else if (name === "trim") {
    const [items, i] = clipRef(d, op.clip);
    const c = items[i];
    const s = op.src_in ?? c.src_in;
    const e = op.src_out ?? c.src_out;
    if (e - s < MIN_CLIP) throw new OpError("trim would leave the clip shorter than 0.08 s");
    c.src_in = r3(s);
    c.src_out = r3(e);
  } else if (name === "split") {
    const [items, i] = clipRef(d, op.clip);
    const c = items[i];
    const at = +op.at;
    if (!(c.src_in + MIN_CLIP <= at && at <= c.src_out - MIN_CLIP)) throw new OpError("split point outside the clip");
    const b = clone(c);
    b.id = newId(d, c.id);
    b.src_in = r3(at);
    delete b.transition_in;
    delete b.fade_in;
    c.src_out = r3(at);
    delete c.fade_out;
    items.splice(i + 1, 0, b);
    (report.created ||= []).push(b.id);
  } else if (name === "delete_clip") {
    const [items, i] = clipRef(d, op.clip);
    items.splice(i, 1);
  } else if (name === "move_clip") {
    const [items, i] = clipRef(d, op.clip);
    const [c] = items.splice(i, 1);
    items.splice(Math.max(0, Math.min(items.length, op.index | 0)), 0, c);
  } else if (name === "set") {
    const [node, key] = walkPath(d, op.path);
    if (op.value === null || op.value === undefined) delete node[key];
    else node[key] = clone(op.value);
    if (op.path.startsWith("captions") || op.path.startsWith("main")) report.captions_dirty = true;
  } else if (name === "add") {
    if (!LISTS.includes(op.list)) throw new OpError(`unknown list '${op.list}'`);
    const item = clone(op.item);
    if (!item.id || allIds(d).has(item.id)) item.id = newId(d, item.id || (op.list.endsWith("s") ? op.list.slice(0, -1) : op.list));
    (d[op.list] ||= []).push(item);
    (report.created ||= []).push(item.id);
  } else if (name === "remove") {
    const [items, i] = find(d, op.list, op.id);
    items.splice(i, 1);
  } else if (name === "update") {
    const [items, i] = find(d, op.list, op.id);
    deepMerge(items[i], op.fields || {});
  } else if (name === "enable") {
    const [items, i] = find(d, op.list, op.id);
    items[i].enabled = op.on !== false;
  } else if (name === "caption_word") {
    const fixes = ((d.captions ||= {}).word_fixes ||= {});
    if (op.text === null || op.text === undefined) delete fixes[op.key];
    else fixes[op.key] = String(op.text);
  } else if (name === "caption_emphasis") {
    const keys = ((d.captions ||= {}).emphasis_keys ||= []);
    const on = op.on !== false;
    const i = keys.indexOf(op.key);
    if (on && i < 0) keys.push(op.key);
    if (!on && i >= 0) keys.splice(i, 1);
  } else if (name === "caption_emoji") {
    const emo = ((d.captions ||= {}).emoji_keys ||= {});
    if (op.emoji) emo[op.key] = op.emoji;
    else delete emo[op.key];
  } else if (name === "knob") {
    if (ctx.knobDefs && !ctx.knobDefs[op.id]) throw new OpError(`unknown knob '${op.id}'`);
    const knobs = (d.knobs ||= {});
    if (op.value === null || op.value === undefined) delete knobs[op.id];
    else knobs[op.id] = op.value;
  } else if (name === "accept" || name === "reject") {
    const items = ctx.suggestions?.items || [];
    const item = items.find((s) => s.id === op.suggestion);
    if (!item) throw new OpError(`no suggestion '${op.suggestion}'`);
    if (name === "accept") {
      const option = (item.options || []).find((o) => o.id === op.option);
      if (!option) throw new OpError(`suggestion '${item.id}' has no option '${op.option}'`);
      for (const sub of option.ops || []) apply(d, sub, ctx, report, depth + 1);
      item.status = "accepted";
      item.chosen = option.id;
    } else {
      item.status = "rejected";
    }
  } else if (name === "choose_direction") {
    const dirs = ctx.directions || { items: [] };
    const item = (dirs.items || []).find((x) => x.id === op.id);
    if (!item) throw new OpError(`no direction '${op.id}'`);
    for (const sub of item.ops || []) apply(d, sub, ctx, report, depth + 1);
    dirs.chosen = item.id;
  } else if (CLAUDE_OPS.includes(name)) {
    report.pending.push(op);
  } else if (name === "approve" || name === "revert") {
    (report.workflow ||= []).push(op);
  } else {
    throw new OpError(`unknown op '${name}'`);
  }
}

function sane(d) {
  for (const c of [...(d.main || []), ...(d.broll || [])]) {
    if (!(c.src_out > c.src_in)) throw new OpError(`clip ${c.id}: src_out must be after src_in`);
    if (!d.sources?.[c.source]) throw new OpError(`clip ${c.id}: unknown source`);
  }
}

// Apply ops to a copy of the raw edit JSON. ctx: {words, suggestions, directions, knobDefs}.
export function applyOps(edit, ops, ctx = {}) {
  let d = clone(edit);
  const report = { applied: [], pending: [], errors: [], captions_dirty: false };
  for (const op of ops) {
    const before = clone(d);
    try {
      apply(d, op, ctx, report);
      if (![...CLAUDE_OPS, "approve", "revert"].includes(op.op)) {
        sane(d);
        report.applied.push(op);
      }
    } catch (e) {
      d = before;
      report.errors.push({ op, error: e.message || String(e) });
    }
  }
  return { edit: d, report };
}
