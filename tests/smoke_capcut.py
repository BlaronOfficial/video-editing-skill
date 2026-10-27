"""Smoke test: build a CapCut project from a hand-written edit (synthetic media). --calibrate, --write."""

import sys
from pathlib import Path

from vedit.capcut import builder, store
from vedit.timeline import (AudioClip, CaptionChunk, Captions, Canvas, Clip, ColorGrade, Edit, Source, TextItem,
                            Transition, Word, Zoom)

ROOT = Path(__file__).resolve().parent
F = ROOT / "footage"

edit = Edit(
    name="vedit_test",
    canvas=Canvas(width=1080, height=1920, fps=30),
    sources={
        "a": Source(id="a", path=str(F / "synthetic_a.mp4"), duration=12, width=1920, height=1080),
        "b": Source(id="b", path=str(F / "synthetic_b.mp4"), duration=8, width=1920, height=1080),
        "m": Source(id="m", path=str(F / "music_test.mp3"), kind="audio", duration=30),
    },
    main=[
        Clip(id="c1", source="a", src_in=0.5, src_out=4.0, zoom=Zoom(start_scale=1.0, end_scale=1.15), label="hook"),
        Clip(id="c2", source="b", src_in=1.0, src_out=4.0, transition_in=Transition(type="dissolve", duration=0.4)),
        Clip(id="c3", source="a", src_in=6.0, src_out=9.0, fit="contain"),
    ],
    texts=[TextItem(id="t1", text="VEDIT TEST", start=0.2, duration=2.5, style={"size": 0.09, "color": "#FFE14D"},
                    capcut_intro="pop")],
    captions=Captions(style="karaoke_pop", chunks=[
        CaptionChunk(start=0.5, end=1.6, text="this is a", words=[Word(w="this", s=0.5, e=0.8), Word(w="is", s=0.8, e=1.0), Word(w="a", s=1.0, e=1.6)]),
        CaptionChunk(start=1.6, end=3.0, text="caption test", words=[Word(w="caption", s=1.6, e=2.3), Word(w="test", s=2.3, e=3.0)]),
        CaptionChunk(start=4.0, end=6.0, text="বাংলা ক্যাপশন", words=[]),
    ]),
    audio=[AudioClip(id="mu", source="m", start=0, volume=0.6, role="music", fade_in=0.5, fade_out=1.0)],
    color=ColorGrade(capcut_filter="warm_cinematic"),
)

if __name__ == "__main__":
    if "--calibrate" in sys.argv:
        print(store.calibrate("1025"))
    built, report = builder.build(edit, pro_allowed=False)
    print("tracks:", [(t.get("type"), len(t.get("segments", []))) for t in built["tracks"]])
    print("warnings:", report.warnings)
    print("counts:", report.counts)
    if "--write" in sys.argv:
        path = store.create_project("vedit_test_01", built, overwrite=True)
        print("written:", path)
