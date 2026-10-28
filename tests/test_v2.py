"""v2 engine checks on a copy of the E2E project (tests/out/e2e_v2). Run from the skill root:

    scripts/.venv/Scripts/python.exe tests/test_v2.py          (Windows)
    scripts/.venv/bin/python tests/test_v2.py                  (macOS/Linux)

Covers: ops (Python) == ops.js (browser mirror) after bake, anchors following re-cuts, suggestions and
directions, the approval gate, Studio apply + revert, custom FX (python overlay + ffmpeg hook), knobs,
routes, capabilities, model ask-first policy, learning profile. Needs node on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
# Never touch the owner's personal/ folder (rules, profile, Studio state) from a test.
import os  # noqa: E402
os.environ["VEDIT_PERSONAL_DIR"] = str(ROOT / "tests" / "out" / "personal_test")

from vedit import custom, learn, models, modes, routes, studio  # noqa: E402
from vedit.captions import transcript_words, word_key  # noqa: E402
from vedit.knobs import bake  # noqa: E402
from vedit.ops import apply_ops  # noqa: E402
from vedit.project import find  # noqa: E402
from vedit.suggest import add_directions, add_suggestions, decide, load_suggestions  # noqa: E402
from vedit.util import VeditError  # noqa: E402

SRC = ROOT / "tests" / "footage" / "e2e" / "edit"
WORK = ROOT / "tests" / "out" / "e2e_v2"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)


def fresh_project():
    if WORK.exists():
        shutil.rmtree(WORK)
    shutil.copytree(SRC, WORK, ignore=shutil.ignore_patterns("work", "studio", "*.mp4"))
    return find(WORK)


def baked_view(e) -> dict:
    b = bake(e)
    r = lambda v: round(v, 3)  # noqa: E731
    return {"main": [[c.id, r(c.src_in), r(c.src_out), r(c.start or 0)] for c in b.main],
            "overlays": [[o.id, r(o.start), r(o.duration)] for o in b.overlays if o.enabled],
            "audio": [[a.id, r(a.start), r(a.volume)] for a in b.audio if a.enabled],
            "duration": r(b.duration),
            "captions": [[r(c.start), r(c.end), c.text, c.emphasis] for c in b.captions.chunks],
            "knobs": e.knobs, "fixes": e.captions.word_fixes}


def main() -> int:
    p = fresh_project()
    e = p.edit()
    c = e.main[2]
    words = [w for w in transcript_words(e.sources[c.source].transcript) if c.src_in <= (w["s"] + w["e"]) / 2 <= c.src_out]
    w1, w2, w3 = words[3], words[5], words[6]
    ops = [
        {"op": "cut_words", "source": c.source, "from": w1["s"], "to": w1["e"]},
        {"op": "cut_words", "source": c.source, "from": w2["s"], "to": w3["e"]},
        {"op": "restore_words", "source": c.source, "from": w2["s"], "to": w2["e"]},
        {"op": "caption_word", "key": word_key(c.source, words[0]["s"]), "text": "Fixed"},
        {"op": "caption_emphasis", "key": word_key(c.source, words[1]["s"]), "on": True},
        {"op": "add", "list": "overlays", "item": {"id": "pin", "start": 0, "duration": 1.2,
                                                   "anchor": {"source": c.source, "t": words[8]["s"]},
                                                   "mg": {"template": "emoji_pop", "data": {"emoji": "🔥"}}}},
        {"op": "update", "list": "overlays", "id": "pin", "fields": {"anchor": {"offset": 0.25}, "transform": {"y": 0.3}}},
        {"op": "knob", "id": "pace", "value": 0.6},
        {"op": "knob", "id": "music_level", "value": 0.5},
        {"op": "set", "path": "captions.style", "value": "bold_box"},
        {"op": "split", "clip": e.main[4].id, "at": round((e.main[4].src_in + e.main[4].src_out) / 2, 3)},
        {"op": "bogus"},
    ]

    # 1. Python apply + bake
    new, report = apply_ops(e, ops)
    py = baked_view(new)
    check("ops: bad op reported, others applied", len(report["errors"]) == 1 and len(report["applied"]) == len(ops) - 1,
          f"{len(report['applied'])} applied")
    pin = next(o for o in bake(new).overlays if o.id == "pin")
    check("anchor: pinned graphic follows its word", pin.start > 0, f"start {pin.start}")

    # 2. JS mirror on the same documents
    built = studio.build(p)
    check("studio build: previews + uploads listed", built["upload_mb"] > 0, f"{built['upload_mb']} MB")
    docs = studio.write_documents(p)
    docs_dir = WORK / "studio" / "docs"
    with tempfile.TemporaryDirectory() as tmp:
        ops_file = Path(tmp) / "ops.json"
        ops_file.write_text(json.dumps(ops, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run(["node", str(ROOT / "tests" / "ops_parity.mjs"), str(docs_dir), str(ops_file)],
                              capture_output=True, text=True, encoding="utf-8")
    if proc.returncode:
        check("ops.js runs", False, proc.stderr[-400:])
    else:
        js = json.loads(proc.stdout)
        for key in ("main", "overlays", "audio", "duration", "knobs", "fixes"):
            check(f"parity: {key}", js[key] == py[key], "" if js[key] == py[key] else f"\n  py={py[key]}\n  js={js[key]}")
        cap_ok = len(js["captions"]) == len(py["captions"]) and all(
            a[2] == b[2] and abs(a[0] - b[0]) < 0.002 and abs(a[1] - b[1]) < 0.002 and a[3] == b[3]
            for a, b in zip(js["captions"], py["captions"]))
        check("parity: captions (text, timing, emphasis)", cap_ok, f"py {len(py['captions'])} / js {len(js['captions'])}")
    check("docs: batches ready for ArtifactData", sum(len(b) for b in docs["batches"]) >= 6)

    # 3. Studio apply from an op folder (as ArtifactData list out_dir writes it) + revert
    rev0 = p.edit().revision
    with tempfile.TemporaryDirectory() as tmp:
        for i, op in enumerate(ops[:4]):
            (Path(tmp) / f"op{i}.json").write_text(json.dumps({"seq": i, "op": op, "status": "new"}), encoding="utf-8")
        res = studio.apply(p, Path(tmp))
    check("studio apply: ops from documents", res["applied"] == 4 and p.edit().revision == rev0 + 1, f"rev {p.edit().revision}")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "r.json").write_text(json.dumps({"seq": 1, "op": {"op": "revert", "revision": rev0}}), encoding="utf-8")
        res = studio.apply(p, Path(tmp))
    reverted = p.edit()
    check("studio revert: back to the earlier cut", len(reverted.main) == len(e.main) and not reverted.captions.word_fixes,
          f"{len(reverted.main)} clips")

    # 4. Suggestions + directions
    s_id = "hook_choice"
    add_suggestions(p, [{"id": s_id, "kind": "hook", "title": "Open on the strongest line", "reason": "test",
                         "options": [{"id": "a", "label": "Zoom harder", "ops": [{"op": "knob", "id": "zoom_strength", "value": 1.6}]},
                                     {"id": "b", "label": "Keep", "ops": []}]}])
    decide(p, s_id, "a")
    sug = load_suggestions(p)["items"][0]
    check("suggestion accept applies its ops", p.edit().knobs.get("zoom_strength") == 1.6 and sug["status"] == "accepted")
    add_directions(p, [{"id": "calm", "title": "Calm explainer", "ops": [{"op": "knob", "id": "grade_preset", "value": "clean"}]}])
    from vedit.ops import apply_ops as _apply
    from vedit.suggest import load_directions
    dirs = load_directions(p)
    e2, r2 = _apply(p.edit(), [{"op": "choose_direction", "id": "calm"}], directions=dirs)
    check("direction applies its ops", e2.knobs.get("grade_preset") == "clean" and dirs["chosen"] == "calm")

    # 5. Approval gate
    try:
        modes.require_execute(p)
        check("plan mode blocks final render before approval", False)
    except VeditError:
        check("plan mode blocks final render before approval", True)
    modes.approve(p)
    check("approved plan passes the gate", modes.require_execute(p)["plan_status"] == "approved")

    # 6. Custom FX: python overlay + ffmpeg hook, materialised for one render
    fx_dir = WORK / "custom"
    fx_dir.mkdir(exist_ok=True)
    (fx_dir / "dot.py").write_text(
        "from vedit.fxkit import args, AlphaWriter\nimport numpy as np\na = args()\n"
        "with AlphaWriter(a.out, a.width, a.height, a.fps) as w:\n"
        "    for i in range(a.frames):\n"
        "        f = np.zeros((a.height, a.width, 4), np.uint8); r = 40 + i\n"
        "        f[a.height//2-r:a.height//2+r, a.width//2-r:a.width//2+r] = (255, 200, 0, 220); w.write(f)\n",
        encoding="utf-8")
    e3 = p.edit()
    from vedit.timeline import CustomFX
    e3.custom_fx = [CustomFX(id="dot", file="custom/dot.py", start=1.0, duration=0.5, params={"note": "t"}),
                    CustomFX(id="grain", kind="ffmpeg", hook="video_post", filter="noise=alls=6:allf=t")]
    e3.canvas.width, e3.canvas.height = 270, 480
    done = custom.prepare(e3, p)
    mat, hooks = custom.materialize(e3, p.root)
    check("custom FX: python overlay rendered", done[0]["path"] and Path(done[0]["path"]).exists())
    check("custom FX: overlay + hook materialised", any(o.fx == "dot" for o in mat.overlays) and hooks["video_post"])

    # 7. Routes, capabilities, model policy, learning
    plan = routes.plan("icon")
    check("routes: free route ranked first", plan[0]["id"] in ("claude_svg", "iconify") and plan[0]["available"])
    models.register(models.Model("big_test", "https://example.invalid/x.bin", 900, "test", "testing", "big_test.bin"))
    try:
        models.ensure("big_test")
        check("models: large download asks first", False)
    except models.NeedsDownload as nd:
        check("models: large download asks first", nd.info["size_mb"] == 900)
    learn.note("captions one size bigger on 9:16", "format:9:16")
    prof = learn.rebuild()
    check("learning: profile rebuilt", "knobs" in prof and "captions one size bigger" in learn.rules())

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
