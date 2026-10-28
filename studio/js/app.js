// vedit Studio: plan, tune and approve an edit live before anything is rendered.
// State flow: the engine's documents (edit, words, media, library, suggestions) arrive from the adapter;
// the owner's actions become ops, applied optimistically here (ops.js + bake.js) and sent to the engine,
// either live (local server / Claude desktop app MCP link) or queued for Claude (Send to Claude).

import { $, h, toast, store, tc, clone } from "./util.js";
import { createAdapter } from "./data.js";
import { applyOps } from "./ops.js";
import { bake, sourceToTimeline, clipEnd, timelineToSource } from "./bake.js";
import { Player } from "./player.js";
import { Timeline } from "./timeline.js";
import { Transcript } from "./transcript.js";
import { renderSuggestions, renderKnobs, renderInspector, renderLibrary } from "./panels.js";
import { Chat } from "./chat.js";

const S = {
  adapter: null, pid: null, docs: {}, meta: {}, raw: null, words: {}, media: {}, library: {},
  suggestions: { items: [] }, directions: { items: [] }, comps: {},
  pending: [],          // ops shown locally but not yet in the engine's edit
  queued: new Map(),    // op object -> db doc id (queued mode)
  undo: [], redo: [], localCards: [], previewing: null, sel: null, tab: "suggestions", seq: 0,
};
const tplCache = new Map();
let player, timeline, transcript, chat, unsub = [];

// ------------------------------------------------------------------ shell

const ui = {
  root: $("#app"),
  head: $("#studio-head"),
  projectSel: $("#project-select"),
  chips: $("#status-chips"),
  approve: $("#approve-btn"),
  pendingBtn: $("#pending-btn"),
  stageBox: $("#stage-box"),
  transport: $("#transport"),
  tabs: $("#tabs"),
  panels: { suggestions: $("#panel-suggestions"), transcript: $("#panel-transcript"), knobs: $("#panel-knobs"),
            inspector: $("#panel-inspector"), library: $("#panel-library"), ask: $("#panel-ask") },
  timeline: $("#timeline"),
  notice: $("#notice"),
};

function showNotice(title, body) {
  ui.notice.hidden = false;
  ui.notice.replaceChildren(h("h2", {}, title), h("p", {}, body));
}

function ctx() {
  return { words: S.words, suggestions: S.suggestions, directions: S.directions, knobDefs: S.library?.knobs };
}

function mergeEdit(docs) {
  const edit = clone(docs.edit || {});
  if (edit._split) {
    for (const [k, v] of Object.entries(docs)) if (k.startsWith("edit_")) edit[k.slice(5)] = v.items;
    delete edit._split;
  }
  return edit;
}

function ingest(docs, { full = true } = {}) {
  Object.assign(S.docs, docs);
  const d = S.docs;
  S.meta = d.meta || {};
  if (full || docs.edit) S.raw = mergeEdit(d);
  const words = {};
  for (const [k, v] of Object.entries(d)) if (k.startsWith("words_")) (words[v.source] ||= []).push(...v.words);
  for (const ws of Object.values(words)) ws.sort((a, b) => a[0] - b[0]);
  S.words = words;
  S.media = d.media || {};
  S.library = d.library || {};
  S.suggestions = clone(d.suggestions || { items: [] });
  S.directions = clone(d.directions || { items: [] });
  S.comps = Object.fromEntries(Object.entries(d).filter(([k]) => k.startsWith("comp_") || k.startsWith("tpl_")));
  loadPeaks();
}

async function loadPeaks() {
  for (const [sid, m] of Object.entries(S.media.sources || {})) {
    if (!m.peaks || timeline?.peaks.has(sid)) continue;
    try {
      const res = await fetch(m.peaks);
      if (res.ok) timeline.setPeaks(sid, await res.json());
    } catch { /* waveform is a nicety */ }
  }
}

function view() {
  let e = S.raw;
  if (S.pending.length) e = applyOps(e, S.pending, ctx()).edit;
  const pv = S.previewing;
  if (pv) {
    const ops = pv.local !== undefined ? S.localCards[pv.local]?.options?.[pv.o]?.ops
      : S.suggestions.items.find((s) => s.id === pv.s)?.options?.find((o) => o.id === pv.o)?.ops;
    if (ops) e = applyOps(e, ops, ctx()).edit;
  }
  return e;
}

function refresh() {
  if (!S.raw) return;
  const raw = view();
  S.view = raw;
  S.baked = bake(raw, S.words, S.library);
  player.setEdit(S.baked, S.media);
  timeline.set(S.baked, S.media, S.baked.canvas?.fps);
  transcript.set(S.baked, raw, S.words);
  renderPanels();
  renderHead();
}

