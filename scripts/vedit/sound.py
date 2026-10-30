"""Sound design: kits of sound effects placed on cues with measured sync points (earshot), plus listening checks.

A *kit* names one sound per role (pop, whoosh.short, hit, tick, ...). With earshot installed
(`vedit setup earshot`) the takes come from its 252-sound bank, rendered in code with measured onset / peak /
end; without it the built-in synth (audio.synth) makes a smaller kit in the same format, so the core stays
standalone. A *cue* is a moment that wants a sound (a graphic landing, a transition, an emphasised word);
`cues()` proposes them from the edit and Claude edits the list. `place()` turns cues into AudioClips:

  * the take's sync point (onset, or peak for whooshes) lands on the cue, shifted by the role's offset_ms
    (taps lead the cut, pop-in thumps land just after);
  * each clip is anchored to the source moment under the cue, so re-cuts and the pace knob keep it in sync;
  * level: the take's loudest 50 ms (K-weighted) is set bed_db over the music bed before the cue (earshot's
    model), or against the voice when there is no music, never over a -1 dBFS peak;
  * takes rotate so repeats never sound identical; runs keep the role's min_gap_ms;
  * big hits get a music stop-down (the bed dips before the hit and comes back on it) instead of ducking.

Listening: `check()` finds the event that answers every placed cue in the render (earshot's model-free
detector, or a simple onset search) and reports the offset; with earshot's ears installed QA also writes
earshot's timeline, sheet and critique.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

from . import addons
from .media import ffmpeg
from .paths import SKILL_ROOT, cache_dir, personal_dir
from .timeline import Anchor, AudioClip, Edit, SfxRef, Source
from .util import VeditError, read_json, run, write_json

SR = 48000
BED_SR = 24000
CEILING_DB = -1.0
BED_FLOOR_LUFS = -60.0
VOICE_REL_DB = -10.0          # without music: an effect's loudest 50 ms sits (bed_db - 10) dB against the voice
DEFAULT_DENSITY = 8.0         # cues per 10 s (voice-led edits; earshot measured 3-13 for music-led films)
ALIGN = {"whoosh.short": "peak", "whoosh.long": "peak", "suck": "end", "riser": "end", "swell": "end"}
FALLBACK = {                  # role -> roles to try when the kit leaves it off
    "whoosh.long": ["whoosh.short"], "whoosh.short": ["whoosh.long", "snap"], "hit": ["drop", "land"],
    "drop": ["hit", "land"], "riser": ["swell", "whoosh.long", "whoosh.short"], "swell": ["riser", "whoosh.long"],
    "suck": ["whoosh.short"], "snap": ["click", "tick"], "click.confirm": ["bell", "pop"], "land.light": ["land", "pop"],
    "land": ["pop", "hit"], "tick.crisp": ["tick"], "tock": ["tick", "click"], "text": ["tick", "pop"],
    "key": ["click", "tick"], "bell": ["click.confirm", "pop"], "pop": ["land", "click"], "tick": ["click", "pop"],
    "click": ["tick", "pop"],
}
PRIORITY = {"hit": 5, "drop": 5, "riser": 5, "swell": 5, "whoosh.long": 4, "land": 4, "whoosh.short": 3, "pop": 3,
            "snap": 3, "click.confirm": 3, "bell": 2, "click": 2, "tock": 2, "text": 1, "tick": 1, "tick.crisp": 1,
            "key": 1, "land.light": 2, "suck": 3}
TEMPLATE_ROLE = {
    "title_card": "whoosh.long", "chapter_title": "whoosh.long", "logo_sting": "hit", "text_punch": "land",
    "kinetic_text": "whoosh.short", "lower_third": "whoosh.short", "callout": "whoosh.short",
    "highlight_box": "whoosh.short", "quote_card": "whoosh.short", "shape_wipe": "whoosh.short",
    "emoji_pop": "pop", "list_reveal": "pop", "bar_chart": "pop", "notification": "click.confirm",
    "subscribe_cta": "click", "counter": "tick", "countdown": "tick", "progress_bar": "tick", "thumbnail": None,
}
EFFECT_ROLE = {"flash": "hit", "shake": "drop", "zoom_pulse": "land", "glitch": "snap", "rgb_split": "snap"}
SOFT_TRANSITIONS = {"fade", "dissolve", "crossfade", "fade_black", "fadeblack"}

# built-in synth kit (no earshot): role -> (audio.synth kind, pitch, duration)
SYNTH_ROLES = {
    "tick": ("tick", 1.0, None), "tick.crisp": ("tick", 1.35, None), "tock": ("click", 0.55, None),
    "hit": ("impact", 1.0, 0.9), "drop": ("bass_drop", 1.0, 1.0), "land": ("pop", 0.45, 0.16),
    "land.light": ("click", 0.5, None), "pop": ("pop", 1.0, None), "whoosh.short": ("whoosh", 1.0, 0.42),
    "whoosh.long": ("whoosh", 0.8, 0.9), "riser": ("riser", 1.0, 1.4), "swell": ("swoosh_up", 0.9, 0.9),
    "key": ("click", 1.2, None), "click": ("click", 1.0, None), "click.confirm": ("ding", 1.0, 0.6),
    "snap": ("shutter", 1.0, None), "bell": ("ding", 1.0, 0.8), "text": ("tick", 0.8, None),
}
SYNTH_LEVEL = {"hit": -6, "drop": -7, "riser": -6, "swell": -7, "whoosh.long": -6, "whoosh.short": -6, "land": -6,
               "pop": -8, "snap": -9, "click.confirm": -9, "bell": -10, "click": -10, "tock": -9, "key": -11,
               "tick": -12, "tick.crisp": -13, "land.light": -11, "text": -15}


# ------------------------------------------------------------------ earshot (isolated tool venv)

def earshot_python() -> Path | None:
    return addons.tool_python("earshot")


def ears_installed() -> bool:
    return addons._earshot_ears()[0] and earshot_python() is not None


def _earshot_env() -> dict:
    env = dict(os.environ)
    env["EARSHOT_HOME"] = str(cache_dir() / "earshot")
    env["PYTHONUTF8"] = "1"
    if not ears_installed():
        env["EARSHOT_OFFLINE"] = "1"      # never let a kit command start a 1 GB model download on its own
    from .media import ffmpeg as _ff, ffprobe as _fp
    env["PATH"] = os.pathsep.join([str(Path(_ff()).parent), str(Path(_fp()).parent), env.get("PATH", "")])
    return env


def earshot(*args: str, timeout: float = 3600, cwd: Path | None = None) -> dict | str:
    """Run the earshot CLI in its venv; `--json` results come back parsed."""
    py = earshot_python()
    if not py:
        raise VeditError("earshot is not installed: `vedit setup earshot` (~70 MB, no models).")
    proc = run([py, "-I", "-m", "earshot", *args], check=False, timeout=timeout, cwd=cwd, env=_earshot_env())
    if proc.returncode != 0:
        raise VeditError(f"earshot {args[0]} failed: {(proc.stderr or proc.stdout or '')[-1500:]}")
    out = proc.stdout or ""
    if "--json" in args:
        start = out.find("{")
        return json.loads(out[start:]) if start >= 0 else {}
    return out


def bridge(command: str, payload: dict, timeout: float = 1800) -> dict:
    """Model-free earshot analysis through scripts/vedit/earshot_bridge.py (runs in the earshot venv)."""
    py = earshot_python()
    if not py:
        raise VeditError("earshot is not installed")
    work = cache_dir() / "earshot" / "bridge"
    work.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
    req, out = work / f"{command}_{key}.in.json", work / f"{command}_{key}.out.json"
    write_json(req, payload)
    script = Path(__file__).with_name("earshot_bridge.py")
    run([py, "-I", script, command, req, out], timeout=timeout, env=_earshot_env())
    return read_json(out) or {}


def setup(ears: bool = False) -> dict:
    """Install earshot into .cache/tools/earshot (kits: numpy/scipy only; --ears adds torch CPU + models)."""
    uv = shutil.which("uv")
    if not uv:
        raise VeditError("uv is required (https://docs.astral.sh/uv/)")
    home = cache_dir() / "tools" / "earshot"
    venv = home / "venv"
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        run([uv, "venv", "--python", "3.12", str(venv)], timeout=900)
    pin = "earshot @ git+https://github.com/Leonxlnx/earshot@591fa3e028032e6dce56620a20e932e35667e8d8"   # v0.4.0
    run([uv, "pip", "install", "--python", str(py), "--no-deps", pin], timeout=1800)
    run([uv, "pip", "install", "--python", str(py), "numpy>=1.26", "scipy>=1.11", "soundfile>=0.12", "soxr>=0.3",
         "pyloudnorm>=0.1", "pillow>=10", "matplotlib>=3.8"], timeout=3600)
    out = {"venv": str(venv), "kits": True, "ears": False}
    if ears:
        run([uv, "pip", "install", "--python", str(py), "torch>=2.6", "--index-url",
             "https://download.pytorch.org/whl/cpu"], timeout=7200)
        run([uv, "pip", "install", "--python", str(py), "transformers>=4.40", "librosa>=0.10",
             "scikit-learn>=1.3"], timeout=3600)
        env = _earshot_env()
        env.pop("EARSHOT_OFFLINE", None)
        run([py, "-I", "-m", "earshot", "doctor", "--fetch"], timeout=14400, env=env)
        out["ears"] = True
    bank()           # cache the bank listing for `vedit sound find`
    return out


# ------------------------------------------------------------------ bank and kits

def bank(refresh: bool = False) -> list[dict]:
    """earshot's sound bank (ids, categories, kinds, notes), cached; [] without earshot."""
    path = cache_dir() / "earshot" / "bank.json"
    if path.exists() and not refresh:
        return read_json(path) or []
    if not earshot_python():
        return []
    sounds = earshot("sfx", "list", "--json").get("sounds", [])
    write_json(path, sounds)
    return sounds


