// In-page Claude (the `sample` capability: runs on the owner's Claude plan, no API key) for quick
// rewrites, alternatives and explanations, plus the Send to Claude composer that hands bigger work to the
// main Claude session (which owns the engine: renders, new compositions, downloads, research).

import { h, tc } from "./util.js";

const SYSTEM = `You are the assistant inside vedit Studio, a mini video editor. The owner is reviewing an edit that
Claude (the main session) drafted. Be brief and concrete; talk like an experienced editor.
You can propose changes with the propose_change tool; each option carries ops the Studio applies when the owner
keeps it. Allowed ops (JSON):
  {"op":"knob","id":"pace|zoom_strength|music_level|sfx_level|voice_level|caption_size|caption_y|caption_words|caption_style|grade_preset|grade_intensity|transitions","value":...}
  {"op":"set","path":"captions.style","value":"<style name>"}
  {"op":"update","list":"overlays|texts|audio|main","id":"<id>","fields":{...}}
  {"op":"add","list":"overlays","item":{"id":"<new id>","start":<s>,"duration":<s>,"mg":{"template":"<template>","data":{...}},"label":"..."}}
  {"op":"caption_word","key":"<word key>","text":"<fixed text>"}   {"op":"caption_emphasis","key":"<word key>","on":true}
  {"op":"cut_words","source":"<source id>","from":<first word start>,"to":<last word end>}   (restore_words likewise)
Word keys, source ids and times come from get_words. Never invent ids. Anything needing new files, renders,
downloads or research belongs to the main session: say "Send this to Claude" and give the owner a one-line brief.`;

export class Chat {
  constructor(root, { adapter, context, onPropose, anchorEl, pendingCount }) {
    this.root = root;
    this.adapter = adapter;
    this.context = context;           // () => {summary, words(from,to), item(id)}
    this.onPropose = onPropose;
    this.anchorEl = anchorEl;
    this.pendingCount = pendingCount;
    this.history = [];
    this.render();
  }

  render() {
    const sample = this.adapter.sample;
    this.log = h("div", { class: "chat-log", role: "log", "aria-live": "polite" });
    this.input = h("textarea", { id: "chat-input", rows: "2", placeholder: sample ? "Ask about this edit, or ask for options…" : "In-page Claude is not available here. Use Send to Claude below." });
    this.input.disabled = !sample;
    const ask = h("button", { class: "btn primary", type: "submit", disabled: !sample }, "Ask");
    const form = h("form", { class: "chat-form" }, h("label", { for: "chat-input", class: "sr-only" }, "Message"), this.input, ask);
    form.addEventListener("submit", (e) => { e.preventDefault(); this.ask(this.input.value); });
    const quick = ["Explain the cut and the hook", "Give me 3 stronger hooks", "Where does the pacing drag?", "Suggest graphics for the next 10 s", "Make the captions punchier"];
    const chips = h("div", { class: "chips" }, ...quick.map((q) => h("button", { class: "chip-btn", type: "button", disabled: !sample, onclick: () => this.ask(q) }, q)));
    this.sendBox = this.composer();
    this.root.replaceChildren(
      h("h2", { class: "panel-h" }, "Ask in the Studio"),
      chips, this.log, form,
      h("h2", { class: "panel-h" }, "Send to Claude"),
      this.sendBox);
    if (!this.history.length) this.say("assistant", sample ? "Ask anything about this edit. I can propose changes you can preview and keep." : "Studio chat needs the Claude app or claude.ai. Notes still reach Claude through Send to Claude.");
  }

  say(role, text) {
    const el = h("div", { class: `msg ${role}` }, text);
    this.log.append(el);
    this.log.scrollTop = this.log.scrollHeight;
    return el;
  }

