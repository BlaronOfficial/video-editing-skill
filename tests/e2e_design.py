"""E2E design pass on tests/footage/e2e: what Claude would write into edit.json after planning the cut."""

from pathlib import Path

from vedit import captions as caps
from vedit.project import add_source, find
from vedit.timeline import AudioClip, MGSpec, Overlay

p = find(Path(__file__).resolve().parent / "footage" / "e2e")
sfx_dir = p.root / "assets" / "sfx"
ids = {k: add_source(p, sfx_dir / f"{k}.wav", origin="generated", sid=f"sfx_{k}") for k in ("whoosh", "pop", "riser", "ding")}

e = p.edit()


def at(phrase: str, nth: int = 0) -> float:
    """Timeline time of a spoken phrase (what `vedit words --find` returns)."""
    words = []
    for clip in e.main:
        for w in caps.transcript_words(e.sources[clip.source].transcript):
            if clip.src_in <= (w["s"] + w["e"]) / 2 <= clip.src_out:
                words.append(((clip.start or 0) + (w["s"] - clip.src_in) / clip.speed, w["w"].lower().strip(".,!?")))
    needle = phrase.lower().split()
    hits = [words[i][0] for i in range(len(words)) if [x[1] for x in words[i:i + len(needle)]] == needle]
    return round(hits[nth], 2)


e.style = "clean_corporate"
e.color.preset = "clean"
e.captions.style = "karaoke_pop"
e.captions.chunks = []
e.captions.chunks = caps.build_chunks(e)
# Claude's caption review: emphasise the money words.
for chunk in e.captions.chunks:
    for i, w in enumerate(chunk.words):
        if w.w.lower().strip(".,!?") in ("couldn't", "wrong", "loving", "smart", "try", "love"):
            chunk.emphasis.append(i)

total = e.duration
brand = {"accent": "#FFE14D", "accent2": "#FF4D6D"}
e.overlays = [
    Overlay(id="hook_title", start=0.05, duration=2.4, mg=MGSpec(template="title_card", data={
        "kicker": "SCIENCE SPEAKS", "title": "I thought I couldn't do it", "highlight": ["couldn't"], "y": 0.17, "brand": brand})),
    Overlay(id="name", start=round(e.main[2].start + 0.2, 2), duration=3.6, mg=MGSpec(template="lower_third", data={
        "name": "Liz", "title": "Epidemiologist", "style": "glass", "y": 0.1, "brand": brand})),
    Overlay(id="flex", start=at("i can do this"), duration=1.6, mg=MGSpec(template="emoji_pop", data={"emoji": "💪", "x": 0.8, "y": 0.28, "size": 0.8})),
    Overlay(id="sticking", start=at("sticking with it") - 0.1, duration=2.3, mg=MGSpec(template="kinetic_text", data={
        "text": "sticking with it", "emphasis": ["sticking"], "y": 0.2, "size": 0.8, "brand": brand})),
    Overlay(id="try_it", start=at("try it", 1) - 0.05, duration=1.3, mg=MGSpec(template="text_punch", data={"text": "TRY IT", "y": 0.2, "brand": brand})),
    # Thin graphics render at their own size (1080x24) and are positioned with transform: 30x fewer pixels.
    Overlay(id="progress", start=0, duration=round(total, 2), layer=1, transform={"y": round(1 - 24 / 1920, 4)},
            mg=MGSpec(template="progress_bar", width=1080, height=24, data={"position": "top", "thickness": 100, "brand": brand})),
    Overlay(id="cta", start=round(total - 3.3, 2), duration=3.3, mg=MGSpec(template="subscribe_cta", data={
        "label": "Follow", "done": "Following ✓", "y": 0.18, "brand": brand})),
]
e.audio = [
    AudioClip(id="sfx_title", source=ids["whoosh"], start=0.0, volume=0.45, role="sfx"),
    AudioClip(id="sfx_pop", source=ids["pop"], start=round(at("i can do this") - 0.04, 2), volume=0.55, role="sfx"),
    AudioClip(id="sfx_riser", source=ids["riser"], start=round(at("try it", 1) - 2.0, 2), volume=0.3, role="sfx"),
    AudioClip(id="sfx_ding", source=ids["ding"], start=round(total - 3.3 + 1.08, 2), volume=0.45, role="sfx"),
]
e.capcut.project_name = "liz_short_e2e"
e.notes = ("Hook: her conclusion first. Story: PhD doubt -> tried anyway -> lesson. Payoff: try it. "
           "Style: clean corporate with karaoke captions; face-tracked 9:16 from a 16:9 interview.")
p.save_edit(e)
print({"duration": round(e.duration, 2), "captions": len(e.captions.chunks), "overlays": len(e.overlays), "sfx": len(e.audio)})