def kit_presets() -> list[dict]:
    """Kits: earshot presets (calm, crisp, minimal, launch), personal kits, and the built-in synth kit."""
    out = []
    py = earshot_python()
    if py:
        kits_dir = py.parent.parent / "Lib" / "site-packages" / "earshot" / "forge" / "kits"
        if not kits_dir.exists():
            kits_dir = next(iter(py.parent.parent.glob("lib/python*/site-packages/earshot/forge/kits")), kits_dir)
        for f in sorted(kits_dir.glob("*.json")):
            doc = read_json(f) or {}
            out.append({"name": f.stem, "source": "earshot", "note": (doc.get("note") or "")[:160],
                        "roles": sorted(r for r, v in (doc.get("roles") or {}).items() if v)})
    for f in sorted((personal_dir() / "sound" / "kits").glob("*.json")):
        doc = read_json(f) or {}
        out.append({"name": f.stem, "source": "personal", "note": (doc.get("note") or "")[:160],
                    "roles": sorted(r for r, v in (doc.get("roles") or {}).items() if v)})
    out.append({"name": "synth", "source": "built-in", "note": "procedural fallback (no earshot)",
                "roles": sorted(SYNTH_ROLES)})
    return out


def default_kit(style: str | None = None) -> str:
    if not earshot_python():
        return "synth"
    calm_styles = {"cinematic", "documentary", "calm", "minimal", "aesthetic", "vlog", "cool_girl"}
    return "calm" if (style or "").lower() in calm_styles else "crisp"


