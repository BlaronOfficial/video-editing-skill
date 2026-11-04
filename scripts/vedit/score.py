"""Music made in code for an edit (`vedit score compose`): a bed shaped by the edit itself, with no licence limits.

A mood recipe (presets/scores/<mood>.json: tempo range, key, mode, chord progression, instruments, density per
section) and the edit's shape (its length, its chapters, the payoff) become a score: sparse at the start, fuller
toward the peak, a hard stop into a short silence before the payoff, the loudest hit on it, a held chord after,
then a decay. It is written as a score body for animate's synth (anim/kit/score-*.js: pad, pluck, bass, sub, noise
hits, risers, chimes, reverb, a loudness stage; MIT, (c) 2026 cth9191), rendered headless in Chrome
(OfflineAudioContext) into mix / music / sfx stems, and added as a music clip that ducks under speech.

It is a fallback bed: the owner's own tracks and good library music rank above it in the route planner. Claude
can't hear it; the numbers are measured (loudness, the silence before the payoff) and the owner listens.
"""

from __future__ import annotations

import random
import re
import shutil
from pathlib import Path

from .paths import SKILL_ROOT, personal_dir
from .util import VeditError, read_json, write_json

MOODS_DIR = SKILL_ROOT / "presets" / "scores"
PC = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8,
      "A": 9, "A#": 10, "Bb": 10, "B": 11}
SCALES = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10], "dorian": [0, 2, 3, 5, 7, 9, 10]}
ROMAN = {"i": 0, "ii": 1, "iii": 2, "iv": 3, "v": 4, "vi": 5, "vii": 6}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

DRUMS_JS = """
// ---- drums and hits for edit scores (built on the kit's osc / env / out / noiseHit)
function kick(t, vel) { const o = osc('sine', 150, t, t + 0.4); o.frequency.exponentialRampToValueAtTime(42, t + 0.12);
  const g = ac.createGain(); env(g, t, 0.002, vel, 0.28); o.connect(g); out(g); noiseHit(t, 0.012, 'highpass', 3000, 0.7, vel * 0.22); }
function snare(t, vel) { noiseHit(t, 0.16, 'bandpass', 1900, 0.9, vel, 0, 0.12);
  const o = osc('triangle', 190, t, t + 0.14); const g = ac.createGain(); env(g, t, 0.002, vel * 0.45, 0.1); o.connect(g); out(g); }
function hat(t, vel, open) { noiseHit(t, open ? 0.18 : 0.035, 'highpass', 7600, 0.8, vel, 0.12); }
"""


def moods() -> dict[str, dict]:
    out = {}
    for d in (MOODS_DIR, personal_dir() / "scores"):
        if d.exists():
            for f in sorted(d.glob("*.json")):
                out[f.stem] = {**(read_json(f) or {}), "file": str(f)}
    return out


def _midi_name(m: int) -> str:
    return f"{NAMES[m % 12]}{m // 12 - 1}"


def chord(numeral: str, key_pc: int, mode: str) -> list[int]:
    """Pitch classes (as MIDI offsets from C-1) of a roman-numeral chord: I, vi, VI, ii7, V7, Imaj7, bVII."""
    m = re.match(r"^(b?)([ivIV]+)(maj7|7)?$", numeral)
    if not m:
        raise VeditError(f"chord '{numeral}': use roman numerals like I, vi, V7, Imaj7, bVII")
    flat, rom, ext = m.groups()
    scale = SCALES.get(mode, SCALES["major"])
    root = key_pc + scale[ROMAN[rom.lower()]] - (1 if flat else 0)
    third = 4 if rom.isupper() else 3
    notes = [root, root + third, root + 7]
    if ext == "7":
        notes.append(root + 10)
    elif ext == "maj7":
        notes.append(root + 11)
    return notes


def _place(pcs: list[int], lo: int, hi: int) -> list[int]:
    """Each pitch class into [lo, hi], sorted (a close voicing)."""
    out = []
    for p in pcs:
        n = lo + ((p - lo) % 12)
        while n > hi:
            n -= 12
        out.append(n)
    return sorted(set(out))


