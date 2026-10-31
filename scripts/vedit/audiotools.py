"""Audio tools beyond the mix: sync with clock-drift correction (external recorders, second cameras),
replacing a camera's sound with a lav/recorder track, dynamics (gate -> compressor -> limiter), stereo
widening, 5.1 downmix, extracting the sound, voice clean-up on a file.

    vedit audio sync <reference> <other> [--drift]           offset (+ drift in ppm) by cross-correlation
    vedit audio replace <video> <recorder.wav> [--drift]       the recorder's sound, aligned, on the video
    vedit audio clean <file> [--voice light|medium|strong] [--denoise]
    vedit audio dynamics <file> [--gate -45] [--compress -20:4] [--limit -1]
    vedit audio widen <file> --amount 0.5 | downmix <file> | extract <file> --out x.wav

In an edit the same processing lives in `output.audio` (`gate_db`, `compress`, `limit_db`, `widen`) and is
applied by the renderer. Approach after kajisho5/ffmpeg-skill (MIT): drift = the offset measured again
near the end of the overlap; the slower clock is resampled to the faster one.
"""

from __future__ import annotations

import math
from pathlib import Path

from .media import ffmpeg, probe
from .util import VeditError, run

VOICE = {
    "light": "highpass=f=80,acompressor=threshold=-18dB:ratio=2:attack=5:release=80:makeup=1",
    "medium": "highpass=f=80,deesser=i=0.4,afftdn=nf=-25:tn=1,acompressor=threshold=-18dB:ratio=3:attack=5:release=80:makeup=2",
    "strong": "highpass=f=80,deesser=i=0.6,afftdn=nf=-25:tn=1,acompressor=threshold=-24dB:ratio=4:attack=5:release=120:"
              "makeup=3,alimiter=limit=0.891:level=disabled",
}


def _db(x: float) -> float:
    return 10 ** (x / 20)


def dynamics_chain(*, gate_db: float | None = None, compress: str | None = None, limit_db: float | None = None,
                   widen: float | None = None) -> list[str]:
    """gate -> compressor -> limiter (-> widen). compress = "threshold_db:ratio" e.g. "-20:4"."""
    out = []
    if gate_db is not None:
        if not -90 <= gate_db <= 0:
            raise VeditError("gate threshold must be between -90 and 0 dB")
        out.append(f"agate=threshold={_db(gate_db):.6f}:ratio=4:attack=5:release=120:range={_db(-30):.4f}")
    if compress:
        thr, _, ratio = compress.partition(":")
        t, r = float(thr), float(ratio or 3)
        if not (-60 <= t <= 0 and 1 <= r <= 20):
            raise VeditError("compress wants threshold -60..0 dB and ratio 1..20, e.g. -20:4")
        out.append(f"acompressor=threshold={_db(t):.6f}:ratio={r:g}:attack=10:release=150:makeup={min(4.0, _db(-t / r / 2)):.3f}")
    if limit_db is not None:
        if not -20 <= limit_db <= 0:
            raise VeditError("limit ceiling must be between -20 and 0 dBFS")
        out.append(f"alimiter=limit={_db(limit_db):.6f}:level=disabled")
    if widen:
        out.append(f"stereowiden=delay=20:feedback=0.3:crossfeed=0.3:drymix=0.8,extrastereo=m={1 + max(0.0, min(widen, 1.0)):.2f}")
    return out


# ------------------------------------------------------------------ sync with drift

def _decode(path: str, start: float, seconds: float, sr: int = 8000):
    import subprocess

    import numpy as np
    cmd = [ffmpeg(), "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{seconds:.3f}", "-i", str(path),
           "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"]
    return np.frombuffer(subprocess.run(cmd, stdout=subprocess.PIPE).stdout, dtype=np.float32)


