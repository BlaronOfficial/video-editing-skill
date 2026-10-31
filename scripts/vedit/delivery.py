"""Delivery: one table per destination, compliance checks, export presets, size targets, before/after
comparison and repair of damaged recordings.

    vedit delivery check <file> --platform reels [--compare master.mp4]
    vedit delivery export <file> --preset reels [--fit pad|crop|blur] [--max-mb 25] [--out x.mp4]
    vedit delivery compare <a> <b>        SSIM / PSNR
    vedit delivery repair <file>          remux what can be read, count the damage
    vedit delivery safe <file> --platform tiktok --at 3    a frame with the app's UI zones drawn on it

Specs are the platforms' published limits (Oct 2026) and the conventional loudness targets; safe zones are
the parts of the frame each app's own UI covers. The table design (one entry feeding checks, exports and
safe zones) follows kajisho5/ffmpeg-skill (MIT).
"""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any

from .media import ffmpeg, ffprobe, measure_loudness, probe
from .util import VeditError, run

SAFE_5 = {"top": 0.05, "bottom": 0.05, "left": 0.05, "right": 0.05}
NO_SAFE = {"top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0}
TP_TOL = 0.1

PLATFORMS: dict[str, dict[str, Any]] = {
    "tiktok":   {"title": "TikTok", "frame": (1080, 1920), "fps": 30, "max_duration": 600, "aspects": ["9:16", "1:1"],
                 "min_short": 1080, "fps_max": 60, "codecs": ["h264", "hevc"], "max_mb": 4096, "lufs": -14, "lufs_tol": 2.0,
                 "tp": -1.0, "sdr_only": True, "safe": {"top": 0.10, "bottom": 0.22, "left": 0.05, "right": 0.14}},
    "reels":    {"title": "Instagram Reels", "frame": (1080, 1920), "fps": 30, "max_duration": 90,
                 "aspects": ["9:16", "4:5", "1:1"], "min_short": 1080, "fps_max": 60, "codecs": ["h264", "hevc"],
                 "max_mb": 4096, "lufs": -14, "lufs_tol": 2.0, "tp": -1.0, "sdr_only": True,
                 "safe": {"top": 0.08, "bottom": 0.20, "left": 0.05, "right": 0.12}},
    "shorts":   {"title": "YouTube Shorts", "frame": (1080, 1920), "fps": 30, "max_duration": 180, "aspects": ["9:16", "1:1"],
                 "min_short": 1080, "fps_max": 60, "codecs": ["h264", "hevc", "vp9", "av1"], "max_mb": None, "lufs": -14,
                 "lufs_tol": 2.0, "tp": -1.0, "sdr_only": False,
                 "safe": {"top": 0.06, "bottom": 0.18, "left": 0.05, "right": 0.12}},
    "youtube":  {"title": "YouTube", "frame": (1920, 1080), "fps": None, "max_duration": 12 * 3600,
                 "aspects": ["16:9", "9:16", "1:1", "4:3"], "min_short": 720, "fps_max": 60,
                 "codecs": ["h264", "hevc", "vp9", "av1", "prores"], "max_mb": 256 * 1024, "lufs": -14, "lufs_tol": 2.0,
                 "tp": -1.0, "sdr_only": False, "safe": SAFE_5},
    "x":        {"title": "X", "frame": (1280, 720), "fps": 30, "max_duration": 140, "aspects": ["16:9", "1:1", "9:16"],
                 "min_short": 720, "fps_max": 60, "codecs": ["h264"], "max_mb": 512, "lufs": -14, "lufs_tol": 3.0,
                 "tp": -1.0, "sdr_only": True, "safe": SAFE_5},
    "linkedin": {"title": "LinkedIn", "frame": (1080, 1080), "fps": 30, "max_duration": 600,
                 "aspects": ["16:9", "1:1", "9:16", "4:5"], "min_short": 720, "fps_max": 60, "codecs": ["h264"],
                 "max_mb": 5120, "lufs": -14, "lufs_tol": 3.0, "tp": -1.0, "sdr_only": True, "safe": SAFE_5},
    "facebook": {"title": "Facebook", "frame": (1920, 1080), "fps": 30, "max_duration": 240 * 60,
                 "aspects": ["16:9", "1:1", "9:16", "4:5"], "min_short": 720, "fps_max": 60, "codecs": ["h264", "hevc"],
                 "max_mb": 10240, "lufs": -14, "lufs_tol": 3.0, "tp": -1.0, "sdr_only": True, "safe": SAFE_5},
    "podcast":  {"title": "Podcast (Spotify/Apple video)", "frame": None, "fps": None, "max_duration": None, "aspects": None,
                 "min_short": 0, "fps_max": None, "codecs": None, "max_mb": None, "lufs": -16, "lufs_tol": 1.0, "tp": -1.0,
                 "sdr_only": False, "safe": NO_SAFE},
    "broadcast": {"title": "Broadcast (EBU R128)", "frame": (1920, 1080), "fps": None, "max_duration": None,
                  "aspects": ["16:9"], "min_short": 1080, "fps_max": 60, "codecs": None, "max_mb": None, "lufs": -23,
                  "lufs_tol": 1.0, "tp": -1.0, "sdr_only": False, "safe": SAFE_5},
}
ALIASES = {"ig": "reels", "instagram": "reels", "youtube-shorts": "shorts", "yt": "youtube", "twitter": "x",
           "fb": "facebook", "spotify": "podcast"}

# encoder settings per preset; frame/fps come from the platform entry
H264 = ["-c:v", "libx264", "-preset", "slow", "-profile:v", "high", "-pix_fmt", "yuv420p"]
PRESETS: dict[str, dict[str, Any]] = {
    **{name: {"platform": name, "video": [*H264, "-crf", "20"], "audio": ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"],
              "ext": ".mp4"} for name in ("tiktok", "reels", "shorts", "x", "linkedin", "facebook")},
    "youtube": {"platform": "youtube", "video": [*H264, "-crf", "18"], "audio": ["-c:a", "aac", "-b:a", "320k", "-ar", "48000"],
                "ext": ".mp4", "keep_size": True},
    "youtube-hdr": {"platform": "youtube", "video": ["-c:v", "libx265", "-preset", "medium", "-crf", "20", "-pix_fmt",
                                                     "yuv420p10le", "-tag:v", "hvc1", "-x265-params", "log-level=error"],
                    "audio": ["-c:a", "aac", "-b:a", "320k"], "ext": ".mp4", "keep_size": True, "keep_hdr": True},
    "h265": {"platform": None, "video": ["-c:v", "libx265", "-preset", "medium", "-crf", "24", "-pix_fmt", "yuv420p",
                                         "-tag:v", "hvc1", "-x265-params", "log-level=error"],
             "audio": ["-c:a", "aac", "-b:a", "192k"], "ext": ".mp4", "keep_size": True},
    "prores": {"platform": None, "video": ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-vendor", "apl0"],
               "audio": ["-c:a", "pcm_s24le"], "ext": ".mov", "keep_size": True},
    "gif": {"platform": None, "video": [], "audio": [], "ext": ".gif", "keep_size": True},
    "podcast": {"platform": "podcast", "video": [*H264, "-crf", "22"], "audio": ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"],
                "ext": ".mp4", "keep_size": True},
}


def platform(name: str) -> dict:
    key = ALIASES.get(name.lower(), name.lower())
    if key not in PLATFORMS:
        raise VeditError(f"Unknown platform '{name}'. Use one of: {', '.join(PLATFORMS)}")
    return {"name": key, **PLATFORMS[key]}


def aspect_name(w: int, h: int) -> str:
    r = w / h if h else 0
    for name, v in (("9:16", 9 / 16), ("16:9", 16 / 9), ("1:1", 1.0), ("4:5", 0.8), ("4:3", 4 / 3), ("21:9", 21 / 9)):
        if abs(r - v) < 0.02:
            return name
    g = math.gcd(w, h) or 1
    return f"{w // g}:{h // g}"


def _streams(path: str) -> dict:
    out = run([ffprobe(), "-v", "error", "-show_streams", "-show_format", "-show_chapters", "-of", "json", path]).stdout
    return json.loads(out or "{}")


# ------------------------------------------------------------------ check

def check(path: str | Path, platform_name: str, *, compare: str | None = None, content: bool = True) -> dict:
    """PASS / WARN / FAIL rows for a delivery. Format rows are safe to fix; judgement rows (duration,
    aspect, fps, loudness of ambience) change the content: report them and let the owner decide."""
    path = str(Path(path).resolve())
    spec = platform(platform_name)
    doc = _streams(path)
    v = next((s for s in doc.get("streams", []) if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in doc.get("streams", []) if s.get("codec_type") == "audio"), None)
    dur = float(doc.get("format", {}).get("duration") or 0)
    size = int(doc.get("format", {}).get("size") or 0)
    rows: list[dict] = []

    def row(name, status, value, expect, fix="", kind="format"):
        rows.append({"check": name, "status": status, "value": value, "expect": expect, "fix": fix, "kind": kind})

    if spec["max_duration"]:
        row("duration", "PASS" if dur <= spec["max_duration"] else "FAIL", f"{dur:.2f}s", f"<= {spec['max_duration']}s",
            "cut (drops content) or speed up (faster motion): the owner decides", "judgement")
    if v:
        w, h = int(v.get("width", 0)), int(v.get("height", 0))
        rot = next((int(float(sd["rotation"])) for sd in v.get("side_data_list", []) or [] if "rotation" in sd), 0)
        if rot % 180:
            w, h = h, w
        asp = aspect_name(w, h)
        if spec["aspects"]:
            row("aspect", "PASS" if asp in spec["aspects"] else "FAIL", asp, "/".join(spec["aspects"]),
                "vedit reframe or delivery export --fit pad|crop|blur", "judgement")
        if spec["min_short"]:
            row("resolution", "PASS" if min(w, h) >= spec["min_short"] else "WARN", f"{w}x{h}",
                f"short side >= {spec['min_short']}", "re-export from the master; upscaling adds no detail")
        r = v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1"
        num, _, den = r.partition("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 0
        if spec["fps_max"]:
            row("fps", "PASS" if fps <= spec["fps_max"] + 0.01 else "FAIL", f"{fps:.3f}", f"<= {spec['fps_max']}",
                "export at 30 (drops frames of fast motion)", "judgement")
        rr = v.get("r_frame_rate") or r
        n2, _, d2 = rr.partition("/")
        vfr = abs(float(n2) / float(d2 or 1) - fps) > 0.01 if float(d2 or 1) else False
        row("frame timing", "WARN" if vfr else "PASS", "variable" if vfr else "constant", "constant",
            "any re-encode (delivery export) conforms it")
        if spec["codecs"]:
            row("video codec", "PASS" if v.get("codec_name") in spec["codecs"] else "FAIL", v.get("codec_name"),
                "/".join(spec["codecs"]), f"vedit delivery export --preset {spec['name']}")
        pf = v.get("pix_fmt", "")
        row("pixel format", "PASS" if pf in ("yuv420p", "yuvj420p") or (not spec["sdr_only"] and pf == "yuv420p10le")
            else "FAIL", pf, "yuv420p", "the export presets write yuv420p")
        trc = v.get("color_transfer") or ""
        hdr = trc in ("smpte2084", "arib-std-b67")
        if hdr and spec["sdr_only"]:
            row("colour", "FAIL", f"HDR ({trc})", "SDR BT.709", "renders tone-map HDR sources; re-export SDR")
        else:
            tags = [v.get("color_primaries"), v.get("color_transfer"), v.get("color_space")]
            ok = hdr or all(t in (None, "", "bt709", "unknown") for t in tags)
            row("colour", "PASS" if ok else "WARN", "/".join(t or "-" for t in tags), "bt709 or untagged (or HDR where allowed)",
                "re-export with BT.709 tags")
    else:
        row("video", "FAIL" if spec["frame"] else "PASS", "none", "a video stream" if spec["frame"] else "any")
    if spec["max_mb"]:
        row("file size", "PASS" if size <= spec["max_mb"] * 1024 * 1024 else "FAIL", f"{size / 1048576:.1f} MB",
            f"<= {spec['max_mb']} MB", "delivery export --max-mb N (two-pass to a size)")
    if a:
        ch = int(a.get("channels") or 0)
        row("audio", "PASS", f"{a.get('codec_name')} {ch}ch {a.get('sample_rate')} Hz", "present")
        row("channels", "PASS" if ch in (1, 2) else "WARN", f"{ch}ch", "mono or stereo", "vedit audio downmix")
        if int(a.get("sample_rate") or 0) not in (44100, 48000):
            row("sample rate", "WARN", a.get("sample_rate"), "44100 or 48000", "re-export (48 kHz)")
        lm = measure_loudness(path)
        if lm and spec["lufs"] is not None:
            quiet = lm["lufs"] <= -40
            row("loudness", "PASS" if abs(lm["lufs"] - spec["lufs"]) <= spec["lufs_tol"] else ("WARN" if quiet else "FAIL"),
                f"{lm['lufs']:.1f} LUFS", f"{spec['lufs']} ± {spec['lufs_tol']} LUFS",
                "delivery export normalises speech/music; never push ambience or near-silence up to a speech target",
                "judgement" if quiet else "format")
            row("true peak", "PASS" if lm["true_peak"] <= spec["tp"] + TP_TOL else "FAIL", f"{lm['true_peak']:.1f} dBTP",
                f"<= {spec['tp']} dBTP", "delivery export (limiter)")
    else:
        row("audio", "WARN" if spec["frame"] else "FAIL", "none", "an audio stream", "silent uploads are often rejected")
    if content and v:
        first = run([ffmpeg(), "-v", "error", "-i", path, "-frames:v", "1", "-vf", "signalstats,metadata=print:file=-",
                     "-f", "null", "-"], check=False).stdout or ""
        m = re.search(r"YAVG=([\d.]+)", first)
        if m and float(m.group(1)) < 20:
            row("first frame", "WARN", f"luma {float(m.group(1)):.0f}", "not black", "the thumbnail/preview frame is black",
                "judgement")
    if compare:
        c = compare_files(path, compare)
        if c.get("ssim") is not None:
            row("similarity", "PASS" if c["ssim"] >= 0.95 else "WARN", f"SSIM {c['ssim']:.4f}, PSNR {c['psnr']:.1f} dB",
                "SSIM >= 0.95 vs the master", "export at higher quality", "judgement")
    fails = [r for r in rows if r["status"] == "FAIL"]
    warns = [r for r in rows if r["status"] == "WARN"]
    return {"file": path, "platform": spec["name"], "verdict": "FAIL" if fails else ("WARN" if warns else "PASS"),
            "passed": len(rows) - len(fails) - len(warns), "total": len(rows), "rows": rows}


# ------------------------------------------------------------------ compare / repair

def compare_files(a: str | Path, b: str | Path, *, max_frames: int = 900) -> dict:
    """Mean and worst SSIM and mean PSNR of a against b (b scaled to a's frame when sizes differ)."""
    ia, ib = probe(a), probe(b)
    if not (ia.width and ib.width):
        return {"ssim": None, "note": "both need a picture"}
    g = (f"[1:v]scale={ia.width}:{ia.height},setsar=1[r];[0:v]setsar=1[o];[o]split[o1][o2];[r]split[r1][r2];"
         f"[o1][r1]ssim=stats_file=-[x];[o2][r2]psnr[y]")
    proc = run([ffmpeg(), "-v", "info", "-i", str(a), "-i", str(b), "-filter_complex", g, "-map", "[x]", "-map", "[y]",
                "-frames:v", str(max_frames), "-f", "null", "-"], check=False)
    per = [float(x) for x in re.findall(r"All:([\d.]+) \(", proc.stdout or "")]
    m = re.search(r"SSIM .*All:([\d.]+)", proc.stderr or "")
    p = re.search(r"PSNR .*average:([\d.inf]+)", proc.stderr or "")
    return {"ssim": float(m.group(1)) if m else (sum(per) / len(per) if per else None),
            "ssim_min": min(per) if per else None,
            "psnr": float(p.group(1)) if p and p.group(1) != "inf" else (99.0 if p else None), "frames": len(per)}


def repair(src: str | Path, out: str | Path | None = None, *, overwrite: bool = False) -> dict:
    """Remux what can still be read (damaged phone/OBS recordings, cut-off downloads) and count the damage."""
    src = Path(src).resolve()
    out = Path(out) if out else src.with_name(f"{src.stem}_repaired{src.suffix if src.suffix.lower() in ('.mp4', '.mov', '.mkv') else '.mp4'}")
    if out.resolve() == src:
        raise VeditError("Refusing to overwrite the original.")
    if out.exists() and not overwrite:
        raise VeditError(f"{out} exists (--overwrite to replace it)")
    before = run([ffmpeg(), "-v", "error", "-i", str(src), "-f", "null", "-"], check=False, timeout=7200).stderr or ""
    run([ffmpeg(), "-y", "-v", "error", "-err_detect", "ignore_err", "-fflags", "+genpts+discardcorrupt", "-i", str(src),
         "-map", "0:v?", "-map", "0:a?", "-c", "copy", "-movflags", "+faststart", str(out)], check=False, timeout=7200)
    if not out.exists() or out.stat().st_size == 0:
        raise VeditError("Nothing readable could be recovered (a recording without its index needs untrunc and a "
                         "healthy file from the same camera).")
    after = run([ffmpeg(), "-v", "error", "-i", str(out), "-f", "null", "-"], check=False, timeout=7200).stderr or ""
    i = probe(out)
    return {"output": str(out), "duration": round(i.duration, 3), "errors_before": len(before.splitlines()),
            "errors_after": len(after.splitlines())}


# ------------------------------------------------------------------ export

def _fit(w0: int, h0: int, W: int, H: int, fit: str) -> str:
    if fit == "crop":
        return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    if fit == "blur":
        return (f"split=2[fg][bg];[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=40,"
                f"eq=brightness=-0.08[bgb];[fg]scale={W}:{H}:force_original_aspect_ratio=decrease[fgs];"
                f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1")
    return f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"


def export(src: str | Path, preset: str, *, out: str | Path | None = None, fit: str = "pad", max_mb: float | None = None,
           normalize: bool = True, overwrite: bool = False, dry_run: bool = False) -> dict:
    """Re-encode for a destination: frame (fit pad|crop|blur), fps, codec, loudness (two-pass loudnorm),
    optionally to a file size (two-pass x264). HDR sources are tone-mapped unless the preset keeps HDR.
    The result is checked against the platform."""
    from .footage import analyze, to_sdr_chain
    if preset not in PRESETS:
        raise VeditError(f"Unknown preset '{preset}'. Use one of: {', '.join(PRESETS)}")
    pr = PRESETS[preset]
    spec = platform(pr["platform"]) if pr["platform"] else None
    src = Path(src).resolve()
    info = probe(src)
    out = Path(out) if out else src.with_name(f"{src.stem}_{preset}{pr['ext']}")
    if out.resolve() == src:
        raise VeditError("Refusing to overwrite the original.")
    if out.exists() and not overwrite:
        raise VeditError(f"{out} exists (--overwrite only for a file this job made or the owner asked to replace)")
    vf: list[str] = []
    a = analyze(src, deep=False) if info.kind == "video" else {}
    if info.kind == "video" and not pr.get("keep_hdr"):
        sdr = to_sdr_chain(a)
        if sdr:
            vf.append(sdr)
    if a.get("interlaced"):
        vf.insert(0, "bwdif")
    W = H = None
    if spec and spec["frame"] and not pr.get("keep_size") and info.kind == "video":
        W, H = spec["frame"]
        dw, dh = info.display_size
        if dw and dh and aspect_name(dw, dh) != aspect_name(W, H) and aspect_name(dw, dh) in (spec["aspects"] or []):
            H = int(round(W * dh / dw / 2) * 2)      # the platform takes the source's own aspect (1:1, 4:5): keep it
        vf.append(_fit(info.width, info.height, W, H, fit))
    if spec and spec.get("fps") and info.fps and info.fps > spec["fps"] + 0.5:
        vf.append(f"fps={spec['fps']}")
    if preset == "gif":
        vf += ["fps=12", "scale=480:-2:flags=lanczos", "split[g1][g2];[g2]palettegen=stats_mode=diff[p];[g1][p]paletteuse=dither=bayer"]
    af: list[str] = []
    measured = None
    if normalize and info.has_audio and preset not in ("gif", "prores"):
        target = (spec or {}).get("lufs") or -14
        tp = (spec or {}).get("tp", -1.0) - 0.5
        if not dry_run:
            proc = run([ffmpeg(), "-v", "info", "-i", str(src), "-af", f"loudnorm=I={target}:TP={tp}:LRA=11:print_format=json",
                        "-f", "null", "-"], check=False, timeout=7200)
            m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr or "", re.S)
            measured = json.loads(m.group(0)) if m else None
        if measured and float(measured["input_i"]) <= -40:
            measured = {"skipped": "ambience/near-silence: not pushed up to a speech target"}
        elif measured:
            af.append(f"loudnorm=I={target}:TP={tp}:LRA=11:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
                      f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
                      f":offset={measured['target_offset']}:linear=true,aresample=48000")
        else:
            af.append(f"loudnorm=I={target}:TP={tp}:LRA=11,aresample=48000")
    video = list(pr["video"])
    two_pass = None
    if max_mb and preset != "gif":
        if "libx264" not in video:
            raise VeditError("--max-mb runs a two-pass x264 encode; pick an H.264 preset.")
        abr = 192_000 if info.has_audio else 0
        vbr = int((max_mb * 0.97 * 8 * 1024 * 1024) / max(info.duration, 0.1) - abr)
        if vbr < 150_000:
            raise VeditError(f"{max_mb} MB is too small for {info.duration:.0f} s of video (under 150 kb/s); cut it "
                             "shorter or allow a bigger file.")
        i = video.index("-crf")
        video[i:i + 2] = ["-b:v", str(vbr), "-maxrate", str(int(vbr * 1.5)), "-bufsize", str(vbr * 2)]
        two_pass = vbr
    plan = {"input": str(src), "output": str(out), "preset": preset, "video_filters": vf, "audio_filters": af,
            "frame": f"{W}x{H}" if W else "source", "two_pass_video_bps": two_pass}
    if dry_run:
        return {"dry_run": True, **plan}
    t0 = time.time()
    base = [ffmpeg(), "-y", "-v", "error", "-i", str(src)]
    vfa = ["-vf", ",".join(vf)] if vf and "[" not in ",".join(vf) else (["-filter_complex", f"[0:v]{','.join(vf)}[v]", "-map", "[v]"] if vf else [])
    maps = [] if vfa[:1] == ["-filter_complex"] else (["-map", "0:v:0?"] if info.kind == "video" else [])
    amap = ["-map", "0:a:0?"] if info.has_audio and preset != "gif" else []
    if preset == "gif":
        run(base + ["-filter_complex", f"[0:v]{','.join(vf)}", str(out)], timeout=7200)
    elif two_pass:
        log = out.with_suffix(".pass")
        run(base + vfa + maps + video + ["-pass", "1", "-passlogfile", str(log), "-an", "-f", "null", "-"], timeout=14400)
        run(base + vfa + maps + amap + video + ["-pass", "2", "-passlogfile", str(log)]
            + (["-af", ",".join(af)] if af else []) + pr["audio"] + ["-movflags", "+faststart", str(out)], timeout=14400)
        for f in out.parent.glob(log.name + "*"):
            f.unlink(missing_ok=True)
    else:
        run(base + vfa + maps + amap + video + (["-af", ",".join(af)] if af else []) + pr["audio"]
            + (["-movflags", "+faststart"] if pr["ext"] in (".mp4", ".mov") else []) + [str(out)], timeout=14400)
    res = {**plan, "seconds": round(time.time() - t0, 1), "size_mb": round(out.stat().st_size / 1048576, 2),
           "loudness_measured": measured}
    if spec and preset != "gif":
        res["check"] = check(out, spec["name"], content=False)
    return res


# ------------------------------------------------------------------ safe zones

def safe_frame(src: str | Path, platform_name: str, out: str | Path, *, at: float = 1.0) -> Path:
    """One frame with the platform's UI zones shaded, to look at before delivery."""
    spec = platform(platform_name)
    sz = spec["safe"]
    i = probe(src)
    w, h = i.display_size
    boxes = [(0, 0, w, int(h * sz["top"])), (0, h - int(h * sz["bottom"]), w, int(h * sz["bottom"])),
             (0, 0, int(w * sz["left"]), h), (w - int(w * sz["right"]), 0, int(w * sz["right"]), h)]
    draw = ",".join(f"drawbox=x={x}:y={y}:w={bw}:h={bh}:color=red@0.35:t=fill" for x, y, bw, bh in boxes if bw and bh)
    run([ffmpeg(), "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(src), "-frames:v", "1", "-vf", draw or "null", str(out)])
    return Path(out)