def sections(length: float, payoff: float | None, beat: float, chapters: list[float]) -> list[dict]:
    """The arc: intro, build, peak, silence (before the payoff), gift (the payoff, held), outro."""
    bar = 4 * beat
    if payoff is not None and 2 * bar < payoff < length - 0.5:
        sil = min(1.2, max(0.5, 2 * beat))
        intro_end = min(payoff * 0.25, 8.0)
        peak0 = max(intro_end, payoff - sil - 2 * bar)
        gift_end = min(length, payoff + 2 * bar)
        rows = [("intro", 0.0, intro_end), ("build", intro_end, peak0), ("peak", peak0, payoff - sil),
                ("silence", payoff - sil, payoff), ("gift", payoff, gift_end), ("outro", gift_end, length)]
    else:
        rows = [("intro", 0.0, length * 0.15), ("build", length * 0.15, length * 0.55),
                ("peak", length * 0.55, length * 0.85), ("outro", length * 0.85, length)]
    return [{"role": r, "t0": round(a, 3), "t1": round(b, 3)} for r, a, b in rows if b - a > 0.05]


def compose(length: float, *, mood: str = "warm", bpm: float | None = None, key: str | None = None, mode: str | None = None,
            payoff: float | None = None, chapters: list[float] = (), seed: str = "vedit") -> tuple[str, dict]:
    """Write the score body (JavaScript for anim/kit/score-head.js) and a summary of what it plays."""
    rec = moods().get(mood)
    if not rec:
        raise VeditError(f"Unknown mood '{mood}'. Moods: {', '.join(moods())}")
    rnd = random.Random(f"{seed}|{mood}|{length:.2f}")
    lo, hi = rec.get("bpm", [96, 110])
    bpm = float(bpm or round(rnd.uniform(lo, hi)))
    beat = 60.0 / bpm
    bar = 4 * beat
    key = key or rec.get("key", "C")
    mode = mode or rec.get("mode", "major")
    key_pc = PC.get(key.replace("s", "#"), 0)
    prog = rec.get("progression", ["I", "V", "vi", "IV"])
    dens = rec.get("density", {})
    pad, pl, bs, dr = rec.get("pad", {}), rec.get("pluck", {}), rec.get("bass", {}), rec.get("drums", {})
    swing = float(rec.get("swing", 0))
    secs = sections(length, payoff, beat, list(chapters))
    # the grid: bars run so the payoff lands on a bar line
    g0 = (payoff % bar) if payoff is not None else 0.0
    if g0 > 0:
        g0 -= bar
    silence = next((s for s in secs if s["role"] == "silence"), None)
    gift = next((s for s in secs if s["role"] == "gift"), None)
    stop = silence["t0"] if silence else None

    def sec_at(t: float) -> dict:
        return next((s for s in secs if s["t0"] <= t < s["t1"]), secs[-1])

    def live(t: float, d: float = 0.0) -> bool:
        """An event may sound only outside the silence and the held gift, and must end before the silence."""
        if t < 0 or t >= length:
            return False
        s = sec_at(t)
        if s["role"] in ("silence", "gift"):
            return False
        return stop is None or t >= (gift["t1"] if gift else stop) or t + d <= stop - 0.02

    js = [f"// edit score: {mood} ({rec.get('about', '')}); {bpm:.0f} BPM, {key} {mode}; generated by vedit score",
          DRUMS_JS]
    n_events = 0
    k = 0
    t = g0
    while t < length:
        ch = chord(prog[k % len(prog)], key_pc, mode)
        k += 1
        b0, b1 = t, t + bar
        t = b1
        s = sec_at(max(0.0, b0 + 0.01))
        d = float(dens.get(s["role"], 0.6))
        # pad: the bar's chord, ended before a silence
        p0, p1 = max(0.0, b0), min(b1, length + 1.5)
        if stop is not None and p0 < stop < p1:
            p1 = stop - 0.03
        if p1 - p0 > 0.3 and live(p0) and s["role"] not in ("silence", "gift"):
            notes = ", ".join(f"'{_midi_name(n)}'" for n in _place(ch, 55, 67))
            lvl = float(pad.get("level", 0.05)) * (0.6 + 0.4 * d)
            js.append(f"to = 'm'; pad({p0:.3f}, {p1 + 0.25:.3f}, [{notes}], {lvl:.4f}, {{ cut: {pad.get('cut', 1200)}, att: 0.35, rel: 0.25 }});")
            n_events += 1
        # bass
        if d >= 0.5:
            root = _place([ch[0]], 38, 49)[0]
            for h in bs.get("hits", [0, 2]):
                tb = b0 + h * beat
                if live(tb, 0.3):
                    js.append(f"to = 'm'; bass({tb:.3f}, nz('{_midi_name(root)}'), {float(bs.get('level', 0.12)) * (0.7 + 0.3 * d):.4f});")
                    n_events += 1
        # plucks: an arpeggio over the chord, more notes as the density rises
        every = int(pl.get("every", 8))
        step = 4 * beat / every
        tones = _place(ch, 62, 74) + [n + 12 for n in _place(ch, 62, 74)][:2]
        pat = pl.get("pattern", "up")
        for i in range(every):
            tp = b0 + i * step + (swing * step if every >= 8 and i % 2 else 0)
            if not live(tp, 0.35) or rnd.random() > d * (0.55 if pat == "sparse" else 1.0):
                continue
            if pat == "chord":
                if i % 2:
                    continue
                for j, n in enumerate(_place(ch, 60, 72)):
                    js.append(f"to = 'm'; pluck({tp + j * 0.012:.3f}, nz('{_midi_name(n)}'), {float(pl.get('level', 0.07)) * 0.6:.4f}, {(j - 1) * 0.2:.2f}, 0.6, {pl.get('bright', 2400)}, 0.3);")
                    n_events += 1
                continue
            if pat == "pulse":
                n = tones[0]
            elif pat == "updown":
                cyc = tones + tones[-2:0:-1]
                n = cyc[i % len(cyc)]
            elif pat == "bounce":
                n = tones[(i * 2) % len(tones)] if i % 2 == 0 else tones[(i * 2 + 1) % len(tones)] + (12 if i % 4 == 1 else 0)
            else:
                n = tones[i % len(tones)]
            vel = float(pl.get("level", 0.07)) * (1.15 if i % 4 == 0 else 0.85) * (0.75 + 0.25 * d) * rnd.uniform(0.9, 1.05)
            dur = 0.18 if pl.get("short") else 0.32
            js.append(f"to = 'm'; pluck({tp:.3f}, nz('{_midi_name(n)}'), {vel:.4f}, {rnd.uniform(-0.3, 0.3):.2f}, {dur}, {pl.get('bright', 2800)}, 0.25);")
            n_events += 1
        # drums (from the build on; the peak plays everything)
        lv = float(dr.get("level", 0.5))
        if lv > 0 and s["role"] in ("build", "peak", "outro") and not (s["role"] == "outro" and d < 0.45):
            for h in dr.get("kick", []):
                tk = b0 + h * beat
                if live(tk, 0.3):
                    js.append(f"to = 'm'; kick({tk:.3f}, {lv * 0.55:.3f});")
                    n_events += 1
            if s["role"] != "build" or d >= 0.6:
                for h in dr.get("snare", []):
                    tk = b0 + h * beat
                    if live(tk, 0.2):
                        js.append(f"to = 'm'; snare({tk:.3f}, {lv * 0.32:.3f});")
                        n_events += 1
            for h in dr.get("hat", []):
                tk = b0 + h * beat + (swing * beat / 2 if (h * 2) % 2 else 0)
                if live(tk, 0.05) and rnd.random() < (0.5 if s["role"] == "build" else 0.95):
                    js.append(f"to = 'm'; hat({tk:.3f}, {lv * 0.07 * rnd.uniform(0.8, 1.1):.4f}, false);")
                    n_events += 1
            for h in dr.get("boom", []):
                tk = b0 + h * beat
                if live(tk, 0.6) and s["role"] == "peak":
                    js.append(f"to = 'm'; sub({tk:.3f}, {lv * 0.5:.3f});")
                    n_events += 1
            for h in dr.get("blip", []):
                tk = b0 + h * beat
                if live(tk, 0.1):
                    js.append(f"to = 's'; blip({tk:.3f}, 900, 1500, 0.06, {lv * 0.05:.3f});")
                    n_events += 1
        # a drone under tense / epic beds
        if rec.get("drone") and live(max(0.0, b0)) and s["role"] in ("intro", "build", "peak"):
            dn = _place([key_pc], 38, 49)[0]
            d1 = min(b1, stop - 0.03) if stop is not None and b0 < stop else b1
            if d1 - max(0.0, b0) > 0.4:
                js.append(f"to = 'm'; drone({max(0.0, b0):.3f}, {d1:.3f}, nz('{_midi_name(dn)}'), {float(rec['drone'].get('level', 0.05)):.4f});")
                n_events += 1
    # the arc's moments: a riser into the silence, the payoff hit, the held chord; sweeps into chapters
    if silence and gift:
        r0 = max(0.0, silence["t0"] - 2 * beat)
        js.append(f"to = 's'; riser({r0:.3f}, {silence['t0'] - 0.02:.3f}, 0.05);")
        P = gift["t0"]
        last = chord(prog[0], key_pc, mode)
        notes = _place(last, 55, 67)
        js.append(f"to = 's'; sub({P:.3f}, 0.9);")
        for j, n in enumerate(_place(last, 60, 76)):
            js.append(f"to = 's'; pluck({P + j * 0.008:.3f}, nz('{_midi_name(n)}'), 0.16, {(j - 1) * 0.25:.2f}, 0.45, 4200, 0.4);")
        js.append(f"to = 's'; chime({P:.3f}, [{', '.join(f'nz({chr(39)}{_midi_name(n + 12)}{chr(39)})' for n in notes)}], 0.06);")
        names = ", ".join(f"'{_midi_name(n)}'" for n in notes)
        js.append(f"to = 'm'; pad({P + 0.05:.3f}, {gift['t1']:.3f}, [{names}], {float(pad.get('level', 0.05)) * 0.8:.4f}, "
                  f"{{ cut: {pad.get('cut', 1200)}, att: 0.08, rel: 0.6 }});")
        n_events += 6
    for c in chapters:
        if 2 * bar < c < length - bar and live(c - bar, bar):
            js.append(f"to = 's'; sweep({c - bar:.3f}, {c - 0.02:.3f}, 0.035, 300, 5200);")
            n_events += 1
    # the end: the home chord rings out
    end_ch = _place(chord(prog[0], key_pc, mode), 55, 67)
    js.append(f"to = 'm'; pad({max(0.0, length - 2 * bar):.3f}, {length + 1.2:.3f}, [{', '.join(repr(_midi_name(n)) for n in end_ch)}], "
              f"{float(pad.get('level', 0.05)) * 0.7:.4f}, {{ cut: {pad.get('cut', 1200)}, att: 0.6, rel: 1.4 }});")
    info = {"mood": mood, "bpm": bpm, "key": key, "mode": mode, "grid0": round(g0, 3), "sections": secs,
            "payoff": payoff, "chapters": list(chapters), "events": n_events, "length": round(length, 3)}
    return "\n".join(js) + "\n", info


