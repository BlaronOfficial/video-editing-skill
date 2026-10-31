"""Camera footage that looks right: HDR / Dolby Vision, BT.2020, Log, variable frame rate, interlacing,
rotation, black bars, and what kind of device made the file.

`analyze(path)` measures a file once (cached on path + mtime); `vedit project init` stores the result on
each Source (`Source.color`), and every place that decodes a source (render segments, b-roll, Studio
proxies) puts `input_chain(src)` first, so an iPhone HDR clip is tone-mapped to SDR BT.709, a Log clip
gets its conversion LUT (`Source.lut`, set by Claude or the owner), and interlaced footage is
deinterlaced before anything else touches it. Variable frame rate needs no extra step: every render
path already conforms to the canvas rate with `fps=`.

Techniques follow kajisho5/ffmpeg-skill (MIT): zscale linearisation + tonemap for PQ/HLG, a gamut-only
path for BT.2020 SDR, signalstats for flat Log pictures, packet timing for VFR.
"""

from __future__ import annotations

import functools
import json
import re
import statistics
from pathlib import Path
from typing import Any

from .media import ffmpeg, ffprobe
from .util import run

HDR_TRC = {"smpte2084": "pq", "arib-std-b67": "hlg"}
TONEMAPS = ("hable", "mobius", "reinhard", "clip", "gamma", "linear")


def _ffprobe_json(path: str) -> dict:
    out = run([ffprobe(), "-v", "error", "-show_streams", "-show_format", "-of", "json", path], check=False).stdout
    try:
        return json.loads(out or "{}")
    except ValueError:
        return {}


def _video(doc: dict) -> dict | None:
    return next((s for s in doc.get("streams", []) if s.get("codec_type") == "video"
                 and not s.get("disposition", {}).get("attached_pic")), None)


def _rate(v: str | None) -> float:
    if not v or v in ("0/0", "N/A"):
        return 0.0
    a, _, b = v.partition("/")
    return float(a) / float(b or 1) if float(b or 1) else 0.0


def device(doc: dict) -> str:
    """Best guess at what recorded the file, from container and stream tags."""
    tags = {k.lower(): str(v) for k, v in (doc.get("format", {}).get("tags") or {}).items()}
    for s in doc.get("streams", []):
        tags.update({f"s.{k.lower()}": str(v) for k, v in (s.get("tags") or {}).items()})
    blob = " ".join(f"{k}={v}" for k, v in tags.items()).lower()
    if "com.apple.quicktime.make=apple" in blob or "iphone" in blob:
        return "iphone"
    if "gopro" in blob:
        return "gopro"
    if "dji" in blob:
        return "dji"
    if "insta360" in blob:
        return "insta360"
    if "samsung" in blob or "com.android" in blob:
        return "android"
    if "zoom" in blob and ("meeting" in blob or "zoom.us" in blob):
        return "zoom"
    if any(x in blob for x in ("obs", "screenflow", "camtasia", "screen recording", "screencapture", "bandicam",
                               "nvidia shadowplay", "xbox game bar")):
        return "screen"
    return ""


def frame_timing(path: str, duration: float, *, windows: int = 3, span: float = 4.0) -> str:
    """'cfr' | 'vfr' | 'unknown' from packet timestamps in a few windows (no decoding)."""
    deltas_all: list[list[float]] = []
    starts = [0.0] if duration < span * 2 else [duration * i / windows for i in range(windows)]
    for i, t in enumerate(starts):
        interval = f"{t:.3f}%{t + span:.3f}" if i else f"%{span:.3f}"
        out = run([ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
                   "-read_intervals", interval, "-of", "csv=p=0", path], check=False).stdout or ""
        pts = sorted(float(x) for x in out.split() if x not in ("N/A", ""))
        pts = [p for p in pts if p >= t - 1e-6]
        d = [b - a for a, b in zip(pts, pts[1:]) if b > a]
        if i == 0:
            d = d[1:]
        if len(d) >= 10:
            deltas_all.append(d)
    if not deltas_all:
        return "unknown"
    medians = [statistics.median(d) for d in deltas_all]
    tol = min(0.002, min(medians) / 2)
    steady = all(abs(x - m) <= tol for d, m in zip(deltas_all, medians) for x in d)
    return "cfr" if steady and max(medians) - min(medians) <= tol else "vfr"


