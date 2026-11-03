// Side panels: suggestion cards, creative directions, tuning knobs, the inspector and the library.
// Each control turns into ops; the app applies them live and sends them to the engine.

import { h, tc, debounce, clone } from "./util.js";

const KIND_LABEL = { hook: "Hook", cut: "Cut", broll: "B-roll", graphic: "Graphic", sfx: "Sound", music: "Music",
                     zoom: "Zoom", caption: "Captions", transition: "Transition", grade: "Look", text: "Text", vfx: "VFX",
                     voice: "Voice", other: "Idea" };

// ------------------------------------------------------------------ suggestions + directions

export function renderSuggestions(root, { suggestions, directions, onOp, onPreview, onSeek, previewing }) {
  const items = suggestions?.items || [];
  const open = items.filter((s) => (s.status || "open") === "open");
  const done = items.filter((s) => (s.status || "open") !== "open");
  const dirs = directions?.items || [];
  const kids = [];
  if (dirs.length) {
    kids.push(h("h2", { class: "panel-h" }, "Creative directions"));
    kids.push(h("p", { class: "muted" }, directions.chosen ? "Chosen direction is marked. Pick another to switch." : "Pick the direction for this edit. Claude builds the draft around it."));
    kids.push(h("div", { class: "dir-grid" }, ...dirs.map((d) => directionCard(d, directions.chosen === d.id, onOp))));
  }
  kids.push(h("h2", { class: "panel-h" }, `Suggestions${open.length ? ` · ${open.length} open` : ""}`));
  if (!items.length) kids.push(h("p", { class: "empty-note" }, "No suggestions yet. Claude adds cards here while drafting; accepting one applies it to the edit."));
  for (const s of open) kids.push(suggestionCard(s, { onOp, onPreview, onSeek, previewing }));
  if (done.length) {
    kids.push(h("details", { class: "done-list" }, h("summary", {}, `${done.length} decided`),
      ...done.map((s) => h("div", { class: `done-row ${s.status}` }, h("span", { class: "chip" }, KIND_LABEL[s.kind] || s.kind), " ", s.title, " · ", s.status === "accepted" ? `kept ${s.options?.find((o) => o.id === s.chosen)?.label || ""}` : "declined"))));
  }
  root.replaceChildren(...kids);
}

function directionCard(d, chosen, onOp) {
  const rows = [["Treatment", d.treatment], ["Hook", d.hook], ["Pacing", d.pacing], ["Look", d.look], ["Sound", d.sound], ["Captions", d.captions]]
    .filter(([, v]) => v);
  const board = (d.moodboard || []).slice(0, 6).filter((m) => m.src || m.url);
  return h("article", { class: `dir-card${chosen ? " chosen" : ""}` },
    board.length ? h("div", { class: "moodboard" }, ...board.map((m) => h("img", { src: m.src || m.url, alt: m.credit || "", loading: "lazy" }))) : null,
    h("h3", {}, d.title),
    h("dl", {}, ...rows.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])),
    h("button", { class: `btn ${chosen ? "" : "primary"}`, type: "button", disabled: chosen, onclick: () => onOp({ op: "choose_direction", id: d.id }) }, chosen ? "Chosen" : "Use this direction"));
}

function suggestionCard(s, { onOp, onPreview, onSeek, previewing }) {
  const at = s.at?.start;
  return h("article", { class: "sug-card", dataset: { id: s.id } },
    h("header", {}, h("span", { class: `chip kind-${s.kind}` }, KIND_LABEL[s.kind] || s.kind),
      at !== undefined ? h("button", { class: "linkish tnum", type: "button", onclick: () => onSeek(at) }, tc(at)) : null),
    h("h3", {}, s.title),
    s.reason ? h("p", { class: "muted" }, s.reason) : null,
    h("div", { class: "opts" }, ...(s.options || []).map((o) => {
      const isPrev = previewing && previewing.s === s.id && previewing.o === o.id;
      return h("div", { class: `opt${isPrev ? " previewing" : ""}${s.default === o.id ? " default" : ""}` },
        h("div", { class: "opt-text" }, h("b", {}, o.label), o.description ? h("span", { class: "muted" }, o.description) : null),
        h("div", { class: "opt-actions" },
          h("button", { class: "btn small", type: "button", onclick: () => onPreview(isPrev ? null : { s: s.id, o: o.id }) }, isPrev ? "Stop preview" : "Preview"),
          h("button", { class: "btn small primary", type: "button", onclick: () => onOp({ op: "accept", suggestion: s.id, option: o.id }) }, "Keep")));
    })),
    h("button", { class: "btn small ghost", type: "button", onclick: () => onOp({ op: "reject", suggestion: s.id }) }, "Not this"));
}