def _page(body: str, length: float) -> str:
    from .anim import ANIM
    head = ("<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>edit score</title></head><body>\n"
            "<canvas id=\"c\" width=\"16\" height=\"16\"></canvas>\n<script>\n\"use strict\";\n"
            f"const FPS = 24, W = 16, H = 16, DURATION = {length:.3f}, NFRAMES = Math.round(DURATION * FPS), LOOP_T = DURATION;\n"
            "const LOOP_AUDIO = false;\n"
            "const TIMELINE = { width: W, height: H, fps: FPS, duration: DURATION, narration: [] };\nwindow.TIMELINE = TIMELINE;\n"
            "function renderFrame() {}\nwindow.__duration = DURATION;\n")
    kit = ANIM / "kit"
    return (head + (kit / "core.js").read_text(encoding="utf-8") + "\n" + (kit / "score-head.js").read_text(encoding="utf-8")
            + "\n" + body + "\n" + (kit / "score-tail.js").read_text(encoding="utf-8"))


def compose_for_edit(proj, *, mood: str = "warm", name: str = "score", bpm: float | None = None, key: str | None = None,
                     mode: str | None = None, payoff: float | None = None, length: float | None = None,
                     db: float | None = None, add: bool = True) -> dict:
    from .anim.pieces import _renderer
    from .assets import add_provenance
    from .media import probe
    from .timeline import AudioClip, Source
    edit = proj.edit().layout()
    L = float(length or edit.duration)
    if L <= 1:
        raise VeditError("The edit has no length yet: cut it first, or pass --length")
    if payoff is None:
        pm = next((m for m in edit.markers if m.name.lower().startswith("payoff") or "payoff" in m.note.lower()), None)
        payoff = pm.t if pm else None
    chapters = [m.t for m in edit.markers if m.kind == "chapter"]
    body, info = compose(L, mood=mood, bpm=bpm, key=key, mode=mode, payoff=payoff, chapters=chapters, seed=proj.root.name)
    d = proj.sub("sound") / "score" / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    (d / "score.js").write_text(body, encoding="utf-8")
    page = d / "score.html"
    page.write_text(_page(body, L), encoding="utf-8")
    res = _renderer(["--input", str(page), "--audio", str(d / "score"), "--audio-parts", "mix", "--width", "16",
                     "--height", "16", "--fps", "24"], timeout=3600)
    mix = Path(res["audio"]["mix"])
    write_json(d / "recipe.json", info)
    out = {"score": str(mix), "stems": res["audio"], **info, "page": str(page),
           "licence": "own: generated in code by vedit (no licence limits)"}
    add_provenance(proj.root, mix, source="vedit score", license="own (generated in code)",
                   notes=f"{mood} bed, {info['bpm']:.0f} BPM {info['key']} {info['mode']}")
    if add:
        edit = proj.edit()
        sid = f"score_{name}"
        edit.audio = [a for a in edit.audio if a.id != sid]
        from .anim.pieces import has_speech
        level = db if db is not None else (-12.0 if has_speech(edit) else 0.0)
        pi = probe(mix)
        edit.sources[sid] = Source(id=sid, path=str(mix.resolve()), kind="audio", duration=round(pi.duration, 3),
                                   has_audio=True, origin="vedit score", notes=[f"code score: {mood}, {info['bpm']:.0f} BPM"])
        edit.audio.append(AudioClip(id=sid, source=sid, start=0.0, src_out=round(min(pi.duration, L + 1.5), 3),
                                    volume=round(10 ** (level / 20), 4), role="music", duck=True, fade_out=1.0,
                                    label=f"score: {mood}"))
        proj.save_edit(edit)
        proj.log(f"score: composed a {mood} bed ({info['bpm']:.0f} BPM, {info['key']} {info['mode']}) at {level:+.0f} dB")
        out["clip"] = sid
        out["level_db"] = level
    out["next"] = "render and listen (Claude can't hear it); QA measures the silence before the payoff"
    return out