function renderPanels() {
  renderSuggestions(ui.panels.suggestions, {
    suggestions: S.suggestions, directions: S.directions, previewing: S.previewing && S.previewing.local === undefined ? S.previewing : null,
    onOp: commit, onSeek: (t) => player.seek(t),
    onPreview: (p) => { S.previewing = p; refresh(); if (p) { const s = S.suggestions.items.find((x) => x.id === p.s); if (s?.at?.start !== undefined) player.seek(Math.max(0, s.at.start - 1)); } },
  });
  if (S.localCards.length) ui.panels.suggestions.prepend(localCards());
  renderKnobs(ui.panels.knobs, { defs: S.library.knobs, values: S.view.knobs || {}, onKnob: (id, value) => commit({ op: "knob", id, value }) });
  renderInspector(ui.panels.inspector, { sel: S.sel, raw: S.view, baked: S.baked, library: S.library, onOp: commit, onSeek: (t) => player.seek(t) });
  renderLibrary(ui.panels.library, { library: S.library, raw: S.view, t: player.t, anchorAt, onOp: commit });
  const open = (S.suggestions.items || []).filter((s) => (s.status || "open") === "open").length + S.localCards.length;
  const tab = ui.tabs.querySelector('[data-tab="suggestions"] .count');
  if (tab) tab.textContent = open ? String(open) : "";
}

function localCards() {
  return h("section", { class: "local-cards" }, h("h2", { class: "panel-h" }, "From Studio chat"),
    ...S.localCards.map((c, i) => h("article", { class: "sug-card" },
      h("header", {}, h("span", { class: "chip" }, c.kind || "idea")),
      h("h3", {}, c.title), c.reason ? h("p", { class: "muted" }, c.reason) : null,
      h("div", { class: "opts" }, ...(c.options || []).map((o, j) => {
        const on = S.previewing?.local === i && S.previewing.o === j;
        return h("div", { class: `opt${on ? " previewing" : ""}` },
          h("div", { class: "opt-text" }, h("b", {}, o.label), o.description ? h("span", { class: "muted" }, o.description) : null),
          h("div", { class: "opt-actions" },
            h("button", { class: "btn small", type: "button", onclick: () => { S.previewing = on ? null : { local: i, o: j }; refresh(); } }, on ? "Stop preview" : "Preview"),
            h("button", { class: "btn small primary", type: "button", onclick: () => { S.previewing = null; S.localCards.splice(i, 1); commit(o.ops || []); } }, "Keep")));
      })),
      h("button", { class: "btn small ghost", type: "button", onclick: () => { S.localCards.splice(i, 1); S.previewing = null; refresh(); } }, "Not this"))));
}

function renderHead() {
  const m = S.meta || {};
  const status = { draft: "Draft", in_review: "In review", changes_requested: "Changes asked", approved: "Approved", executed: "Rendered" }[m.plan_status] || m.plan_status || "Draft";
  const mode = { plan: "Plan", step: "Step by step", auto: "Auto" }[m.mode] || "Plan";
  ui.chips.replaceChildren(...[
    h("span", { class: "chip mode" }, mode),
    h("span", { class: `chip status-${m.plan_status || "draft"}` }, status),
    m.mode === "step" ? h("span", { class: "chip" }, `Stage: ${m.stage || "cut"}`) : null,
    h("span", { class: "chip tnum" }, `${tc(S.baked?._duration || 0)} · ${S.baked?.canvas?.width}×${S.baked?.canvas?.height}`),
    h("span", { class: "chip ghost tnum", title: "Engine revision" }, `rev ${S.raw?.revision ?? m.revision ?? 0}`),
    S.adapter?.live ? h("span", { class: "chip live", title: "Edits apply to the project immediately" }, "Live link") : null,
  ].filter(Boolean));
  const stage = m.mode === "step" ? (m.stage || "cut") : null;
  ui.approve.textContent = stage && stage !== "final" ? `Approve ${stage}` : m.plan_status === "approved" ? "Approved" : "Approve plan";
  ui.approve.disabled = m.plan_status === "approved" || m.plan_status === "executed";
  const n = S.queued.size;
  ui.pendingBtn.hidden = !n;
  ui.pendingBtn.textContent = `${n} change${n === 1 ? "" : "s"} for Claude`;
}

// ------------------------------------------------------------------ editing

