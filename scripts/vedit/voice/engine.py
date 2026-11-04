"""Speak a script with any voice and get a word-timed transcript, so captions and cuts treat it like a recording.

    say(text, out, voice)        -> wav + <out>.transcript.json (vedit's transcript format)
    vo(project, script, voice)   -> the same, added to the edit (main track for faceless videos, or a VO clip)
    clone(name, files, consent)  -> a personal voice (reference clip + OpenVoice embedding), consent recorded

Every voice works sentence by sentence: one model load, natural pauses we place ourselves (so sentence
boundaries are exact), and word times from the service (Edge, ElevenLabs) or from Whisper aligned to the
script, falling back to a proportional spread inside each sentence.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
import wave
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

from .. import models
from ..addons import tool_python
from ..media import ffmpeg
from ..paths import IS_WINDOWS, cache_dir, personal_dir, tools_dir
from ..util import VeditError, read_json, run, write_json
from . import catalog, text as T

SR = 48000
# sherpa-onnx 2.x dropped its built-in espeak-ng: Kokoro then skips every English word missing from its
# lexicon (names, brands) and cannot speak its other languages; Piper/Mimic 3 voices fail outright. 1.13.8 is
# the last release with espeak inside (and it already has Pocket TTS).
VOICE_PINS = ["sherpa-onnx==1.13.8", "edge-tts==7.3.1", "numpy"]
OPENVOICE_REF = "git+https://github.com/myshell-ai/OpenVoice@74a1d147b17a8c3092dd5430504bd83ef6c7eb23"
OPENVOICE_PINS = ["librosa", "soundfile", "numpy"]
BRIDGES = {"voice": "voice_bridge.py", "openvoice": "openvoice_bridge.py"}


# ------------------------------------------------------------------ tool venvs

def setup(tool: str = "voice") -> dict:
    """voice: sherpa-onnx + edge-tts (~20 MB). openvoice: PyTorch CPU + OpenVoice V2 (~0.8 GB). Ask first."""
    uv = shutil.which("uv")
    if not uv:
        raise VeditError("uv is required (https://docs.astral.sh/uv/)")
    venv = tools_dir() / tool / "venv"
    py = venv / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
    if not py.exists():
        run([uv, "venv", "--python", "3.12", str(venv)], timeout=900)
    if tool == "voice":
        run([uv, "pip", "install", "--python", str(py), *VOICE_PINS], timeout=3600)
    elif tool == "openvoice":
        run([uv, "pip", "install", "--python", str(py), "torch", "--index-url", "https://download.pytorch.org/whl/cpu"],
            timeout=7200)
        run([uv, "pip", "install", "--python", str(py), *OPENVOICE_PINS], timeout=3600)
        # its setup.py pins Python-3.9-era packages; the converter needs none of them
        run([uv, "pip", "install", "--python", str(py), "--no-deps", OPENVOICE_REF], timeout=1800)
    else:
        raise VeditError(f"Unknown voice tool '{tool}' (voice | openvoice)")
    return {"tool": tool, "venv": str(venv)}


def _bridge(tool: str, cmd: str, req: dict, timeout: int = 3600):
    py = tool_python(tool)
    if not py:
        size = "~20 MB" if tool == "voice" else "~0.8 GB"
        raise VeditError(f"The {tool} tools are not installed ({size}). Ask the owner, then `vedit setup {tool}`.")
    work = cache_dir() / "voice_jobs"
    work.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex[:10]
    rq, rs = work / f"{cmd}_{tag}.req.json", work / f"{cmd}_{tag}.res.json"
    write_json(rq, req)
    try:
        run([py, "-I", Path(__file__).resolve().parents[1] / BRIDGES[tool], cmd, rq, rs], timeout=timeout,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        return read_json(rs)
    finally:
        rq.unlink(missing_ok=True)
        rs.unlink(missing_ok=True)


# ------------------------------------------------------------------ audio helpers

def load_audio(path: str | Path) -> np.ndarray:
    import subprocess
    p = subprocess.run([ffmpeg(), "-v", "error", "-nostdin", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                       capture_output=True)
    if p.returncode or not p.stdout:
        raise VeditError(f"Could not read audio {path}: {p.stderr.decode('utf-8', 'replace')[-300:]}")
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def write_wav(path: str | Path, x: np.ndarray, sr: int = SR) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767.0).astype(np.int16).tobytes())
    return path


TRIM_KEEP = 0.04            # silence kept before and after each spoken sentence (seconds)


def _trim(x: np.ndarray, keep: float = TRIM_KEEP) -> tuple[np.ndarray, float]:
    """Cut silence at both ends (-42 dB below the peak, 10 ms frames); returns (audio, seconds cut at the start)."""
    if not len(x):
        return x, 0.0
    hop = SR // 100
    n = len(x) // hop
    if n < 3:
        return x, 0.0
    e = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    thr = e.max() * 10 ** (-42 / 20)
    on = np.nonzero(e > thr)[0]
    if not len(on):
        return x, 0.0
    a = max(0, on[0] * hop - int(keep * SR))
    b = min(len(x), (on[-1] + 1) * hop + int(keep * SR))
    return x[a:b], a / SR


# ------------------------------------------------------------------ voices

def parse(voice: str) -> tuple[str, str]:
    if ":" not in voice:
        raise VeditError(f"Voice ids look like kokoro:af_heart, edge:bn-BD-PradeepNeural, bn_coqui:female, "
                         f"pocket:<your voice>, openvoice:<your voice>@<base voice>, eleven:<name> (got '{voice}')")
    backend, rest = voice.split(":", 1)
    if backend not in catalog.LICENCE:
        raise VeditError(f"Unknown voice backend '{backend}'. Known: {', '.join(catalog.LICENCE)}")
    return backend, rest


def row(voice: str) -> dict:
    backend, rest = parse(voice)
    if backend in ("pocket", "openvoice"):
        name = rest.split("@", 1)[0]
        base = rest.split("@", 1)[1] if "@" in rest else None
        lang = row(base)["language"] if base else "en"
        lic, com, online = catalog.LICENCE[backend]
        if base:   # the base voice's terms apply too
            b = row(base)
            lic = f"{lic}; base voice: {b['licence']}"
            com = min((com, b["commercial"]), key=lambda c: ["no", "unclear", "verify", "credit", "yes"].index(c))
            online = online or b["online"]
        return {"id": voice, "backend": backend, "language": lang, "licence": lic, "commercial": com, "online": online,
                "personal": name, "base": base}
    if backend == "eleven":
        lic, com, online = catalog.LICENCE[backend]
        return {"id": voice, "backend": backend, "language": None, "licence": lic, "commercial": com, "online": online}
    r = next((r for r in catalog.builtin() if r["id"] == voice), None)
    if r is None:
        raise VeditError(f"No voice '{voice}'. See `vedit voice list`.")
    return r


def personal_voice(name: str) -> dict:
    meta = read_json(personal_dir() / "voices" / name / "voice.json")
    if not meta:
        raise VeditError(f"No personal voice '{name}'. Make one with `vedit voice clone {name} --files ... --consent ...`.")
    meta["dir"] = str(personal_dir() / "voices" / name)
    return meta


def list_voices(*, language: str | None = None, ready_only: bool = False) -> list[dict]:
    rows = []
    venv = bool(tool_python("voice"))
    for r in catalog.builtin():
        ready = (models.is_ready(r["model"]) if r["model"] else True) and venv
        rows.append({**r, "ready": ready})
    for d in sorted((personal_dir() / "voices").glob("*/voice.json")) if (personal_dir() / "voices").exists() else []:
        meta = read_json(d) or {}
        name = meta.get("name") or d.parent.name
        rows.append({**row(f"pocket:{name}"), "ready": venv and models.is_ready("pocket_tts"), "consent": bool(meta.get("consent"))})
        rows.append({**row(f"openvoice:{name}@edge:bn-BD-PradeepNeural"), "id": f"openvoice:{name}@<base voice>",
                     "ready": bool(tool_python("openvoice")) and models.is_ready("openvoice_v2"),
                     "consent": bool(meta.get("consent"))})
    if language:
        rows = [r for r in rows if r.get("language") in (language, None)]
    if ready_only:
        rows = [r for r in rows if r["ready"]]
    return rows


# ------------------------------------------------------------------ synthesis

def _kind_and_dir(backend: str) -> tuple[str, str]:
    mid = catalog.MODEL_OF[backend]
    return ("kokoro" if backend == "kokoro" else "pocket" if backend == "pocket" else "vits"), str(models.ensure(mid))


def _prep(backend: str, s: str) -> str:
    s = T.clean(s)
    if backend in ("bn_coqui", "bn_mimic3"):
        s = T.bn_spell_numbers(s)
    return s


def _synth(voice: str, sents: list[str], parts: Path, *, speed: float) -> list[dict]:
    """Per-sentence audio files ([{"wav", "words" (times inside the file) or None}])."""
    backend, rest = parse(voice)
    parts.mkdir(parents=True, exist_ok=True)
    outs = [str(parts / f"s{i:03d}.wav") for i in range(len(sents))]
    texts = [_prep(backend, s) for s in sents]
    if backend in ("kokoro", "bn_coqui", "bn_mimic3", "pocket"):
        kind, mdir = _kind_and_dir(backend)
        req = {"kind": kind, "model_dir": mdir, "texts": texts, "outs": outs, "speed": speed, "threads": 4}
        if backend == "kokoro":
            sid, accent, _ = catalog.KOKORO[rest]
            req.update({"sid": sid, "lang": accent})
            if models.is_ready("kokoro_fp32"):
                # full precision runs 3-4x faster than the int8 file on this kind of CPU (RTF 0.87 vs 2.6-3.5)
                req.update({"model_file": str(models.path_of("kokoro_fp32")), "threads": 8})
        elif backend == "bn_mimic3":
            req["sid"] = int(rest)
        elif backend == "pocket":
            req["reference"] = str(_reference(rest))
        _bridge("voice", "tts", req, timeout=7200)
        return [{"wav": o, "words": None} for o in outs]
    if backend == "edge":
        mp3s = [str(parts / f"s{i:03d}.mp3") for i in range(len(sents))]
        rate = f"{int(round((speed - 1) * 100)):+d}%"
        res = _bridge("voice", "edge", {"voice": rest, "texts": texts, "outs": mp3s, "rate": rate}, timeout=1800)
        return [{"wav": r["out"], "words": r["words"]} for r in res]
    if backend == "openvoice":
        name, base = (rest.split("@", 1) + [None])[:2]
        if not base:
            raise VeditError("openvoice voices need a base voice: openvoice:<your voice>@<base voice id>, "
                             "e.g. openvoice:me@edge:bn-BD-PradeepNeural")
        src = _synth(base, sents, parts / "base", speed=speed)
        wavs = []
        for i, p in enumerate(src):           # the converter reads WAV; Edge parts are MP3
            w = parts / f"base_{i:03d}.wav"
            write_wav(w, load_audio(p["wav"]))
            wavs.append(str(w))
        se = _openvoice_se(name)
        conv = models.ensure("openvoice_v2")
        _bridge("openvoice", "convert", {"config": str(models.ensure("openvoice_v2_config")), "ckpt": str(conv),
                                         "src": wavs, "outs": outs, "tgt_se": str(se), "tau": 0.3}, timeout=7200)
        return [{"wav": o, "words": p["words"]} for o, p in zip(outs, src)]   # conversion keeps the timing
    if backend == "eleven":
        from .. import tts
        res = tts.speak(" ".join(texts), parts / "eleven.mp3", voice=rest, speed=speed)
        words = read_json(res["transcript"]).get("words", [])
        return [{"wav": res["audio"], "words": words, "whole": True}]
    raise VeditError(f"Backend {backend} cannot speak")


def say(script: str, out: str | Path, voice: str, *, speed: float = 1.0, language: str | None = None,
        align: str | bool = "auto", lines: list[dict] | None = None, lead: float = 0.12, tail: float = 0.25) -> dict:
    """Speak `script` with `voice` into `out` (48 kHz mono WAV) plus `<out>.transcript.json`.

    `lines` = [{id, text, after}] speaks a script line by line with each line's own pause after it (one beat of
    an animation per line); the transcript then carries `lines` with each line's start, end and words. `lead`
    and `tail` are the silences before the first and after the last line.
    """
    out = Path(out).with_suffix(".wav")
    info = row(voice)
    owner: list[int] | None = None
    if lines:
        pairs, owner = [], []
        for li, line in enumerate(lines):
            ps = T.sentences(T.clean(str(line.get("text", ""))))
            if not ps:
                raise VeditError(f"Script line {line.get('id', li + 1)} is empty.")
            for k, (sent, pause) in enumerate(ps):
                pairs.append((sent, float(line.get("after", 0.45)) if k == len(ps) - 1 else pause))
                owner.append(li)
        pairs[-1] = (pairs[-1][0], 0.0)                              # the tail follows the last line
        script = "\n".join(str(line.get("text", "")) for line in lines)
    else:
        pairs = T.sentences(T.clean(script))
    lang = language or info.get("language") or ("bn" if T.is_bangla(script) else "en")
    if not pairs:
        raise VeditError("Nothing to say: the script is empty after clean-up.")
    sents = [s for s, _ in pairs]
    parts = out.with_name(out.stem + "_parts")
    shutil.rmtree(parts, ignore_errors=True)
    t0 = time.time()
    produced = _synth(voice, sents, parts, speed=speed)
    t_synth = time.time() - t0
    chunks, spans, words, cursor = [np.zeros(int(lead * SR), np.float32)], [], [], lead
    if len(produced) == 1 and produced[0].get("whole"):            # one take for the whole script (ElevenLabs)
        x = load_audio(produced[0]["wav"])
        x, cut = _trim(x)
        chunks.append(x)
        spans.append((cursor, cursor + len(x) / SR))
        words = [{**w, "s": round(w["s"] - cut + cursor, 3), "e": round(w["e"] - cut + cursor, 3)} for w in produced[0]["words"]]
        cursor += len(x) / SR
    else:
        for (sent, pause), part in zip(pairs, produced):
            x = load_audio(part["wav"])
            x, cut = _trim(x)
            chunks.append(x)
            start = cursor
            cursor += len(x) / SR
            spans.append((start, cursor))
            if part["words"]:
                for w in part["words"]:
                    s = max(start, min(cursor, w["s"] - cut + start))
                    e = max(s + 0.02, min(cursor, w["e"] - cut + start))
                    words.append({"w": w["w"], "s": round(s, 3), "e": round(e, 3), "si": len(spans) - 1})
            if pause:
                chunks.append(np.zeros(int(pause * SR), np.float32))
                cursor += pause
    chunks.append(np.zeros(int(tail * SR), np.float32))
    audio = np.concatenate(chunks)
    peak = float(np.abs(audio).max()) or 1.0
    audio = audio * min(1.0, 0.89 / peak)                           # -1 dBFS headroom, never louder than made
    write_wav(out, audio)
    method = "service" if words else "proportional"
    matched = None
    t1 = time.time()
    if not words:
        # Whisper refines word times well on English (base.en, ~4 s); on synthetic Bangla it matched 16 % of the
        # words and took a minute, so other languages keep the spread inside each (exactly known) sentence
        use = align == "whisper" or (align in ("auto", True) and lang == "en")
        words, matched = _align(out, sents, spans, lang) if use else (_spread(sents, spans), None)
        if matched is not None and matched < 0.5:
            words, matched = _spread(sents, spans), matched
            method = "proportional"
        else:
            method = "whisper" if matched else "proportional"
    t_align = time.time() - t1
    for w in words:
        w.pop("si", None)
        w.update({"p": 1.0, "type": "word"})
    shutil.rmtree(parts, ignore_errors=True)
    dur = round(len(audio) / SR, 3)
    transcript = {"version": 1, "source": str(out.resolve()), "engine": f"voice:{info['backend']}", "voice": voice,
                  "language": lang, "duration": dur, "words": words,
                  "segments": [{"s": round(a, 3), "e": round(b, 3), "text": s} for (a, b), s in zip(spans, sents)],
                  "script": script, "alignment": {"method": method, "matched": matched},
                  "licence": {k: info.get(k) for k in ("licence", "commercial", "online")}}
    if lines:
        transcript["lines"] = _line_spans(lines, owner or [], spans, words)
    tpath = out.with_suffix(".transcript.json")
    write_json(tpath, transcript)
    return {"audio": str(out), "transcript": str(tpath), "duration": dur, "voice": voice, "language": lang,
            "sentences": len(sents), "words": len(words), "alignment": transcript["alignment"],
            "licence": info["licence"], "commercial": info["commercial"], "online": info["online"],
            "seconds": round(time.time() - t0, 1), "timing": {"speech": round(t_synth, 1), "align": round(t_align, 1)}}


def _line_spans(lines: list[dict], owner: list[int], spans: list[tuple[float, float]], words: list[dict]) -> list[dict]:
    """Each script line's start and end (its first and last sentence) and the words spoken inside it."""
    out = []
    one_take = len(spans) == 1 and len(owner) > 1                    # ElevenLabs: one take, split by word counts
    if one_take:
        k = 0
        for line in lines:
            n = len(T.words(str(line.get("text", ""))))
            ws = words[k:k + n] or words[k:k + 1]
            k += n
            out.append({"id": str(line.get("id", len(out) + 1)), "text": line.get("text", ""),
                        "t0": ws[0]["s"] if ws else 0.0, "t1": ws[-1]["e"] if ws else 0.0,
                        "words": [{"w": w["w"], "t0": w["s"], "t1": w["e"]} for w in ws]})
        return out
    for li, line in enumerate(lines):
        idx = [i for i, o in enumerate(owner) if o == li]
        # a sentence's audio keeps TRIM_KEEP of silence at each end: the line starts and ends with the speech
        t0, t1 = spans[idx[0]][0] + TRIM_KEEP, spans[idx[-1]][1] - TRIM_KEEP
        ws = [w for w in words if t0 - 0.05 <= (w["s"] + w["e"]) / 2 <= t1 + 0.05]
        out.append({"id": str(line.get("id", li + 1)), "text": line.get("text", ""), "t0": round(t0, 3), "t1": round(t1, 3),
                    "words": [{"w": w["w"], "t0": w["s"], "t1": w["e"]} for w in ws]})
    return out


