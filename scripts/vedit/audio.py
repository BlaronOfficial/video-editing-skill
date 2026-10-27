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
    tmp = cache_dir() / "audio" / (Path(path).stem + f".{sr}.wav")
    if not tmp.exists() or tmp.stat().st_mtime < Path(path).stat().st_mtime:
        extract_audio(path, tmp, sample_rate=sr)
    with wave.open(str(tmp), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return data


def beats(path: str | Path, *, sr: int = 22050) -> dict:
    """Tempo + beat times via spectral-flux onsets and autocorrelation (no heavy deps)."""
    y = load_mono(path, sr)
    hop, win = 512, 2048
    if len(y) < win * 4:
        return {"bpm": None, "beats": [], "onsets": []}
    frames = np.lib.stride_tricks.sliding_window_view(y, win)[::hop] * np.hanning(win)
    mag = np.abs(np.fft.rfft(frames, axis=1))
    flux = np.maximum(0, np.diff(np.log1p(mag), axis=0)).sum(axis=1)
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    fps = sr / hop
    # tempo: autocorrelation peak between 70 and 180 BPM
    ac = np.correlate(flux, flux, mode="full")[len(flux) - 1:]
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 70)
    lag = lo + int(np.argmax(ac[lo:hi])) if hi > lo else lo
    bpm = 60 * fps / lag if lag else None
    # beat phase: offset maximising flux on the grid
    period = lag
    best = max(range(period), key=lambda o: flux[o::period].sum()) if period else 0
    beat_frames = np.arange(best, len(flux), period)
    onset_frames = np.where((flux[1:-1] > flux[:-2]) & (flux[1:-1] >= flux[2:]) & (flux[1:-1] > 1.5))[0] + 1
    return {"bpm": round(float(bpm), 1) if bpm else None,
            "beats": [round(float(f / fps), 3) for f in beat_frames],
            "onsets": [round(float(f / fps), 3) for f in onset_frames][:2000]}


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
