"""Captions: word chunking, style presets, ASS (render), SRT/VTT (sidecar), shared with the CapCut builder.

Caption sizes are fractions of min(canvas width, height) so one preset works for 9:16 and 16:9.
Vertical position `y` uses half-canvas units from the centre, +up (CapCut convention).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from .paths import personal_dir, presets_dir
from .timeline import CaptionChunk, Edit, Word
from .util import VeditError, read_json, write_text

BANGLA_RE = re.compile(r"[ঀ-৿]")
PUNCT_END = re.compile(r"[.!?।…]$")
PUNCT_SOFT = re.compile(r"[,;:—–-]$")

BASE_STYLE: dict[str, Any] = {
    "mode": "karaoke",            # karaoke | word | chunk | sentence
    "max_words": 3,
    "max_chars": 22,
    "font": "Poppins ExtraBold",
    "font_bangla": "Hind Siliguri SemiBold",
    "size": 0.085,                # fraction of min(width, height)
    "color": "#FFFFFF",
    "highlight": "#FFE14D",
    "stroke": "#000000",
    "stroke_width": 0.09,         # fraction of font size
    "shadow": 0.04,               # fraction of font size
    "shadow_color": "#000000AA",
    "background": None,           # {"color": "#000000", "alpha": 0.55}
    "y": -0.42,                   # lower third of a vertical frame, clear of platform UI
    "y_landscape": -0.72,
    "uppercase": True,
    "bold": True,
    "pop_scale": 1.12,            # active-word scale in karaoke/word modes
    "animation": "pop",           # pop | fade | slide | none
    "letter_spacing": 0,
    "capcut": {"font": None, "intro": None, "size_scale": 1.0},
}


# ------------------------------------------------------------------ presets

def _preset_dirs() -> list[Path]:
    return [presets_dir() / "captions", personal_dir() / "styles" / "captions"]


def list_presets() -> dict[str, dict]:
    found: dict[str, dict] = {}
    for d in _preset_dirs():
        if d.is_dir():
            for f in sorted(d.glob("*.json")):
                data = read_json(f) or {}
                found[data.get("name", f.stem)] = data
    return found


def resolve_style(name_or_dict: str | dict | None, overrides: dict | None = None) -> dict[str, Any]:
    style = dict(BASE_STYLE)
    style["capcut"] = dict(BASE_STYLE["capcut"])
    preset: dict[str, Any] = {}
    if isinstance(name_or_dict, dict):
        preset = name_or_dict
    elif name_or_dict:
        presets = list_presets()
        if name_or_dict not in presets:
            raise VeditError(f"Unknown caption style '{name_or_dict}'. Available: {', '.join(sorted(presets))}")
        preset = presets[name_or_dict]
    for src in (preset, overrides or {}):
        for k, v in src.items():
            if k == "capcut" and isinstance(v, dict):
                style["capcut"].update(v)
            else:
                style[k] = v
    # Learned adjustments (from diffs of the user's CapCut edits) arrive as relative tweaks.
    if style.get("size_scale"):
        style["size"] = round(style["size"] * float(style.pop("size_scale")), 4)
    if style.get("y_delta"):
        delta = float(style.pop("y_delta"))
        style["y"] = round(style["y"] + delta, 3)
        style["y_landscape"] = round(style.get("y_landscape", style["y"]) + delta, 3)
    return style


def is_bangla(text: str) -> bool:
    return bool(BANGLA_RE.search(text or ""))


# ------------------------------------------------------------------ chunking

def chunk_words(words: list[Word], *, max_words: int = 3, max_chars: int = 22, pause_break: float = 0.35,
                mode: str = "karaoke") -> list[CaptionChunk]:
    """Group timed words into on-screen chunks; break on punctuation and pauses."""
    if mode == "word":
        max_words, max_chars = 1, 999
    elif mode == "sentence":
        max_words, max_chars = max(max_words, 10), max(max_chars, 60)
    chunks: list[CaptionChunk] = []
    cur: list[Word] = []

    def flush() -> None:
        if cur:
            text = " ".join(w.w for w in cur)
            chunks.append(CaptionChunk(start=cur[0].s, end=cur[-1].e, text=text, words=list(cur)))
            cur.clear()

    for i, word in enumerate(words):
        if cur:
            gap = word.s - cur[-1].e
            length = len(" ".join(w.w for w in cur)) + 1 + len(word.w)
            if gap > pause_break or len(cur) >= max_words or length > max_chars:
                flush()
        cur.append(word)
        if PUNCT_END.search(word.w) or (mode != "word" and PUNCT_SOFT.search(word.w) and len(cur) >= 2):
            flush()
    flush()
    # Hold each chunk until the next starts (no flicker), capped so text doesn't linger in silence.
    for a, b in zip(chunks, chunks[1:]):
        a.end = min(b.start, a.end + 0.6) if b.start - a.end < 0.6 else a.end + 0.25
    if chunks:
        chunks[-1].end += 0.3
    return chunks


def transcript_words(path: str | Path) -> list[dict]:
    data = read_json(path) or {}
    return [w for w in data.get("words", []) if w.get("type", "word") == "word" and w.get("w", "").strip()]


def build_chunks(edit: Edit) -> list[CaptionChunk]:
    """Map every kept word through the main track (and voiceover clips) and chunk it with the caption style."""
    style = resolve_style(edit.captions.style, edit.captions.overrides)
    cap = edit.captions
    words: list[Word] = []
    for clip in edit.main:
        src = edit.sources[clip.source]
        if not src.transcript or clip.mute:
            continue
        for w in transcript_words(src.transcript):
            mid = (w["s"] + w["e"]) / 2
            if clip.src_in <= mid <= clip.src_out:
                key = word_key(clip.source, w["s"])
                text = cap.word_fixes.get(key, w["w"].strip())
                if not text.strip():
                    continue
                s = (clip.start or 0) + (max(w["s"], clip.src_in) - clip.src_in) / clip.speed
                e = (clip.start or 0) + (min(w["e"], clip.src_out) - clip.src_in) / clip.speed
                words.append(Word(w=text.strip(), s=round(s, 3), e=round(max(e, s + 0.05), 3), k=key))
    for a in edit.audio:                     # voiceover clips over footage or b-roll speak too
        src = edit.sources.get(a.source)
        if a.role != "vo" or not a.enabled or not src or not src.transcript:
            continue
        end = a.src_out if a.src_out is not None else float("inf")
        for w in transcript_words(src.transcript):
            mid = (w["s"] + w["e"]) / 2
            if a.src_in <= mid <= end:
                key = word_key(a.source, w["s"])
                text = cap.word_fixes.get(key, w["w"].strip())
                if not text.strip():
                    continue
                s = a.start + (w["s"] - a.src_in)
                e = a.start + (min(w["e"], end) - a.src_in)
                words.append(Word(w=text.strip(), s=round(s, 3), e=round(max(e, s + 0.05), 3), k=key))
    words.sort(key=lambda w: w.s)
    max_words = cap.max_words or style["max_words"]
    max_chars = cap.max_chars or style["max_chars"]
    chunks = chunk_words(words, max_words=max_words, max_chars=max_chars, mode=style["mode"])
    total = edit.duration
    emphasis = set(cap.emphasis_keys)
    for c in chunks:          # the hold after the last word must not outlast the video
        c.end = round(min(c.end, total), 3)
        c.emphasis = [i for i, w in enumerate(c.words) if w.k in emphasis]
        c.emoji = next((cap.emoji_keys[w.k] for w in c.words if w.k in cap.emoji_keys), None)
    return [c for c in chunks if c.end - c.start > 0.05]


def word_key(source_id: str, src_start: float) -> str:
    """Stable identity of a transcript word across re-cuts (Studio edits and fixes are keyed by it)."""
    return f"{source_id}@{src_start:.2f}"


# ------------------------------------------------------------------ ASS output

def _ass_color(hex_color: str, alpha: float | None = None) -> str:
    """#RRGGBB[AA] -> &HAABBGGRR (ASS alpha: 00 opaque, FF transparent)."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    if alpha is None:
        a = 255 - int(h[6:8], 16) if len(h) >= 8 else 0
    else:
        a = int(round((1 - alpha) * 255))
    return f"&H{a:02X}{b}{g}{r}".upper()


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def _display(text: str, style: dict) -> str:
    if style.get("uppercase") and not is_bangla(text):
        return text.upper()
    return text


