"""Phase 2 checks (senses and sourcing) on a copy of the E2E project (tests/out/e2e_p2t). Run from the skill root:

    scripts/.venv/Scripts/python.exe tests/test_phase2.py [--net] [--render]

Offline by default: sound cues + placement (synth kit, and earshot's kit when installed), anchored effects
following a re-cut, music stop-downs (Python == Studio JS), subtitle transcripts, the writing check, licence
flags, inbox pull with duplicates, footage memory, multicam merging. --render adds a preview render with
the SFX sync check; --net adds Wikimedia search + download.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["VEDIT_PERSONAL_DIR"] = str(ROOT / "tests" / "out" / "personal_test")

from vedit import inbox, sound, writing  # noqa: E402
from vedit.knobs import bake  # noqa: E402
from vedit.ops import apply_ops  # noqa: E402
from vedit.project import add_source, find  # noqa: E402
from vedit.sources import licence_flags  # noqa: E402
from vedit.timeline import AudioClip, Clip  # noqa: E402
from vedit.transcribe import subtitles  # noqa: E402

SRC = ROOT / "tests" / "footage" / "e2e" / "edit"
WORK = ROOT / "tests" / "out" / "e2e_p2t"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)


def fresh():
    if WORK.exists():
        shutil.rmtree(WORK)
    shutil.copytree(SRC, WORK, ignore=shutil.ignore_patterns("work", "studio", "*.mp4"))
    p = find(WORK)
    e = p.edit()
    e.audio = [a for a in e.audio if a.role != "sfx"]
    p.save_edit(e)
    sid = add_source(p, ROOT / "tests" / "footage" / "music_test.mp3", origin="test")
    e = p.edit()
    e.audio.append(AudioClip(id="music", source=sid, start=0, volume=0.35, role="music", loop=True))
    p.save_edit(e)
    return p


def main() -> int:
    net, do_render = "--net" in sys.argv, "--render" in sys.argv
    p = fresh()
    e = p.edit()

    # ---- cues and placement
    cs = sound.cues(e)
    roles = {c["id"]: c["role"] for c in cs}
    check("cues: graphics mapped to roles", roles.get("ov_name") == "whoosh.short" and roles.get("ov_flex") == "pop",
          json.dumps(roles))
    check("cues: anchored to source moments", all(c.get("anchor") for c in cs))
    kit = "crisp" if sound.earshot_python() else "synth"
    for k in ("synth", kit) if kit != "synth" else ("synth",):
        e2, rep = sound.place(e, cs, kit=k, root=p.root)
        check(f"place ({k}): every cue placed", rep["placed"] == len(cs) and not rep["skipped"],
              f"{rep['placed']}/{len(cs)} skipped={rep['skipped']}")
        sfx = [a for a in e2.audio if a.sfx]
        ok = all(abs(a.sfx.cue_time(a.start) - next(c["t"] for c in cs if c["id"] == a.sfx.cue)) < 0.002 for a in sfx)
        check(f"place ({k}): sync point + offset land on the cue", ok)
        check(f"place ({k}): levels below the -1 dBFS ceiling and set against a bed",
              all(i["gain_db"] < 20 and i["against"] in ("music", "voice") for i in rep["items"]),
              ", ".join(f"{i['role']} {i['gain_db']:+.1f} vs {i['against']}" for i in rep["items"]))
    p.save_edit(e2)

    # takes rotate for repeated roles
    many = [{"id": f"p{i}", "t": 5 + i * 0.5, "role": "pop", "priority": 3} for i in range(4)]
    e3, _ = sound.place(e, many, kit="synth", root=p.root)
    takes = [a.sfx.take for a in e3.audio if a.sfx]
    check("place: repeated role rotates takes", len(set(takes)) >= 3, ", ".join(takes))

    # re-cut: an anchored effect follows its word
    e4 = p.edit()
    target = next(a for a in e4.audio if a.sfx and a.sfx.cue == "ov_sticking")
    before = bake(e4.layout()).active()
    t_before = next(a for a in before.audio if a.id == target.id).start
    first = e4.main[0]
    e4, _rep = apply_ops(e4, [{"op": "trim", "clip": first.id, "src_in": first.src_in + 1.0}])
    after = bake(e4.layout()).active()
    t_after = next(a for a in after.audio if a.id == target.id).start
    check("anchored effect follows a re-cut", abs((t_before - t_after) - 1.0) < 0.05, f"{t_before:.3f} -> {t_after:.3f}")

    # stop-downs: python == studio js
    e5 = p.edit()
    big = [{"id": "boom", "t": 10.0, "role": "hit", "priority": 5}]
    e5, _ = sound.place(e5, big, kit="synth", root=p.root, replace=False)
    d_py = sound.dips(e5)
    check("hit gets a music stop-down", len(d_py) == 1 and abs(d_py[0][1] - 10.0) < 0.01, str(d_py))
    js = ("import('" + (ROOT / "studio" / "js" / "audio.js").as_uri() + "').then(m => console.log(JSON.stringify("
          "m.musicDips(JSON.parse(process.argv[1])))))")
    try:
        proc = subprocess.run(["node", "--input-type=module", "-e", js, json.dumps([a.model_dump() for a in e5.audio])],
                              capture_output=True, text=True, timeout=60)
        d_js = json.loads(proc.stdout or "[]")
        check("stop-downs: Studio JS == renderer", [[round(x, 3) for x in r] for r in d_js] ==
              [[round(x, 3) for x in r] for r in d_py], f"js={d_js} py={d_py}")
    except Exception as exc:
        check("stop-downs: Studio JS == renderer", False, str(exc))
    check("stop-down expression is valid ffmpeg", "between(t," in (sound.dip_expr(d_py) or ""))

    # ---- subtitles transcript
    sub_dir = ROOT / "tests" / "out" / "subs_test"
    shutil.rmtree(sub_dir, ignore_errors=True)
    sub_dir.mkdir(parents=True)
    vid = sub_dir / "talk.mp4"
    vid.write_bytes(b"")
    (sub_dir / "talk.en.vtt").write_text("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello <c>there</c> everyone\n\n"
                                         "00:00:03.000 --> 00:00:05.500\nHello there everyone\nwelcome back\n\n", encoding="utf-8")
    res = subtitles(vid)
    words = [w["w"] for w in res["words"]]
    check("subtitles: rolling captions de-duplicated", words == ["Hello", "there", "everyone", "welcome", "back"],
          " ".join(words))
    check("subtitles: word times inside their caption", res["words"][0]["s"] >= 1.0 and res["words"][-1]["e"] <= 5.5)

    # ---- writing pass
    bad = writing.check("In today's fast-paced world, editing isn't just about cutting — it's about storytelling. "
                        "This video will delve into the tools that serve as a testament to great editing.")
    good = writing.check("Cut by the transcript. Delete the pauses and retakes, and the rough cut takes minutes.")
    check("writing: machine-sounding copy flagged", bad["verdict"] == "fix" and bad["strong"] >= 4, str(bad["strong"]))
    check("writing: plain copy passes", good["verdict"] == "clean", str(good["findings"]))

    # ---- licences
    check("licence flags", licence_flags("cc-by-nc-4.0")["commercial"] is False and licence_flags("cc0")["commercial"]
          and licence_flags("cc-by-sa-4.0")["attribution"] and licence_flags("unknown")["unknown"])

    # ---- inbox
    dl = ROOT / "tests" / "out" / "fake_downloads_t"
    shutil.rmtree(dl, ignore_errors=True)
    dl.mkdir(parents=True)
    since = time.time() - 1
    (dl / "old.png").write_bytes(b"x" * 100)
    os.utime(dl / "old.png", (since - 3600, since - 3600))
    (dl / "Gemini_Generated_Image.png").write_bytes(b"\x89PNG" + b"0" * 500)
    (dl / "clip.mp4.crdownload").write_bytes(b"partial")
    got = inbox.pull(p.root, since=since, folder=dl, service="gemini", prompt="test")
    names = [Path(g["file"]).name for g in got["pulled"]]
    again = inbox.pull(p.root, since=since, folder=dl)
    check("inbox: new finished files only, with provenance", names == ["Gemini_Generated_Image.png"] and
          "Google" in got["pulled"][0]["provenance"]["license"], str(names))
    check("inbox: duplicates skipped", not again["pulled"] and again["duplicates"] == ["Gemini_Generated_Image.png"])

    # ---- memory
    from vedit import watch
    mem = watch.remember(p)
    hits = watch.ask("epidemiolog")
    check("memory: transcripts indexed and searchable", mem["lines"] > 10 and len(hits) > 0,
          f"{mem['lines']} lines, {len(hits)} hits")

    # ---- multicam merge logic (synthetic turns; the source doubles as its own angle)
    pm = find(WORK)
    em = pm.edit()
    base = em.main[0].source
    em.main = [Clip(id="mc", source=base, src_in=10.0, src_out=30.0)]
    pm.save_edit(em)
    turns = [{"start": 10.0, "end": 14.0, "speaker": "SPEAKER_00"}, {"start": 14.5, "end": 18.0, "speaker": "SPEAKER_00"},
             {"start": 18.6, "end": 24.0, "speaker": "SPEAKER_01"}, {"start": 24.5, "end": 30.0, "speaker": "SPEAKER_00"}]
    (pm.root / "transcripts").mkdir(exist_ok=True)
    (pm.root / "transcripts" / f"{base}.speakers.json").write_text(json.dumps({"turns": turns}), encoding="utf-8")
    em.sources["cam_b"] = em.sources[base].model_copy(update={"id": "cam_b"})
    pm.save_edit(em)
    res = watch.multicam(pm, ["cam_b"], {"SPEAKER_00": base, "SPEAKER_01": "cam_b"})
    seq = [(c.source, round(c.src_in, 1), round(c.src_out, 1)) for c in pm.edit().main]
    check("multicam: one shot per speaker turn, pauses hold the angle",
          [s for s, _, _ in seq] == [base, "cam_b", base] and abs(res["offsets"]["cam_b"]) < 0.01, str(seq))

    # ---- optional: render + sync check
    if do_render:
        p = find(WORK)
        e = p.edit()
        e.main = fresh().edit().main
        p = find(WORK)
        e = p.edit()
        e, rep = sound.place(e, sound.cues(e), kit=kit, root=p.root)
        p.save_edit(e)
        r = subprocess.run([str(ROOT / "vedit.cmd"), "render", str(WORK), "--preview"], capture_output=True, text=True)
        out = WORK / "render" / "preview.mp4"
        check("preview render with effects and stop-downs", r.returncode == 0 and out.exists(), (r.stderr or "")[-300:])
        if out.exists():
            res = sound.check(p.edit(), out, WORK / "qa")
            st = res.get("stats", {})
            check("effects heard on their cues (within 100 ms)", (st.get("hit_within_100ms") or 0) >= 0.8,
                  f"engine={res.get('engine')} median={st.get('median_abs_offset_ms')} ms")
    if net:
        from vedit import sources
        r = sources.search("lighthouse", only=["wikimedia"], limit=2)
        check("wikimedia search", len(r["results"]) > 0, str(r["errors"]))
        if r["results"]:
            got = sources.get(r["results"][0], WORK)
            check("download with provenance + licence", Path(got["file"]).exists() and got["provenance"]["license"] != "unknown")

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