function anchorAt(t) {
  const hit = timelineToSource(S.baked || {}, t);
  if (!hit) return null;
  const [source, srcT] = hit;
  const ws = S.words[source] || [];
  let best = null;
  for (const w of ws) { if (w[0] <= srcT + 0.05) best = w; else break; }
  return best ? { source, t: best[0], offset: Math.round((t - (sourceToTimeline(S.baked, source, best[0]) ?? t)) * 1000) / 1000 } : { source, t: Math.round(srcT * 1000) / 1000 };
}

async function commit(ops, { record = true } = {}) {
  ops = (Array.isArray(ops) ? ops : [ops]).filter(Boolean);
  if (!ops.length || !S.raw) return;
  const test = applyOps(view(), ops, ctx());
  for (const err of test.report.errors) toast(`Skipped: ${err.error}`, "warn");
  const good = ops.filter((op) => !test.report.errors.some((e) => e.op === op));
  if (!good.length) return;
  S.previewing = null;
  S.pending.push(...good);
  if (record) { S.undo.push({ ops: good, revision: S.raw.revision }); S.redo = []; }
  refresh();
  try {
    const res = await S.adapter.submit(good, S.seq);
    S.seq += good.length;
    if (res.mode === "live") {
      S.pending = S.pending.filter((op) => !good.includes(op));
      ingest(res.docs, { full: false });
      if (res.docs.edit) S.raw = mergeEdit(S.docs);
      for (const e of res.report.errors || []) toast(`Engine skipped a change: ${e.error}`, "warn");
      if ((res.report.for_claude || []).length) toast("Saved your note for Claude.");
    } else {
      good.forEach((op, i) => S.queued.set(op, res.ids[i]));
    }
  } catch (e) {
    S.pending = S.pending.filter((op) => !good.includes(op));
    toast(`Could not save that change: ${e.message || e}`, "error", 6000);
  }
  refresh();
}

async function undo() {
  const last = S.undo.pop();
  if (!last) return toast("Nothing to undo.");
  S.redo.push(last);
  const queuedIds = last.ops.map((op) => S.queued.get(op)).filter(Boolean);
  if (!S.adapter.live && queuedIds.length === last.ops.length) {
    for (const op of last.ops) {
      await S.adapter.unqueue(S.queued.get(op)).catch(() => {});
      S.queued.delete(op);
    }
    S.pending = S.pending.filter((op) => !last.ops.includes(op));
    refresh();
    return;
  }
  await commit({ op: "revert", revision: last.revision }, { record: false });
}

async function redo() {
  const next = S.redo.pop();
  if (!next) return toast("Nothing to redo.");
  await commit(clone(next.ops), { record: true });
}

function splitAtPlayhead() {
  const hit = timelineToSource(S.baked || {}, player.t);
  if (!hit) return;
  const [, srcT, clip] = hit;
  commit({ op: "split", clip: String(clip.id).split(".p")[0], at: Math.round(srcT * 1000) / 1000 });
}

function deleteSelected() {
  if (!S.sel) return;
  if (S.sel.kind === "main" || S.sel.kind === "broll") commit({ op: "delete_clip", clip: String(S.sel.id).split(".p")[0] });
  else commit({ op: "remove", list: S.sel.kind === "audio" ? "audio" : S.sel.kind, id: S.sel.id });
  S.sel = null;
}

async function approve() {
  const m = S.meta || {};
  const stage = m.mode === "step" ? (m.stage || "cut") : null;
  const note = stage && stage !== "final" ? `Stage "${stage}" approved. Continue with the next stage.` : "Plan approved. Please execute: render the final video, run QA, and make the hand-offs we agreed.";
  const status = $("#approve-status");
  chat.send(note, status).catch(() => {});
  await commit(stage ? { op: "approve", stage } : { op: "approve" });
  toast(stage ? `Approved ${stage}.` : "Plan approved. Claude will render it.");
}

function pinAt(kind, source, srcT) {
  const at = { source, t: srcT };
  const tl = sourceToTimeline(S.baked, source, srcT) ?? player.t;
  if (kind === "overlay") {
    selectTab("library");
    player.seek(tl);
    toast("Pick a graphic: it pins to the selected word.");
  } else {
    const sfx = Object.entries(S.view.sources || {}).find(([, s]) => s.kind === "audio");
    if (!sfx) return toast("No sound files in this project yet. Ask Claude for effects.", "warn");
    commit({ op: "add", list: "audio", item: { id: `${sfx[0]}_pin`, source: sfx[0], start: tl, role: "sfx", volume: 0.6, anchor: at } });
  }
}

// ------------------------------------------------------------------ chat context