def log_levels(path: str, seconds: float = 20.0) -> dict:
    """Flat, low-contrast, desaturated picture tagged as SDR -> probably Log (S-Log, V-Log, C-Log, D-Log)."""
    proc = run([ffmpeg(), "-hide_banner", "-nostdin", "-t", f"{seconds:.1f}", "-i", path, "-an", "-vf",
                "fps=2,signalstats,metadata=print:file=-", "-f", "null", "-"], check=False)
    vals: dict[str, list[float]] = {}
    for line in (proc.stdout or "").splitlines():
        m = re.search(r"lavfi\.signalstats\.(\w+)=([-\d.]+)", line)
        if m:
            vals.setdefault(m.group(1), []).append(float(m.group(2)))
    if not vals.get("YAVG"):
        return {"looks_like_log": False, "measured": False}
    ymax = max(vals.get("YMAX") or [255])
    scale = 1.0 if ymax <= 255 else (1 / 4 if ymax <= 1023 else 1 / 16)
    lows = sorted(x * scale for x in (vals.get("YLOW") or vals["YMIN"]))
    highs = sorted(x * scale for x in (vals.get("YHIGH") or vals["YMAX"]))
    p_low, p_high = lows[len(lows) // 20], highs[-1 - len(highs) // 20]
    sat = statistics.mean(vals.get("SATAVG") or [0]) * scale
    return {"looks_like_log": p_low >= 64 and p_high <= 235 and sat < 40, "measured": True,
            "y_low_p5": round(p_low, 1), "y_high_p95": round(p_high, 1), "saturation": round(sat, 1)}


def black_bars(path: str, duration: float, w: int, h: int) -> dict | None:
    """A steady letterbox/pillarbox (cropdetect on samples through the file); None when the picture is full."""
    boxes = []
    for i in range(6):
        t = duration * (i + 0.5) / 6
        out = run([ffmpeg(), "-hide_banner", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "12", "-vf",
                   "cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"], check=False).stderr or ""
        found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", out)
        if found:
            boxes.append(tuple(int(x) for x in found[-1]))
    if len(boxes) < 4:
        return None
    cw, ch, cx, cy = (statistics.median(b[i] for b in boxes) for i in range(4))
    steady = all(abs(b[0] - cw) <= 8 and abs(b[1] - ch) <= 8 for b in boxes)
    if not steady or (cw >= w - 8 and ch >= h - 8):
        return None
    return {"x": int(cx), "y": int(cy), "w": int(cw), "h": int(ch)}


@functools.lru_cache(maxsize=256)
def _analyze_cached(path: str, mtime: float, deep: bool) -> dict:
    doc = _ffprobe_json(path)
    v = _video(doc)
    res: dict[str, Any] = {"device": device(doc)}
    if not v:
        return res
    trc, prim = v.get("color_transfer") or "", v.get("color_primaries") or ""
    dovi = any("dovi" in (sd.get("side_data_type", "").lower() + json.dumps(sd).lower())
               or "dolby vision" in sd.get("side_data_type", "").lower() for sd in v.get("side_data_list", []) or [])
    dovi = dovi or v.get("codec_tag_string", "") in ("dvh1", "dvhe", "dav1")
    res.update({"transfer": trc, "primaries": prim, "matrix": v.get("color_space") or "",
                "range": v.get("color_range") or "", "pix_fmt": v.get("pix_fmt", ""),
                "bit_depth": 10 if "10" in v.get("pix_fmt", "") else (12 if "12" in v.get("pix_fmt", "") else 8),
                "hdr": "dovi" if dovi and trc in HDR_TRC else HDR_TRC.get(trc),
                "dolby_vision": dovi,
                "bt2020_sdr": prim == "bt2020" and trc not in HDR_TRC,
                "interlaced": (v.get("field_order") or "progressive") not in ("progressive", "unknown"),
                "field_order": v.get("field_order") or "progressive"})
    r, avg = _rate(v.get("r_frame_rate")), _rate(v.get("avg_frame_rate"))
    duration = float(doc.get("format", {}).get("duration") or v.get("duration") or 0)
    res["timing"] = "vfr" if (r and avg and abs(r - avg) > 0.01) else ("cfr" if not deep else frame_timing(path, duration))
    if deep and not res["hdr"]:
        res["log"] = log_levels(path)
    if deep:
        res["black_bars"] = black_bars(path, duration, int(v.get("width", 0)), int(v.get("height", 0)))
    return res


def analyze(path: str | Path, *, deep: bool = True) -> dict:
    p = Path(path).resolve()
    return dict(_analyze_cached(str(p), p.stat().st_mtime, deep))


def notes(a: dict) -> list[str]:
    """What the director should know about this source, one line each."""
    out = []
    if a.get("hdr"):
        out.append(f"HDR ({a['hdr'].upper()}{', Dolby Vision' if a.get('dolby_vision') else ''}): tone-mapped to SDR "
                   f"BT.709 in every render; say so if the owner wants an HDR delivery instead (youtube-hdr preset)")
    elif a.get("bt2020_sdr"):
        out.append("BT.2020 primaries on SDR: converted to BT.709 (gamut only)")
    if (a.get("log") or {}).get("looks_like_log"):
        out.append("looks like Log (flat, grey, desaturated): set the camera's conversion LUT "
                   "(`vedit footage lut <p> <source> <file.cube>`) before grading")
    if a.get("matrix") in ("smpte170m", "bt470bg") and not a.get("hdr"):
        out.append("BT.601 colour matrix: converted to BT.709 at decode (renders are tagged BT.709)")
    if a.get("interlaced"):
        out.append(f"interlaced ({a.get('field_order')}): deinterlaced (bwdif) before anything else")
    if a.get("timing") == "vfr":
        out.append("variable frame rate (phone or screen recording): conformed to the canvas rate in renders; "
                   "check lip sync on long clips")
    if a.get("black_bars"):
        b = a["black_bars"]
        out.append(f"black bars: picture is {b['w']}x{b['h']} at {b['x']},{b['y']}; crop them away with the clip's "
                   f"src_crop before reframing")
    dev = a.get("device")
    if dev:
        out.append({"iphone": "iPhone: often HDR (HLG/Dolby Vision) and variable frame rate",
                    "gopro": "GoPro: wide lens, often 2.7K/4K at 50-60 fps, sometimes HEVC; consider stabilizing",
                    "dji": "DJI: often D-Log/HLG and HEVC; 4K at high frame rates",
                    "insta360": "Insta360: 360 video needs a flat reframe (clip projection)",
                    "android": "Android phone: often variable frame rate and HDR10+",
                    "zoom": "Zoom recording: low bitrate, variable frame rate, gallery layout possible",
                    "screen": "screen recording: variable frame rate, sharp text (avoid heavy denoise and blur)"}.get(dev, dev))
    return out


# ------------------------------------------------------------------ filters

def to_sdr_chain(a: dict, *, tonemap: str = "mobius", peak: float = 100.0) -> str:
    """PQ / HLG / Dolby Vision base layer -> SDR BT.709; BT.2020 SDR -> BT.709 (gamut only).
    npl=100 puts SDR reference white at 1.0 in linear light; mobius keeps in-range material (faces, skies)
    as it is and rolls the highlights off smoothly (hable darkens everyday HDR footage noticeably)."""
    rng = a.get("range") or "tv"
    rng = "tv" if rng in ("tv", "limited", "") else "pc"
    space = a.get("matrix") or "bt2020nc"
    if a.get("hdr"):
        trc = a.get("transfer") or ("arib-std-b67" if a["hdr"] == "hlg" else "smpte2084")
        return ",".join([f"zscale=tin={trc}:pin={a.get('primaries') or 'bt2020'}:min={space}:rin={rng}:t=linear:npl={peak:g}",
                         "format=gbrpf32le", "zscale=p=bt709", f"tonemap=tonemap={tonemap}:desat=0",
                         "zscale=t=bt709:m=bt709:r=tv", "format=yuv420p"])
    if a.get("bt2020_sdr"):
        return ",".join([f"zscale=tin={a.get('transfer') or 'bt709'}:pin=bt2020:min={space}:rin={rng}:t=linear",
                         "format=gbrpf32le", "zscale=p=bt709", "zscale=t=bt709:m=bt709:r=tv", "format=yuv420p"])
    return ""


def input_chain(src, *, lut_dir: Path | None = None) -> list[str]:
    """Filters every decode of this source starts with: deinterlace, HDR -> SDR, the camera LUT."""
    a = getattr(src, "color", None) or {}
    chain: list[str] = []
    if a.get("interlaced"):
        chain.append("bwdif=mode=send_frame:deint=interlaced")
    sdr = to_sdr_chain(a)
    if sdr:
        chain.append(sdr)
    elif a.get("matrix") in ("smpte170m", "bt470bg", "fcc", "smpte240m"):
        # SD/BT.601-tagged camera files: convert the matrix, renders are tagged BT.709 (a relabel would shift hues)
        chain.append("scale=in_color_matrix=bt601:out_color_matrix=bt709,"
                     "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709")
    lut = getattr(src, "lut", None)
    if lut:
        p = Path(lut)
        if lut_dir is not None:
            import shutil
            from .util import short_hash
            local = Path(lut_dir) / ("camlut_" + short_hash(str(p)) + p.suffix)
            if not local.exists():
                shutil.copy(p, local)
            chain.append(f"lut3d=file={local.name}")
        else:
            chain.append("lut3d=file='" + p.as_posix().replace(":", "\\:") + "'")
    return chain


def summary(path: str | Path) -> dict:
    a = analyze(path)
    return {**a, "notes": notes(a)}