def _xcorr(a, b, sr: int = 8000) -> tuple[float, float]:
    """PHAT cross-correlation: lag (seconds, b relative to a) and a peak-to-sidelobe confidence."""
    import numpy as np
    if len(a) < sr or len(b) < sr:
        return 0.0, 0.0
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    fa, fb = np.fft.rfft(a - a.mean(), n), np.fft.rfft(b - b.mean(), n)
    x = np.conj(fa) * fb
    cc = np.fft.irfft(x / (np.abs(x) + 1e-9), n)
    k = int(np.argmax(cc))
    frac = 0.0
    y0, y1, y2 = cc[k - 1], cc[k], cc[(k + 1) % n]
    if (y0 - 2 * y1 + y2) != 0:                       # parabolic peak: sub-sample lag
        frac = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
    lag = (k if k < n // 2 else k - n) + frac
    guard = int(0.05 * sr)                            # the peak's own lobe (drift smears it) is not a sidelobe
    mask = np.ones(n, bool)
    idx = (np.arange(-guard, guard + 1) + k) % n
    mask[idx] = False
    side = float(np.abs(cc[mask]).max()) + 1e-12
    return lag / sr, float(cc[k]) / side


def sync(reference: str | Path, other: str | Path, *, window: float = 30.0, drift: bool = False) -> dict:
    """other_time = ref_time + offset (at ref time 0), measured on several windows across the overlap.

    Some passages correlate badly (music beds, silence, title cards), so no single window is trusted: the
    confident ones (peak-to-sidelobe >= 3) are kept and, with `drift`, a line through their offsets gives the
    clock ratio (the slope) and the offset at 0. Each measurement belongs to the middle of its window; short
    windows keep drift from smearing the peak. confidence < 3 overall: look and listen before trusting it."""
    ra, ob = probe(reference), probe(other)
    sr = 16000
    span = min(ra.duration, ob.duration)
    starts = [0.0, window * 1.5, window * 3.0]
    if drift and span > window * 6:
        starts += [span * k / 6 for k in range(2, 6)] + [max(0.0, span - window * 2.5)]
    starts = sorted({round(t, 2) for t in starts if t + window <= ra.duration})
    meas: list[tuple[float, float, float]] = []      # (ref mid time, offset, confidence)
    guess = None
    for t in starts:
        other_at = t + (guess if guess is not None else 0.0)
        if guess is None:
            lag, c = _xcorr(_decode(str(reference), t, window, sr), _decode(str(other), t, window, sr), sr)
        else:                                           # search around the known offset: a narrower, surer peak
            pad = 3.0
            lag, c = _xcorr(_decode(str(reference), t, window, sr), _decode(str(other), max(0.0, other_at - pad), window + 2 * pad, sr), sr)
            lag += max(0.0, other_at - pad) - t
        if c >= 3:
            meas.append((t + window / 2, float(lag), float(c)))
            guess = float(lag) if guess is None else guess
        if not drift and meas:
            break
    if not meas:
        lag, c = _xcorr(_decode(str(reference), 0, min(120.0, span), sr), _decode(str(other), 0, min(120.0, span), sr), sr)
        return {"offset": round(float(lag), 4), "confidence": round(float(c), 2), "drift_ppm": 0.0, "ratio": 1.0,
                "windows": 0, "note": "no window correlated clearly"}
    conf = max(m[2] for m in meas)
    if not drift or len(meas) < 2 or meas[-1][0] - meas[0][0] < 90:
        t_mid, off, _ = max(meas, key=lambda m: m[2])
        res = {"offset": round(off, 4), "confidence": round(conf, 2), "drift_ppm": 0.0, "ratio": 1.0, "windows": len(meas)}
        if drift:
            res["drift"] = "skipped: needs two clear windows at least 90 s apart"
        return res
    import numpy as np
    ts = np.array([m[0] for m in meas])
    os_ = np.array([m[1] for m in meas])
    w = np.array([m[2] for m in meas])
    slope, icept = np.polyfit(ts, os_, 1, w=w)
    resid = float(np.abs(os_ - (slope * ts + icept)).max())
    ratio = 1.0 + float(slope)
    return {"offset": round(float(icept), 4), "confidence": round(conf, 2), "drift_ppm": round(float(slope) * 1e6, 1),
            "ratio": ratio, "windows": len(meas), "fit_error_ms": round(resid * 1000, 1)}


def replace(video: str | Path, recorder: str | Path, out: str | Path, *, drift: bool = False, overwrite: bool = False) -> dict:
    """The recorder's sound on the video: aligned, drift-corrected, picture stream-copied."""
    out = Path(out)
    if out.resolve() == Path(video).resolve():
        raise VeditError("Refusing to overwrite the original.")
    if out.exists() and not overwrite:
        raise VeditError(f"{out} exists (--overwrite to replace it)")
    s = sync(video, recorder, drift=drift)
    if s["confidence"] < 3:
        raise VeditError(f"The two recordings do not line up clearly (confidence {s['confidence']}); check they "
                         "recorded the same moment.")
    vi = probe(video)
    chain = []
    if abs(s["ratio"] - 1) > 2e-6:
        # clock drift is a sample-rate error: resample (no time-stretch artefacts); the other recording's
        # (tail x ratio) seconds then play in the reference's tail seconds
        sr = probe(recorder).sample_rate or 48000
        chain.append(f"asetrate={sr * s['ratio']:.4f},aresample={sr}")
    off = s["offset"]
    pre = ["-ss", f"{off:.4f}"] if off > 0 else []
    if off < 0:
        d = int(round(-off * 1000))
        chain.append(f"adelay={d}|{d}")
    chain += ["aresample=48000", f"apad,atrim=0:{vi.duration:.4f}"]
    run([ffmpeg(), "-y", "-v", "error", "-i", str(video), *pre, "-i", str(recorder), "-map", "0:v:0", "-map", "1:a:0",
         "-af", ",".join(chain), "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-shortest", str(out)], timeout=14400)
    return {"output": str(out), **s}


# ------------------------------------------------------------------ file tools

def file_tool(tool: str, path: str | Path, *, out: str | Path | None = None, overwrite: bool = False, **kw) -> dict:
    src = Path(path).resolve()
    info = probe(src)
    if not info.has_audio:
        raise VeditError("input has no audio stream")
    ext = src.suffix if info.kind == "video" else ".wav"
    o = Path(out) if out else src.with_name(f"{src.stem}_{tool}{'.wav' if tool == 'extract' else ext}")
    if o.resolve() == src:
        raise VeditError("Refusing to overwrite the original.")
    if o.exists() and not overwrite:
        raise VeditError(f"{o} exists (--overwrite to replace it)")
    af: list[str] = []
    if tool == "clean":
        af.append(VOICE[kw.get("voice") or "medium"])
        if kw.get("denoise") and "afftdn" not in af[0]:
            af.append("afftdn=nf=-25:tn=1")
    elif tool == "dynamics":
        af += dynamics_chain(gate_db=kw.get("gate"), compress=kw.get("compress"), limit_db=kw.get("limit"))
    elif tool == "widen":
        af += dynamics_chain(widen=float(kw.get("amount") or 0.5))
    elif tool == "downmix":
        af.append("pan=stereo|FL=0.5*FL+0.354*FC+0.354*BL+0.25*LFE|FR=0.5*FR+0.354*FC+0.354*BR+0.25*LFE")
    elif tool != "extract":
        raise VeditError(f"Unknown audio tool '{tool}'")
    if not af and tool != "extract":
        raise VeditError("Nothing to do: give at least one option")
    args = [ffmpeg(), "-y", "-v", "error", "-i", str(src)]
    if tool == "extract" or o.suffix.lower() in (".wav", ".flac", ".m4a", ".mp3"):
        args += ["-vn"] + (["-af", ",".join(af)] if af else []) + (["-c:a", "pcm_s24le"] if o.suffix.lower() == ".wav" else [])
    else:
        args += ["-map", "0:v?", "-map", "0:a:0", "-c:v", "copy", "-af", ",".join(af), "-c:a", "aac", "-b:a", "256k"]
    run(args + [str(o)], timeout=14400)
    return {"output": str(o), "filters": af, "duration": round(probe(o).duration, 3)}


def speech_aware_keeps(source_id: str, transcript_path: str, *, max_pause: float = 0.6, long_pause: float = 1.5,
                       drop_fillers: bool = True, min_keep: float = 0.4) -> list[dict]:
    """Rough cut that never cuts inside a sentence: a pause is cut only after a word that ends a sentence
    (. ! ? ।) and lasts more than `max_pause`, or anywhere it lasts more than `long_pause`."""
    from .captions import PUNCT_END, transcript_words
    from .cuts import HARD_FILLERS, _norm
    words = transcript_words(transcript_path)
    if drop_fillers:
        words = [w for w in words if _norm(w["w"]) not in HARD_FILLERS]
    keeps: list[dict] = []
    cur = None
    prev = None
    for w in words:
        if cur is None:
            cur = [w["s"], w["e"]]
        else:
            gap = w["s"] - cur[1]
            boundary = bool(prev and PUNCT_END.search(prev["w"].strip()))
            if (boundary and gap > max_pause) or gap > long_pause:
                if cur[1] - cur[0] >= min_keep:
                    keeps.append({"source": source_id, "from": cur[0], "to": cur[1]})
                cur = [w["s"], w["e"]]
            else:
                cur[1] = w["e"]
        prev = w
    if cur and cur[1] - cur[0] >= min_keep:
        keeps.append({"source": source_id, "from": cur[0], "to": cur[1]})
    return keeps


def clock_note(res: dict) -> str:
    if not res.get("drift_ppm"):
        return ""
    per_hour = res["drift_ppm"] * 3.6 / 1000
    return f"{res['drift_ppm']:+.1f} ppm = {per_hour:+.2f} s per hour" if math.isfinite(per_hour) else ""
