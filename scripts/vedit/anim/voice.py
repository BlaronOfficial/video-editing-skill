"""A piece's voice-over, from vedit's own voices: the voice is the clock.

<piece>/voice/script.json
    {"voice": "kokoro:af_heart", "lead": 0.8, "tail": 1.5,
     "lines": [{"id": "open", "text": "As it is spoken.", "after": 0.45}, ...]}
One line per beat; `after` is the pause after the line (give the picture time to land: a count, a caption, the
silence before the payoff). Writes <piece>/voice/voice.wav + its transcript, and <piece>/voice.json, which the
build injects as VOICE: {duration, voice, lines: [{id, text, t0, t1, words: [{w, t0, t1}]}]}. Scenes cue on it with
VL(id) / VW(id, word, n); a re-take or an edited line moves the picture on the next build.
"""

from __future__ import annotations

from pathlib import Path

from ..util import VeditError, read_json, write_json
from .pieces import piece_dir

SCRATCH = {"en": "kokoro:af_heart", "bn": "bn_mimic3:0"}       # offline timing voices (no network, no licence worry)


def speak(proj, name: str, *, voice: str | None = None, speed: float = 1.0, language: str | None = None,
          scratch: bool = False) -> dict:
    from ..voice import engine
    from ..voice import text as T
    pd = piece_dir(proj, name)
    sf = pd / "voice" / "script.json"
    sc = read_json(sf, default=None)
    if not sc or not sc.get("lines"):
        raise VeditError(f"Write the script first: {sf} with \"lines\": [{{\"id\", \"text\", \"after\"}}, ...]")
    joined = " ".join(str(l.get("text", "")) for l in sc["lines"])
    lang = language or sc.get("language") or ("bn" if T.is_bangla(joined) else "en")
    v = SCRATCH.get(lang, SCRATCH["en"]) if scratch else (voice or sc.get("voice") or SCRATCH.get(lang, SCRATCH["en"]))
    res = engine.say("", pd / "voice" / "voice.wav", v, speed=speed, language=lang, lines=sc["lines"],
                     lead=float(sc.get("lead", 0.8)), tail=float(sc.get("tail", 1.5)))
    tr = read_json(Path(res["transcript"]))
    lines = tr.get("lines") or []
    out = {"duration": tr["duration"], "voice": v, "language": lang, "scratch": bool(scratch),
           "lead": float(sc.get("lead", 0.8)), "tail": float(sc.get("tail", 1.5)), "lines": lines,
           "alignment": tr.get("alignment"), "licence": tr.get("licence")}
    write_json(pd / "voice.json", out)
    m = read_json(pd / "piece.json", default={}) or {}
    m.setdefault("voice", {"file": "voice/voice.wav", "music": -12})
    write_json(pd / "piece.json", m)
    from ..checks import line_pace
    pace = line_pace(lines, lang)
    return {"piece": name, "voice": v, "scratch": bool(scratch), "duration": tr["duration"], "lines": len(lines),
            "words": sum(len(l.get("words", [])) for l in lines), "alignment": tr.get("alignment"),
            "licence": tr.get("licence"), "fast_lines": [p for p in pace if not p["ok"]],
            "voice_json": str(pd / "voice.json"),
            "next": "rebuild: scenes cued with VL()/VW() follow the voice; the scratch voice is for timing only"
                    if scratch else "rebuild and check the cues (vedit anim still / review)"}
