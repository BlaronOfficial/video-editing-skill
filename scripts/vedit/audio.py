"""Audio analysis (beats, energy, speech regions) and procedural SFX synthesis.

Beat times let Claude cut b-roll and land graphics on the music; procedural SFX give every edit
whooshes/pops/risers even with an empty asset library (library or CapCut SFX are still preferred
when they sound better).
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .media import extract_audio

SR = 48000


def load_mono(path: str | Path, sr: int = 22050) -> np.ndarray:
    from .paths import cache_dir
    from .util import short_hash
    src = Path(path)
    # the cache name carries the full path: two "track.wav" files in different folders must not share one
    tmp = cache_dir() / "audio" / f"{src.stem}.{short_hash(str(src.resolve()), length=8)}.{sr}.wav"
    if not tmp.exists() or tmp.stat().st_mtime < src.stat().st_mtime:
        extract_audio(path, tmp, sample_rate=sr)
    with wave.open(str(tmp), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return data


# ------------------------------------------------------------------ beat map
# Method adapted from animate (MIT, (c) 2026 cth9191), tools/beats.mjs: log spectral flux -> tempo candidates by
# autocorrelation plus their metrical relatives -> each refined (+-2%) by a beat comb over the whole track ->
# phase -> bars from the low band. Added here: a weighted fit of the grid to the onsets themselves, so a
# constant-tempo grid stays on the beat to the end (the old integer-lag grid read a 120 BPM track as 117.5 and
# was a whole beat late after 29 s).

_NFFT, _HOP = 1024, 256
_LAT = 0.0345                   # onset-frame time -> attack time (measured: clicks 35.0 ms, drum loops 33.3-34.0 ms)


def _flux(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per hop: log-magnitude spectral flux (onset strength), its low band (<= 150 Hz: the kick), and a
    linear-magnitude flux below 5 kHz that keeps loudness differences (a hi-hat stays quieter than a snare)."""
    n = max(0, (len(y) - _NFFT) // _HOP + 1)
    onset, low, lin = np.zeros(n, np.float32), np.zeros(n, np.float32), np.zeros(n, np.float32)
    if not n:
        return onset, low, lin
    win = np.hanning(_NFFT).astype(np.float32)
    low_bin = max(1, round(150 / (sr / _NFFT)))
    mid_bin = max(low_bin + 1, round(5000 / (sr / _NFFT)))
    view = np.lib.stride_tricks.sliding_window_view(y, _NFFT)[::_HOP]
    prev = prev_lin = None
    for a in range(0, n, 2048):                       # chunks keep memory flat on long tracks
        spec = np.abs(np.fft.rfft(view[a:a + 2048] * win, axis=1)[:, 1:_NFFT // 2]).astype(np.float32)
        mag = np.log1p(100 * spec)
        d = np.maximum(np.diff(mag, axis=0, prepend=mag[:1] if prev is None else prev[None, :]), 0)
        onset[a:a + len(mag)] = d.sum(axis=1)
        low[a:a + len(mag)] = d[:, :low_bin].sum(axis=1)
        sl = spec[:, :mid_bin]
        lin[a:a + len(mag)] = np.maximum(np.diff(sl, axis=0, prepend=sl[:1] if prev_lin is None else prev_lin[None, :]), 0).sum(axis=1)
        prev, prev_lin = mag[-1], sl[-1]
    return onset, low, lin


def _max3(a: np.ndarray) -> np.ndarray:
    """Each value's maximum over +-1 frame (a beat tooth takes the strongest onset next to it)."""
    return np.maximum(a, np.maximum(np.r_[a[:1], a[:-1]], np.r_[a[1:], a[-1:]]))


def _comb(env3: np.ndarray, fps: float, per: float, phases: np.ndarray) -> np.ndarray:
    """Mean onset strength on the grid `phase + k * period` over the whole track, for each phase."""
    k = np.arange(int(len(env3) / fps / per) + 1)
    idx = np.rint((phases[:, None] + k[None, :] * per) * fps).astype(np.int64)
    ok = idx < len(env3)
    vals = np.where(ok, env3[np.minimum(idx, len(env3) - 1)], 0.0)
    return vals.sum(axis=1) / np.maximum(1, ok.sum(axis=1))


def _fit_grid(env: np.ndarray, fps: float, o: float, per: float) -> tuple[float, float]:
    """Refine phase and period by a weighted least-squares fit of the observed onset peaks to the grid."""
    thr = float(env.mean() + 0.5 * env.std())
    for _ in range(3):
        ks, ts, ws = [], [], []
        for k in range(int((len(env) / fps - o) / per) + 1):
            i = int(round((o + k * per) * fps))
            lo, hi = max(1, i - 2), min(len(env) - 2, i + 2)
            if hi < lo:
                continue
            j = lo + int(np.argmax(env[lo:hi + 1]))
            if env[j] < thr:
                continue
            a, b, c = float(env[j - 1]), float(env[j]), float(env[j + 1])
            den = a - 2 * b + c
            ks.append(k)
            ts.append((j + (0.5 * (a - c) / den if den else 0.0)) / fps)   # parabolic peak
            ws.append(b)
        if len(ks) < 8:
            break
        w = np.sqrt(np.asarray(ws))
        K = np.asarray(ks, float)
        sol, *_ = np.linalg.lstsq(np.vstack([np.ones_like(K), K]).T * w[:, None], np.asarray(ts) * w, rcond=None)
        o2, per2 = float(sol[0]), float(sol[1])
        if per2 <= 0 or abs(per2 - per) / per > 0.005:
            break
        o, per = o2 % per2, per2
    return o, per


def beats(path: str | Path, *, sr: int = 22050, start: float = 0.0, dur: float | None = None,
          bpm: float | str | None = None) -> dict:
    """Beat map of a music track: tempo, a beat grid that stays on the beat, bars, the big hits, the loudest
    moment and the drops. Times are seconds into the used window (`start`, `dur`). Constant tempo is assumed
    (most pop, electronic and library music); `bpm` = a known tempo (refined +-0.2%) or a range "70-180".
    """
    y = load_mono(path, sr)
    y = y[int(start * sr):] if not dur else y[int(start * sr):int((start + dur) * sr)]
    dur_s = len(y) / sr
    out: dict = {"source": Path(path).name, "start": round(float(start), 3), "duration": round(dur_s, 3),
                 "bpm": None, "beats": [], "downbeats": [], "onsets": [], "hits": []}
    if dur_s < 4.0:
        return out
    onset, low, lin = _flux(y, sr)
    fps = sr / _HOP
    r = max(1, round(0.186 * fps))
    env = np.maximum(0, onset - np.convolve(onset, np.ones(2 * r + 1) / (2 * r + 1), mode="same")).astype(np.float64)
    env3 = _max3(env)
    if isinstance(bpm, str) and "-" in bpm:
        bmin, bmax = (float(v) for v in bpm.split("-", 1))
        known = None
    else:
        known = float(bpm) if bpm else None
        bmin, bmax = (known, known) if known else (70.0, 180.0)

    # tempo candidates: peaks of the onset autocorrelation (fractional lags), plus their metrical relatives
    def ac_at(b: float) -> float:
        lag = 60.0 / b * fps
        i = np.arange(int(np.ceil(lag)), len(env))
        if not len(i):
            return 0.0
        j = i - lag
        j0 = np.floor(j).astype(np.int64)
        fr = j - j0
        return float(np.sum(env[i] * (env[j0] * (1 - fr) + env[np.minimum(j0 + 1, len(env) - 1)] * fr)) / len(i))

    if known:
        cands = {known}
    else:
        grid = [(b, ac_at(b)) for b in np.arange(bmin, bmax + 1e-9, 0.5)]
        peaks = sorted((g for i, g in enumerate(grid) if 0 < i < len(grid) - 1
                        and g[1] >= grid[i - 1][1] and g[1] >= grid[i + 1][1]), key=lambda g: -g[1])[:5]
        cands = set() if peaks else {round((bmin + bmax) / 2 * 4) / 4}
        for b, _ in peaks:
            for m in (1, 2, 0.5, 1.5, 2 / 3, 4 / 3, 0.75):
                if bmin <= b * m <= bmax:
                    cands.add(round(b * m * 4) / 4)

    def prior(b: float) -> float:
        return float(np.exp(-0.5 * (np.log2(b / 120.0) / 0.6) ** 2))   # tempo prior around 120 BPM

    rw = 0.002 if known else 0.02
    scored = []
    for b0 in sorted(cands):
        best = (0.0, b0, 0.0)
        for b in np.arange(b0 * (1 - rw), b0 * (1 + rw) + 1e-9, 0.05 if not known else 0.01):
            per = 60.0 / b
            ph = np.arange(0, per, 1 / fps / 2)
            sc = _comb(env3, fps, per, ph)
            i = int(np.argmax(sc))
            if sc[i] > best[0]:
                best = (float(sc[i]), float(b), float(ph[i]))
        s, b1, o1 = best                               # fine pass around the coarse winner
        for b in np.arange(b1 - 0.06, b1 + 0.06 + 1e-9, 0.005):
            per = 60.0 / b
            ph = (o1 + np.arange(-1 / fps, 1 / fps + 1e-9, 1 / fps / 8)) % per
            sc = _comb(env3, fps, per, ph)
            i = int(np.argmax(sc))
            if sc[i] > s:
                s, b1, o1 = float(sc[i]), float(b), float(ph[i])
        scored.append({"bpm": b1, "o": o1, "s": s, "score": s * prior(b1)})
    scored.sort(key=lambda c: -c["score"])
    top = dict(scored[0])
    # double time: when the teeth between the beats are about as loud (snares between kicks, every click of a
    # fast track), the faster grid is the beat; the tempo prior alone would pick the half-time reading. Judged
    # on the linear flux: on the log flux, off-beat hi-hats look as strong as the drums.
    if not known and top["bpm"] * 2 <= bmax:
        lin3 = _max3(lin.astype(np.float64))
        per1, per2 = 60.0 / top["bpm"], 30.0 / top["bpm"]
        on = float(_comb(lin3, fps, per1, np.array([top["o"]]))[0])
        mid = float(_comb(lin3, fps, per1, np.array([(top["o"] + per2) % per1]))[0])
        if on > 0 and mid >= 0.8 * on:
            ph2 = (top["o"] + np.arange(-1 / fps, 1 / fps + 1e-9, 1 / fps / 8)) % per2
            s2 = _comb(env3, fps, per2, ph2)
            top = {"bpm": top["bpm"] * 2, "o": float(ph2[int(np.argmax(s2))]), "s": float(s2.max()), "score": top["score"]}
            scored.insert(0, top)
    o, per = _fit_grid(env, fps, top["o"], 60.0 / top["bpm"])
    o = (o + _LAT) % per
    beat_t = np.arange(o, dur_s - 1e-6, per)

    # bars: of the 4 beat phases, the one with the most low-band (kick) energy starts the bar. A kick's low band
    # builds up over a few hops, so each beat sums the 50 ms after it.
    lowc = np.convolve(low.astype(np.float64), np.ones(6), mode="full")[5:5 + len(low)]   # sum of frames i..i+5
    idx = np.clip(np.rint((beat_t - _LAT) * fps).astype(np.int64) - 1, 0, len(lowc) - 1)
    bar = int(np.argmax([lowc[idx[k::4]].sum() for k in range(4)])) if len(idx) >= 8 else 0
    downbeats = beat_t[bar::4]

    # how many beats have a real onset on them (the grid's confidence)
    thr1 = env.mean() + env.std()
    eidx = np.clip(np.rint((beat_t - _LAT) * fps).astype(np.int64), 0, len(env3) - 1)
    confidence = float(np.mean(_max3(env3)[eidx] > thr1)) if len(eidx) else 0.0

    # hits (the strongest onsets, >= 0.4 s apart) and onsets
    mean, sd = float(env.mean()), float(env.std())
    is_peak = np.r_[False, (env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]), False]
    pk = np.where(is_peak & (env > mean + 2.5 * sd))[0]
    hits: list[float] = []
    for i in pk[np.argsort(-env[pk])]:
        t = i / fps + _LAT
        if all(abs(t - h) > 0.4 for h in hits):
            hits.append(t)
        if len(hits) >= 64:
            break
    onsets = (np.where(is_peak & (env > mean + 1.5 * sd))[0] / fps + _LAT)[:2000]

    # loudness per 100 ms: the loudest moment, and the drops (>= 0.5 s at 15 dB under the median)
    blk = sr // 10
    nb = len(y) // blk
    db = 10 * np.log10(np.mean(y[:nb * blk].reshape(nb, blk).astype(np.float64) ** 2, axis=1) + 1e-12)
    med = float(np.median(db))
    loud = int(np.argmax(db))
    quiet, q0 = [], -1
    for i, v in enumerate(list(db) + [med]):
        if v < med - 15:
            q0 = i if q0 < 0 else q0
        else:
            if q0 >= 0 and i - q0 >= 5:
                quiet.append([round(q0 / 10, 1), round(i / 10, 1)])
            q0 = -1

    out.update({
        "bpm": round(60.0 / per, 2), "period": round(per, 5), "offset": round(float(o), 4),
        "beats": [round(float(t), 3) for t in beat_t],
        "downbeats": [round(float(t), 3) for t in downbeats], "beats_per_bar": 4,
        "hits": sorted(round(float(t), 3) for t in hits),
        "loudest": {"t": round(loud / 10, 1), "db": round(float(db[loud]), 1)},
        "quiet": quiet,
        "onsets": [round(float(t), 3) for t in onsets],
        "confidence": round(confidence, 2),
        "other_tempos": [{"bpm": round(c["bpm"], 2), "score": round(c["score"] / top["score"], 2)}
                         for c in scored[1:4]],
    })
    return out


def energy_curve(path: str | Path, *, step: float = 0.5) -> list[tuple[float, float]]:
    """RMS loudness (dBFS) per step; highlights loud/energetic moments for shorts selection."""
    y = load_mono(path, 16000)
    n = int(16000 * step)
    out = []
    for i in range(0, len(y) - n, n):
        rms = float(np.sqrt(np.mean(y[i:i + n] ** 2)) + 1e-9)
        out.append((round(i / 16000, 2), round(20 * np.log10(rms), 1)))
    return out


# ------------------------------------------------------------------ procedural SFX

def _env(n: int, attack: float, release: float, sr: int = SR) -> np.ndarray:
    a = max(1, int(attack * sr))
    r = max(1, int(release * sr))
    e = np.ones(n)
    e[:a] = np.linspace(0, 1, a) ** 2
    e[-r:] *= np.linspace(1, 0, r) ** 2
    return e


def _noise(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n)


def _lowpass_sweep(x: np.ndarray, f0: float, f1: float, sr: int = SR) -> np.ndarray:
    """One-pole low-pass with a cutoff sweep (cheap, smooth)."""
    out = np.empty_like(x)
    fc = np.geomspace(max(f0, 20), max(f1, 20), len(x))
    alpha = 1 - np.exp(-2 * np.pi * fc / sr)
    acc = 0.0
    for i, v in enumerate(x):
        acc += alpha[i] * (v - acc)
        out[i] = acc
    return out


def synth(kind: str, *, duration: float | None = None, seed: int = 3, pitch: float = 1.0) -> np.ndarray:
    kinds = {"whoosh": 0.6, "swoosh_up": 0.7, "pop": 0.12, "click": 0.05, "riser": 2.0, "impact": 1.2, "glitch": 0.35,
             "ding": 0.9, "swipe": 0.25, "bass_drop": 1.4, "tick": 0.04, "shutter": 0.18}
    if kind not in kinds:
        raise ValueError(f"unknown sfx '{kind}'. Options: {', '.join(kinds)}")
    d = duration or kinds[kind]
    n = int(d * SR)
    t = np.arange(n) / SR
    if kind in ("whoosh", "swipe"):
        x = _lowpass_sweep(_noise(n, seed), 300 * pitch, 6000 * pitch) * np.sin(np.pi * t / d) ** 2
    elif kind == "swoosh_up":
        x = _lowpass_sweep(_noise(n, seed), 200 * pitch, 9000 * pitch) * (t / d) ** 1.5 * _env(n, 0.01, 0.08)
    elif kind == "pop":
        f = 900 * pitch * np.exp(-t * 30)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 40)
    elif kind in ("click", "tick"):
        x = _noise(n, seed) * np.exp(-t * (300 if kind == "click" else 500)) + np.sin(2 * np.pi * 2500 * pitch * t) * np.exp(-t * 200)
    elif kind == "riser":
        f = np.geomspace(150 * pitch, 1800 * pitch, n)
        x = 0.5 * np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.5 * _lowpass_sweep(_noise(n, seed), 200, 8000)
        x *= (t / d) ** 2 * _env(n, 0.01, 0.03)
    elif kind in ("impact", "bass_drop"):
        f = (120 if kind == "impact" else 90) * pitch * np.exp(-t * (6 if kind == "impact" else 2.5)) + 35
        body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * (4 if kind == "impact" else 1.8))
        crack = _noise(n, seed) * np.exp(-t * 35) * 0.6
        x = np.tanh(2.2 * (body + crack))
    elif kind == "glitch":
        x = np.sign(np.sin(2 * np.pi * 180 * pitch * t)) * (np.random.default_rng(seed).random(n) > 0.6) * 0.6
        x += np.sin(2 * np.pi * 1200 * pitch * t * (1 + 0.5 * np.sin(2 * np.pi * 23 * t))) * 0.3
        x *= _env(n, 0.002, 0.05)
    elif kind == "ding":
        x = sum(np.sin(2 * np.pi * f * pitch * t) * np.exp(-t * k) * a for f, k, a in ((1320, 4, 0.6), (2640, 7, 0.25), (3960, 10, 0.1)))
    elif kind == "shutter":
        x = _noise(n, seed) * (np.exp(-t * 60) + 0.7 * np.exp(-np.maximum(0, t - 0.09) * 70) * (t > 0.09))
    else:  # pragma: no cover
        x = np.zeros(n)
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.89
    return x.astype(np.float32)


def write_wav(samples: np.ndarray, path: str | Path, sr: int = SR) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stereo = np.repeat((np.clip(samples, -1, 1) * 32767).astype(np.int16)[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(stereo.tobytes())
    return path
