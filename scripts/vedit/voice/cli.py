"""`vedit voice ...`: list voices (with licences), speak, voiceover into a project, clone (consent first),
compare voices."""

from __future__ import annotations

from pathlib import Path

from ..util import VeditError, print_json


def _script(a) -> str:
    if a.text:
        return a.text
    if a.file:
        return Path(a.file).read_text(encoding="utf-8")
    raise VeditError("Give the words: --text \"...\" or --file script.txt")


def cmd(a) -> None:
    from . import engine
    if a.action == "list":
        rows = engine.list_voices(language=a.language, ready_only=a.ready)
        if not a.all:
            rows = [{k: r.get(k) for k in ("id", "language", "gender", "commercial", "online", "ready", "licence")} for r in rows]
        print_json(rows)
    elif a.action == "say":
        if not a.voice:
            raise VeditError("--voice is required (see `vedit voice list`)")
        out = a.out or f"voice_{a.voice.replace(':', '_').replace('@', '_')}.wav"
        print_json(engine.say(_script(a), out, a.voice, speed=a.speed, language=a.language, align=a.align))
    elif a.action == "vo":
        from ..project import find
        if not (a.path and a.voice):
            raise VeditError("vedit voice vo <project> --voice <id> --file script.txt [--place main|audio] [--at 0]")
        print_json(engine.vo(find(a.path), _script(a), a.voice, name=a.name, place=a.place, at=a.at, speed=a.speed,
                             language=a.language))
    elif a.action == "clone":
        if not (a.path and a.files):
            raise VeditError("vedit voice clone <name> --files a.wav b.wav --consent \"I, <speaker>, agree ...\"")
        print_json(engine.clone(a.path, a.files, consent=a.consent or "", speaker=a.speaker or "", eleven=a.eleven))
    elif a.action == "compare":
        if not a.files or len(a.files) != 2:
            raise VeditError("vedit voice compare --files a.wav b.wav")
        print_json({"similarity": round(engine.similarity(a.files[0], a.files[1]), 3),
                    "reading": "same speaker usually > 0.6; different speakers usually < 0.4"})
    elif a.action == "setup":
        print_json(engine.setup(a.path or "voice"))


def register_cli(sp) -> None:
    s = sp.add_parser("voice", help="voices: offline / online / cloned narration with word timings and licences")
    s.add_argument("action", choices=["list", "say", "vo", "clone", "compare", "setup"])
    s.add_argument("path", nargs="?", help="project (vo), voice name (clone), tool (setup: voice|openvoice)")
    s.add_argument("--voice"); s.add_argument("--text"); s.add_argument("--file"); s.add_argument("--out")
    s.add_argument("--speed", type=float, default=1.0); s.add_argument("--language")
    s.add_argument("--name", default="vo"); s.add_argument("--place", default="main", choices=["main", "audio"])
    s.add_argument("--at", type=float, default=0.0); s.add_argument("--files", nargs="*")
    s.add_argument("--consent", help="the speaker's own words agreeing to the clone"); s.add_argument("--speaker")
    s.add_argument("--eleven", action="store_true", help="clone: also upload the samples to ElevenLabs (ask first)")
    s.add_argument("--ready", action="store_true"); s.add_argument("--all", action="store_true")
    s.add_argument("--align", default="auto", choices=["auto", "whisper", "proportional"],
                   help="word timing for offline voices: auto = Whisper for English, spread inside sentences otherwise")
    s.set_defaults(fn=cmd)
