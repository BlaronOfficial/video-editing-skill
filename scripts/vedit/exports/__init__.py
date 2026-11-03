"""Hand-offs to other editors: one neutral timeline, many writers.

`flatten(edit)` turns edit.json into a plain, editor-agnostic timeline (tracks of placed media with
source ranges, transforms, keyframes, fades, volumes, markers). Every writer reads that model:

  fcpxml.py   FCPXML 1.10 (DaVinci Resolve, Final Cut Pro), written natively
  otio.py     OpenTimelineIO, FCP7 XML (Premiere), CMX EDL, Kdenlive, through the otio tool venv
  mlt.py      MLT XML for Shotcut, written natively
  package.py  the import package: timeline files + ProRes 4444 graphics + SRT + stems + LUT + README
  diff.py     read an editor's re-export back, learn from the changes, pull trimmed cuts back in

Things an NLE cannot rebuild from a timeline file (styled captions, titles, effects, the ducked mix)
travel as rendered layers and stems, and as markers that say what was there.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..media import ffprobe, probe
from ..timeline import Clip, Edit
from ..util import run

COLORS = ("blue", "red", "green", "yellow", "purple", "cyan", "orange", "pink")


@dataclass
class Item:
    id: str
    name: str
    path: str
    media: str                      # video | audio | image
    start: float                    # timeline seconds
    duration: float                 # timeline seconds
    src_in: float = 0.0             # seconds inside the file
    speed: float = 1.0
    has_video: bool = True
    has_audio: bool = False
    volume: float = 1.0             # linear gain
    fade_in: float = 0.0            # opacity fade (video) or level fade (audio)
    fade_out: float = 0.0
    fit: str = "cover"              # cover | contain | stretch | none
    scale: float = 1.0
    x: float = 0.0                  # canvas px from the centre, +right
    y: float = 0.0                  # canvas px from the centre, +up
    rotation: float = 0.0           # degrees clockwise
    opacity: float = 1.0
    keys: dict[str, list] = field(default_factory=dict)   # {"scale": [[t, s]], "position": [[t, x, y]]}, clip-local t
    transition: dict | None = None  # into this item: {"type", "duration", "native"}
    role: str = "video"             # video | broll | graphics | titles | dialogue | music | effects | vo
    src_duration: float = 0.0       # length of the file (0 for stills)
    src_fps: float = 0.0
    width: int = 0
    height: int = 0
    tc_start: float = 0.0           # embedded start timecode of the file, seconds
    ref: str = ""                   # edit.json item id this came from
    linked: bool = False            # audio mirror of a main clip (FCPXML keeps it inside the video clip)
    note: str = ""

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def src_out(self) -> float:
        return self.src_in + self.duration * self.speed


@dataclass
class Track:
    name: str
    kind: str                       # video | audio
    role: str
    items: list[Item] = field(default_factory=list)


@dataclass
class MarkerOut:
    t: float
    name: str
    note: str = ""
    duration: float = 0.0
    kind: str = "note"              # note | chapter | todo
    color: str = "blue"


@dataclass
class Handoff:
    name: str
    width: int
    height: int
    fps: float
    duration: float
    tracks: list[Track]
    markers: list[MarkerOut]
    captions: list[dict] = field(default_factory=list)    # [{"start", "end", "text"}]
    notes: list[str] = field(default_factory=list)          # what did not translate, said once
    lut: str | None = None

    def video_tracks(self) -> list[Track]:
        return [t for t in self.tracks if t.kind == "video"]

    def audio_tracks(self) -> list[Track]:
        return [t for t in self.tracks if t.kind == "audio"]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Handoff":
        tracks = [Track(name=t["name"], kind=t["kind"], role=t["role"], items=[Item(**i) for i in t["items"]])
                  for t in d["tracks"]]
        return cls(**{**d, "tracks": tracks, "markers": [MarkerOut(**m) for m in d["markers"]]})


# ------------------------------------------------------------------ time

def rate(fps: float) -> Fraction:
    """Exact frame rate: 29.97 -> 30000/1001."""
    for nominal in (24, 30, 60, 120):
        if abs(fps - nominal * 1000 / 1001) < 0.005:
            return Fraction(nominal * 1000, 1001)
    return Fraction(fps).limit_denominator(1001)


def frames(t: float, fps: float) -> int:
    return int(round(t * float(rate(fps))))


def timecode(t: float, fps: float) -> str:
    """HH:MM:SS:FF (non-drop) for EDL-style displays and LosslessCut-free readers."""
    r = rate(fps)
    base = round(float(r))
    f = frames(t, fps)
    return f"{f // (3600 * base):02d}:{f // (60 * base) % 60:02d}:{f // base % 60:02d}:{f % base:02d}"


def file_timecode(path: str) -> float:
    """Embedded start timecode (camera files, NLE renders), in seconds; 0 when there is none."""
    try:
        out = run([ffprobe(), "-v", "error", "-show_entries", "format_tags=timecode:stream_tags=timecode",
                   "-of", "json", path], check=False).stdout
        data = json.loads(out or "{}")
    except Exception:
        return 0.0
    tcs = [(data.get("format", {}).get("tags") or {}).get("timecode")]
    tcs += [(s.get("tags") or {}).get("timecode") for s in data.get("streams", [])]
    tc = next((x for x in tcs if x), None)
    if not tc:
        return 0.0
    fps = probe(path).fps or 30.0
    parts = tc.replace(";", ":").split(":")
    if len(parts) != 4:
        return 0.0
    h, m, s, f = (int(p) for p in parts)
    return h * 3600 + m * 60 + s + f / round(fps)


# ------------------------------------------------------------------ flatten

def _ease(p: float, ease: str) -> float:
    if ease == "in":
        return p * p
    if ease == "out":
        return 1 - (1 - p) * (1 - p)
    if ease == "inout":
        return p * p * (3 - 2 * p)
    if ease == "hold":
        return 1.0
    return p


def _clip_keys(edit: Edit, clip: Clip, iw: int, ih: int) -> dict[str, list]:
    """Zoom and auto-reframe paths as scale/position keyframes (clip-local seconds, canvas px)."""
    W, H = edit.canvas.width, edit.canvas.height
    D = clip.duration
    times: set[float] = set()
    if clip.zoom:
        steps = 1 if clip.zoom.ease in ("linear", "hold") else 6
        times |= {round(D * i / steps, 4) for i in range(steps + 1)}
    if clip.crop:
        times |= {round(min(max(k.t, 0.0), D), 4) for k in clip.crop}
    if not times:
        return {}
    k = max(W / iw, H / ih) if iw and ih else 1.0          # "fill" scale of the source
    cw, ch = min(iw, ih * W / H), min(ih, iw * H / W)

    def crop_at(t: float) -> tuple[float, float]:
        if not clip.crop:
            return 0.0, 0.0
        keys = sorted((c.t, c.cx, c.cy) for c in clip.crop)
        if t <= keys[0][0]:
            cx, cy = keys[0][1], keys[0][2]
        elif t >= keys[-1][0]:
            cx, cy = keys[-1][1], keys[-1][2]
        else:
            for (t0, x0, y0), (t1, x1, y1) in zip(keys, keys[1:]):
                if t0 <= t <= t1:
                    u = (t - t0) / max(t1 - t0, 1e-6)
                    cx, cy = x0 + (x1 - x0) * u, y0 + (y1 - y0) * u
                    break
        cx = min(max(cx, cw / 2 / iw), 1 - cw / 2 / iw)
        cy = min(max(cy, ch / 2 / ih), 1 - ch / 2 / ih)
        return (0.5 - cx) * iw * k, (cy - 0.5) * ih * k

    out: dict[str, list] = {"scale": [], "position": []}
    for t in sorted(times):
        z = 1.0
        ax = ay = 0.0
        if clip.zoom:
            zz = clip.zoom
            z = zz.start_scale + (zz.end_scale - zz.start_scale) * _ease(min(1.0, t / max(D, 1e-6)), zz.ease)
            ax, ay = zz.anchor_x, zz.anchor_y
        px, py = crop_at(t)
        out["scale"].append([t, round(z * clip.transform.scale, 5)])
        out["position"].append([t, round(px * z - W * (z - 1) / 2 * ax + clip.transform.x * W / 2, 2),
                                round(py * z - H * (z - 1) / 2 * ay + clip.transform.y * H / 2, 2)])
    return out


def _lanes(items: list[Item]) -> list[list[Item]]:
    """Greedy split so no two items on one track overlap (editors bump overlapping clips)."""
    lanes: list[list[Item]] = []
    for it in sorted(items, key=lambda i: (i.start, i.id)):
        for lane in lanes:
            if lane[-1].end <= it.start + 1e-4:
                lane.append(it)
                break
        else:
            lanes.append([it])
    return lanes


def _overlay_file(ov) -> str | None:
    """Prefer the ProRes 4444 render (alpha that every NLE reads), then WebM, then whatever was rendered."""
    r = ov.renders or {}
    return r.get(".mov") or ov.path or r.get(".webm")


def flatten(edit: Edit, *, overlay_files: dict[str, str] | None = None, graphics: dict[str, str] | None = None,
            lut: str | None = None, suggestions: list[dict] | None = None) -> Handoff:
    """The neutral hand-off timeline. `overlay_files` maps overlay ids to NLE-friendly renders (ProRes),
    `graphics` adds pre-rendered full-length layers ({"captions": mov, "titles": mov})."""
    from ..knobs import bake
    e = bake(edit.layout()).active()
    W, H, fps = e.canvas.width, e.canvas.height, e.canvas.fps
    overlay_files = overlay_files or {}
    notes: list[str] = []
    tc_cache: dict[str, float] = {}

    def src_meta(sid: str) -> dict:
        s = e.sources[sid]
        if s.path not in tc_cache:
            tc_cache[s.path] = file_timecode(s.path) if s.kind == "video" else 0.0
        return {"path": str(Path(s.path).resolve()), "media": s.kind, "src_duration": s.duration, "src_fps": s.fps,
                "width": s.width, "height": s.height, "tc_start": tc_cache[s.path]}

    def clip_item(c: Clip, role: str) -> Item:
        s = e.sources[c.source]
        m = src_meta(c.source)
        it = Item(id=c.id, name=c.label or c.id, start=c.start or 0.0, duration=c.duration, src_in=c.src_in,
                  speed=c.speed, has_video=s.kind != "audio", has_audio=s.kind != "image" and s.has_audio and not c.mute,
                  volume=0.0 if c.mute else c.volume, fade_in=c.fade_in, fade_out=c.fade_out, fit=c.fit,
                  scale=c.transform.scale, x=c.transform.x * W / 2, y=c.transform.y * H / 2,
                  rotation=c.transform.rotation, opacity=c.transform.opacity, role=role, ref=c.id, **m)
        if s.kind == "image":
            it.src_in = 0.0
        keys = _clip_keys(e, c, s.width, s.height)
        pos, sc = keys.get("position"), keys.get("scale")
        if pos and all(abs(k[1] - pos[0][1]) < 0.01 and abs(k[2] - pos[0][2]) < 0.01 for k in pos):
            it.x, it.y = pos[0][1], pos[0][2]           # a still reframe or zoom anchor: one static offset
            keys.pop("position")
        if sc and all(abs(k[1] - sc[0][1]) < 1e-4 for k in sc):
            it.scale = sc[0][1]
            keys.pop("scale")
        it.keys = keys
        if c.transition_in:
            tr = c.transition_in
            native = tr.type in ("fade", "dissolve", "crossfade")
            it.transition = {"type": tr.type, "duration": tr.duration, "native": native}
            if not native:
                it.note = f"transition was '{tr.type}' (exported as a dissolve)"
        if c.color:
            it.note = (it.note + "; " if it.note else "") + f"clip grade '{c.color}'"
        fx = [n for n, on in (("stabilized", c.stabilize is not None), (f"denoise {c.denoise}", bool(c.denoise)),
                              ("reversed", c.reverse), (f"{c.smooth} slow motion", bool(c.smooth)),
                              ("black bars cropped", bool(c.src_crop)), ("360 reframed", bool(c.projection)),
                              (f"{len(c.redact)} redaction(s)", bool(c.redact)),
                              ("tracked blur", any(r.get("track") for r in c.redact)),
                              (f"person cut-out ({(c.subject or {}).get('background') or 'layer'})", bool(c.subject)),
                              ("depth of field", bool(c.dof)), (f"{len(c.screen)} screen replacement(s)", bool(c.screen))) if on]
        if s.color and (s.color.get("hdr") or s.color.get("bt2020_sdr")):
            fx.append("HDR source tone-mapped to SDR in vedit (the editor shows the original HDR)")
        if s.lut:
            fx.append(f"camera LUT {Path(s.lut).name}")
        if fx:
            it.note = (it.note + "; " if it.note else "") + "vedit FX: " + ", ".join(fx)
        return it

    tracks: list[Track] = []
    main = [clip_item(c, "video") for c in e.main]
    tracks.append(Track("V1 main", "video", "video", main))
    broll = [clip_item(c, "broll") for c in e.broll if c.start is not None]
    for i, lane in enumerate(_lanes(broll)):
        tracks.append(Track(f"V{len(tracks) + 1} b-roll" + (f" {i + 1}" if i else ""), "video", "broll", lane))

    ovs: list[Item] = []
    for ov in sorted(e.overlays, key=lambda o: o.layer):
        f = overlay_files.get(ov.id) or _overlay_file(ov)
        if not f or not Path(f).exists():
            notes.append(f"overlay {ov.id} has no rendered file (run `vedit mg render`)")
            continue
        info = probe(f)
        media = "image" if info.kind == "image" or info.duration <= 0 else "video"
        t = ov.transform
        ovs.append(Item(id=ov.id, name=ov.label or ov.id, path=str(Path(f).resolve()), media=media, start=ov.start,
                        duration=ov.duration, has_video=True, has_audio=False, fade_in=ov.fade_in, fade_out=ov.fade_out,
                        fit=ov.fit if ov.fit != "none" else "none", scale=t.scale, x=t.x * W / 2, y=t.y * H / 2,
                        rotation=t.rotation, opacity=t.opacity, role="graphics", src_duration=info.duration,
                        src_fps=info.fps, width=info.width, height=info.height, ref=ov.id,
                        note="chroma key " + ov.chroma if ov.chroma else ""))
    for i, lane in enumerate(_lanes(ovs)):
        tracks.append(Track(f"V{len(tracks) + 1} graphics" + (f" {i + 1}" if i else ""), "video", "graphics", lane))

    for key, path in (graphics or {}).items():
        if path and Path(path).exists():
            info = probe(path)
            tracks.append(Track(f"V{len(tracks) + 1} {key}", "video", "titles", [Item(
                id=f"layer_{key}", name=f"{key} (styled, alpha)", path=str(Path(path).resolve()), media="video",
                start=0.0, duration=min(info.duration, e.duration), fit="none", role="titles",
                src_duration=info.duration, src_fps=info.fps, width=info.width, height=info.height, ref=key)]))

    # audio: the main clips' own sound first (linked), then music / voice-over / effects
    dialogue = []
    for it in main:
        if it.has_audio:
            a = Item(**{**asdict(it), "has_video": False, "role": "dialogue", "linked": True, "keys": {},
                        "fade_in": 0.0, "fade_out": 0.0})
            dialogue.append(a)
    tracks.append(Track("A1 dialogue", "audio", "dialogue", dialogue))
    by_role: dict[str, list[Item]] = {"music": [], "vo": [], "effects": []}
    for a in e.audio:
        s = e.sources[a.source]
        m = src_meta(a.source)
        length = (a.src_out if a.src_out is not None else s.duration) - a.src_in
        if a.loop or a.role in ("music", "ambience"):
            length = min(length, max(0.1, e.duration - a.start)) if not a.loop else max(0.1, e.duration - a.start)
        role = {"music": "music", "ambience": "music", "vo": "vo"}.get(a.role, "effects")
        it = Item(id=a.id, name=a.label or (a.sfx.role if a.sfx else a.id), start=a.start, duration=length, src_in=a.src_in,
                  has_video=False, has_audio=True, volume=a.volume, fade_in=a.fade_in, fade_out=a.fade_out, role=role,
                  ref=a.id, **{**m, "media": "audio"})
        if a.loop and s.duration and length > s.duration - a.src_in + 0.01:
            # NLEs have no "loop" on a clip: lay the file end to end
            t, n = a.start, 0
            while t < a.start + length - 0.01:
                seg = min(s.duration - (a.src_in if n == 0 else 0.0), a.start + length - t)
                part = Item(**{**asdict(it), "id": f"{a.id}_{n}", "start": t, "duration": seg,
                               "src_in": a.src_in if n == 0 else 0.0,
                               "fade_in": a.fade_in if n == 0 else 0.0, "fade_out": 0.0})
                by_role[role].append(part)
                t, n = t + seg, n + 1
            by_role[role][-1].fade_out = a.fade_out
        else:
            by_role[role].append(it)
        if a.ducks:
            it.note = "ducks under speech in the vedit mix (use the stems or duck by hand)"
    labels = {"music": "music", "vo": "voice-over", "effects": "sfx"}
    for role in ("music", "vo", "effects"):
        for i, lane in enumerate(_lanes(by_role[role])):
            tracks.append(Track(f"A{len([t for t in tracks if t.kind == 'audio']) + 1} {labels[role]}"
                                + (f" {i + 1}" if i else ""), "audio", role, lane))

    markers = [MarkerOut(t=m.t, name=m.name or m.kind, note=m.note, duration=m.duration, kind=m.kind,
                         color=m.color if m.color in COLORS else "blue") for m in e.markers]
    for fx in e.effects:
        what = fx.render or fx.capcut or "effect"
        markers.append(MarkerOut(t=fx.start, duration=fx.duration, name=f"FX: {what}",
                                 note=f"vedit effect '{what}' (intensity {fx.intensity:g}) - rebuild in the editor or "
                                      f"use the reference render", color="purple"))
    for it in main + broll:
        if it.note:
            markers.append(MarkerOut(t=it.start, name=f"{it.name}: note", note=it.note, color="yellow"))
    for s in suggestions or []:
        if s.get("status", "open") == "open" and s.get("range"):
            markers.append(MarkerOut(t=float(s["range"][0]), duration=max(0.0, float(s["range"][1]) - float(s["range"][0])),
                                     name=f"Idea: {s.get('title') or s.get('kind', 'suggestion')}",
                                     note=s.get("reason", ""), kind="todo", color="green"))
    markers.sort(key=lambda m: m.t)

    captions = []
    if e.captions.enabled:
        from ..captions import build_chunks
        for c in e.captions.chunks or build_chunks(e):
            captions.append({"start": round(c.start, 3), "end": round(c.end, 3), "text": c.text})
    if e.color.preset or e.color.lut:
        notes.append("the grade travels as a .cube LUT (look.cube): apply it on the timeline or an adjustment layer")
    if any(c.speed != 1 for c in e.main + e.broll):
        notes.append("speed changes are constant retimes; check them in the editor")
    if e.custom_fx:
        notes.append("custom FX are baked into the reference render only")
    return Handoff(name=e.name, width=W, height=H, fps=fps, duration=e.duration, tracks=tracks, markers=markers,
                   captions=captions, notes=notes, lut=lut)


def summary(h: Handoff) -> dict[str, Any]:
    return {"duration": round(h.duration, 3), "tracks": {t.name: len(t.items) for t in h.tracks},
            "markers": len(h.markers), "captions": len(h.captions)}
