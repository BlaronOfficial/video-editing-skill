// Runs an op sequence through studio/js/ops.js + bake.js and prints the baked timeline as JSON, so
// tests/test_v2.py can compare it with the Python engine (scripts/vedit/ops.py + knobs.bake).
// usage: node tests/ops_parity.mjs <studio docs dir> <ops.json>
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { applyOps } from "../studio/js/ops.js";
import { bake } from "../studio/js/bake.js";

const [docsDir, opsFile] = process.argv.slice(2);
const read = (f) => JSON.parse(readFileSync(join(docsDir, f), "utf8"));
const edit = read("edit.json");
const library = read("library.json");
const words = {};
for (const f of readdirSync(docsDir).filter((f) => f.startsWith("words_"))) {
  const d = read(f);
  (words[d.source] ||= []).push(...d.words);
}
for (const ws of Object.values(words)) ws.sort((a, b) => a[0] - b[0]);
const ops = JSON.parse(readFileSync(opsFile, "utf8"));
const { edit: out, report } = applyOps(edit, ops, { words, knobDefs: library.knobs });
const b = bake(out, words, library);
const r = (v) => Math.round(v * 1000) / 1000;
console.log(JSON.stringify({
  errors: report.errors.map((e) => e.error),
  main: b.main.map((c) => [c.id, r(c.src_in), r(c.src_out), r(c.start)]),
  overlays: b.overlays.map((o) => [o.id, r(o.start), r(o.duration)]),
  audio: b.audio.map((a) => [a.id, r(a.start), r(a.volume ?? 1)]),
  duration: r(b._duration),
  captions: b.captions.chunks.map((c) => [r(c.start), r(c.end), c.text, c.emphasis]),
  knobs: out.knobs || {},
  fixes: out.captions?.word_fixes || {},
}));