def kit_dir(name: str) -> Path:
    return cache_dir() / "sound" / "kits" / re.sub(r"[^\w.-]", "_", name)


def ensure_kit(name: str, *, force: bool = False) -> dict:
    """Render a kit once (cached) and return its lock: roles -> takes with onset_s / peak_s / end_s."""
    if name == "synth":
        return _synth_kit(force=force)
    out = kit_dir(name)
    lock_path = out / "takes" / "kit.lock.json"
    personal = personal_dir() / "sound" / "kits" / f"{name}.json"
    if lock_path.exists() and not force and not (personal.exists() and personal.stat().st_mtime > lock_path.stat().st_mtime):
        return _with_dir(read_json(lock_path), out / "takes")
    if not earshot_python():
        raise VeditError(f"kit '{name}' needs earshot (`vedit setup earshot`); the 'synth' kit works without it")
    out.mkdir(parents=True, exist_ok=True)
    kit_json = out / "kit.json"
    if personal.exists():
        shutil.copy(personal, kit_json)
    else:
        earshot("kit", "init", "--preset", name, "-o", str(kit_json), "--force")
    args = ["kit", "render", str(kit_json), "--out", str(out / "takes"), "--json"] + (["--force"] if force else [])
    earshot(*args, timeout=3600)
    return _with_dir(read_json(lock_path), out / "takes")


def _with_dir(lock: dict, takes: Path) -> dict:
    lock = dict(lock or {})
    lock["dir"] = str(takes)
    kit_json = takes.parent / "kit.json"
    if kit_json.exists() and "mix" not in lock:
        lock["mix"] = (read_json(kit_json) or {}).get("mix")
    return lock


def _measure(x: np.ndarray, sr: int = SR) -> dict:
    """onset / peak / end of a take (the points a kit lock carries)."""
    a = np.abs(x)
    win = max(1, int(0.005 * sr))
    env = np.convolve(a, np.ones(win) / win, mode="same")
    peak_i = int(np.argmax(env))
    top = env[peak_i] + 1e-12
    onset_i = int(np.argmax(env >= 0.1 * top))
    above = np.where(env >= top * 10 ** (-50 / 20))[0]
    end_i = int(above[-1]) if len(above) else len(x) - 1
    return {"onset_s": round(onset_i / sr, 4), "peak_s": round(peak_i / sr, 4), "end_s": round(end_i / sr, 4),
            "dur_s": round(len(x) / sr, 4), "peak_db": round(float(20 * np.log10(a.max() + 1e-12)), 2)}