# ------------------------------------------------------------------ word timing

def _weights(ws: list[str]) -> np.ndarray:
    return np.asarray([max(1, len(T.norm(w))) + 1.5 for w in ws], dtype=float)


def _spread(sents: list[str], spans: list[tuple[float, float]]) -> list[dict]:
    """Words spread over each sentence's sound in proportion to their length."""
    out = []
    for si, (s, (a, b)) in enumerate(zip(sents, spans)):
        ws = T.words(s)
        if not ws:
            continue
        w = _weights(ws)
        edges = a + (b - a) * np.concatenate([[0], np.cumsum(w) / w.sum()])
        for k, word in enumerate(ws):
            out.append({"w": word, "s": round(float(edges[k]), 3), "e": round(float(edges[k + 1]), 3), "si": si})
    return out


def _align(wav: Path, sents: list[str], spans: list[tuple[float, float]], lang: str) -> tuple[list[dict], float]:
    """Whisper word times matched to the script (the script's spelling wins); gaps are spread by length
    between matched neighbours inside the sentence."""
    from ..transcribe import whisper
    model = "base.en" if lang == "en" else "large-v3-turbo"
    try:
        # no script prompt: Whisper takes a prompt as text already spoken and then skips or invents words
        rec = whisper(wav, language=lang if lang != "mixed" else None, model=model).get("words", [])
    except Exception as exc:                                    # alignment is a refinement, never a blocker
        print(f"warning: alignment fell back to proportional timing ({exc})")
        return _spread(sents, spans), 0.0
    toks = [(si, w) for si, s in enumerate(sents) for w in T.words(s)]
    a = [T.norm(w) for _, w in toks]
    b = [T.norm(w["w"]) for w in rec]
    times: list[tuple[float, float] | None] = [None] * len(a)
    sm = SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                times[i1 + k] = (rec[j1 + k]["s"], rec[j1 + k]["e"])
    for k, (si, _) in enumerate(toks):                         # an anchor outside its sentence is a mismatch
        if times[k] and not (spans[si][0] - 0.3 <= times[k][0] <= spans[si][1] + 0.3):
            times[k] = None
    matched = sum(1 for t in times if t) / max(1, len(times))
    out = []
    for si, s in enumerate(sents):
        idx = [k for k, (sj, _) in enumerate(toks) if sj == si]
        if not idx:
            continue
        lo, hi = spans[si]
        k = 0
        while k < len(idx):
            if times[idx[k]]:
                s0, e0 = times[idx[k]]
                out.append({"w": toks[idx[k]][1], "s": max(lo, s0), "e": min(hi, max(e0, s0 + 0.05)), "si": si})
                k += 1
                continue
            j = k
            while j < len(idx) and not times[idx[j]]:
                j += 1
            left = out[-1]["e"] if out and out[-1]["si"] == si else lo
            right = times[idx[j]][0] if j < len(idx) else hi
            right = max(right, left + 0.06 * (j - k))
            ws = [toks[idx[q]][1] for q in range(k, j)]
            w = _weights(ws)
            edges = left + (right - left) * np.concatenate([[0], np.cumsum(w) / w.sum()])
            for q, word in enumerate(ws):
                out.append({"w": word, "s": float(edges[q]), "e": float(edges[q + 1]), "si": si})
            k = j
    for w in out:
        w["s"] = round(float(w["s"]), 3)
        w["e"] = round(float(max(w["e"], w["s"] + 0.03)), 3)
    return out, round(matched, 3)