// ------------------------------------------------------------------ knobs

export function renderKnobs(root, { defs, values, onKnob }) {
  const groups = {};
  for (const [id, d] of Object.entries(defs || {})) (groups[d.group || "Other"] ||= []).push([id, d]);
  const send = new Map();
  const later = (id) => (send.get(id) || send.set(id, debounce((v) => onKnob(id, v), 250)).get(id));
  const kids = [h("p", { class: "muted" }, "Knobs tune the whole edit without touching Claude's decisions. Reset returns a knob to the edit as written.")];
  for (const [group, list] of Object.entries(groups)) {
    kids.push(h("h2", { class: "panel-h" }, group));
    for (const [id, d] of list) {
      const v = values?.[id];
      const set = v !== undefined && v !== null;
      const field = `knob-${id}`;
      let control, readout = null;
      if (d.type === "range") {
        const mid = (d.min + d.max) / 2;
        control = h("input", { type: "range", id: field, min: d.min, max: d.max, step: d.step || 0.01, value: set ? v : (id.endsWith("level") || id === "zoom_strength" || id === "caption_size" ? 1 : id === "grade_intensity" ? 1 : mid) });
        readout = h("output", { for: field, class: "tnum" }, set ? String(v) : "—");
        control.addEventListener("input", () => { readout.textContent = control.value; later(id)(+control.value); });
      } else if (d.type === "choice") {
        control = h("select", { id: field }, h("option", { value: "" }, "As written"), ...(d.options || []).map((o) => h("option", { value: o, selected: v === o }, o.replaceAll("_", " "))));
        control.addEventListener("change", () => onKnob(id, control.value || null));
      } else {
        control = h("select", { id: field }, h("option", { value: "" }, "As written"), h("option", { value: "on", selected: v === true }, "On"), h("option", { value: "off", selected: v === false }, "Off"));
        control.addEventListener("change", () => onKnob(id, control.value === "" ? null : control.value === "on"));
      }
      kids.push(h("div", { class: `knob${set ? " set" : ""}` },
        h("label", { for: field }, d.label || id), control, readout,
        h("button", { class: "btn tiny ghost", type: "button", disabled: !set, onclick: () => onKnob(id, null), "aria-label": `Reset ${d.label || id}` }, "Reset"),
        d.help ? h("p", { class: "knob-help muted" }, d.help) : null));
    }
  }
  root.replaceChildren(...kids);
}

// ------------------------------------------------------------------ inspector

const LIST_NAME = { main: "Clip", broll: "B-roll", overlays: "Graphic", texts: "Text", audio: "Sound" };