  tools() {
    return [
      { name: "get_words", description: "Kept words on the timeline between two timeline times (seconds), with their keys, source ids and source times.",
        inputSchema: { type: "object", properties: { from: { type: "number" }, to: { type: "number" } }, required: ["from", "to"] },
        execute: (i) => this.context().words(+i.from, +i.to) },
      { name: "get_item", description: "Full JSON of one timeline item (clip, overlay, text, audio) by id.",
        inputSchema: { type: "object", properties: { id: { type: "string" } }, required: ["id"] },
        execute: (i) => this.context().item(String(i.id)) },
      { name: "propose_change", description: "Show the owner a suggestion card with 1-4 options; each option has ops applied if kept.",
        inputSchema: { type: "object", properties: { title: { type: "string" }, kind: { type: "string" }, reason: { type: "string" },
          options: { type: "array", items: { type: "object", properties: { label: { type: "string" }, description: { type: "string" }, ops: { type: "array" } }, required: ["label", "ops"] } } },
          required: ["title", "options"] },
        execute: (i) => { this.onPropose(i); return { shown: true }; } },
    ];
  }

  async ask(text) {
    text = (text || "").trim();
    if (!text || !this.adapter.sample) return;
    this.input.value = "";
    this.say("user", text);
    const out = this.say("assistant", "Thinking…");
    const ctx = this.context();
    const messages = [
      { role: "user", content: `${SYSTEM}\n\nEdit summary (JSON):\n${JSON.stringify(ctx.summary)}` },
      { role: "assistant", content: "Understood. I have the edit summary." },
      ...this.history.slice(-8),
      { role: "user", content: text },
    ];
    try {
      const res = await this.adapter.sample(messages, { modelTier: "default", cache: false, tools: this.tools(),
                                                         onText: ({ text: t }) => { out.textContent = t || "Thinking…"; } });
      out.textContent = res.text || "(no answer)";
      this.history.push({ role: "user", content: text }, { role: "assistant", content: res.text || "" });
    } catch (e) {
      out.textContent = e?.code === "rate_limited" ? "Busy for a moment. Try again shortly." :
        e?.code === "not_granted" ? "Studio chat was not allowed. Use Send to Claude instead." : `Could not answer: ${e?.message || e}`;
    }
  }

  composer() {
    const ta = h("textarea", { id: "send-text", rows: "3", placeholder: "What should Claude do next? e.g. “Find a calmer music bed and render the final.”" });
    const status = h("p", { class: "send-status muted" });
    const btn = h("button", { class: "btn primary", type: "submit" }, "Send to Claude");
    const form = h("form", { class: "send-form" }, h("label", { for: "send-text", class: "sr-only" }, "Message for Claude"), ta, h("div", { class: "row" }, btn, status));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      await this.send(ta.value, status);
      ta.value = "";
    });
    this.adapter.canSend().then((state) => {
      const msg = { available: "", writers_only: "Only people who can edit this Studio can send to Claude.", no_session: "No Claude session is watching right now. Open Claude Code (or the Claude app) on this project, then send.", off: "Sending to Claude is off in this view." }[state];
      if (msg) status.textContent = msg;
      btn.disabled = state !== "available";
    });
    return form;
  }

  async send(text, statusEl, extra = "") {
    const ctx = this.context();
    const pending = this.pendingCount();
    const lines = [
      (text || "").trim() || "Please apply my Studio changes.",
      extra,
      `— vedit Studio · ${ctx.summary.name} (${ctx.summary.project_id}) · revision ${ctx.summary.revision} · playhead ${tc(ctx.summary.playhead)}`,
      pending ? `${pending} change(s) are queued in projects/${ctx.summary.project_id}/ops: apply them with vedit studio apply.` : "No queued changes (applied live).",
    ].filter(Boolean);
    try {
      statusEl.textContent = "Sending…";
      await this.adapter.sendToClaude(lines.join("\n"), this.anchorEl());
      statusEl.textContent = "Sent. Claude replies in the comment thread and updates the Studio.";
    } catch (e) {
      statusEl.textContent = e?.code === "claude_unavailable" ? "No Claude session could take it. Open Claude on this project and try again." : `Not sent: ${e?.message || e}`;
    }
  }
}