def _synth_kit(force: bool = False) -> dict:
    from .audio import synth, write_wav
    out = kit_dir("synth") / "takes"
    lock_path = out / "kit.lock.json"
    if lock_path.exists() and not force:
        return _with_dir(read_json(lock_path), out)
    out.mkdir(parents=True, exist_ok=True)
    roles = {}
    for role, (kind, pitch, dur) in SYNTH_ROLES.items():
        takes = []
        for k, seed in enumerate((3, 11, 29), start=1):
            x = synth(kind, duration=dur, seed=seed, pitch=pitch * (1 + 0.03 * (k - 2)))
            name = f"{role.replace('.', '-')}_{k}.wav"
            write_wav(x, out / name)
            takes.append({"file": name, "seed": seed, **_measure(x)})
        roles[role] = {"sound": f"synth/{kind}", "align": ALIGN.get(role, "onset"), "level_db": SYNTH_LEVEL[role],
                       "takes": takes}
    lock = {"kit": 1, "name": "synth", "sr": SR, "roles": roles,
            "mix": {"stop_down": {"before": ["hit", "drop", "whoosh.long", "swell"], "depth_db": [6, 12],
                                  "length_s": [0.3, 0.5]}}}
    write_json(lock_path, lock)
    return _with_dir(lock, out)


def find(query: str, *, role: str | None = None, limit: int = 12) -> list[dict]:
    """Search the bank by words (ids, categories, cue kinds, notes). Ears add `vedit sound rank` by listening."""
    words = [w for w in re.split(r"\W+", query.lower()) if len(w) > 1]
    rows = []
    for s in bank():
        if role and role not in (s.get("kinds") or []):
            continue
        hay = " ".join([s.get("id", ""), s.get("category", ""), " ".join(s.get("kinds") or []), s.get("notes", "")]).lower()
        score = sum(hay.count(w) * (3 if w in s.get("id", "").lower() else 1) for w in words)
        if score:
            rows.append({"id": s["id"], "score": score, "kinds": s.get("kinds"), "dur_s": s.get("dur_s"),
                         "notes": s.get("notes", "")})
    rows.sort(key=lambda r: -r["score"])
    if not rows and not bank():
        rows = [{"id": f"synth/{k}", "score": 1, "kinds": [r], "notes": "built-in synth"}
                for r, (k, _, _) in SYNTH_ROLES.items() if any(w in r or w in k for w in words)]
    return rows[:limit]


def render_sound(sound_id: str, out: Path, *, pitch: str | None = None, dur: float | None = None,
                 seed: int | None = None) -> Path:
    """One bank sound to a WAV (earshot), or a built-in synth kind ('synth/whoosh')."""
    out = Path(out)
    if sound_id.startswith("synth/"):
        from .audio import synth, write_wav
        return write_wav(synth(sound_id.split("/", 1)[1], duration=dur, seed=seed or 3), out)
    args = ["sfx", "render", sound_id, "-o", str(out)]
    if pitch:
        args += ["--pitch", str(pitch)]
    if dur:
        args += ["--dur", str(dur)]
    if seed is not None:
        args += ["--seed", str(seed)]
    earshot(*args)
    return out


# ------------------------------------------------------------------ levels (K-weighted, numpy only)

