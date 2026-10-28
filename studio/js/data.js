// Data adapters. Same interface, two homes:
//   ArtifactAdapter  inside claude.ai / the Claude app: db documents written by Claude, ops written back,
//                    Send to Claude via comments, in-page Claude via `sample`, and (Claude desktop app with
//                    vedit's MCP server named "vedit") a live engine link that applies ops immediately.
//   LocalAdapter     `vedit studio-local`: the same app on 127.0.0.1, ops applied by the local server.

const HOST = "host:vedit";

async function useCap(name, ms = 12000) {
  if (!window.claude?.use) return null;
  return Promise.race([window.claude.use(name).catch(() => null), new Promise((r) => setTimeout(() => r(null), ms))]);
}

export async function createAdapter() {
  if (window.claude?.use) {
    const a = new ArtifactAdapter();
    await a.init();
    return a;
  }
  const a = new LocalAdapter();
  await a.init();
  return a;
}

class ArtifactAdapter {
  constructor() {
    this.kind = "artifact";
    this.live = false;
  }

  async init() {
    [this.db, this.comments, this.sampleNs, this.mcp, this.user] = await Promise.all(
      ["db", "comments", "sample", "mcp", "user"].map((n) => useCap(n)));
    if (!this.db) throw new Error("The Studio needs its database. Sign in to Claude, then reload.");
  }

  async projects() {
    const snap = await this.db.collection("projects").get();
    return snap.docs.map((d) => ({ id: d.id, ...d.data() })).sort((a, b) => String(b.updated).localeCompare(String(a.updated)));
  }

  watchProjects(fn) {
    return this.db.collection("projects").onSnapshot((snap) => fn(snap.docs.map((d) => ({ id: d.id, ...d.data() }))));
  }

  async load(pid) {
    const snap = await this.db.collection(`projects/${pid}/docs`).get();
    const docs = {};
    for (const d of snap.docs) docs[d.id] = d.data();
    this.pid = pid;
    this.root = docs.meta?.root || null;
    this.live = await this.probeLive();
    return docs;
  }

  // Claude's syncs arrive as document changes: the Studio refreshes without a reload.
  watch(pid, fn) {
    return this.db.collection(`projects/${pid}/docs`).onSnapshot((snap) => {
      const changed = {};
      for (const ch of snap.docChanges()) if (ch.type !== "removed") changed[ch.doc.id] = ch.doc.data();
      if (Object.keys(changed).length) fn(changed);
    });
  }

  watchOps(pid, fn) {
    return this.db.collection(`projects/${pid}/ops`).onSnapshot((snap) => fn(snap.docs.map((d) => ({ id: d.id, ...d.data() }))));
  }

  async probeLive() {
    if (!this.mcp || !this.root) return false;
    try {
      const res = await this.mcp.callTool(HOST, "studio_state", { project: this.root }, { cache: false });
      return !!res;
    } catch {
      return false;
    }
  }

  async callLive(tool, input) {
    const res = await this.mcp.callTool(HOST, tool, input, { cache: false });
    const text = res?.payload ?? res?.content?.find((c) => c.type === "text")?.text;
    return typeof text === "string" ? JSON.parse(text) : text;
  }

  // Returns {mode: "live", report, docs} when the engine applied the ops, or {mode: "queued", ids}.
  async submit(ops, seqBase) {
    if (this.live) {
      const report = await this.callLive("studio_apply", { project: this.root, ops });
      for (const [name, doc] of Object.entries(report.docs || {})) {
        try { await this.db.doc(`projects/${this.pid}/docs/${name}`).set(doc); } catch { /* Claude can resync */ }
      }
      return { mode: "live", report, docs: report.docs || {} };
    }
    const ids = [];
    let seq = seqBase;
    for (const op of ops) {
      const ref = await this.db.collection(`projects/${this.pid}/ops`).add({ seq: seq++, op, at: new Date().toISOString(), status: "new" });
      ids.push(ref.id);
    }
    return { mode: "queued", ids };
  }

  async unqueue(id) {
    await this.db.doc(`projects/${this.pid}/ops/${id}`).delete();
  }

  async canSend() {
    if (!this.comments) return "off";
    try { return await this.comments.canSendToClaude(); } catch { return "off"; }
  }

  async sendToClaude(text, anchorEl) {
    if (!this.comments) throw new Error("Comments are not available in this view.");
    const anchor = await this.comments.anchorFor(anchorEl);
    return this.comments.sendToClaude({ anchor, text });
  }

  get sample() { return this.sampleNs; }
}

class LocalAdapter {
  constructor() {
    this.kind = "local";
    this.live = true;
  }

  async init() {
    const res = await fetch("/local/api/project");
    if (!res.ok) throw new Error("Start the local Studio with `vedit studio-local <project>`.");
    this.payload = await res.json();
  }

  async projects() {
    const m = this.payload.docs.meta || {};
    return [{ id: this.payload.pid, ...m }];
  }

  watchProjects() { return () => {}; }

  async load(pid) {
    this.pid = pid;
    return this.payload.docs;
  }

  watch() { return () => {}; }
  watchOps() { return () => {}; }

  async submit(ops) {
    const res = await fetch("/local/api/apply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ops }) });
    const report = await res.json();
    return { mode: "live", report, docs: report.docs || {} };
  }

  async unqueue() {}

  async canSend() { return "available"; }

  async sendToClaude(text) {
    await fetch("/local/api/send", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    return { threadId: "local" };
  }

  get sample() { return null; }
}