def register_cli(sp) -> None:
    s = sp.add_parser("score", help="music made in code, shaped by the edit (a fallback bed with no licence limits)")
    s.add_argument("action", choices=["moods", "compose"])
    s.add_argument("path", nargs="?")
    s.add_argument("--mood", default="warm"); s.add_argument("--name", default="score")
    s.add_argument("--bpm", type=float); s.add_argument("--key"); s.add_argument("--mode", choices=list(SCALES))
    s.add_argument("--payoff", type=float, help="seconds: the moment the score hits hardest (default: a `payoff` marker)")
    s.add_argument("--length", type=float); s.add_argument("--db", type=float, help="level (default -12 under speech, 0 without)")
    s.add_argument("--no-add", action="store_true", help="render only; don't put it in the edit")
    s.set_defaults(fn=_cmd)


def _cmd(a) -> None:
    from .util import print_json
    if a.action == "moods":
        print_json({k: v.get("about", "") for k, v in moods().items()})
        return
    from .project import find
    if not a.path:
        raise VeditError("vedit score compose <project> --mood warm")
    print_json(compose_for_edit(find(a.path), mood=a.mood, name=a.name, bpm=a.bpm, key=a.key, mode=a.mode,
                                payoff=a.payoff, length=a.length, db=a.db, add=not a.no_add))