def to_ass(edit: Edit, chunks: Iterable[CaptionChunk], out_path: str | Path, style: dict | None = None) -> Path:
    style = style or resolve_style(edit.captions.style, edit.captions.overrides)
    if edit.captions.uppercase is not None:
        style = {**style, "uppercase": edit.captions.uppercase}
    W, H = edit.canvas.width, edit.canvas.height
    base = min(W, H)
    font_px = max(12, round(style["size"] * base))
    outline = round(style["stroke_width"] * font_px, 1) if style.get("stroke") else 0
    shadow = round(style.get("shadow", 0) * font_px, 1)
    landscape = W > H
    y_units = style.get("y_landscape" if landscape else "y", style["y"])
    cx, cy = W / 2, H / 2 - y_units * H / 2
    bg = style.get("background")
    border_style = 3 if bg else 1
    outline_colour = _ass_color(bg["color"], bg.get("alpha", 0.6)) if bg else _ass_color(style.get("stroke") or "#000000")
    back_colour = _ass_color(style.get("shadow_color", "#000000AA"))
    if bg:
        outline = round(font_px * 0.18, 1)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
    ]
    for name, font in (("Cap", style["font"]), ("CapBn", style["font_bangla"])):
        lines.append(
            f"Style: {name},{font},{font_px},{_ass_color(style['color'])},{_ass_color(style['highlight'])},"
            f"{outline_colour},{back_colour},{-1 if style.get('bold') else 0},0,0,0,100,100,"
            f"{style.get('letter_spacing', 0)},0,{border_style},{outline},{shadow},5,40,40,40,1"
        )
    lines += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]

    hi = _ass_color(style["highlight"])
    base_c = _ass_color(style["color"])
    pop = int(style.get("pop_scale", 1.1) * 100)
    anim = style.get("animation", "pop")

    def event(start: float, end: float, text: str, bn: bool, y_override: float | None) -> str:
        y = H / 2 - y_override * H / 2 if y_override is not None else cy
        return f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{'CapBn' if bn else 'Cap'},,0,0,0,,{{\\pos({cx:.0f},{y:.0f})}}{text}"

    def intro_tag() -> str:
        if anim == "pop":
            return "{\\fscx70\\fscy70\\t(0,90,\\fscx100\\fscy100)}"
        if anim == "fade":
            return "{\\fad(120,0)}"
        if anim == "slide":
            return "{\\alpha&HFF&\\t(0,120,\\alpha&H00&)}"
        return ""

    for chunk in chunks:
        bn = is_bangla(chunk.text)
        words = chunk.words or [Word(w=t, s=chunk.start, e=chunk.end) for t in chunk.text.split()]
        tokens = [_escape(_display(w.w, style)) for w in words]
        emph = set(chunk.emphasis)
        emoji = f" {chunk.emoji}" if chunk.emoji else ""
        mode = style["mode"]
        if mode in ("karaoke", "word") and len(words) > 0:
            for i, w in enumerate(words):
                start = chunk.start if i == 0 else w.s
                end = words[i + 1].s if i + 1 < len(words) else chunk.end
                if end <= start:
                    continue
                if mode == "word":
                    body = f"{{\\c{hi if i in emph else base_c}\\fscx{pop}\\fscy{pop}\\t(0,80,\\fscx100\\fscy100)}}{tokens[i]}"
                else:
                    parts = []
                    for j, tok in enumerate(tokens):
                        if j == i:
                            parts.append(f"{{\\c{hi}\\fscx{pop}\\fscy{pop}}}{tok}{{\\c{base_c}\\fscx100\\fscy100}}")
                        elif j in emph:
                            parts.append(f"{{\\c{hi}}}{tok}{{\\c{base_c}}}")
                        else:
                            parts.append(tok)
                    body = (intro_tag() if i == 0 else "") + " ".join(parts)
                lines.append(event(start, end, body + emoji, bn, chunk.y))
        else:
            parts = [f"{{\\c{hi}}}{tok}{{\\c{base_c}}}" if j in emph else tok for j, tok in enumerate(tokens)]
            body = intro_tag() + " ".join(parts)
            if mode == "sentence":
                body = "{\\fad(100,100)}" + " ".join(parts)
            lines.append(event(chunk.start, chunk.end, body + emoji, bn, chunk.y))
    return write_text(out_path, "\n".join(lines) + "\n")