# ------------------------------------------------------------------ personal voices (consent first)

def _reference(name: str) -> Path:
    """Reference clip for Pocket TTS: a personal voice, or `sample:<name>` from the model's test clips."""
    if name.startswith("sample:"):
        p = Path(models.ensure("pocket_tts")) / "test_wavs" / f"{name.split(':', 1)[1]}.wav"
        if not p.exists():
            raise VeditError(f"No sample voice {name}")
        tmp = cache_dir() / "voice_jobs" / f"ref_{p.stem}.wav"
        write_wav(tmp, load_audio(p)[: SR * 15], SR)
        return tmp
    return Path(personal_voice(name)["dir"]) / "reference.wav"


def _openvoice_se(name: str) -> Path:
    meta = personal_voice(name)
    d = Path(meta["dir"])
    se = d / "openvoice_se.npy"
    if not se.exists():
        refs = sorted(str(p) for p in d.glob("sample_*.wav")) or [str(d / "reference.wav")]
        _bridge("openvoice", "se", {"config": str(models.ensure("openvoice_v2_config")),
                                    "ckpt": str(models.ensure("openvoice_v2")), "wavs": refs, "out": str(se)}, timeout=1800)
        meta = read_json(d / "voice.json") or {}
        meta["openvoice_se"] = se.name
        write_json(d / "voice.json", meta)
    return se


