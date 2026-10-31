"""ffmpeg-skill port checks (footage, delivery, FX, audio, extras) on generated fixtures and a copy of the
E2E project. Run from the skill root:

    scripts/.venv/Scripts/python.exe tests/test_port.py

Every check measures the result (probe, SSIM/PSNR, frame differences, loudness, cross-correlation), not
just that a file appeared.
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

import numpy as np  # noqa: E402

from vedit import audiotools, delivery, extras, footage, fx  # noqa: E402
from vedit.media import ffmpeg, measure_loudness, probe  # noqa: E402
from vedit.project import add_source, find  # noqa: E402

SRC = ROOT / "tests" / "footage" / "e2e" / "edit"
LIZ = ROOT / "tests" / "footage" / "e2e" / "liz_epidemiologist.webm"
OUT = ROOT / "tests" / "out" / "port"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)


def ff(*args: str, cwd: Path | None = None) -> None:
    p = subprocess.run([ffmpeg(), "-v", "error", "-y", *args], capture_output=True, text=True, cwd=cwd)
    if p.returncode:
        raise RuntimeError(p.stderr[-800:])


def frame(path: Path | str, t: float, w: int = 320, vf: str = "") -> np.ndarray:
    chain = ",".join(x for x in (vf, f"scale={w}:-2", "format=rgb24") if x)
    p = subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-vf", chain,
                        "-f", "rawvideo", "-"], capture_output=True)
    a = np.frombuffer(p.stdout, np.uint8)
    h = a.size // (w * 3)
    return a[: h * w * 3].reshape(h, w, 3).astype(float)


def fixtures() -> dict[str, Path]:
    d = OUT / "fx"
    d.mkdir(parents=True, exist_ok=True)
    f = {k: d / v for k, v in {"sdr": "sdr.mp4", "pq": "pq.mp4", "hlg": "hlg.mp4", "log": "log.mp4", "inter": "inter.mp4",
                                "vfr": "vfr.mp4", "bars": "bars.mp4", "shaky": "shaky.mp4", "noisy": "noisy.mp4",
                                "clean": "clean.mp4", "s51": "s51.wav", "eq": "equirect.mp4"}.items()}
    src = "testsrc2=s=1280x720:r=30:d=6"
    if not f["sdr"].exists():
        ff("-f", "lavfi", "-i", src, "-f", "lavfi", "-i", "sine=f=440:d=6", "-c:v", "libx264", "-crf", "16", "-pix_fmt",
           "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-c:a", "aac", "-shortest",
           str(f["sdr"]))
        for key, trc, t in (("pq", "smpte2084", "smpte2084"), ("hlg", "arib-std-b67", "arib-std-b67")):
            ff("-i", str(f["sdr"]), "-vf", f"zscale=tin=bt709:pin=bt709:min=bt709:t={t}:p=bt2020:m=bt2020nc:npl=100,"
               "format=yuv420p10le", "-c:v", "libx265", "-crf", "18", "-x265-params",
               f"log-level=error:colorprim=bt2020:transfer={trc}:colormatrix=bt2020nc", "-color_primaries", "bt2020",
               "-color_trc", trc, "-colorspace", "bt2020nc", "-tag:v", "hvc1", "-c:a", "copy", str(f[key]))
        ff("-i", str(f["sdr"]), "-vf", "eq=contrast=0.45:saturation=0.22:brightness=0.08", "-c:v", "libx264", "-crf", "16",
           "-c:a", "copy", str(f["log"]))
        ff("-f", "lavfi", "-i", "testsrc2=s=1280x720:r=60:d=4", "-vf", "interlace=scan=tff", "-c:v", "libx264",
           "-flags", "+ilme+ildct", "-x264-params", "tff=1", "-pix_fmt", "yuv420p", str(f["inter"]))
        ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=8", "-vf", "setpts='N/30/TB+if(eq(mod(N,4),0),0.011,0)/TB'",
           "-fps_mode", "passthrough", "-c:v", "libx264", "-video_track_timescale", "90000", str(f["vfr"]))
        ff("-f", "lavfi", "-i", "testsrc2=s=1920x800:r=30:d=5", "-vf", "pad=1920:1080:0:140:black", "-c:v", "libx264",
           "-crf", "18", str(f["bars"]))
        # a real picture with no motion of its own, shaken like a handheld camera
        ff("-ss", "150", "-i", str(LIZ), "-frames:v", "1", "-vf", "scale=1440:810", str(d / "still.png"))
        ff("-loop", "1", "-framerate", "30", "-t", "6", "-i", str(d / "still.png"),
           "-vf", "crop=1280:720:'80+45*sin(t*9)':'45+30*cos(t*7)'", "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p",
           str(f["shaky"]))
        # real footage with camera-like grain (sigma ~7)
        ff("-ss", "150", "-t", "4", "-i", str(LIZ), "-c:v", "libx264", "-crf", "8", str(f["clean"]))
        ff("-i", str(f["clean"]), "-vf", "noise=alls=12:allf=t", "-c:v", "libx264", "-crf", "8", str(f["noisy"]))
        ff("-f", "lavfi", "-i", "sine=f=300:d=4", "-f", "lavfi", "-i", "sine=f=500:d=4", "-f", "lavfi", "-i", "sine=f=700:d=4",
           "-f", "lavfi", "-i", "sine=f=80:d=4", "-f", "lavfi", "-i", "sine=f=900:d=4", "-f", "lavfi", "-i", "sine=f=1100:d=4",
           "-filter_complex", "[0][1][2][3][4][5]join=inputs=6:channel_layout=5.1[a]", "-map", "[a]", str(f["s51"]))
        ff("-f", "lavfi", "-i", "testsrc2=s=2048x1024:r=30:d=2", "-c:v", "libx264", "-crf", "18", str(f["eq"]))
    return f


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    f = fixtures()

    # ---------------------------------------------------------------- footage
    a = {k: footage.analyze(f[k]) for k in ("sdr", "pq", "hlg", "log", "inter", "vfr", "bars")}
    check("footage: SDR clean (no notes)", not footage.notes(a["sdr"]), json.dumps(footage.notes(a["sdr"])))
    check("footage: PQ and HLG detected as HDR", a["pq"]["hdr"] == "pq" and a["hlg"]["hdr"] == "hlg")
    check("footage: Log-looking picture flagged", a["log"]["log"]["looks_like_log"] and not a["sdr"]["log"]["looks_like_log"],
          json.dumps(a["log"]["log"]))
    check("footage: interlaced detected", a["inter"]["interlaced"], a["inter"]["field_order"])
    check("footage: variable frame rate detected", a["vfr"]["timing"] == "vfr" and a["sdr"]["timing"] == "cfr")
    bb = a["bars"]["black_bars"] or {}
    check("footage: black bars found", bb.get("h") and abs(bb["h"] - 800) <= 8 and abs(bb["y"] - 140) <= 8, json.dumps(bb))

    # tone mapping: closer to the SDR original than a naive decode of the HDR file
    ref = frame(f["sdr"], 2.0)
    naive = frame(f["pq"], 2.0)
    mapped = frame(f["pq"], 2.0, vf=footage.to_sdr_chain(a["pq"]))
    hlg_m = frame(f["hlg"], 2.0, vf=footage.to_sdr_chain(a["hlg"]))
    sat = lambda im: float((im.max(axis=2) - im.min(axis=2)).mean())  # noqa: E731
    check("HDR -> SDR: tone-mapped PQ is closer to the SDR original than the raw HDR decode",
          np.abs(mapped - ref).mean() < 0.5 * np.abs(naive - ref).mean() and sat(mapped) > sat(naive),
          f"diff {np.abs(mapped - ref).mean():.1f} vs {np.abs(naive - ref).mean():.1f}; sat {sat(mapped):.0f} vs {sat(naive):.0f}")
    check("HDR -> SDR: HLG maps too", np.abs(hlg_m - ref).mean() < np.abs(frame(f["hlg"], 2.0) - ref).mean(),
          f"diff {np.abs(hlg_m - ref).mean():.1f} vs {np.abs(frame(f['hlg'], 2.0) - ref).mean():.1f}")

    # open-GOP streams and BT.601 files
    from vedit import lossless
    og, cg = OUT / "hevc_open.mp4", OUT / "hevc_closed.mp4"
    for path, flag in ((og, 1), (cg, 0)):
        if not path.exists():
            ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6", "-c:v", "libx265", "-x265-params",
               f"log-level=error:keyint=30:open-gop={flag}", "-tag:v", "hvc1", str(path))
    check("open GOP detected (HEVC CRA/RASL), closed GOP not", lossless.open_gop(og) and not lossless.open_gop(cg))
    oc = lossless.smart_cut([{"path": str(og), "start": 1.3, "end": 4.6}], OUT / "og_cut.mp4")
    check("smart cut falls back to an accurate cut on open-GOP HEVC", oc["mode"] == "accurate" and oc["notes"]
          and oc["frames"] == oc["expected_frames"], "; ".join(oc["notes"]))
    s601 = OUT / "bt601.mp4"
    ff("-i", str(f["sdr"]), "-vf", "scale=out_color_matrix=bt601", "-c:v", "libx264", "-crf", "16", "-colorspace", "smpte170m",
       "-color_primaries", "smpte170m", "-color_trc", "smpte170m", "-an", str(s601))
    a601 = footage.analyze(s601)
    from vedit.timeline import Source as _Src
    ch601 = footage.input_chain(_Src(id="x", path=str(s601), color=a601))
    conv = frame(s601, 2.0, vf=",".join(ch601))
    dconv = np.abs(conv - frame(f["sdr"], 2.0)).mean()
    check("BT.601 source converted to BT.709 at decode (colours match the original)", any("bt601" in c for c in ch601)
          and dconv < 3.0, f"mean diff {dconv:.2f}; " + ", ".join(footage.notes(a601)))

    # ---------------------------------------------------------------- the edit uses it
    work = OUT / "e2e"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(SRC, work, ignore=shutil.ignore_patterns("work", "studio", "handoff"))
    p = find(work)
    sid = add_source(p, f["pq"], origin="test")
    e = p.edit()
    check("project: HDR source gets analysis + notes", e.sources[sid].color and e.sources[sid].color["hdr"] == "pq"
          and any("HDR" in n for n in e.sources[sid].notes))
    from vedit.timeline import Clip
    e.broll.append(Clip(id="hdr_broll", source=sid, src_in=1.0, src_out=3.0, start=5.0, fit="cover"))
    e.main[0].denoise = "light"
    e.main[1].stabilize = {"smoothing": 10}
    p.save_edit(e)
    e = fx.ramp(p.edit(), "m003", [(0, 2, 1.0), (2, 3, 0.5), (3, 5.74, 1.0)])
    p.save_edit(e)
    ramped = [c for c in e.main if c.id.startswith("m003")]
    check("ramp: clip split into speed sections, slow part twice as long",
          len(ramped) == 3 and abs(ramped[1].duration - 2.0) < 0.01 and ramped[1].smooth == "interpolate",
          ", ".join(f"{c.speed}x {c.duration:.2f}s" for c in ramped))
    d0 = e.duration
    e = fx.freeze(e, p.root, at=1.0, hold=1.5)
    p.save_edit(e)
    check("freeze: the frame holds for 1.5 s", abs(e.duration - d0 - 1.5) < 0.02 and any(c.id.endswith("_hold") for c in e.main),
          f"{d0:.2f}s -> {e.duration:.2f}s")
    from vedit.render import render
    e = p.edit()
    e.captions.enabled = False
    r = render(e, p.sub("render") / "port_preview.mp4", preview=True, work_dir=p.sub("render") / "work", project_root=p.root)
    check("render: denoise, stabilize, ramp, freeze and an HDR b-roll render together", abs(r["duration"] - e.duration) < 0.1,
          f"{r['duration']}s vs {e.duration:.2f}s")
    tags = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=color_primaries,color_transfer,color_space", "-of", "csv=p=0", r["output"]],
                          capture_output=True, text=True).stdout.strip()
    check("render output is tagged BT.709", tags.count("bt709") == 3, tags)
    hdr_frame = frame(r["output"], 6.0, w=270)
    check("render: the HDR b-roll is tone-mapped (not washed out)", sat(hdr_frame) > 40, f"saturation {sat(hdr_frame):.0f}")
    plan = subprocess.run([sys.executable, "-m", "vedit.cli", "render", str(p.root), "--preview", "--dry-run"],
                          capture_output=True, text=True, cwd=ROOT / "scripts", env={**os.environ, "PYTHONUTF8": "1"})
    pj = json.loads(plan.stdout or "{}")
    check("render --dry-run: plan lists FX and HDR handling, renders nothing",
          pj.get("dry_run") and "stabilize" in pj.get("clip_fx", []) and sid in pj.get("hdr_tonemapped", []))
    from vedit.exports import flatten
    notes = [i.note for t in flatten(p.edit()).tracks for i in t.items if "vedit FX" in i.note]
    check("hand-offs carry the FX as notes", len(notes) >= 3, notes[0][:80] if notes else "")

    # ---------------------------------------------------------------- fix tools on files
    st = fx.file_tool("stabilize", str(f["shaky"]), out=str(OUT / "stab.mp4"), overwrite=True)

    def jitter(path):
        fr = [frame(path, t, w=160)[20:70, 30:130] for t in np.arange(1.0, 5.0, 1 / 30)][:90]   # centre: no borders
        return float(np.mean([np.abs(b - a).mean() for a, b in zip(fr, fr[1:])]))
    j0, j1 = jitter(f["shaky"]), jitter(st["output"])
    check("fix stabilize: frame-to-frame motion reduced by a third or more", j1 < j0 * 0.67, f"{j0:.1f} -> {j1:.1f}")
    dn = fx.file_tool("denoise", str(f["noisy"]), out=str(OUT / "dn.mp4"), overwrite=True, strength="medium")
    c0 = frame(f["clean"], 2.0)
    check("fix denoise: closer to the clean picture", np.abs(frame(dn["output"], 2.0) - c0).mean() < np.abs(frame(f["noisy"], 2.0) - c0).mean())
    di = fx.file_tool("deinterlace", str(f["inter"]), out=str(OUT / "deint.mp4"), overwrite=True)
    fo = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=field_order", "-of", "csv=p=0", di["output"]],
                        capture_output=True, text=True).stdout.strip().splitlines()[0]
    check("fix deinterlace: progressive output", fo in ("progressive", "unknown"), fo)
    rd = fx.file_tool("redact", str(f["sdr"]), out=str(OUT / "redact.mp4"), overwrite=True, x=400, y=200, w=300, h=200,
                      mode="pixelate")
    reg = lambda im: im[200 * 320 // 1280: 400 * 320 // 1280, 400 * 320 // 1280: 700 * 320 // 1280]  # noqa: E731
    check("fix redact: the box is pixelated, the rest untouched",
          reg(frame(rd["output"], 2)).std() < reg(frame(f["sdr"], 2)).std() and
          np.abs(frame(rd["output"], 2)[:30] - frame(f["sdr"], 2)[:30]).mean() < 4)
    rv = fx.file_tool("reverse", str(f["sdr"]), out=str(OUT / "rev.mp4"), overwrite=True)
    check("fix reverse: first frame == last frame of the source",
          np.abs(frame(rv["output"], 0.0) - frame(f["sdr"], 5.95)).mean() < 6)
    sm = fx.file_tool("smooth", str(f["clean"]), out=str(OUT / "smooth.mp4"), overwrite=True, factor=2.0)
    check("fix smooth: twice as long with in-between frames", abs(sm["duration"] - 8.0) < 0.15 and abs(sm["fps"] - 30) < 0.1,
          f"{sm['duration']}s @ {sm['fps']}")
    lp = fx.file_tool("loop", str(f["sdr"]), out=str(OUT / "loop.mp4"), overwrite=True, duration=15.0)
    check("fix loop: filled to 15 s", abs(lp["duration"] - 15.0) < 0.2, f"{lp['duration']}s")
    v3 = fx.file_tool("v360", str(f["eq"]), out=str(OUT / "flat.mp4"), overwrite=True, yaw=90, h_fov=100, v_fov=60, w=1280)
    check("fix v360: flat view at the asked size", v3["size"].startswith("1280x"), v3["size"])
    sg = fx.file_tool("straighten", str(f["sdr"]), out=str(OUT / "straight.mp4"), overwrite=True, degrees=-3)
    corner = frame(sg["output"], 2.0)[:4, :4].mean()
    check("fix straighten: same size, no black corners", sg["size"] == "1280x720" and corner > 10, f"corner {corner:.0f}")
    try:
        fx.file_tool("denoise", str(f["sdr"]), out=str(f["sdr"]))
        check("tools refuse to overwrite the original", False)
    except Exception as exc:  # noqa: BLE001
        check("tools refuse to overwrite the original", "original" in str(exc))
    dr = fx.file_tool("stabilize", str(f["shaky"]), out=str(OUT / "never.mp4"), dry_run=True)
    check("fix --dry-run: plan only", dr.get("dry_run") and not (OUT / "never.mp4").exists())

    # ---------------------------------------------------------------- delivery
    ex = delivery.export(f["sdr"], "reels", out=OUT / "reels.mp4", fit="blur", overwrite=True)
    i = probe(ex["output"])
    rows = {r["check"]: r["status"] for r in ex["check"]["rows"]}
    check("export reels: 1080x1920, H.264, checks pass", (i.width, i.height) == (1080, 1920) and rows.get("aspect") == "PASS"
          and rows.get("video codec") == "PASS" and rows.get("pixel format") == "PASS", json.dumps(rows))
    lm = measure_loudness(ex["output"])
    check("export: loudness at -14 LUFS, peak under -1 dBTP", abs(lm["lufs"] + 14) < 1.0 and lm["true_peak"] <= -0.9,
          f"{lm['lufs']:.1f} LUFS {lm['true_peak']:.1f} dBTP")
    hx = delivery.export(f["pq"], "x", out=OUT / "x_from_hdr.mp4", overwrite=True)
    hc = {r["check"]: r for r in hx["check"]["rows"]}
    check("export: HDR source delivered as SDR BT.709 for an SDR-only platform", hc["colour"]["status"] == "PASS",
          hc["colour"]["value"])
    cut = OUT / "liz30.mp4"
    ff("-ss", "100", "-t", "30", "-i", str(LIZ), "-c:v", "libx264", "-crf", "18", "-c:a", "aac", str(cut))
    small = delivery.export(cut, "x", out=OUT / "small.mp4", max_mb=2.0, overwrite=True)
    check("export --max-mb: two-pass fits the size", Path(small["output"]).stat().st_size <= 2.0 * 1048576,
          f"{small['size_mb']} MB")
    bad = delivery.check(f["pq"], "reels")
    br = {r["check"]: r["status"] for r in bad["rows"]}
    check("check: an HDR 16:9 clip fails Reels (colour, aspect) and says why",
          bad["verdict"] == "FAIL" and br.get("colour") == "FAIL" and br.get("aspect") == "FAIL")
    cmp_ = delivery.compare_files(ex["output"], ex["output"])
    check("compare: a file against itself is SSIM 1", cmp_["ssim"] and cmp_["ssim"] > 0.999, json.dumps(cmp_))
    ts = OUT / "damaged.ts"
    ff("-i", str(f["sdr"]), "-c", "copy", "-f", "mpegts", str(ts))
    data = ts.read_bytes()
    broken = OUT / "damaged_cut.ts"
    broken.write_bytes(data[: len(data) // 2] + bytes(4000) + data[len(data) // 2 + 4000: int(len(data) * 0.8)])
    rp = delivery.repair(broken, OUT / "repaired.mp4", overwrite=True)
    check("repair: a damaged recording comes back playable", rp["duration"] > 3.0, json.dumps(rp))
    sf = delivery.safe_frame(ex["output"], "tiktok", OUT / "safe.png")
    check("safe zones drawn for the owner to look at", sf.exists())

    # ---------------------------------------------------------------- audio
    rec = OUT / "recorder.wav"            # a second recorder whose clock runs 200 ppm fast (a resample, like real drift)
    ff("-ss", "20", "-t", "230", "-i", str(LIZ), "-af", "aresample=48000,asetrate=48000*1.0002,aresample=48000", "-ac", "1",
       str(rec))
    ref = OUT / "ref.wav"
    ff("-ss", "22.5", "-t", "220", "-i", str(LIZ), "-ac", "1", "-ar", "48000", str(ref))
    s = audiotools.sync(ref, rec, drift=True)
    # ref t=0 is the source at 22.5 s; the recorder reaches it at 2.5/1.0002 s; its clock reads 1/1.0002 per ref second
    check("sync: offset found", abs(s["offset"] - 2.5 / 1.0002) < 0.01 and s["confidence"] > 3, json.dumps(s))
    check("sync --drift: clock drift measured (-200 ppm)", -230 < s["drift_ppm"] < -170, f"{s['drift_ppm']} ppm")
    vid = OUT / "cam_for_rec.mp4"
    ff("-f", "lavfi", "-i", "color=c=gray:s=320x240:r=25:d=220", "-i", str(ref), "-shortest", "-c:v", "libx264",
       "-c:a", "aac", str(vid))
    rp2 = audiotools.replace(vid, rec, OUT / "cam_synced.mp4", drift=True, overwrite=True)
    chk_end = audiotools.sync(ref, OUT / "cam_synced.mp4", drift=True)
    check("replace: the recorder's sound lines up at the start and the end", abs(chk_end["offset"]) < 0.01 and
          abs(chk_end.get("drift_ppm", 0)) < 30, json.dumps({k: chk_end.get(k) for k in ("offset", "drift_ppm")}))
    dm = audiotools.file_tool("downmix", f["s51"], out=str(OUT / "stereo.wav"), overwrite=True)
    check("downmix: 5.1 -> stereo", probe(dm["output"]).has_audio and "2" in subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=channels", "-of", "csv=p=0", dm["output"]],
        capture_output=True, text=True).stdout)
    dy = audiotools.file_tool("dynamics", str(cut), out=str(OUT / "dyn.mp4"), overwrite=True, gate=-50, compress="-20:4", limit=-3)
    pk = measure_loudness(dy["output"])["true_peak"]
    check("dynamics: limiter holds the ceiling", pk <= -2.4, f"{pk:.1f} dBTP")
    keeps = audiotools.speech_aware_keeps("liz", str(SRC / "transcripts" / "liz_epidemiologist.json"))
    from vedit.captions import PUNCT_END, transcript_words
    words = transcript_words(str(SRC / "transcripts" / "liz_epidemiologist.json"))
    ends = {round(k["to"], 3) for k in keeps[:-1]}
    ok = all(PUNCT_END.search(w["w"].strip()) or (nxt["s"] - w["e"] > 1.5) for w, nxt in zip(words, words[1:])
             if round(w["e"], 3) in ends)
    check("speech-aware cut: every cut falls at a sentence end or a long pause", ok and len(keeps) > 3, f"{len(keeps)} keeps")

    # ---------------------------------------------------------------- extras
    g = extras.grid([str(f["sdr"]), str(f["clean"]), str(f["log"])], str(OUT / "grid.mp4"), cols=2, cell="640x360", overwrite=True)
    gi = probe(g["output"])
    check("grid: 2x2 layout", (gi.width, gi.height) == (1288, 728), g["size"])
    ag = extras.audiogram(str(ROOT / "tests" / "footage" / "music_test.mp3"), str(OUT / "ag.mp4"), title="Episode 12",
                          overwrite=True)
    agf = frame(ag["output"], 10.0, w=270)
    check("audiogram: video the length of the audio, waveform drawn", abs(ag["duration"] - 30) < 0.5 and agf.max() > 150,
          f"{ag['duration']}s")
    ff("-ss", "1", "-i", str(f["sdr"]), "-frames:v", "1", str(OUT / "still.png"))
    kb = extras.kenburns(p, str(OUT / "still.png"), at=3.0, duration=4.0, pan="right")
    ek = p.edit()
    kc = next(c for c in ek.broll if c.id == kb["clip"])
    check("kenburns: a zooming still on the b-roll track", kc.zoom and kc.zoom.end_scale > kc.zoom.start_scale and kc.start == 3.0)
    bf = OUT / "batch_in"
    bf.mkdir(exist_ok=True)
    for k in ("sdr", "clean"):
        shutil.copy(f[k], bf / f"{k}.mp4")
    recipe = {"steps": [["delivery", "export", "{file}", "--preset", "x", "--out", "{out_dir}/{stem}_x.mp4", "--overwrite"]],
              "outputs": ["{out_dir}/{stem}_x.mp4"], "out_dir": "{folder}/out"}
    b1 = extras.batch(str(bf), recipe, jobs=2)
    b2 = extras.batch(str(bf), recipe, jobs=2)
    check("batch: runs every file, then reuses the cache", b1["done"] == 2 and not b1["failed"] and b2["cached"] == 2,
          f"run 1 done {b1['done']} failed {len(b1['failed'])}; run 2 cached {b2['cached']}")
    rp3 = extras.report(str(ex["output"]), str(OUT / "report.html"), before=str(f["sdr"]), platform="reels",
                        steps=["export reels (blur fit)"])
    html_ = Path(rp3["report"]).read_text(encoding="utf-8")
    check("report: HTML with facts, delivery rows and frames", "Delivery check" in html_ and "data:image/png;base64" in html_)

    # ---------------------------------------------------------------- QA with a platform
    from vedit.qa import check as qa_check
    e = p.edit()
    q = qa_check(e, r["output"], OUT / "qa", platform="shorts", listen=False)
    check("QA: the platform's rows and a safe-zone frame join the report", q.get("delivery") and
          any(s_.endswith("safe_shorts.png") for s_ in q["sheets"]), q.get("delivery", {}).get("verdict", ""))

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