function summary() {
  const b = S.baked || {};
  const kept = (from, to) => {
    const out = [];
    for (const c of b.main || []) {
      for (const w of S.words[c.source] || []) {
        const mid = (w[0] + w[1]) / 2;
        if (mid < c.src_in || mid > c.src_out) continue;
        const t = (c.start || 0) + (w[0] - c.src_in) / (c.speed || 1);
        if (t >= from && t <= to) out.push({ t: Math.round(t * 100) / 100, w: w[2], key: w[4], source: c.source, s: w[0], e: w[1] });
      }
    }
    return out;
  };
  const t = player.t;
  return {
    summary: {
      project_id: S.pid, name: S.meta.name, revision: S.raw?.revision, playhead: t, duration: b._duration, canvas: b.canvas,
      style: S.raw?.style, captions: { style: b.captions?.style, enabled: b.captions?.enabled }, knobs: S.raw?.knobs || {},
      clips: (b.main || []).map((c) => ({ id: c.id, start: c.start, dur: +(clipEnd(c) - c.start).toFixed(2), src: [c.src_in, c.src_out], label: c.label })),
      overlays: (b.overlays || []).map((o) => ({ id: o.id, start: o.start, dur: o.duration, what: o.mg?.template || o.label, anchored: !!o.anchor })),
      audio: (b.audio || []).map((a) => ({ id: a.id, role: a.role, start: a.start, label: a.label || a.source })),
      templates: Object.keys(S.library.templates || {}), caption_styles: Object.keys(S.library.caption_styles || {}),
      open_suggestions: (S.suggestions.items || []).filter((s) => (s.status || "open") === "open").map((s) => ({ id: s.id, kind: s.kind, title: s.title })),
      words_near_playhead: kept(Math.max(0, t - 15), t + 15).map((w) => `${w.t}:${w.w}`).join(" "),
    },
    words: kept,
    item: (id) => { for (const l of ["main", "broll", "overlays", "texts", "audio", "effects"]) { const x = (S.view[l] || []).find((i) => i.id === id); if (x) return x; } return null; },
  };
}

// ------------------------------------------------------------------ layout bits

function selectTab(tab) {
  S.tab = tab;
  for (const b of ui.tabs.querySelectorAll("[data-tab]")) b.setAttribute("aria-selected", String(b.dataset.tab === tab));
  for (const [k, el] of Object.entries(ui.panels)) el.hidden = k !== tab;
  store("tab", tab);
  if (tab === "library" && S.view) renderLibrary(ui.panels.library, { library: S.library, raw: S.view, t: player.t, anchorAt, onOp: commit });
}

function buildTransport() {
  const play = h("button", { class: "btn icon primary", type: "button", id: "play-btn", "aria-label": "Play" }, "▶");
  const time = h("span", { class: "tc tnum", id: "tc" }, "0:00.00");
  const step = (d) => h("button", { class: "btn icon", type: "button", "aria-label": d < 0 ? "Back" : "Forward", onclick: () => player.seek(player.t + d) }, d < 0 ? "◀◀" : "▶▶");
  const safe = h("select", { id: "safe-select", "aria-label": "Platform safe zone" }, ...["none", "tiktok", "reels", "shorts", "youtube"].map((z) => h("option", { value: z }, z === "none" ? "No safe zone" : `${z} UI`)));
  safe.addEventListener("change", () => { if (S.baked) { S.baked.knobs = { ...(S.baked.knobs || {}), safe_zone: safe.value }; player.renderSafe(safe.value); } });
  play.addEventListener("click", () => player.toggle());
  player.on("play", () => { play.textContent = "❚❚"; play.setAttribute("aria-label", "Pause"); });
  player.on("pause", () => { play.textContent = "▶"; play.setAttribute("aria-label", "Play"); });
  player.on("time", (t) => { time.textContent = `${tc(t, S.baked?.canvas?.fps)} / ${tc(S.baked?._duration || 0, S.baked?.canvas?.fps)}`; timeline.setTime(t); transcript.follow(t); });
  ui.transport.replaceChildren(step(-1), play, step(1), time, h("span", { class: "spacer" }),
    h("button", { class: "btn small", type: "button", onclick: splitAtPlayhead, title: "S" }, "Split"),
    h("button", { class: "btn small", type: "button", onclick: undo, title: "Ctrl+Z" }, "Undo"),
    h("button", { class: "btn small", type: "button", onclick: redo, title: "Ctrl+Shift+Z" }, "Redo"), safe);
}