def _decode(path: str | Path, sr: int, start: float = 0.0, dur: float | None = None) -> np.ndarray:
    cmd = [ffmpeg(), "-v", "error", "-ss", f"{max(0.0, start):.3f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return np.frombuffer(proc.stdout, dtype=np.float32).astype(np.float64)


_KW: dict[tuple[int, int], np.ndarray] = {}


def _kweight_mag(n: int, sr: int) -> np.ndarray:
    """|H| of the ITU-R BS.1770 K-weighting (48 kHz biquads) at the rfft bins."""
    key = (n, sr)
    if key not in _KW:
        f = np.fft.rfftfreq(n, 1 / sr)
        z = np.exp(-1j * 2 * np.pi * np.minimum(f, 23999) / 48000)
        def biquad(b, a):
            return (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
        h = biquad((1.53512485958697, -2.69169618940638, 1.19839281085285), (1.0, -1.69065929318241, 0.73248077421585))
        h *= biquad((1.0, -2.0, 1.0), (1.0, -1.99004745483398, 0.99007225036621))
        _KW[key] = np.abs(h)
    return _KW[key]


def _kpower(x: np.ndarray, sr: int) -> np.ndarray:
    if len(x) == 0:
        return x
    spec = np.fft.rfft(x) * _kweight_mag(len(x), sr)
    return np.fft.irfft(spec, len(x)) ** 2


def l50_lufs(x: np.ndarray, sr: int = SR) -> float:
    """The loudest 50 ms, K-weighted (earshot's measure for a take)."""
    p = _kpower(x, sr)
    win = int(0.05 * sr)
    if len(p) < win:
        return float(-0.691 + 10 * np.log10(p.mean() + 1e-24))
    c = np.convolve(p, np.ones(win) / win, mode="valid")
    return round(float(-0.691 + 10 * np.log10(c.max() + 1e-24)), 2)


def bed_lufs(x: np.ndarray, sr: int = BED_SR, pct: float = 50) -> float | None:
    """Median 50 ms K-weighted level of a window (earshot's bed_level; pct=75 for speech with its gaps);
    None under the floor."""
    win = int(0.05 * sr)
    k = len(x) // win
    if k < 1:
        return None
    p = _kpower(x, sr)[:k * win].reshape(k, win).mean(1)
    lv = float(-0.691 + 10 * np.log10(np.percentile(p, pct) + 1e-24))
    return None if lv < BED_FLOOR_LUFS else round(lv, 2)


def _music_window(edit: Edit, t: float) -> np.ndarray | None:
    """The music/ambience bed in the second before t, at its mix volume (power-summed across clips)."""
    total = None
    for clip in edit.audio:
        if not clip.ducks or not clip.enabled:
            continue
        src = edit.sources.get(clip.source)
        if not src:
            continue
        a = max(clip.start, t - 1.0)
        if a >= t:
            continue
        s0 = clip.src_in + (a - clip.start)
        span = src.duration - clip.src_in if src.duration else None
        if clip.loop and span:
            s0 = clip.src_in + (s0 - clip.src_in) % span
        if clip.src_out is not None and s0 >= clip.src_out:
            continue
        x = _decode(src.path, BED_SR, s0, t - a) * clip.volume
        if len(x) < int(0.05 * BED_SR):
            continue
        x = np.pad(x, (int((a - (t - 1.0)) * BED_SR), 0))[: BED_SR]
        total = x if total is None else total[: len(x)] + x[: len(total)]
    return total


def _voice_window(edit: Edit, t: float) -> np.ndarray | None:
    hit = edit.timeline_to_source(max(0.0, t - 0.5))
    if not hit:
        return None
    sid, st = hit
    src = edit.sources[sid]
    if not src.has_audio:
        return None
    return _decode(src.path, BED_SR, max(0.0, st - 1.0), 2.0)


# ------------------------------------------------------------------ cues

def cues(edit: Edit, *, density: float | None = None, emphasis: bool = True) -> list[dict]:
    """Propose sound cues from the edit: graphics landing, texts, transitions, effects, emphasised words.

    Each cue: {id, t (timeline s), role, why, priority, anchor}. Claude reviews, edits, adds or deletes cues
    (edit/sound/cues.json) before `place`. The density cap keeps the strongest cues per 10 s window.
    """
    from .knobs import bake
    e = bake(edit.layout()).active()
    out: list[dict] = []

    def add(cid: str, t: float, role: str | None, why: str, prio: int | None = None) -> None:
        if role is None or t < 0 or t > e.duration:
            return
        out.append({"id": cid, "t": round(t, 3), "role": role, "why": why, "priority": prio or PRIORITY.get(role, 2)})

    for ov in e.overlays:
        tpl = (ov.mg.template if ov.mg else None) or ""
        role = TEMPLATE_ROLE.get(tpl, "pop") if tpl else ("pop" if ov.mg or ov.path else None)
        add(f"ov_{ov.id}", ov.start + 0.05, role, f"graphic {ov.id} ({tpl or 'custom'}) lands", PRIORITY.get(role or "", 3) + 1)
    for tx in e.texts:
        add(f"tx_{tx.id}", tx.start + 0.03, "pop", f"text '{tx.text[:24]}' appears")
    for clip in e.main[1:]:
        tr = clip.transition_in
        if tr and tr.type not in SOFT_TRANSITIONS:
            role = "hit" if tr.type in ("flash", "white_flash", "fadewhite") else "whoosh.short"
            add(f"tr_{clip.id}", clip.start or 0.0, role, f"{tr.type} transition into {clip.id}")
    for clip in e.broll:
        if clip.transition_in and clip.transition_in.type not in SOFT_TRANSITIONS:
            add(f"br_{clip.id}", clip.start or 0.0, "whoosh.short", f"b-roll {clip.id} swipes in")
    for fx in e.effects:
        add(f"fx_{fx.id}", fx.start, EFFECT_ROLE.get(fx.render or ""), f"{fx.render} effect")
    if emphasis and e.captions.enabled:
        keys = set(e.captions.emphasis_keys)
        for chunk in e.captions.chunks:
            for w in chunk.words:
                if w.k and w.k in keys:
                    add(f"em_{w.k}", w.s, "tick", f"emphasised word '{w.w}'")

    for c in out:                                   # anchor every cue to the source moment under it
        hit = e.timeline_to_source(c["t"])
        if hit:
            c["anchor"] = {"source": hit[0], "t": round(hit[1], 3)}
    return _thin(out, density or DEFAULT_DENSITY)


def _thin(items: list[dict], density: float) -> list[dict]:
    """Keep the strongest cues: at most `density` per 10 s and 0.25 s apart (runs of one role excepted)."""
    keep: list[dict] = []
    for c in sorted(items, key=lambda c: (-c["priority"], c["t"])):
        window = [k for k in keep if abs(k["t"] - c["t"]) < 5.0]
        if len(window) >= density:
            continue
        if any(abs(k["t"] - c["t"]) < 0.25 and k["role"] != c["role"] for k in keep):
            continue
        keep.append(c)
    return sorted(keep, key=lambda c: c["t"])


def cues_path(root: Path) -> Path:
    return root / "sound" / "cues.json"


# ------------------------------------------------------------------ placement

def _role_for(lock: dict, role: str) -> tuple[str, dict] | None:
    roles = lock.get("roles") or {}
    for r in [role, *FALLBACK.get(role, [])]:
        if roles.get(r) and roles[r].get("takes"):
            return r, roles[r]
    return None


def _space(cs: list[dict], lock: dict) -> None:
    by_role: dict[str, list[dict]] = {}
    for c in cs:
        by_role.setdefault(c["role"], []).append(c)
    for role, group in by_role.items():
        spec = (lock.get("roles") or {}).get(role) or {}
        gap = float(spec.get("min_gap_ms") or 0) / 1000
        last = None
        for c in sorted(group, key=lambda c: c["t"]):
            if last is not None and c["t"] < last + gap:
                c["t"] = round(last + gap, 4)
            last = c["t"]


def place(edit: Edit, cue_list: list[dict], *, kit: str, root: Path, replace: bool = True) -> tuple[Edit, dict]:
    """Turn cues into anchored, levelled sfx AudioClips from a kit. Returns (edit, report)."""
    lock = ensure_kit(kit)
    takes_dir = Path(lock["dir"])
    dest = root / "sound" / "takes" / kit
    dest.mkdir(parents=True, exist_ok=True)
    e = edit.model_copy(deep=True)
    if replace:
        e.audio = [a for a in e.audio if not (a.sfx and a.sfx.kit)]
    has_music = any(a.ducks and a.enabled for a in e.audio)
    stop = ((lock.get("mix") or {}).get("stop_down") or {})
    stop_roles = set(stop.get("before") or [])
    depth = float(np.mean(stop.get("depth_db") or [9]))
    length = float(np.mean(stop.get("length_s") or [0.4]))

    resolved = []
    for c in cue_list:
        got = _role_for(lock, c["role"])
        if not got:
            continue
        resolved.append({**c, "role": got[0], "asked": c["role"]})
    _space(resolved, lock)

    used: dict[str, int] = {}
    placed, skipped = [], []
    l50_cache: dict[str, tuple[float, float]] = {}
    for c in resolved:
        role, spec = c["role"], lock["roles"][c["role"]]
        takes = spec["takes"]
        k = used.get(role, 0)
        used[role] = k + 1
        take = takes[k % len(takes)]
        align = spec.get("align") or ALIGN.get(role, "onset")
        sync = float(take.get(f"{align}_s", 0.0))
        offset_ms = float(spec.get("offset_ms") or 0.0)
        start = c["t"] + offset_ms / 1000 - sync
        trim = 0.0
        if start < 0:                    # a lead-in before 0:00 is trimmed while its sync point stays
            if -start >= sync - 0.01:
                skipped.append({"cue": c["id"], "why": "its sync point falls before the video starts"})
                continue
            trim, start = -start, 0.0
        src_file = takes_dir / take["file"]
        local = dest / take["file"]
        if not local.exists() or local.stat().st_size != src_file.stat().st_size:
            shutil.copy(src_file, local)
        if take["file"] not in l50_cache:
            x = _decode(local, SR)
            l50_cache[take["file"]] = (take.get("l50_lufs") or l50_lufs(x), take.get("peak_db", float(20 * np.log10(np.abs(x).max() + 1e-12))))
        l50, peak = l50_cache[take["file"]]
        bed_db = spec.get("bed_db")
        if bed_db is None:
            bed_db = float(np.clip(8 + float(spec.get("level_db") or 0) / 2, 2, 10))
        # the effect must read over whatever plays under it: the music bed (earshot's bed_db) or the voice
        music = _music_window(e, c["t"]) if has_music else None
        bed = bed_lufs(music) if music is not None else None
        voice = _voice_window(e, c["t"])
        vb = bed_lufs(voice, pct=75) if voice is not None else None
        targets = {}
        if bed is not None:
            targets["music"] = bed + 10 * np.log10(10 ** (bed_db / 10) - 1)
        if vb is not None:
            targets["voice"] = vb + bed_db + VOICE_REL_DB
        if targets:
            against = max(targets, key=targets.get)
            gain = targets[against] - l50
        else:
            gain, against = float(spec.get("level_db") or 0.0) - 6, "level"
        gain = float(min(gain, CEILING_DB - peak))
        sid = "sfx_" + re.sub(r"[^\w]", "_", f"{kit}_{Path(take['file']).stem}")
        if sid not in e.sources:
            e.sources[sid] = Source(id=sid, path=str(local.resolve()), kind="audio", duration=float(take.get("dur_s", 0)),
                                    has_audio=True, origin=f"earshot:{spec.get('sound')}" if kit != "synth" else "synth")
        anchor = None
        if c.get("anchor") and not trim:
            anchor = Anchor(source=c["anchor"]["source"], t=c["anchor"]["t"], offset=round(offset_ms / 1000 - sync, 4))
        dip = {"depth_db": round(depth, 1), "length_s": round(length, 2)} if (role in stop_roles and has_music) else None
        cid = re.sub(r"[^\w.-]", "_", c["id"])
        clip = AudioClip(id=f"sfx_{cid}", source=sid, start=round(start, 4), src_in=round(trim, 4), volume=round(float(10 ** (gain / 20)), 4),
                         role="sfx", anchor=anchor, label=role, fade_in=0.015 if trim else 0.0,
                         sfx=SfxRef(role=role, kit=kit, take=take["file"], align=align, sync_s=round(sync - trim, 4), offset_ms=offset_ms,
                                    cue=c["id"], dip=dip))
        e.audio = [a for a in e.audio if a.id != clip.id] + [clip]
        placed.append({"cue": c["id"], "role": role, "asked": c["asked"], "t": c["t"], "take": take["file"],
                       "gain_db": round(gain, 1), "against": against, "bed_lufs": bed, "dip": bool(dip)})
    report = {"kit": kit, "placed": len(placed), "skipped": skipped, "items": placed,
              "unplaced_roles": sorted({c["role"] for c in cue_list} - {p["asked"] for p in placed})}
    return e, report


def dips(edit: Edit) -> list[tuple[float, float, float]]:
    """Music stop-downs (start, end, gain) from placed effects; the renderer and the Studio apply them to the bed."""
    out = []
    for a in edit.audio:
        if a.enabled and a.sfx and a.sfx.dip:
            hit = a.sfx.cue_time(a.start)
            g = 10 ** (-float(a.sfx.dip.get("depth_db", 9)) / 20)
            if hit > 0.05:
                out.append((round(max(0.0, hit - float(a.sfx.dip.get("length_s", 0.4))), 4), round(hit, 4), round(g, 4)))
    return sorted(out)


def dip_expr(ds: list[tuple[float, float, float]], ramp: float = 0.08) -> str | None:
    """ffmpeg volume expression: the bed eases down at each dip start and comes back on the hit."""
    if not ds:
        return None
    terms = [f"if(between(t,{a:.3f},{b:.3f}),1-{1 - g:.4f}*min(1,(t-{a:.3f})/{ramp}),1)" for a, b, g in ds]
    return "*".join(terms)


# ------------------------------------------------------------------ listening

def check(edit: Edit, render_path: str | Path, out_dir: str | Path) -> dict:
    """Does every placed effect sound where it should? Offsets of the event that answers each cue."""
    from .knobs import bake
    e = bake(edit.layout()).active()
    items = [{"t": round(a.sfx.cue_time(a.start), 3), "kind": a.sfx.role, "id": a.id}
             for a in e.audio if a.sfx]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not items:
        return {"n": 0, "items": [], "engine": None}
    expected = []                      # where the take's sync point actually lands (cue + offset_ms)
    for a in e.audio:
        if a.sfx:
            expected.append({"t": round(a.start + a.sfx.sync_s, 4), "kind": a.sfx.role, "id": a.id,
                             "align": a.sfx.align})
    if earshot_python():
        res = bridge("sync", {"audio": str(Path(render_path).resolve()), "cues": expected})
        res["engine"] = "earshot"
    else:
        res = _simple_sync(render_path, expected)
        res["engine"] = "simple"
    write_json(out_dir / "sfx_sync.json", res)
    return res


def _simple_sync(render_path: str | Path, expected: list[dict]) -> dict:
    sr = 24000
    x = _decode(render_path, sr)
    hp = np.diff(x, prepend=0.0)
    win = int(0.005 * sr)
    env = np.convolve(np.abs(hp), np.ones(win) / win, mode="same")
    items = []
    for c in expected:
        i = int(c["t"] * sr)
        lo, hi = max(1, i - int(0.1 * sr)), min(len(env) - 1, i + int(0.1 * sr))
        if hi <= lo:
            continue
        seg = env[lo:hi]
        rise = np.diff(seg, prepend=seg[0])
        j = int(np.argmax(rise)) if c.get("align") == "onset" else int(np.argmax(seg))
        off = round(((lo + j) / sr - c["t"]) * 1000, 1)
        items.append({**c, "offset_ms": off, "status": "OK" if abs(off) <= 40 else "near" if abs(off) <= 100 else "off"})
    offs = [abs(i["offset_ms"]) for i in items]
    return {"items": items, "stats": {"n": len(items), "median_abs_offset_ms": float(np.median(offs)) if offs else None,
                                      "hit_within_40ms": round(float(np.mean([o <= 40 for o in offs])), 3) if offs else None}}


def ears(render_path: str | Path, out_dir: str | Path, cue_items: list[dict] | None = None) -> dict:
    """earshot's ears on a render: timeline (events, tags, sync), annotated sheet, critique scorecard."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not ears_installed():
        return {"installed": False, "hint": "`vedit setup earshot --ears` (~1.3 GB incl. torch CPU; ask first)"}
    cue_arg = []
    if cue_items:
        cf = out_dir / "ears_cues.json"
        write_json(cf, {"events": cue_items})
        cue_arg = ["--cues", str(cf)]
    rp = str(Path(render_path).resolve())
    tl = earshot("timeline", rp, *cue_arg, "--json", "--out", str(out_dir / "ears_timeline.json"), timeout=3600)
    earshot("sheet", rp, *cue_arg, "-o", str(out_dir / "ears_sheet.png"), timeout=3600)
    cr = earshot("critique", rp, "--json", "--out", str(out_dir / "ears_critique.json"), timeout=3600)
    return {"installed": True, "timeline": (tl or {}).get("summary"), "critique": (cr or {}).get("summary"),
            "sheet": str(out_dir / "ears_sheet.png")}


# ------------------------------------------------------------------ CLI

def _proj(path: str):
    from .project import find as find_project
    return find_project(path)


def cmd_sound(a) -> None:
    from .util import print_json
    if a.action == "kits":
        print_json(kit_presets())
        return
    if a.action == "find":
        print_json(find(a.target, role=a.role, limit=a.limit))
        return
    if a.action == "render":
        print_json({"file": str(render_sound(a.target, Path(a.out), pitch=a.pitch, dur=a.dur, seed=a.seed))})
        return
    if a.action == "kit":
        name = a.kit or a.target
        lock = ensure_kit(name, force=a.force)
        print_json({"kit": name, "dir": lock["dir"], "roles": {r: len(v["takes"]) for r, v in (lock.get("roles") or {}).items() if v}})
        return
    p = _proj(a.target)
    settings_path = p.root / "sound" / "sound.json"
    settings = read_json(settings_path, default={}) or {}
    if a.action == "cues":
        cs = cues(p.edit(), density=a.density, emphasis=not a.no_emphasis)
        write_json(cues_path(p.root), {"cues": cs})
        print_json({"file": str(cues_path(p.root)), "n": len(cs), "cues": cs})
        return
    if a.action == "place":
        kit = a.kit or settings.get("kit") or default_kit(p.edit().style)
        cfile = Path(a.cues) if a.cues else cues_path(p.root)
        doc = read_json(cfile) if cfile.exists() else None
        cs = (doc or {}).get("cues") if isinstance(doc, dict) else doc
        if cs is None:
            cs = cues(p.edit(), density=a.density)
            write_json(cues_path(p.root), {"cues": cs})
        e, rep = place(p.edit(), cs, kit=kit, root=p.root, replace=not a.keep)
        p.save_edit(e)
        write_json(settings_path, {**settings, "kit": kit})
        from . import learn
        learn.event("sound", {"kit": kit, "placed": rep["placed"]}, project=p.root.parent.name, scope={"style": e.style or ""})
        print_json(rep)
        return
    if a.action == "check":
        render = Path(a.render) if a.render else p.root / "render" / f"{p.edit().name}.mp4"
        res = check(p.edit(), render, p.sub("qa"))
        if a.ears:
            res["ears"] = ears(render, p.sub("qa"), [{"t": i["t"], "kind": i.get("kind"), "id": i.get("id")}
                                                      for i in res.get("items", [])])
        print_json(res)
        return
    raise VeditError(f"unknown action {a.action}")


def register_cli(sp) -> None:
    s = sp.add_parser("sound", help="sound design: kits, cues, placement, listening checks (earshot optional)")
    s.add_argument("action", choices=["kits", "kit", "find", "render", "cues", "place", "check"])
    s.add_argument("target", nargs="?", default="", help="project path, kit name, search words or sound id")
    s.add_argument("--kit"); s.add_argument("--cues"); s.add_argument("--density", type=float)
    s.add_argument("--no-emphasis", action="store_true"); s.add_argument("--keep", action="store_true",
                                                                         help="keep effects already placed")
    s.add_argument("--role"); s.add_argument("--limit", type=int, default=12)
    s.add_argument("--out"); s.add_argument("--pitch"); s.add_argument("--dur", type=float); s.add_argument("--seed", type=int)
    s.add_argument("--render"); s.add_argument("--ears", action="store_true"); s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_sound)
