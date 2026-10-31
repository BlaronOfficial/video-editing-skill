"""Phase 3 checks (hand-offs) on copies of the E2E project. Run from the skill root:

    scripts/.venv/Scripts/python.exe tests/test_phase3.py [--full]

Offline. Covers the neutral timeline (geometry checked against the vedit renderer), FCPXML 1.10 (Apple's
DTD when .cache/tools/otio/dtd/FCPXMLv1_10.dtd is present, plus read-back), OTIO / Premiere XML / EDL /
Kdenlive through OpenTimelineIO, Shotcut MLT, the grade LUT against the FFmpeg grade, stems, editor diffs
with --apply-cuts, LosslessCut .llc round trips, smart cut (frame counts + SSIM against the source),
merge/split/chapters, render --lossless, cut lists, markers following re-cuts, Execute's hand-off step and
the CapCut builder. --full also builds the Resolve package with the styled caption layer (~4 min).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["VEDIT_PERSONAL_DIR"] = str(ROOT / "tests" / "out" / "personal_test")

from vedit import cutlist, llc, lossless  # noqa: E402
from vedit.exports import diff as hdiff  # noqa: E402
from vedit.exports import fcpxml, flatten, mlt, otio  # noqa: E402
from vedit.exports.package import build, grade_lut  # noqa: E402
from vedit.media import ffmpeg  # noqa: E402
from vedit.project import add_source, find  # noqa: E402
from vedit.render import GRADES, render, render_stems  # noqa: E402
from vedit.timeline import Clip, CropKey, Edit, Marker, Anchor, Zoom  # noqa: E402

SRC = ROOT / "tests" / "footage" / "e2e" / "edit"
OUT = ROOT / "tests" / "out" / "p3"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)


def ff(*args: str) -> str:
    return subprocess.run([ffmpeg(), "-v", "error", *args], capture_output=True, text=True).stderr


def ssim(a: str, b: str, extra: str = "") -> list[float]:
    log = OUT / "ssim.log"
    ff("-i", a, "-i", b, "-filter_complex", f"{extra}[0:v]settb=1/90000,setpts=PTS-STARTPTS[x];[1:v]settb=1/90000,"
       f"setpts=PTS-STARTPTS[y];[x][y]ssim=stats_file='{log.as_posix().replace(':', chr(92) + ':')}'", "-f", "null", "-")
    return [float(re.search(r"All:([0-9.]+)", l).group(1)) for l in log.read_text().splitlines()]


def fresh(name: str):
    work = OUT / name
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(SRC, work, ignore=shutil.ignore_patterns("work", "studio", "handoff"))
    return find(work)


def camera_file() -> Path:
    """H.264 with B-frames and a 3 s GOP, so cuts land mid-GOP."""
    cam = OUT / "cam.mp4"
    if not cam.exists():
        ff("-y", "-ss", "140", "-t", "40", "-i", str(SRC.parent / "liz_epidemiologist.webm"), "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "20", "-x264-params", "keyint=90:min-keyint=90:scenecut=0:bframes=3",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", str(cam))
    return cam


def apps(e, cam: Path) -> None:
    """With the real apps (owner's OK; portable copies under .cache/tools): Shotcut's melt renders our MLT and
    LosslessCut opens our .llc and exports through its HTTP API. Skipped when they are not there."""
    from vedit.addons import find_losslesscut
    from vedit.exports.package import grade_lut
    melt = ROOT / ".cache" / "tools" / "shotcut" / "Shotcut" / "melt.exe"
    ref = SRC / "render" / f"{e.name}.mp4"
    if melt.exists() and ref.exists():
        d = OUT / "apps"
        d.mkdir(exist_ok=True)
        lut = grade_lut(e.color.preset, e.color.lut, e.color.intensity, d / "look.cube")
        mlt.write(flatten(e, lut=str(lut) if lut else None), d / "e2e.mlt")
        subprocess.run([str(melt), "-quiet", "e2e.mlt", "out=239", "-consumer", "avformat:melt.mp4", "vcodec=libx264",
                        "preset=veryfast", "crf=20", "acodec=aac"], cwd=d, capture_output=True, timeout=1800)
        scores = []
        for t in ("1.0", "6.5"):
            ff("-y", "-ss", t, "-i", str(d / "melt.mp4"), "-frames:v", "1", "-vf", "crop=iw:ih*0.6:0:0", str(d / f"m{t}.png"))
            ff("-y", "-ss", t, "-i", str(ref), "-frames:v", "1", "-vf", "crop=iw:ih*0.6:0:0", str(d / f"r{t}.png"))
            scores += ssim(str(d / f"m{t}.png"), str(d / f"r{t}.png"))
        check("apps: Shotcut (melt) renders the MLT like vedit (framing, zoom, graphics, LUT)",
              scores and min(scores) > 0.8, ", ".join(f"{s:.3f}" for s in scores))
    else:
        print("SKIP Shotcut: no .cache/tools/shotcut or reference render")
    exe = find_losslesscut()
    if exe:
        import time
        d = OUT / "apps_llc"
        d.mkdir(exist_ok=True)
        shutil.copy(cam, d / "cam.mp4")
        llc.write(d / "cam-proj.llc", d / "cam.mp4", [{"start": 1.2, "end": 7.9, "name": "hook"},
                                                      {"start": 12.0, "end": 18.0, "name": "point"}])
        info = llc.open_app([d / "cam-proj.llc"], wait=60)
        try:
            time.sleep(6)
            res = llc.export(timeout=300)
            saved = llc.read(d / "cam-proj.llc")
        finally:
            subprocess.run(["taskkill", "/PID", str(info["pid"]), "/T", "/F"], capture_output=True)
        check("apps: LosslessCut opens our .llc and exports both segments via its API",
              info.get("api") and len(res.get("paths", [])) == 2, json.dumps(res)[:160])
        check("apps: LosslessCut's own saved .llc (JSON5) reads back", len(saved["cutSegments"]) == 2
              and saved["cutSegments"][0]["name"] == "hook")
    else:
        print("SKIP LosslessCut: not installed")


def main() -> int:
    full = "--full" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    p = fresh("e2e")
    e = p.edit()

    # ---- neutral timeline
    h = flatten(e)
    names = [t.name for t in h.tracks]
    check("flatten: main, graphics, dialogue and sfx tracks", names[0] == "V1 main" and any("graphics" in n for n in names)
          and "A1 dialogue" in names and any("sfx" in n for n in names), ", ".join(names))
    lanes_ok = all(a.end <= b.start + 1e-4 for t in h.tracks for a, b in zip(sorted(t.items, key=lambda i: i.start),
                                                                          sorted(t.items, key=lambda i: i.start)[1:]))
    check("flatten: no overlaps inside a track", lanes_ok)
    m3 = next(i for i in h.tracks[0].items if i.id == "m003")
    check("flatten: zoom + reframe become scale/position keyframes", len(m3.keys.get("scale", [])) > 2 and "position" in m3.keys)

    # geometry: the model's transform reproduces the renderer's framing
    g = Edit(name="geo", canvas=e.canvas.model_copy(), sources={"cam": e.sources["liz_epidemiologist"].model_copy(
        update={"id": "cam"})}, main=[Clip(id="g1", source="cam", src_in=150.0, src_out=153.0,
                                            crop=[CropKey(t=0, cx=0.7, cy=0.5), CropKey(t=3, cx=0.7, cy=0.5)],
                                            zoom=Zoom(start_scale=1.1, end_scale=1.1, ease="hold"))])
    g.captions.enabled = False
    g.output.audio.denoise = g.output.audio.voice_enhance = False
    geo_dir = OUT / "geo"
    r = render(g, geo_dir / "geo.mp4", work_dir=geo_dir / "work")
    gi = flatten(g).tracks[0].items[0]
    W, H = g.canvas.width, g.canvas.height
    iw, ih = gi.width, gi.height
    k = max(W / iw, H / ih) * gi.scale
    sw, sh = round(iw * k / 2) * 2, round(ih * k / 2) * 2
    x0, y0 = round((sw - W) / 2 - gi.x), round((sh - H) / 2 + gi.y)
    model = geo_dir / "model.png"
    ff("-y", "-ss", "151.0", "-i", g.sources["cam"].path, "-frames:v", "1", "-vf",
       f"scale={sw}:{sh},crop={W}:{H}:{max(0, x0)}:{max(0, y0)}", str(model))
    rend = geo_dir / "render.png"
    ff("-y", "-ss", "1.0", "-i", r["output"], "-frames:v", "1", str(rend))
    s = ssim(str(rend), str(model))
    check("geometry: model framing == rendered framing", s and s[0] > 0.9, f"SSIM {s[0]:.3f}" if s else "no frame")

    # ---- FCPXML
    fx = fcpxml.write(h, OUT / "e2e.fcpxml")
    v = otio.validate_fcpxml(fx)
    check("FCPXML 1.10: Apple DTD", v.get("valid") is True or v.get("valid") is None,
          "valid" if v.get("valid") else (v.get("errors") or ["no DTD here"])[0])
    rb = fcpxml.read(fx)
    fr = 1 / e.canvas.fps
    main_ok = len(rb["clips"]) == len(h.tracks[0].items) and all(
        abs(c["start"] - i.start) <= fr and abs(c["src_in"] - i.src_in) <= fr for c, i in zip(rb["clips"], h.tracks[0].items))
    check("FCPXML: storyline reads back (starts, in-points)", main_ok, f"{len(rb['clips'])} clips")
    conn = sum(len(t.items) for t in h.tracks[1:] if t.role != "dialogue")
    check("FCPXML: connected clips at their times", len(rb["connected"]) == conn and all(
        any(abs(c["start"] - i.start) <= fr for t in h.tracks[1:] for i in t.items) for c in rb["connected"]),
        f"{len(rb['connected'])}/{conn}")

    # ---- OTIO family
    for fmt in ("otio", "xml", "edl", "kdenlive"):
        f = otio.write(h, OUT / f"e2e.{ 'otio' if fmt == 'otio' else fmt}", fmt)
        rr = otio.read(f, fps=h.fps)
        items = rr["tracks"][0]["items"]
        ok = len(items) == len(h.tracks[0].items) and all(
            abs(a["start"] - b.start) <= fr and abs(a["src_in"] - b.src_in) <= fr for a, b in zip(items, h.tracks[0].items))
        tracks_ok = fmt == "edl" or len(rr["tracks"]) == len(h.tracks)
        check(f"OTIO {fmt}: writes and reads back (main cut, tracks)", ok and tracks_ok,
              f"{len(rr['tracks'])} tracks, {len(items)} main clips")

    # ---- MLT
    mf = mlt.write(h, OUT / "e2e.mlt")
    mr = mlt.read(mf)
    ok = [len(t["items"]) for t in mr["tracks"]] == [len(t.items) for t in h.tracks] and all(
        abs(a["start"] - b.start) <= fr and abs(a["src_in"] - b.src_in) <= fr
        for a, b in zip(mr["tracks"][0]["items"], h.tracks[0].items))
    check("MLT (Shotcut): tracks and main cut read back", ok)

    # ---- LUT == grade
    lut = grade_lut("warm_cinematic", None, 1.0, OUT / "warm.cube")
    src_png = OUT / "lut_src.png"
    ff("-y", "-ss", "150", "-i", e.sources["liz_epidemiologist"].path, "-frames:v", "1", str(src_png))
    ff("-y", "-i", str(src_png), "-vf", GRADES["warm_cinematic"], str(OUT / "lut_grade.png"))
    shutil.copy(lut, OUT / "lut_tmp.cube")
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", "lut_src.png", "-vf", "lut3d=file=lut_tmp.cube", "lut_lut.png"], cwd=OUT)
    s = ssim(str(OUT / "lut_grade.png"), str(OUT / "lut_lut.png"))
    import numpy as np
    from PIL import Image
    d = np.abs(np.asarray(Image.open(OUT / "lut_grade.png").convert("RGB"), float)
               - np.asarray(Image.open(OUT / "lut_lut.png").convert("RGB"), float)).mean()
    check("LUT: look.cube reproduces the FFmpeg grade", s and s[0] > 0.98 and d < 3.0, f"SSIM {s[0]:.4f}, mean diff {d:.2f}/255")

    # ---- stems
    st = render_stems(e, OUT / "stems", work_dir=p.sub("render") / "work", project_root=p.root)
    lens = {k: subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=duration_ts", "-of", "csv=p=0", v],
                              capture_output=True, text=True).stdout.strip() for k, v in st.items()}
    check("stems: dialogue / music / effects, sample-identical lengths", len(set(lens.values())) == 1, json.dumps(lens))

    # ---- package (Resolve) + diff + apply-cuts
    pk = build(p, "resolve", styled_captions=full)
    files = pk["files"]
    check("package: FCPXML, LUT, SRT, stems, README, graphics", all(k in files for k in ("fcpxml", "lut", "srt", "readme",
                                                                                        "stem_dialogue"))
          and len(list((Path(pk["dir"]) / "graphics").glob("*.mov"))) >= len(e.overlays), f"{pk['seconds']} s")
    if full:
        cap = Path(pk["dir"]) / "graphics" / "captions_styled.mov"
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=pix_fmt", "-of", "csv=p=0", str(cap)],
                             capture_output=True, text=True).stdout
        check("package: styled caption layer has alpha", "yuva" in out, out.strip())
    # the editor trims every head by 0.2 s and deletes clip 4
    man = json.loads((Path(pk["dir"]) / "handoff.json").read_text(encoding="utf-8"))
    from vedit.exports import Handoff
    h2 = Handoff.from_dict(man["handoff"])
    keep = [i for i in h2.tracks[0].items if i.id != "m004"]
    t = 0.0
    for it in keep:
        it.src_in += 0.2
        it.duration -= 0.2
        it.start = t
        t += it.duration
    h2.tracks[0].items = keep
    h2.markers = []
    edited = fcpxml.write(h2, OUT / "edited_in_resolve.fcpxml")
    ins = hdiff.run_diff(p, edited, learn_style="test_handoff", apply_cuts=True)
    check("diff: sees the tighter cut, head trims and the removed clip",
          ins.get("main_duration_ratio", 1) < 0.95 and abs(ins.get("head_trim_s", 0) - 0.2) < 0.05
          and any("removed" in n for n in ins["notes"]), "; ".join(ins["notes"]))
    e2 = p.edit()
    labels_kept = all(c.label for c in e2.main)
    check("diff --apply-cuts: editor's cut becomes the main track, labels kept",
          len(e2.main) == len(keep) and abs(e2.main[0].src_in - (e.main[0].src_in + 0.2)) < 0.01 and labels_kept,
          f"{len(e2.main)} clips, {e2.duration:.2f}s")
    check("diff: learned into the style profile", ins.get("learned_into") == "test_handoff")

    # ---- LosslessCut .llc
    p3 = fresh("e2e_llc")
    w = llc.from_edit(p3.edit(), p3.sub("handoff") / "losslesscut", footage_dir=p3.footage_dir)
    data = llc.read(w[0]["llc"])
    check(".llc: one project per source, segments == main clips",
          len(w) == 1 and len(data["cutSegments"]) == len(p3.edit().main) and data["version"] == 2)
    data["cutSegments"][0]["end"] -= 0.5             # tuned in LosslessCut
    txt = json.dumps(data, indent=2).replace('"version"', "version").replace('"cutSegments"', "cutSegments")
    tuned = OUT / "tuned-proj.llc"
    tuned.write_text("// edited\n" + txt.replace("]\n}", "],\n}"), encoding="utf-8")
    shutil.copy(tuned, Path(w[0]["llc"]).with_name("tuned-proj.llc"))
    res = cutlist.import_file(p3, Path(w[0]["llc"]).with_name("tuned-proj.llc"))
    e3 = p3.edit()
    check(".llc (JSON5) import: tuned segment comes back", res["main_clips"] == len(data["cutSegments"])
          and abs(e3.main[0].src_out - data["cutSegments"][0]["end"]) < 1e-3)
    Path(w[0]["llc"]).with_name("tuned-proj.llc").unlink()
    Path(w[0]["llc"]).unlink(missing_ok=True)

    # ---- smart cut
    cam = camera_file()
    segs = [{"path": str(cam), "start": 1.234, "end": 7.9}, {"path": str(cam), "start": 20.5, "end": 21.1},
            {"path": str(cam), "start": 12.0, "end": 18.0}]
    sc = lossless.smart_cut(segs, OUT / "cut_smart.mp4")
    check("smart cut: exact frame count", sc["frames"] == sc["expected_frames"], f"{sc['frames']}/{sc['expected_frames']}")
    check("smart cut: whole GOPs stream-copied", sc["copied_share"] > 0.3, f"{sc['copied_share']:.0%} copied")
    p0 = lossless.params(cam)
    refs = ";".join(f"[1:v]trim=start={round(s['start'] * p0.fps) / p0.fps:.6f}:end={round(s['end'] * p0.fps) / p0.fps:.6f},"
                    f"setpts=PTS-STARTPTS[r{i}]" for i, s in enumerate(segs))
    log = OUT / "sc.log"
    ff("-i", sc["output"], "-i", str(cam), "-filter_complex",
       f"{refs};[r0][r1][r2]concat=n=3:v=1:a=0,settb=1/90000[ref];[0:v]settb=1/90000,setpts=PTS-STARTPTS[o];"
       f"[o][ref]ssim=stats_file='{log.as_posix().replace(':', chr(92) + ':')}'", "-f", "null", "-")
    sv = [float(re.search(r"All:([0-9.]+)", l).group(1)) for l in log.read_text().splitlines()]
    check("smart cut: every frame matches the source (SSIM)", min(sv) > 0.95 and sum(sv) / len(sv) > 0.99,
          f"mean {sum(sv) / len(sv):.4f}, min {min(sv):.4f}")
    steps = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
                            "-of", "csv=p=0", sc["output"]], capture_output=True, text=True).stdout.split()
    ts = sorted(float(x) for x in steps)
    check("smart cut: evenly spaced timestamps across joins", max(b - a for a, b in zip(ts, ts[1:])) < 1.5 / p0.fps
          and min(b - a for a, b in zip(ts, ts[1:])) > 0.5 / p0.fps)
    durs = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=duration", "-of", "csv=p=0", sc["output"]],
                          capture_output=True, text=True).stdout.split()
    check("smart cut: picture and sound the same length", abs(float(durs[0]) - float(durs[1])) < 0.05, " / ".join(durs))
    kfm = lossless.smart_cut(segs, OUT / "cut_kf.mp4", mode="keyframe")
    check("keyframe mode: pure copy", kfm["copied_share"] == 1.0)
    parts = lossless.split(cam, [10.0, 25.0], OUT / "parts")
    merged = lossless.merge([x["output"] for x in parts], OUT / "merged.mp4")
    check("split + merge: back to the full length", abs(merged["duration"] - 40.0) < 0.1, f"{merged['duration']} s")
    chap = lossless.add_chapters(cam, [{"t": 0, "title": "Intro"}, {"t": 15, "title": "Middle"}], OUT / "chap.mp4")
    n = subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-of", "json", chap["output"]], capture_output=True,
                       text=True).stdout
    check("chapters written into the file", len(json.loads(n)["chapters"]) == 2)

    # render --lossless: cuts-only project vs one with graphics
    lp = OUT / "lossless_proj"
    if lp.exists():
        shutil.rmtree(lp)
    lp.mkdir()
    shutil.copy(cam, lp / "cam.mp4")
    from vedit.project import init
    pl = init(lp, ratio="16:9")
    el = pl.edit()
    el.main = [Clip(id="a", source="cam", src_in=2.5, src_out=8.2), Clip(id="b", source="cam", src_in=30.1, src_out=33.0)]
    el.markers = [Marker(id="c1", t=0, name="Start", kind="chapter"), Marker(id="c2", t=5.7, name="Later", kind="chapter")]
    el.captions.enabled = False
    pl.save_edit(el)
    lr = lossless.render_edit(pl.edit(), lp / "edit" / "render" / "lossless.mp4")
    check("render --lossless: cuts-only edit renders without a full re-encode",
          lr["frames"] == lr["expected_frames"] and lr["copied_share"] > 0.2, f"{lr['copied_share']:.0%} copied")
    try:
        lossless.render_edit(p.edit(), OUT / "nope.mp4")
        check("render --lossless: refuses edits with graphics", False)
    except Exception as exc:  # noqa: BLE001
        check("render --lossless: refuses edits with graphics", "more than cuts" in str(exc), str(exc)[:80])

    # ---- cut lists + markers
    p4 = fresh("e2e_cuts")
    exp = cutlist.export(p4, "csv")
    before = [(c.src_in, c.src_out) for c in p4.edit().main]
    cutlist.import_file(p4, exp["files"][0])
    after = [(c.src_in, c.src_out) for c in p4.edit().main]
    check("cut list CSV: export -> import is identity", all(abs(a[0] - b[0]) < 1e-3 and abs(a[1] - b[1]) < 1e-3
                                                            for a, b in zip(before, after)) and len(before) == len(after))
    chtxt = OUT / "chapters.txt"
    chtxt.write_text("0:00 Hook\n0:12 The doubt\n0:24 The turn\n", encoding="utf-8")
    cutlist.import_file(p4, chtxt)
    e4 = p4.edit()
    text, problems = cutlist.chapters_text(e4)
    check("chapters: import -> markers -> YouTube text", text.startswith("0:00 Hook") and len(text.splitlines()) == 3,
          "; ".join(problems) or "no problems")
    # markers follow a re-cut: drop the first clip, the "doubt" chapter moves earlier with its words
    mk = next(m for m in e4.markers if m.name == "The doubt")
    t_before = mk.t
    e4.main = e4.main[1:]
    p4.save_edit(e4)
    t_after = next(m for m in p4.edit().markers if m.name == "The doubt").t
    check("markers anchored to words follow a re-cut", mk.anchor is not None and t_after < t_before,
          f"{t_before:.2f}s -> {t_after:.2f}s")

    # ---- Execute's hand-off step
    from vedit import modes
    p5 = fresh("e2e_exec")
    wf = modes.state(p5)
    wf["handoffs"] = ["otio", "llc"]
    modes._save(p5, wf, "test")
    hr = modes.run_handoffs(p5)
    check("Execute writes the picked hand-offs", "dir" in hr.get("otio", {}) and isinstance(hr.get("llc"), list),
          json.dumps({k: list(v)[:2] if isinstance(v, dict) else len(v) for k, v in hr.items()}))
    for w_ in hr.get("llc", []):
        if w_.get("beside_media"):
            Path(w_["llc"]).unlink(missing_ok=True)

    # ---- CapCut still builds
    from vedit.capcut import builder
    from vedit.knobs import bake
    try:
        built, rep = builder.build(bake(p5.edit()).active(), pro_allowed=False, overlay_mode="chroma")
        check("CapCut builder still builds the E2E edit", bool(built), json.dumps(rep.counts))
    except Exception as exc:  # noqa: BLE001
        check("CapCut builder still builds the E2E edit", False, str(exc)[:200])

    if "--apps" in sys.argv:
        apps(e, cam)

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