def clone(name: str, files: list[str], *, consent: str, speaker: str = "", eleven: bool = False) -> dict:
    """A personal voice from clean recordings of ONE speaker who agreed to it. Keeps the samples, a 15 s
    reference for Pocket TTS, the OpenVoice embedding (when installed), and the consent statement."""
    if not consent or len(consent.strip()) < 10:
        raise VeditError("Cloning needs the speaker's consent, in words: --consent \"I, <name>, agree to ...\". "
                         "Only clone your own voice or someone who said yes to this use.")
    if not files:
        raise VeditError("Give 1-5 clean recordings (--files), 30-120 s in total is plenty.")
    import re
    if not re.fullmatch(r"[A-Za-z0-9_\-]{2,40}", name):
        raise VeditError("Voice names: 2-40 letters, digits, - or _")
    d = personal_dir() / "voices" / name
    d.mkdir(parents=True, exist_ok=True)
    clips = []
    for i, f in enumerate(files):
        x, _ = _trim(load_audio(Path(f)))
        x = x / max(1e-6, float(np.abs(x).max())) * 0.8
        clips.append(x)
        write_wav(d / f"sample_{i + 1}.wav", x)
    allx = np.concatenate(clips)
    # reference: the most voiced 15 s (frames with steady energy), so Pocket TTS hears speech, not room tone
    hop = SR // 10
    n = len(allx) // hop
    if n >= 20:
        e = np.sqrt((allx[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
        win = 150
        if n > win:
            score = np.convolve((e > e.max() * 0.08).astype(float), np.ones(win), "valid")
            k = int(np.argmax(score))
            ref = allx[k * hop:(k + win) * hop]
        else:
            ref = allx
    else:
        ref = allx
    write_wav(d / "reference.wav", ref)
    meta = {"name": name, "created": time.strftime("%Y-%m-%d %H:%M"), "speaker": speaker or name,
            "consent": {"statement": consent.strip(), "recorded": time.strftime("%Y-%m-%d %H:%M")},
            "samples": [f"sample_{i + 1}.wav" for i in range(len(files))], "reference": "reference.wav",
            "reference_seconds": round(len(ref) / SR, 1), "total_seconds": round(len(allx) / SR, 1)}
    write_json(d / "voice.json", meta)
    out = {"voice": name, "dir": str(d), "reference_seconds": meta["reference_seconds"],
           "total_seconds": meta["total_seconds"], "use": [f"pocket:{name}"]}
    if tool_python("openvoice") and models.is_ready("openvoice_v2"):
        _openvoice_se(name)
        out["use"].append(f"openvoice:{name}@<base voice, e.g. edge:bn-BD-PradeepNeural>")
    if eleven:
        from .. import tts
        res = tts.clone(name, [str(d / s) for s in meta["samples"]], description=f"vedit personal voice {name}")
        meta["eleven_voice_id"] = res["voice_id"]
        write_json(d / "voice.json", meta)
        out["use"].append(f"eleven:{name}")
    from .. import learn
    learn.event("voice_clone", {"name": name, "samples": len(files), "seconds": meta["total_seconds"]})
    return out


def similarity(a: str | Path, b: str | Path) -> float:
    """Speaker similarity (cosine of 3D-Speaker embeddings, -1..1): did a clone land on the target voice?"""
    tmp = cache_dir() / "voice_jobs"
    tmp.mkdir(parents=True, exist_ok=True)
    wavs = []
    for i, p in enumerate((a, b)):
        w = tmp / f"sim_{uuid.uuid4().hex[:8]}_{i}.wav"
        x = load_audio(Path(p))
        write_wav(w, _resample(x, SR, 16000), 16000)
        wavs.append(str(w))
    try:
        e = _bridge("voice", "embed", {"model": str(models.ensure("speaker_emb")), "wavs": wavs})
    finally:
        for w in wavs:
            Path(w).unlink(missing_ok=True)
    va, vb = np.asarray(e[0]), np.asarray(e[1])
    return float(va @ vb / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-9))


def _resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x
    n = int(len(x) * sr_out / sr_in)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


# ------------------------------------------------------------------ in an edit

def vo(proj, script: str, voice: str, *, name: str = "vo", place: str = "main", at: float = 0.0, speed: float = 1.0,
       language: str | None = None) -> dict:
    """Voiceover into the project: `main` puts it on the main track (faceless videos: the voice is the
    timeline, captions come from it, b-roll and graphics go above); `audio` adds it as a VO clip at `at`
    over existing footage (captions include its words too)."""
    from ..project import add_source
    from ..timeline import AudioClip, Clip
    out = proj.root / "assets" / "vo" / f"{name}.wav"
    res = say(script, out, voice, speed=speed, language=language)
    sid = add_source(proj, out, origin="vo")
    e = proj.edit()
    src = e.sources[sid]
    src.transcript = res["transcript"]
    src.notes = [f"voice {voice}: {res['licence']} (commercial: {res['commercial']})"]
    if place == "main":
        e.main = [c for c in e.main if c.source != sid]
        e.main.append(Clip(id=f"vo_{sid}", source=sid, src_in=0.0, src_out=res["duration"], label=f"voiceover ({voice})"))
    else:
        e.audio = [a for a in e.audio if a.source != sid]
        e.audio.append(AudioClip(id=f"vo_{sid}", source=sid, start=at, role="vo", label=f"voiceover ({voice})"))
    proj.save_edit(e)
    from ..assets import add_provenance
    add_provenance(proj.root, out, source=f"tts:{voice}", license=res["licence"],
                   notes=f"commercial use: {res['commercial']}" + ("; made by an online service" if res["online"] else ""))
    proj.log(f"voiceover {name} with {voice} ({res['duration']} s, {place})")
    return {**res, "source": sid, "place": place}
