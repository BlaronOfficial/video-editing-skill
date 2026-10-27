"""edit.json: the single source of truth for an edit.

Both outputs are generated from this one document:
  * render.py  -> final.mp4 (FFmpeg + motion-graphics renders)
  * capcut/    -> an editable CapCut project

Conventions
  * All times are seconds (float). CapCut microseconds are derived at build time.
  * `src_in`/`src_out` are positions inside the source file; `start` is a timeline position.
  * Positions use CapCut's convention: x/y in half-canvas units from the centre, +y is up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .util import read_json, write_json

EDIT_VERSION = 1


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Canvas(_Model):
    width: int = 1080
    height: int = 1920
    fps: float = 30.0
    background: str = "#000000"

    @property
    def ratio(self) -> str:
        from math import gcd
        g = gcd(self.width, self.height)
        return f"{self.width // g}:{self.height // g}"


class Source(_Model):
    id: str
    path: str
    kind: Literal["video", "audio", "image"] = "video"
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = True
    transcript: Optional[str] = None        # path to the normalised transcript JSON
    origin: Optional[str] = None            # provenance: "camera", "higgsfield", "pinterest:<url>", "library", ...


class Transform(_Model):
    scale: float = 1.0
    x: float = 0.0          # half-canvas units, +right
    y: float = 0.0          # half-canvas units, +up
    rotation: float = 0.0   # degrees clockwise
    opacity: float = 1.0


class Zoom(_Model):
    """Punch-in / Ken Burns over the life of a clip."""
    start_scale: float = 1.0
    end_scale: float = 1.12
    ease: Literal["linear", "in", "out", "inout", "hold"] = "out"
    anchor_x: float = 0.0
    anchor_y: float = 0.0


class Transition(_Model):
    type: str = "fade"                       # renderer: fade | wipeleft | slideup | circleopen | ... (ffmpeg xfade names)
    duration: float = 0.3
    capcut: Optional[str] = None             # explicit CapCut transition name (pyCapCut TransitionType)


class CropKey(_Model):
    t: float                                 # seconds from clip start
    cx: float                                # crop centre, 0..1 of source width
    cy: float = 0.5


class Clip(_Model):
    id: str
    source: str
    src_in: float
    src_out: float
    start: Optional[float] = None            # computed for the main track
    speed: float = 1.0
    volume: float = 1.0                      # linear gain
    mute: bool = False
    fit: Literal["cover", "contain", "stretch"] = "cover"
    transform: Transform = Field(default_factory=Transform)
    zoom: Optional[Zoom] = None
    crop: list[CropKey] = Field(default_factory=list)   # auto-reframe path
    transition_in: Optional[Transition] = None
    fade_in: float = 0.0
    fade_out: float = 0.0
    audio_fade_in: float = 0.0
    audio_fade_out: float = 0.0
    color: Optional[str] = None              # grade preset override for this clip
    capcut_filter: Optional[str] = None
    capcut_animation_in: Optional[str] = None
    capcut_animation_out: Optional[str] = None
    label: str = ""                          # "hook", "take 3", "broll: city"

    @property
    def duration(self) -> float:
        return max(0.0, (self.src_out - self.src_in) / max(self.speed, 1e-6))

    @property
    def end(self) -> float:
        return (self.start or 0.0) + self.duration


class MGSpec(_Model):
    """A motion graphic to be rendered by one of the engines."""
    engine: Literal["auto", "html", "hyperframes", "remotion", "pil"] = "auto"
    template: Optional[str] = None           # name under mg/templates
    file: Optional[str] = None               # custom composition written for this edit
    data: dict[str, Any] = Field(default_factory=dict)
    width: Optional[int] = None
    height: Optional[int] = None
    alpha: bool = True


class Overlay(_Model):
    id: str
    start: float
    duration: float
    path: Optional[str] = None               # rendered media used by our renderer (alpha video, png, gif)
    renders: dict[str, str] = Field(default_factory=dict)   # variants by suffix: ".webm", ".mov" (ProRes 4444), "_key.mp4"
    mg: Optional[MGSpec] = None
    fit: Literal["none", "cover", "contain"] = "none"
    transform: Transform = Field(default_factory=Transform)
    layer: int = 0
    chroma: Optional[str] = None             # "#00FF00" if the overlay relies on a key colour
    fade_in: float = 0.0
    fade_out: float = 0.0
    label: str = ""


class Word(_Model):
    w: str
    s: float
    e: float


class CaptionChunk(_Model):
    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)
    emphasis: list[int] = Field(default_factory=list)   # indices into words to highlight
    emoji: Optional[str] = None
    y: Optional[float] = None                            # per-chunk vertical override (half-canvas units)


class Captions(_Model):
    enabled: bool = True
    style: str = "karaoke_pop"
    overrides: dict[str, Any] = Field(default_factory=dict)
    engine: Literal["ass", "html"] = "ass"
    max_words: int = 3
    max_chars: int = 22
    uppercase: Optional[bool] = None
    language: Optional[str] = None
    chunks: list[CaptionChunk] = Field(default_factory=list)


class TextItem(_Model):
    id: str
    text: str
    start: float
    duration: float
    style: dict[str, Any] = Field(default_factory=dict)  # font, size, color, stroke, background, align, weight
    transform: Transform = Field(default_factory=Transform)
    capcut_intro: Optional[str] = None
    capcut_outro: Optional[str] = None
    capcut_loop: Optional[str] = None
    label: str = ""


class AudioClip(_Model):
    id: str
    source: str
    start: float = 0.0
    src_in: float = 0.0
    src_out: Optional[float] = None
    volume: float = 1.0
    role: Literal["music", "sfx", "vo", "ambience"] = "music"
    duck: Optional[bool] = None              # default: music/ambience duck under speech
    fade_in: float = 0.0
    fade_out: float = 0.0
    loop: bool = False
    label: str = ""

    @property
    def ducks(self) -> bool:
        return self.duck if self.duck is not None else self.role in ("music", "ambience")


class EffectItem(_Model):
    id: str
    start: float
    duration: float
    capcut: Optional[str] = None             # pyCapCut VideoSceneEffectType name
    capcut_params: Optional[list[float]] = None
    render: Optional[str] = None             # renderer approximation: flash | shake | blur | glitch | vignette | zoom_pulse | rgb_split | film_grain
    intensity: float = 1.0


class ColorGrade(_Model):
    preset: Optional[str] = None             # renderer grade preset (see render.GRADES)
    lut: Optional[str] = None                # .cube file
    capcut_filter: Optional[str] = None      # pyCapCut FilterType name
    intensity: float = 1.0


class AudioSettings(_Model):
    denoise: bool = True
    voice_enhance: bool = True
    target_lufs: Optional[float] = None
    duck_db: float = -14.0                   # music level reduction under speech


class Output(_Model):
    path: Optional[str] = None
    encoder: Optional[str] = None
    crf: Optional[int] = None
    preset: Optional[str] = None
    audio: AudioSettings = Field(default_factory=AudioSettings)
    extra_ratios: list[str] = Field(default_factory=list)   # e.g. ["1:1", "16:9"] via auto-reframe


class CapCutSettings(_Model):
    project_name: Optional[str] = None
    pro_allowed: Optional[bool] = None       # None = use config / ask
    include_captions: bool = True
    overlay_mode: Literal["auto", "alpha", "chroma", "flatten"] = "auto"


class Edit(_Model):
    version: int = EDIT_VERSION
    name: str = "edit"
    canvas: Canvas = Field(default_factory=Canvas)
    sources: dict[str, Source] = Field(default_factory=dict)
    main: list[Clip] = Field(default_factory=list)
    broll: list[Clip] = Field(default_factory=list)
    overlays: list[Overlay] = Field(default_factory=list)
    captions: Captions = Field(default_factory=Captions)
    texts: list[TextItem] = Field(default_factory=list)
    audio: list[AudioClip] = Field(default_factory=list)
    effects: list[EffectItem] = Field(default_factory=list)
    color: ColorGrade = Field(default_factory=ColorGrade)
    style: Optional[str] = None
    brand: Optional[str] = None
    capcut: CapCutSettings = Field(default_factory=CapCutSettings)
    output: Output = Field(default_factory=Output)
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "Edit":
        for clip in [*self.main, *self.broll]:
            if clip.source not in self.sources:
                raise ValueError(f"clip {clip.id} references unknown source '{clip.source}'")
            if clip.src_out <= clip.src_in:
                raise ValueError(f"clip {clip.id}: src_out ({clip.src_out}) must be after src_in ({clip.src_in})")
        for a in self.audio:
            if a.source not in self.sources:
                raise ValueError(f"audio {a.id} references unknown source '{a.source}'")
        return self

    # ------------------------------------------------------------ layout

    def layout(self) -> "Edit":
        """Place main clips back to back.

        Transitions never change timing (CapCut's model): they are drawn across the cut using
        source handles, so captions and overlays line up identically in both outputs.
        """
        t = 0.0
        for clip in self.main:
            clip.start = round(t, 6)
            t = clip.start + clip.duration
        return self

    @property
    def duration(self) -> float:
        """The video length is defined by the main track (and b-roll); graphics that run past it are
        trimmed rather than padding the video with black. Without a main track, everything counts."""
        ends = [c.end for c in self.main] + [c.end for c in self.broll if c.start is not None]
        if ends:
            return max(ends)
        ends = [o.start + o.duration for o in self.overlays] + [x.start + x.duration for x in self.texts]
        return max(ends) if ends else 0.0

    def source_to_timeline(self, source_id: str, t: float) -> Optional[float]:
        """Map a time inside a source to the timeline through the main track (None if cut out)."""
        for clip in self.main:
            if clip.source == source_id and clip.src_in <= t <= clip.src_out:
                return (clip.start or 0.0) + (t - clip.src_in) / clip.speed
        return None

    def timeline_to_source(self, t: float) -> Optional[tuple[str, float]]:
        for clip in self.main:
            if clip.start is not None and clip.start <= t < clip.end:
                return clip.source, clip.src_in + (t - clip.start) * clip.speed
        return None


def load_edit(path: str | Path) -> Edit:
    data = read_json(path)
    if data is None:
        raise FileNotFoundError(path)
    return Edit.model_validate(data).layout()


def save_edit(edit: Edit, path: str | Path) -> Path:
    edit.layout()
    return write_json(path, edit.model_dump(mode="json", exclude_none=True))


def json_schema() -> dict:
    return Edit.model_json_schema()
