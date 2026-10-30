// Transcript editing: every word of every source, struck through where it is cut. Select words (click,
// shift-click or drag) and cut, restore, emphasise, fix, add an emoji, or pin a graphic/sound to them.
// Filler words and low-confidence words are marked; the word under the playhead is highlighted.

import { h, tc, isBangla } from "./util.js";
import { sourceToTimeline } from "./bake.js";

export class Transcript {
  constructor(root, { onOp, onSeek, onAsk, onPin }) {
    this.root = root;
    this.onOp = onOp;
    this.onSeek = onSeek;
    this.onAsk = onAsk;
    this.onPin = onPin;
    this.bar = h("div", { class: "tx-bar", role: "toolbar", "aria-label": "Selected words" });
    this.list = h("div", { class: "tx-list", tabindex: "0" });
    this.hint = h("p", { class: "tx-hint" }, "Click a word to jump there. Drag across words, then cut or restore them.");
    root.append(this.hint, this.bar, this.list);
    this.sel = null;          // {source, a, b} word indexes
    this.list.addEventListener("keydown", (e) => {
      if (!this.sel) return;
      if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); this.apply("cut_words"); }
      if (e.key.toLowerCase() === "r") { e.preventDefault(); this.apply("restore_words"); }
    });
    this.renderBar();
  }

  set(baked, raw, words) {
    this.baked = baked;
    this.raw = raw;
    this.words = words;
    this.render();
  }

  kept(sid, w) {
    const mid = (w[0] + w[1]) / 2;
    return (this.raw.main || []).some((c) => c.source === sid && c.src_in <= mid && mid <= c.src_out);
  }

  render() {
    const frag = document.createDocumentFragment();
    const fixes = this.raw.captions?.word_fixes || {};
    const emph = new Set(this.raw.captions?.emphasis_keys || []);
    const emoji = this.raw.captions?.emoji_keys || {};
    this.spans = {};
    for (const [sid, ws] of Object.entries(this.words || {})) {
      if (!ws.length) continue;
      const block = h("section", { class: "tx-source" }, h("h3", {}, sid));
      let para = h("p", { class: "tx-para" });
      const spans = [];
      ws.forEach((w, i) => {
        const prev = ws[i - 1];
        if (prev && (w[0] - prev[1] > 1.2 || /[.!?।]$/.test(prev[2]) && w[0] - prev[1] > 0.6)) {
          block.append(para);
          para = h("p", { class: "tx-para" }, h("span", { class: "tx-gap tnum" }, tc(w[0])));
        } else if (i === 0) {
          para.append(h("span", { class: "tx-gap tnum" }, tc(w[0])));
        }
        const key = w[4];
        const text = key in fixes ? fixes[key] : w[2];
        const cls = ["tx-w"];
        if (!this.kept(sid, w)) cls.push("cut");
        if ((w[3] || "").includes("f")) cls.push("filler");
        if ((w[3] || "").includes("?")) cls.push("unsure");
        if (key in fixes) cls.push("fixed");
        if (emph.has(key)) cls.push("emph");
        if (isBangla(text)) cls.push("bn");
        const span = h("span", { class: cls.join(" "), dataset: { i, sid }, title: `${tc(w[0])}${key in fixes ? ` · heard "${w[2]}"` : ""}` }, text || "∅");
        if (emoji[key]) span.append(h("sup", {}, emoji[key]));
        spans.push(span);
        para.append(span, " ");
      });
      block.append(para);
      this.spans[sid] = spans;
      frag.append(block);
    }
    this.list.replaceChildren(frag);
    this.list.onpointerdown = (e) => this.down(e);
    if (this.sel) this.paintSel();
  }

  down(e) {
    const span = e.target.closest(".tx-w");
    if (!span) return;
    const sid = span.dataset.sid, i = +span.dataset.i;
    if (e.shiftKey && this.sel && this.sel.source === sid) {
      this.sel = { source: sid, a: Math.min(this.sel.a, i), b: Math.max(this.sel.b, i) };
    } else {
      this.sel = { source: sid, a: i, b: i };
      const w = this.words[sid][i];
      const t = sourceToTimeline(this.baked, sid, w[0]);
      if (t !== null) this.onSeek(t);
    }
    const start = this.sel.a;
    const move = (ev) => {
      const el = document.elementFromPoint(ev.clientX, ev.clientY)?.closest?.(".tx-w");
      if (el && el.dataset.sid === sid) {
        const j = +el.dataset.i;
        this.sel = { source: sid, a: Math.min(start, j), b: Math.max(start, j) };
        this.paintSel();
      }
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); this.renderBar(); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    this.paintSel();
  }

  paintSel() {
    for (const spans of Object.values(this.spans || {})) for (const s of spans) s.classList.remove("sel");
    if (!this.sel) return;
    const spans = this.spans[this.sel.source] || [];
    for (let i = this.sel.a; i <= this.sel.b; i++) spans[i]?.classList.add("sel");
  }

  selWords() {
    if (!this.sel) return [];
    return (this.words[this.sel.source] || []).slice(this.sel.a, this.sel.b + 1);
  }

  apply(kind) {
    const ws = this.selWords();
    if (!ws.length) return;
    this.onOp({ op: kind, source: this.sel.source, from: ws[0][0], to: ws[ws.length - 1][1] });
  }

  renderBar() {
    const ws = this.selWords();
    const n = ws.length;
    const label = n ? `${n} word${n > 1 ? "s" : ""} · ${tc(ws[0][0])}` : "Select words to edit them";
    const btn = (text, fn, attrs = {}) => h("button", { class: "btn small", type: "button", disabled: !n, onclick: fn, ...attrs }, text);
    this.bar.replaceChildren(
      h("span", { class: "tx-sel tnum" }, label),
      btn("Cut", () => this.apply("cut_words"), { title: "Delete key" }),
      btn("Restore", () => this.apply("restore_words"), { title: "R key" }),
      btn("Emphasize", () => this.toggleEmph()),
      btn("Fix word", () => this.fix()),
      btn("Emoji", () => this.emoji()),
      btn("Pin graphic", () => this.onPin?.("overlay", this.sel.source, ws[0][0])),
      btn("Pin sound", () => this.onPin?.("sfx", this.sel.source, ws[0][0])),
      btn("Ask Claude", () => this.onAsk?.(this.sel.source, ws)),
    );
  }

  toggleEmph() {
    const emph = new Set(this.raw.captions?.emphasis_keys || []);
    const ws = this.selWords();
    const on = !ws.every((w) => emph.has(w[4]));
    for (const w of ws) this.onOp({ op: "caption_emphasis", key: w[4], on });
  }

  // Inline editors: the page cannot use prompt(), so the toolbar swaps to a small form.
  inlineInput(label, value, done) {
    const input = h("input", { type: "text", id: "tx-inline", value: value || "", "aria-label": label });
    const ok = h("button", { class: "btn small primary", type: "submit" }, "Save");
    const cancel = h("button", { class: "btn small", type: "button", onclick: () => this.renderBar() }, "Cancel");
    const form = h("form", { class: "tx-form" }, h("label", { for: "tx-inline" }, label), input, ok, cancel);
    form.addEventListener("submit", (e) => { e.preventDefault(); done(input.value); this.renderBar(); });
    this.bar.replaceChildren(form);
    input.focus();
    input.select();
  }

  // A row of choices in place of the toolbar (sound roles, ...).
  choose(label, options, done) {
    const cancel = h("button", { class: "btn small", type: "button", onclick: () => this.renderBar() }, "Cancel");
    const btns = options.map((o) => h("button", { class: "btn small", type: "button", title: o.title || "",
      onclick: () => { done(o.value); this.renderBar(); } }, o.label));
    this.bar.replaceChildren(h("div", { class: "tx-form", role: "group", "aria-label": label },
      h("span", { class: "tx-sel" }, label), ...btns, cancel));
  }

  fix() {
    const ws = this.selWords();
    if (ws.length !== 1) {
      this.inlineInput("Fix one word at a time. Replacement for the first word", ws[0]?.[2], (v) => this.onOp({ op: "caption_word", key: ws[0][4], text: v }));
      return;
    }
    const fixes = this.raw.captions?.word_fixes || {};
    this.inlineInput(`Caption text for "${ws[0][2]}" (empty hides it)`, fixes[ws[0][4]] ?? ws[0][2], (v) =>
      this.onOp({ op: "caption_word", key: ws[0][4], text: v === ws[0][2] ? null : v }));
  }

  emoji() {
    const ws = this.selWords();
    const cur = this.raw.captions?.emoji_keys?.[ws[0][4]] || "";
    this.inlineInput("Emoji after this caption (empty removes it)", cur, (v) => this.onOp({ op: "caption_emoji", key: ws[0][4], emoji: v.trim() || null }));
  }

  follow(t) {
    const hit = this.baked && (this.baked.main || []).find((c) => c.start <= t && t < c.start + (c.src_out - c.src_in) / (c.speed || 1));
    if (!hit) return;
    const srcT = hit.src_in + (t - hit.start) * (hit.speed || 1);
    const ws = this.words?.[hit.source] || [];
    let lo = 0, hi = ws.length - 1, idx = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (ws[m][0] <= srcT) { idx = m; lo = m + 1; } else hi = m - 1; }
    const span = this.spans?.[hit.source]?.[idx];
    if (span === this._cur) return;
    this._cur?.classList.remove("now");
    span?.classList.add("now");
    this._cur = span;
  }
}
