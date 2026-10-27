"""Word-level transcription with local Whisper (faster-whisper, CPU-friendly) or ElevenLabs Scribe.

Normalised output (transcripts/<source_id>.json):
  {"version": 1, "source", "engine", "model", "language", "duration",
   "words": [{"w", "s", "e", "p", "type": "word"|"event", "speaker"}],
   "segments": [{"s", "e", "text"}]}

Editing needs verbatim text: Whisper normally drops "um/uh", so we prime it with a filler-rich prompt.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import config
from .media import extract_audio, ffmpeg, probe
from .paths import cache_dir
from .util import VeditError, read_json, run, write_json

VERBATIM_PROMPTS = {
    "en": "Umm, so, uh, I was like, you know... hmm. Okay, so basically, I mean, let's go.",
    "bn": "আচ্ছা, মানে, উম, আসলে... তো, এই যে, হ্যাঁ। ঠিক আছে, so basically, চলো শুরু করি।",
    None: "Umm, uh, okay... আচ্ছা, মানে, so basically, you know.",
}


def _audio_for(src: Path, work: Path) -> Path:
    out = work / f"{src.stem}.16k.wav"
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        extract_audio(src, out)
    return out


def _model_for(language: str | None, override: str | None) -> str:
    cfg = config.load()["transcription"]
    if override:
        return override
    if language in ("bn", "mixed") or language is None:
        return cfg["whisper_model_bangla"] if language in ("bn", "mixed") else cfg["whisper_model"]
    return cfg["whisper_model"]


def whisper(src: Path, *, language: str | None = None, model: str | None = None, prompt: str | None = None) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover
        raise VeditError("faster-whisper is not installed. Run `vedit setup`.") from exc
    cfg = config.load()["transcription"]
    model_name = _model_for(language, model)
    lang = None if language in (None, "auto", "mixed") else language
    # First use downloads the model (~1.6 GB for large-v3-turbo). On slow links the Hugging Face
    # chunked transfer can stall; a longer timeout plus resumable plain HTTP is more forgiving.
    import os
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    work = cache_dir() / "audio"
    work.mkdir(parents=True, exist_ok=True)
    audio = _audio_for(src, work)
    t0 = time.time()
    wm = WhisperModel(model_name, device="auto", compute_type=cfg["whisper_compute_type"],
                      download_root=str(cache_dir() / "whisper"))
    # Feed samples directly: faster-whisper's own decoder depends on PyAV APIs that change between
    # versions (e.g. `metadata_errors` was removed); our FFmpeg-extracted 16 kHz mono WAV avoids that.
    import wave

    import numpy as np
    with wave.open(str(audio), "rb") as w:
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    segments, info = wm.transcribe(
        samples, language=lang, word_timestamps=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 250, "speech_pad_ms": 120},
        beam_size=5, condition_on_previous_text=False,
        initial_prompt=prompt or VERBATIM_PROMPTS.get(lang, VERBATIM_PROMPTS[None]),
    )
    words, segs = [], []
    for seg in segments:
        segs.append({"s": round(seg.start, 3), "e": round(seg.end, 3), "text": seg.text.strip()})
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"w": text, "s": round(w.start, 3), "e": round(w.end, 3), "p": round(w.probability, 3),
                              "type": "word"})
    return {"engine": "whisper", "model": model_name, "language": info.language,
            "language_probability": round(info.language_probability, 3), "words": words, "segments": segs,
            "elapsed_s": round(time.time() - t0, 1)}


def scribe(src: Path, *, language: str | None = None, model: str | None = None, diarize: bool = True) -> dict:
    import httpx
    key = config.secret("elevenlabs")
    if not key:
        raise VeditError("No ElevenLabs API key. Set ELEVENLABS_API_KEY or run `vedit secret set elevenlabs <key>`.")
    cfg = config.load()["transcription"]
    work = cache_dir() / "audio"
    work.mkdir(parents=True, exist_ok=True)
    upload = work / f"{src.stem}.scribe.mp3"
    if not upload.exists() or upload.stat().st_mtime < src.stat().st_mtime:
        run([ffmpeg(), "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "22050", "-b:a", "64k", str(upload)])
    data = {"model_id": model or cfg["scribe_model"], "timestamps_granularity": "word", "tag_audio_events": "true",
            "diarize": "true" if diarize else "false"}
    if language and language not in ("auto", "mixed"):
        data["language_code"] = language
    t0 = time.time()
    with open(upload, "rb") as f:
        resp = httpx.post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": key}, data=data,
                          files={"file": (upload.name, f, "audio/mpeg")}, timeout=1800)
    if resp.status_code >= 400:
        raise VeditError(f"Scribe error {resp.status_code}: {resp.text[:500]}")
    body = resp.json()
    words = []
    for w in body.get("words", []):
        kind = w.get("type")
        if kind == "spacing" or w.get("start") is None:
            continue
        words.append({"w": w.get("text", "").strip(), "s": round(w["start"], 3), "e": round(w["end"], 3),
                      "p": round(2.718281828 ** w["logprob"], 3) if w.get("logprob") is not None else None,
                      "type": "event" if kind == "audio_event" else "word", "speaker": w.get("speaker_id")})
    return {"engine": "scribe", "model": data["model_id"], "language": body.get("language_code"),
            "language_probability": body.get("language_probability"), "words": words,
            "segments": _segments_from_words(words), "elapsed_s": round(time.time() - t0, 1)}


def _segments_from_words(words: list[dict], gap: float = 0.7) -> list[dict]:
    segs: list[dict] = []
    cur: list[dict] = []
    for w in words:
        if w["type"] != "word":
            continue
        if cur and (w["s"] - cur[-1]["e"] > gap or cur[-1]["w"].endswith((".", "?", "!", "।"))):
            segs.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["w"] for x in cur)})
            cur = []
        cur.append(w)
    if cur:
        segs.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["w"] for x in cur)})
    return segs


def transcribe_file(src: str | Path, out: str | Path, *, engine: str = "whisper", language: str | None = None,
                    model: str | None = None, force: bool = False) -> dict:
    src = Path(src).resolve()
    out = Path(out)
    existing = read_json(out)
    if existing and not force and existing.get("source") == str(src):
        return existing
    info = probe(src)
    if not info.has_audio:
        raise VeditError(f"{src.name} has no audio track to transcribe.")
    if engine == "scribe":
        result = scribe(src, language=language, model=model)
    elif engine == "whisper":
        result = whisper(src, language=language, model=model)
    else:
        raise VeditError("engine must be 'whisper' or 'scribe' (the skill asks the user per project).")
    result = {"version": 1, "source": str(src), "duration": round(info.duration, 3), **result}
    write_json(out, result)
    return result
