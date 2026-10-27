"""ElevenLabs voiceover + instant voice clone. Output includes a word-timed transcript in vedit's normal
format, so captions and cuts work on generated voiceovers exactly like on recorded speech."""

from __future__ import annotations

import base64
from pathlib import Path

from . import config
from .paths import personal_dir
from .util import VeditError, read_json, write_json

API = "https://api.elevenlabs.io/v1"


def _key() -> str:
    key = config.secret("elevenlabs")
    if not key:
        raise VeditError("No ElevenLabs API key. Run `vedit secret set elevenlabs <key>` (or set ELEVENLABS_API_KEY).")
    return key


def voices() -> list[dict]:
    import httpx
    r = httpx.get(f"{API}/voices", headers={"xi-api-key": _key()}, timeout=60)
    r.raise_for_status()
    mine = read_json(personal_dir() / "voices.json", default={}) or {}
    return [{"voice_id": v["voice_id"], "name": v["name"], "category": v.get("category"),
             "mine": v["voice_id"] in mine.values()} for v in r.json().get("voices", [])]


def models() -> list[dict]:
    import httpx
    r = httpx.get(f"{API}/models", headers={"xi-api-key": _key()}, timeout=60)
    r.raise_for_status()
    return [{"model_id": m["model_id"], "name": m.get("name"), "tts": m.get("can_do_text_to_speech"),
             "languages": [l.get("language_id") for l in m.get("languages", [])]} for m in r.json()]


def pick_model(language: str | None) -> str:
    preferred = ["eleven_v3", "eleven_multilingual_v2", "eleven_turbo_v2_5", "eleven_flash_v2_5"]
    try:
        avail = {m["model_id"]: m for m in models() if m["tts"]}
    except Exception:
        return "eleven_multilingual_v2"
    for mid in preferred:
        m = avail.get(mid)
        if m and (not language or not m["languages"] or language in m["languages"]):
            return mid
    return next(iter(avail), "eleven_multilingual_v2")


def _words_from_alignment(text_alignment: dict) -> list[dict]:
    chars = text_alignment.get("characters", [])
    starts = text_alignment.get("character_start_times_seconds", [])
    ends = text_alignment.get("character_end_times_seconds", [])
    words, cur, s = [], "", None
    for ch, a, b in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append({"w": cur, "s": round(s, 3), "e": round(prev_end, 3), "p": 1.0, "type": "word"})
            cur, s = "", None
            continue
        if s is None:
            s = a
        cur += ch
        prev_end = b
    if cur:
        words.append({"w": cur, "s": round(s, 3), "e": round(prev_end, 3), "p": 1.0, "type": "word"})
    return words


def speak(text: str, out: str | Path, *, voice: str, model: str | None = None, language: str | None = None,
          stability: float = 0.45, similarity: float = 0.8, style: float = 0.15, speed: float = 1.0) -> dict:
    import httpx
    mine = read_json(personal_dir() / "voices.json", default={}) or {}
    voice_id = mine.get(voice, voice)
    model = model or pick_model(language)
    body = {"text": text, "model_id": model,
            "voice_settings": {"stability": stability, "similarity_boost": similarity, "style": style, "speed": speed}}
    if language and model != "eleven_multilingual_v2":
        body["language_code"] = language
    r = httpx.post(f"{API}/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128",
                   headers={"xi-api-key": _key()}, json=body, timeout=600)
    if r.status_code >= 400:
        raise VeditError(f"ElevenLabs TTS error {r.status_code}: {r.text[:400]}")
    data = r.json()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(data["audio_base64"]))
    words = _words_from_alignment(data.get("alignment") or data.get("normalized_alignment") or {})
    transcript = {"version": 1, "source": str(out.resolve()), "engine": "elevenlabs-tts", "model": model,
                  "language": language, "duration": words[-1]["e"] if words else 0, "words": words,
                  "segments": [{"s": words[0]["s"], "e": words[-1]["e"], "text": text}] if words else []}
    tpath = out.with_suffix(".transcript.json")
    write_json(tpath, transcript)
    return {"audio": str(out), "transcript": str(tpath), "model": model, "voice_id": voice_id}


def clone(name: str, files: list[str | Path], *, description: str = "", remove_noise: bool = True) -> dict:
    """Instant voice clone from 1-25 clean samples (1-3 minutes total is plenty). Requires consent of the speaker."""
    import httpx
    handles = [("files", (Path(f).name, open(f, "rb"))) for f in files]
    try:
        r = httpx.post(f"{API}/voices/add", headers={"xi-api-key": _key()},
                       data={"name": name, "description": description, "remove_background_noise": str(remove_noise).lower()},
                       files=handles, timeout=600)
    finally:
        for _, (_, fh) in handles:
            fh.close()
    if r.status_code >= 400:
        raise VeditError(f"Voice clone failed {r.status_code}: {r.text[:400]}")
    vid = r.json()["voice_id"]
    mine = read_json(personal_dir() / "voices.json", default={}) or {}
    mine[name] = vid
    write_json(personal_dir() / "voices.json", mine)
    return {"name": name, "voice_id": vid}