def titles_to_ass(edit: Edit, out_path: str | Path, *, canvas: tuple[int, int] | None = None) -> Path | None:
    """Burn edit.texts (titles, labels) with the same look the CapCut text segments get."""
    if not edit.texts:
        return None
    W, H = canvas or (edit.canvas.width, edit.canvas.height)
    base = min(W, H)
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0",
             "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
             "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
             "MarginR, MarginV, Encoding"]
    events = ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for i, item in enumerate(edit.texts):
        st = {**BASE_STYLE, "uppercase": False, "stroke_width": 0.07, **item.style}
        font = st["font_bangla"] if is_bangla(item.text) else st["font"]
        px = max(12, round(st["size"] * base))
        bg = st.get("background")
        outline = round(px * 0.18, 1) if bg else (round(st["stroke_width"] * px, 1) if st.get("stroke") else 0)
        oc = _ass_color(bg["color"], bg.get("alpha", 0.6)) if bg else _ass_color(st.get("stroke") or "#000000")
        lines.append(f"Style: T{i},{font},{px},{_ass_color(st['color'])},{_ass_color(st['highlight'])},{oc},"
                     f"{_ass_color(st.get('shadow_color', '#000000AA'))},{-1 if st.get('bold') else 0},0,0,0,100,100,"
                     f"{st.get('letter_spacing', 0)},0,{3 if bg else 1},{outline},{round(st.get('shadow', 0) * px, 1)},5,40,40,40,1")
        x = W / 2 + item.transform.x * W / 2
        y = H / 2 - item.transform.y * H / 2
        anim = st.get("animation", "pop")
        intro = {"pop": "\\fscx70\\fscy70\\t(0,120,\\fscx100\\fscy100)", "fade": "\\fad(150,150)",
                 "slide": "\\fad(120,120)"}.get(anim, "")
        text = _escape(_display(item.text, st))
        events.append(f"Dialogue: 1,{_ass_time(item.start)},{_ass_time(item.start + item.duration)},T{i},,0,0,0,,"
                      f"{{\\pos({x:.0f},{y:.0f}){intro}}}{text}")
    return write_text(out_path, "\n".join(lines + events) + "\n")


# ------------------------------------------------------------------ sidecars

def _srt_time(t: float) -> str:
    t = max(0.0, t)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(chunks: Iterable[CaptionChunk], out_path: str | Path) -> Path:
    blocks = []
    for i, c in enumerate(chunks, 1):
        blocks.append(f"{i}\n{_srt_time(c.start)} --> {_srt_time(c.end)}\n{c.text}\n")
    return write_text(out_path, "\n".join(blocks))


def to_vtt(chunks: Iterable[CaptionChunk], out_path: str | Path) -> Path:
    blocks = ["WEBVTT\n"]
    for c in chunks:
        blocks.append(f"{_srt_time(c.start).replace(',', '.')} --> {_srt_time(c.end).replace(',', '.')}\n{c.text}\n")
    return write_text(out_path, "\n".join(blocks))


def parse_srt(path: str | Path) -> list[CaptionChunk]:
    text = Path(path).read_text(encoding="utf-8-sig")
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", lines[1] if "-->" in lines[1] else lines[0])
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = " ".join(lines[2:] if "-->" in lines[1] else lines[1:])
        out.append(CaptionChunk(start=start, end=end, text=body))
    return out