function keys(e) {
  if (e.target.closest("input, textarea, select, [contenteditable]")) return;
  const fps = S.baked?.canvas?.fps || 30;
  const k = e.key;
  if (k === " " || k === "k" || k === "K") { e.preventDefault(); player.toggle(); }
  else if (k === "ArrowLeft") { e.preventDefault(); player.seek(player.t - (e.shiftKey ? 1 : 1 / fps)); }
  else if (k === "ArrowRight") { e.preventDefault(); player.seek(player.t + (e.shiftKey ? 1 : 1 / fps)); }
  else if (k === "j" || k === "J") player.seek(player.t - 5);
  else if (k === "l" || k === "L") player.play();
  else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); }
  else if (k === "s" || k === "S") splitAtPlayhead();
  else if ((k === "Delete" || k === "Backspace") && S.sel) { e.preventDefault(); deleteSelected(); }
  else if (k === "Home") player.seek(0);
  else if (k === "End") player.seek(S.baked?._duration || 0);
}

// ------------------------------------------------------------------ boot

async function getHTML(ov) {
  if (ov.mg?.file) return S.comps[`comp_${ov.id}`]?.html || null;
  const name = ov.mg?.template;
  if (!name) return null;
  if (S.comps[`tpl_${name}`]) return S.comps[`tpl_${name}`].html;
  if (!tplCache.has(name)) tplCache.set(name, fetch(`mg/templates/${name}.html`).then((r) => (r.ok ? r.text() : null)).catch(() => null));
  return tplCache.get(name);
}

async function openProject(pid) {
  for (const u of unsub) { try { u(); } catch { /* ignore */ } }
  unsub = [];
  S.pid = pid;
  store("project", pid);
  S.pending = []; S.queued = new Map(); S.undo = []; S.redo = []; S.localCards = []; S.previewing = null; S.sel = null;
  ingest(await S.adapter.load(pid));
  ui.notice.hidden = true;
  refresh();
  unsub.push(S.adapter.watch(pid, (changed) => {
    const newer = changed.edit && (changed.edit.revision ?? 0) !== (S.raw?.revision ?? -1);
    ingest(changed, { full: false });
    if (newer) S.raw = mergeEdit(S.docs);
    refresh();
    if (newer) toast("Claude updated the edit.");
  }));
  unsub.push(S.adapter.watchOps(pid, (rows) => {
    const live = new Set(rows.filter((r) => (r.status || "new") === "new").map((r) => r.id));
    let changed = false;
    for (const [op, id] of [...S.queued]) {
      if (!live.has(id)) { S.queued.delete(op); S.pending = S.pending.filter((p) => p !== op); changed = true; }
    }
    if (changed) refresh();
  }));
}

async function main() {
  player = new Player(ui.stageBox, { getHTML, assetUrl: () => "" });
  timeline = new Timeline(ui.timeline, { onSeek: (t) => player.seek(t), onOp: commit, onSelect: (sel) => { S.sel = sel; if (sel) selectTab("inspector"); renderPanels(); } });
  transcript = new Transcript(ui.panels.transcript, { onOp: commit, onSeek: (t) => player.seek(t), onPin: pinAt,
    onAsk: (sid, ws) => { selectTab("ask"); chat.input.value = `About "${ws.map((w) => w[2]).join(" ")}" (${tc(ws[0][0])} in ${sid}): `; chat.input.focus(); } });
  buildTransport();
  for (const b of ui.tabs.querySelectorAll("[data-tab]")) b.addEventListener("click", () => selectTab(b.dataset.tab));
  selectTab(store("tab") || "suggestions");
  document.addEventListener("keydown", keys);
  ui.approve.addEventListener("click", approve);
  ui.pendingBtn.addEventListener("click", () => selectTab("ask"));
  try {
    S.adapter = await createAdapter();
  } catch (e) {
    showNotice("The Studio could not start", e.message || String(e));
    return;
  }
  chat = new Chat(ui.panels.ask, { adapter: S.adapter, context: summary, anchorEl: () => player.stage, pendingCount: () => S.queued.size,
    onPropose: (card) => { S.localCards.push(card); selectTab("suggestions"); refresh(); } });
  const projects = await S.adapter.projects();
  if (!projects.length) {
    showNotice("No projects yet", "Ask Claude to open a video in plan mode. Its draft, transcript and suggestions appear here.");
    return;
  }
  const fill = (list) => ui.projectSel.replaceChildren(...list.map((p) => h("option", { value: p.id, selected: p.id === S.pid }, p.name || p.id)));
  fill(projects);
  ui.projectSel.addEventListener("change", () => openProject(ui.projectSel.value));
  S.adapter.watchProjects(fill);
  const hash = location.hash.slice(1);
  const want = projects.find((p) => p.id === hash)?.id || projects.find((p) => p.id === store("project"))?.id || projects[0].id;
  await openProject(want);
}

main().catch((e) => { console.error(e); showNotice("Something broke while loading", e.message || String(e)); });
