"""edit.json: the single source of truth for an edit.

Both outputs are generated from this one document:
  * render.py  -> final.mp4 (FFmpeg + motion-graphics renders)
  * capcut/    -> an editable CapCut project

Conventions
  * All times are seconds (float). CapCut microseconds are derived at build time.
  * `src_in`/`src_out` are positions inside the source file; `start` is a timeline position.
  * Positions use CapCut's convention: x/y in half-canvas units from the centre, +y is up.
  * Items that belong to a spoken moment carry an `anchor` (a time inside a source). `layout()` maps it
    through the main track, so graphics and sounds follow the words when the cut changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .util import read_json, write_json

EDIT_VERSION = 2


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
    color: Optional[dict[str, Any]] = None   # footage.analyze(): hdr, bt2020_sdr, log, interlaced, timing, device, ...
    lut: Optional[str] = None                # camera conversion LUT (Log footage), applied at decode
    notes: list[str] = Field(default_factory=list)   # what footage.analyze() found, for the director


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


class Anchor(_Model):
    """Pin an item to a moment inside a source; its timeline start follows re-cuts."""
    source: str
    t: float                                 # seconds inside the source (e.g. a word's start)
    offset: float = 0.0                      # timeline seconds relative to the anchor point
    policy: Literal["nearest", "drop", "keep"] = "nearest"   # when the moment is cut out


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
    # clean-up and time FX (vedit fx ...; rendered at decode, before framing)
    src_crop: Optional[dict[str, int]] = None    # {x, y, w, h} in source pixels: black bars, a region
    projection: Optional[dict[str, float]] = None  # 360 -> flat: {yaw, pitch, roll, h_fov, v_fov, input: "e"}
    stabilize: Optional[dict[str, float]] = None  # vidstab: {smoothing: 15, shakiness: 5, zoom: 0}
    denoise: Optional[Literal["light", "medium", "strong"]] = None
    reverse: bool = False
    smooth: Optional[Literal["interpolate", "blend"]] = None   # slow motion: motion-interpolated or blended frames
    redact: list[dict[str, Any]] = Field(default_factory=list)  # [{x, y, w, h (source px), mode blur|pixelate|delogo, start?, end?}]
                                             # or tracked: [{track: id, mode, shape: box|ellipse, pad: 0.15}]
    # phase 4 VFX, all in source space (references/vfx.md)
    subject: Optional[dict[str, Any]] = None   # person cut-out: {background: "blur:14"|"#hex"|"image:<path>"|"darken:0.5"|
                                               #   "desaturate", outline: {color, width}, glow: {color, size}, above: <layer>}
    dof: Optional[dict[str, Any]] = None       # fake depth of field: {focus: 0..1 (1 = nearest), range: 0.15, blur: 10,
                                               #   pull: [[clip-local s, focus], ...]}
    screen: list[dict[str, Any]] = Field(default_factory=list)   # planar inserts: [{track: id, media: path, fit: cover|stretch,
                                               #   keep_light: 0..1, start?, end?}] or a request {corners, at, media}
    label: str = ""                          # "hook", "take 3", "broll: city"

    @property
    def duration(self) -> float:
        return max(0.0, (self.src_out - self.src_in) / max(self.speed, 1e-6))

    @property
    def end(self) -> float:
        return (self.start or 0.0) + self.duration


class MGSpec(_Model):
    """A motion graphic to be rendered by one of the engines."""
    engine: Literal["auto", "html", "hyperframes", "remotion", "pil", "blender"] = "auto"
    template: Optional[str] = None           # name under mg/templates (or blender/ for engine=blender)
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
    anchor: Optional[Anchor] = None
    enabled: bool = True
    fx: Optional[str] = None                 # id of the CustomFX that produced `path`
    attach: Optional[dict[str, Any]] = None  # follow a track: {track: id, offset: [x, y] half-canvas units, smooth: s}
    label: str = ""


class Word(_Model):
    w: str
    s: float
    e: float
    k: Optional[str] = None                  # stable key "<source>@<src start>" for fixes/emphasis


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
    from_words: bool = True                  # False = chunks were written by hand (translation, rewording): keep them
    chunks: list[CaptionChunk] = Field(default_factory=list)
    # Word-keyed edits survive re-cuts and re-chunking (keys from `Word.k`, i.e. "<source>@<start>").
    word_fixes: dict[str, str] = Field(default_factory=dict)      # misheard word -> correct text ("" hides it)
    emphasis_keys: list[str] = Field(default_factory=list)
    emoji_keys: dict[str, str] = Field(default_factory=dict)


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
    anchor: Optional[Anchor] = None
    enabled: bool = True
    label: str = ""


class SfxRef(_Model):
    """How a sound effect was placed (vedit sound place): which kit take, and its sync point on the cue."""
    role: str                                # earshot kit role: pop, whoosh.short, hit, tick, ...
    kit: str = ""
    take: str = ""                           # file name inside the kit
    align: Literal["onset", "peak", "end"] = "onset"
    sync_s: float = 0.0                      # the sync point, seconds from the start of the file
    offset_ms: float = 0.0                   # sync point vs the cue (negative = the sound leads the picture)
    cue: Optional[str] = None                # id in edit/sound/cues.json
    dip: Optional[dict[str, float]] = None   # music stop-down before the cue: {"depth_db": 9, "length_s": 0.4}

    def cue_time(self, start: float) -> float:
        return start + self.sync_s - self.offset_ms / 1000.0


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
    anchor: Optional[Anchor] = None
    enabled: bool = True
    fx: Optional[str] = None                 # id of the CustomFX that produced the source
    sfx: Optional[SfxRef] = None             # set on effects placed from a sound kit
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
    anchor: Optional[Anchor] = None
    enabled: bool = True


class CustomFX(_Model):
    """Code Claude writes for this edit when no template or built-in effect fits.

    kind=python  `file` runs as `python file --in .. --out .. --params ..` in the vedit venv (numpy, OpenCV,
                 PIL). output=overlay: an alpha video or PNG placed like an Overlay. output=audio: a WAV on the
                 mix. output=source: a processed copy of `inputs[0]` swapped into the clips in params.targets.
    kind=ffmpeg  `filter` is a single-input filter chain spliced into the final graph at `hook`.
    kind=html    `file` is a composition rendered by the motion-graphics renderer (like Overlay.mg.file).
    """
    id: str
    kind: Literal["python", "ffmpeg", "html", "blender"] = "python"
    file: Optional[str] = None               # project-relative, absolute, or "personal:fx/<name>.py"
    hook: Optional[Literal["video_pre_overlays", "video_pre_captions", "video_post", "audio_voice",
                           "audio_master"]] = None
    filter: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: list[str] = Field(default_factory=list)       # source ids or files
    output: Literal["overlay", "audio", "source", "none"] = "overlay"
    start: float = 0.0
    duration: Optional[float] = None         # None = to the end of the video
    anchor: Optional[Anchor] = None
    transform: Transform = Field(default_factory=Transform)
    fit: Literal["none", "cover", "contain"] = "none"
    layer: int = 0
    volume: float = 1.0
    path: Optional[str] = None               # last produced file
    cache_key: Optional[str] = None
    enabled: bool = True
    label: str = ""


class Track(_Model):
    """Motion measured on a source (vedit vfx track/faces/screen): samples live in `file` (JSON)."""
    id: str
    source: str
    kind: Literal["object", "face", "planar"] = "object"
    t0: float                                # source seconds covered
    t1: float
    file: str                                # edit/vfx/tracks/<id>.json
    label: str = ""


class Marker(_Model):
    """A note on the timeline: carried into hand-offs (NLE markers, chapters, to-dos) and the Studio."""
    id: str
    t: float                                 # timeline seconds (follows `anchor` when set)
    duration: float = 0.0
    name: str = ""
    note: str = ""
    kind: Literal["note", "chapter", "todo"] = "note"
    color: str = "blue"                      # blue | red | green | yellow | purple | cyan | orange | pink
    anchor: Optional[Anchor] = None

    @property
    def start(self) -> float:                # anchors write `start`; markers read `t`
        return self.t

    @start.setter
    def start(self, value: float) -> None:
        self.t = value


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
    gate_db: Optional[float] = None          # voice: noise gate threshold (dBFS), e.g. -45 for room noise between words
    compress: Optional[str] = None           # voice: extra compressor "threshold_db:ratio", e.g. "-20:4"
    limit_db: Optional[float] = None         # voice: limiter ceiling before the mix
    widen: Optional[float] = None            # master: stereo widening 0..1 (needs real stereo content)


class Output(_Model):
    path: Optional[str] = None
    encoder: Optional[str] = None
    crf: Optional[int] = None
    preset: Optional[str] = None
    audio: AudioSettings = Field(default_factory=AudioSettings)
    extra_ratios: list[str] = Field(default_factory=list)   # e.g. ["1:1", "16:9"] via auto-reframe
    platform: Optional[str] = None           # delivery destination (tiktok, reels, shorts, youtube, ...): QA checks it


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
    custom_fx: list[CustomFX] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    tracks: list[Track] = Field(default_factory=list)          # vfx tracks (faces, objects, planes)
    knobs: dict[str, Any] = Field(default_factory=dict)       # Studio tuning values (presets/knobs.json)
    revision: int = 0                                         # bumped on every save (Studio sync)
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
        self._resolve_anchors()
        return self

    def _resolve_anchors(self) -> None:
        if not self.main:
            return
        for item in [*self.overlays, *self.texts, *self.audio, *self.effects, *self.custom_fx, *self.markers]:
            a = getattr(item, "anchor", None)
            if a is None:
                continue
            at = self.source_to_timeline(a.source, a.t)
            if at is None and a.policy == "nearest":
                at = self._nearest_kept(a.source, a.t)
            if at is None:
                if a.policy == "drop" and hasattr(item, "enabled"):
                    item.enabled = False
                continue
            item.start = round(max(0.0, at + a.offset), 4)
            if a.policy == "drop" and hasattr(item, "enabled"):
                item.enabled = True

    def _nearest_kept(self, source_id: str, t: float) -> Optional[float]:
        """Timeline time of the kept point of `source_id` closest to source time `t`."""
        best: tuple[float, float] | None = None
        for clip in self.main:
            if clip.source != source_id:
                continue
            for src_t, tl in ((clip.src_in, clip.start or 0.0), (clip.src_out, clip.end)):
                d = abs(src_t - t)
                if best is None or d < best[0]:
                    best = (d, tl)
        return best[1] if best else None

    def active(self) -> "Edit":
        """A copy without disabled items (cut-out anchors with policy=drop, items switched off in the Studio)."""
        e = self.model_copy(deep=True)
        e.overlays = [o for o in e.overlays if o.enabled]
        e.texts = [x for x in e.texts if x.enabled]
        e.audio = [a for a in e.audio if a.enabled]
        e.effects = [x for x in e.effects if x.enabled]
        e.custom_fx = [f for f in e.custom_fx if f.enabled]
        return e

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
    edit.revision += 1
    return write_json(path, edit.model_dump(mode="json", exclude_none=True))


def json_schema() -> dict:
    return Edit.model_json_schema()