export function renderInspector(root, { sel, raw, baked, library, onOp, onSeek, onPick, now }) {
  if (!sel) {
    root.replaceChildren(h("p", { class: "empty-note" }, "Select a clip, graphic, text or sound on the timeline to edit it here."));
    return;
  }
  const list = sel.kind;
  const rawItem = (raw[list] || []).find((x) => x.id === sel.id) || (raw.main || []).find((x) => x.id === String(sel.id).split(".p")[0]);
  const item = (baked[list] || []).find((x) => x.id === sel.id) || rawItem;
  if (!rawItem) {
    root.replaceChildren(h("p", { class: "empty-note" }, "That item changed. Select it again."));
    return;
  }
  const id = rawItem.id;
  const upd = (fields) => onOp(list === "main" || list === "broll" ? { op: "update", list, id, fields } : { op: "update", list, id, fields });
  const num = (label, value, fields, step = 0.01) => {
    const fid = `ins-${label.replace(/\W+/g, "-").toLowerCase()}`;
    const input = h("input", { type: "number", id: fid, step, value: value ?? "" });
    input.addEventListener("change", () => upd(fields(input.value === "" ? null : +input.value)));
    return h("div", { class: "field" }, h("label", { for: fid }, label), input);
  };
  const text = (label, value, fields) => {
    const fid = `ins-${label.replace(/\W+/g, "-").toLowerCase()}`;
    const input = h("input", { type: "text", id: fid, value: value ?? "" });
    input.addEventListener("change", () => upd(fields(input.value)));
    return h("div", { class: "field" }, h("label", { for: fid }, label), input);
  };
  const tr = rawItem.transform || {};
  const kids = [
    h("header", { class: "ins-head" }, h("span", { class: "chip" }, LIST_NAME[list] || list), h("h2", {}, rawItem.label || id),
      h("button", { class: "linkish tnum", type: "button", onclick: () => onSeek(item.start || 0) }, tc(item.start || 0))),
  ];
  if (rawItem.anchor) kids.push(h("p", { class: "muted" }, `Follows the word at ${tc(rawItem.anchor.t)} in ${rawItem.anchor.source}. Moving it changes its offset from that word.`));
  if (list === "main" || list === "broll") {
    kids.push(num("In (source s)", rawItem.src_in, (v) => ({ src_in: v }), 0.01), num("Out (source s)", rawItem.src_out, (v) => ({ src_out: v }), 0.01));
    kids.push(num("Speed", rawItem.speed ?? 1, (v) => ({ speed: v || 1 }), 0.05), num("Volume", rawItem.volume ?? 1, (v) => ({ volume: v ?? 1 }), 0.05));
    kids.push(num("Zoom from", rawItem.zoom?.start_scale ?? 1, (v) => ({ zoom: { ...(rawItem.zoom || {}), start_scale: v ?? 1 } }), 0.01),
              num("Zoom to", rawItem.zoom?.end_scale ?? 1, (v) => ({ zoom: { ...(rawItem.zoom || {}), end_scale: v ?? 1 } }), 0.01));
    const trSel = h("select", { id: "ins-transition" }, h("option", { value: "" }, "Cut"), ...["fade", "fade_black", "flash", "slide_left", "slide_up", "zoom_in", "push", "circle", "blur", "glitch", "whip_left", "whip_right", "whip_up", "zoom_blur"].map((t) => h("option", { value: t, selected: rawItem.transition_in?.type === t }, t.replaceAll("_", " "))));
    trSel.addEventListener("change", () => upd({ transition_in: trSel.value ? { type: trSel.value, duration: rawItem.transition_in?.duration || 0.3 } : null }));
    kids.push(h("div", { class: "field" }, h("label", { for: "ins-transition" }, "Transition in"), trSel));
    kids.push(h("div", { class: "row" },
      h("button", { class: "btn small", type: "button", onclick: () => onOp({ op: "split", clip: id, at: Math.min(rawItem.src_out - 0.1, Math.max(rawItem.src_in + 0.1, (item.src_in + item.src_out) / 2)) }) }, "Split in half"),
      h("button", { class: "btn small danger", type: "button", onclick: () => onOp({ op: "delete_clip", clip: id }) }, "Delete clip")));
    kids.push(...vfxControls(rawItem, item, list, { upd, onOp, onPick, now }));
  } else {
    kids.push(num("Length (s)", rawItem.duration, (v) => ({ duration: v ?? rawItem.duration }), 0.05));
    if (!rawItem.anchor) kids.push(num("Start (s)", rawItem.start, (v) => ({ start: v ?? 0 }), 0.05));
    else kids.push(num("Offset from word (s)", rawItem.anchor.offset ?? 0, (v) => ({ anchor: { offset: v ?? 0 } }), 0.05));
    if (list === "texts") kids.push(text("Text", rawItem.text, (v) => ({ text: v })));
    if (list === "audio") kids.push(num("Volume", rawItem.volume ?? 1, (v) => ({ volume: v ?? 1 }), 0.05), num("Fade in", rawItem.fade_in ?? 0, (v) => ({ fade_in: v ?? 0 }), 0.05), num("Fade out", rawItem.fade_out ?? 0, (v) => ({ fade_out: v ?? 0 }), 0.05));
    if (list === "overlays" || list === "texts") {
      kids.push(num("X (−1 left … 1 right)", tr.x ?? 0, (v) => ({ transform: { x: v ?? 0 } }), 0.02), num("Y (−1 bottom … 1 top)", tr.y ?? 0, (v) => ({ transform: { y: v ?? 0 } }), 0.02),
                num("Scale", tr.scale ?? 1, (v) => ({ transform: { scale: v ?? 1 } }), 0.05), num("Opacity", tr.opacity ?? 1, (v) => ({ transform: { opacity: v ?? 1 } }), 0.05));
    }
    if (list === "overlays" && rawItem.mg) {
      const schema = library?.templates?.[rawItem.mg.template]?.data || {};
      const data = rawItem.mg.data || {};
      const keys = [...new Set([...Object.keys(schema), ...Object.keys(data)])].filter((k) => k !== "brand" && k !== "duration");
      if (keys.length) kids.push(h("h3", { class: "panel-h" }, `${rawItem.mg.template || "Composition"} fields`));
      for (const k of keys) {
        const v = data[k];
        const fid = `ins-mg-${k}`;
        const isObj = v !== undefined && typeof v === "object";
        const input = h(isObj ? "textarea" : "input", { id: fid, rows: isObj ? 3 : undefined, type: isObj ? undefined : "text", placeholder: typeof schema[k] === "string" ? schema[k] : "" });
        input.value = v === undefined ? "" : isObj ? JSON.stringify(v) : String(v);
        input.addEventListener("change", () => {
          let val = input.value;
          if (isObj || /^[[{]/.test(val.trim())) { try { val = JSON.parse(val); } catch { /* keep text */ } }
          else if (val !== "" && !Number.isNaN(+val) && /num|int|0\.\.1|vmin|deg/.test(String(schema[k]))) val = +val;
          else if (val === "true" || val === "false") val = val === "true";
          onOp({ op: "update", list, id, fields: { mg: { data: { [k]: val === "" ? null : val } } } });
        });
        kids.push(h("div", { class: "field" }, h("label", { for: fid }, k), input));
      }
    }
    kids.push(h("div", { class: "row" },
      h("button", { class: "btn small", type: "button", onclick: () => onOp({ op: "enable", list, id, on: rawItem.enabled === false }) }, rawItem.enabled === false ? "Show" : "Hide"),
      h("button", { class: "btn small danger", type: "button", onclick: () => onOp({ op: "remove", list, id }) }, "Remove")));
  }
  root.replaceChildren(...kids);
}

// ------------------------------------------------------------------ library

export function renderLibrary(root, { library, raw, t, anchorAt, onOp }) {
  const tpls = Object.entries(library?.templates || {});
  const styles = Object.keys(library?.caption_styles || {});
  const grades = library?.grades || [];
  const sfx = Object.entries(raw.sources || {}).filter(([, s]) => s.kind === "audio");
  const at = anchorAt(t);
  const add = (item, list) => onOp({ op: "add", list, item: { ...item, start: +t.toFixed(3), ...(at ? { anchor: at } : {}) } });
  const card = (title, sub, fn, extra) => h("button", { class: "lib-item", type: "button", onclick: fn }, h("b", {}, title), sub ? h("span", { class: "muted" }, sub) : null, extra || null);
  root.replaceChildren(
    h("p", { class: "muted" }, `Adds at the playhead (${tc(t)})${at ? ", pinned to the word there" : ""}.`),
    h("h2", { class: "panel-h" }, "Graphics templates"),
    h("div", { class: "lib-grid" }, ...tpls.map(([name, d]) => card(name.replaceAll("_", " "), d.use, () => add({ id: name, duration: typeof d.duration === "number" ? d.duration : 3, mg: { template: name, data: {} }, label: name }, "overlays"), d.personal ? h("span", { class: "chip" }, "yours") : null))),
    h("h2", { class: "panel-h" }, "Caption styles"),
    h("div", { class: "lib-grid" }, ...styles.map((s) => card(s.replaceAll("_", " "), raw.captions?.style === s ? "current" : "", () => onOp({ op: "set", path: "captions.style", value: s })))),
    h("h2", { class: "panel-h" }, "Looks"),
    h("div", { class: "lib-grid" }, card("none", "", () => onOp({ op: "knob", id: "grade_preset", value: "none" })), ...grades.map((g) => card(g.replaceAll("_", " "), raw.color?.preset === g ? "current" : "", () => onOp({ op: "knob", id: "grade_preset", value: g })))),
    h("h2", { class: "panel-h" }, "Sounds in this project"),
    sfx.length ? h("div", { class: "lib-grid" }, ...sfx.map(([sid]) => card(sid.replaceAll("_", " "), "add at playhead", () => add({ id: `${sid}_at`, source: sid, role: sid.startsWith("music") ? "music" : "sfx", volume: 0.6 }, "audio")))) : h("p", { class: "empty-note" }, "No sound files yet. Ask Claude for music or effects; they appear here."),
  );
}

export { clone };


// ------------------------------------------------------------------ clip VFX (rendered by the engine)

function vfxControls(rawItem, item, list, { upd, onOp, onPick, now }) {
  const sub = rawItem.subject || {};
  const out = [h("h3", { class: "panel-h" }, "Effects on this clip"),
    h("p", { class: "muted" }, "Rendered by the engine (person cut-outs, tracking, depth). The preview here shows the plain clip; a preview render shows the result.")];
  const bg = h("select", { id: "ins-subject-bg" }, ...[["", "Keep the background"], ["blur:14", "Blur the background"], ["darken:0.5", "Darken the background"],
    ["desaturate", "Black and white background"], ["#101014", "Plain dark background"]].map(([v, l]) => h("option", { value: v, selected: (sub.background || "") === v }, l)));
  bg.addEventListener("change", () => upd({ subject: bg.value || sub.above !== undefined ? { ...sub, background: bg.value || undefined } : null }));
  out.push(h("div", { class: "field" }, h("label", { for: "ins-subject-bg" }, "Person cut-out"), bg));
  const behind = h("input", { type: "checkbox", id: "ins-subject-above", checked: sub.above !== undefined });
  behind.addEventListener("change", () => {
    const next = { ...sub };
    if (behind.checked) next.above = 1; else delete next.above;
    upd({ subject: Object.keys(next).length ? next : null });
  });
  out.push(h("div", { class: "field check" }, behind, h("label", { for: "ins-subject-above" }, "Graphics on layer 0 go behind the person")));
  const dof = h("input", { type: "range", id: "ins-dof", min: 0, max: 1, step: 0.05, value: rawItem.dof ? rawItem.dof.focus : 0 });
  dof.addEventListener("change", () => upd({ dof: +dof.value > 0 ? { focus: +dof.value, range: rawItem.dof?.range || 0.25, blur: rawItem.dof?.blur || 10 } : null }));
  out.push(h("div", { class: "field" }, h("label", { for: "ins-dof" }, "Depth of field (0 = off, 1 = focus on the nearest)"), dof));
  const nScreens = (rawItem.screen || []).length;
  out.push(h("div", { class: "row" },
    h("button", { class: "btn small", type: "button", onclick: () => onOp({ op: "request", what: "vfx", target: rawItem.id,
      text: `Blur every face in clip ${rawItem.id} (tracked, follows them).` }) }, "Blur faces"),
    h("button", { class: "btn small", type: "button", onclick: async () => {
      if (!onPick) return;
      const pts = await onPick(4, "Click the four corners of the screen or sign");
      if (!pts) return;
      const at = now ? now() : item.start || 0;
      onOp([{ op: "update", list, id: rawItem.id, fields: { screen: [...(rawItem.screen || []), { canvas_corners: pts, timeline_at: +at.toFixed(3), media: "" }] } },
            { op: "request", what: "vfx", target: rawItem.id, text: `Replace the screen picked at ${at.toFixed(2)}s in clip ${rawItem.id}: track it and ask me which image or video goes on it.` }]);
    } }, nScreens ? `Replace another screen (${nScreens})` : "Replace a screen")));
  return out;
}
