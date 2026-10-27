"""edit.json -> CapCut project content, using pyCapCut's segment builders.

The result (`tracks`, `materials`, canvas, duration) is merged into the user's calibrated seed by
store.create_project(), so the version markers always match the installed CapCut.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pycapcut as cc

from .. import captions as caps
from ..media import probe
from ..timeline import Clip, Edit, Overlay
from . import resources

US = 1_000_000

# CapCut text `size` per fraction-of-short-side. Calibrated on CapCut 9.6 against the libass render
# (105 drew text at ~0.66x), so caption presets look the same in both outputs.
CAPCUT_TEXT_SIZE_PER_FRAC = 160.0


def us(seconds: float) -> int:
    return int(round(seconds * US))


def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


@dataclass
class BuildReport:
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def count(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n


class Builder:
    def __init__(self, edit: Edit, *, pro_allowed: bool, overlay_mode: str = "alpha"):
        self.edit = edit.layout()
        self.pro = pro_allowed
        self.overlay_mode = overlay_mode
        self.report = BuildReport()
        c = edit.canvas
        self.script = cc.ScriptFile(c.width, c.height, int(round(c.fps)))
        self.materials: dict[str, Any] = {}

    # -------------------------------------------------------------- helpers

    def _lookup(self, category: str, name: str | None):
        if not name:
            return None
        try:
            return resources.lookup(category, name, pro_allowed=self.pro)
        except ValueError as exc:
            self.report.warn(str(exc))
            return None

    def _video_material(self, path: str) -> Any:
        if path not in self.materials:
            self.materials[path] = cc.VideoMaterial(str(Path(path).resolve()))
        return self.materials[path]

    def _audio_material(self, path: str) -> Any:
        key = "audio:" + path
        if key not in self.materials:
            self.materials[key] = cc.AudioMaterial(str(Path(path).resolve()))
        return self.materials[key]

    def _fit_scale(self, path: str, fit: str) -> float:
        """CapCut shows media 'contained' in the canvas; return the extra scale for cover/stretch."""
        info = probe(path)
        mw, mh = info.display_size
        if not mw or not mh:
            return 1.0
        cw, ch = self.edit.canvas.width, self.edit.canvas.height
        contain = min(cw / mw, ch / mh)
        if fit == "cover":
            return max(cw / mw, ch / mh) / contain
        return 1.0

    def _native_scale(self, path: str) -> float:
        """Scale that shows media at its native pixel size (for overlays authored at canvas resolution)."""
        info = probe(path)
        mw, mh = info.display_size
        if not mw or not mh:
            return 1.0
        cw, ch = self.edit.canvas.width, self.edit.canvas.height
        return 1.0 / min(cw / mw, ch / mh)

    # -------------------------------------------------------------- tracks

    def build(self) -> tuple[dict, BuildReport]:
        e = self.edit
        s = self.script
        s.add_track(cc.TrackType.video, "main")
        if e.broll:
            s.add_track(cc.TrackType.video, "broll", relative_index=1)
        overlay_layers = sorted({o.layer for o in e.overlays})
        for i, layer in enumerate(overlay_layers):
            s.add_track(cc.TrackType.video, f"overlay_{layer}", relative_index=2 + i)

        self._main_track()
        self._broll_track()
        self._overlays()
        self._texts()
        self._captions()
        self._audio()
        self._effects()
        self._grade()

        built = self._export()
        return built, self.report

    def _crop_keyframes(self, seg: Any, clip: Clip, path: str, base: float) -> None:
        """Auto-reframe: move a cover-scaled clip so the tracked subject stays centred (CapCut units)."""
        info = probe(path)
        mw, mh = info.display_size
        cw, ch = self.edit.canvas.width, self.edit.canvas.height
        contain = min(cw / mw, ch / mh)
        dw, dh = mw * contain * base, mh * contain * base
        max_x, max_y = max(0.0, (dw - cw) / cw), max(0.0, (dh - ch) / ch)
        for k in clip.crop:
            tx = min(max_x, max(-max_x, (0.5 - k.cx) * dw / (cw / 2)))
            ty = min(max_y, max(-max_y, (k.cy - 0.5) * dh / (ch / 2)))
            seg.add_keyframe(cc.KeyframeProperty.position_x, us(k.t), tx)
            seg.add_keyframe(cc.KeyframeProperty.position_y, us(k.t), ty)
        self.report.count("reframe_keyframes", len(clip.crop))

    def _clip_segment(self, clip: Clip, *, mute: bool = False) -> Any:
        src = self.edit.sources[clip.source]
        fit = "cover" if clip.crop else clip.fit
        base = self._fit_scale(src.path, fit) * clip.transform.scale
        settings = cc.ClipSettings(alpha=clip.transform.opacity, rotation=clip.transform.rotation,
                                   scale_x=base, scale_y=base, transform_x=clip.transform.x, transform_y=clip.transform.y)
        kwargs: dict[str, Any] = {"clip_settings": settings, "volume": 0.0 if (mute or clip.mute) else clip.volume}
        if src.kind == "image":
            seg = cc.VideoSegment(self._video_material(src.path), cc.Timerange(us(clip.start or 0), us(clip.duration)), **kwargs)
        else:
            seg = cc.VideoSegment(
                self._video_material(src.path),
                cc.Timerange(us(clip.start or 0), us(clip.duration)),
                source_timerange=cc.Timerange(us(clip.src_in), us(clip.src_out - clip.src_in)),
                speed=clip.speed if abs(clip.speed - 1.0) > 1e-3 else None, **kwargs,
            )
        if clip.crop and src.kind == "video":
            self._crop_keyframes(seg, clip, src.path, base)
        if clip.zoom:
            z = clip.zoom
            seg.add_keyframe(cc.KeyframeProperty.uniform_scale, 0, base * z.start_scale)
            seg.add_keyframe(cc.KeyframeProperty.uniform_scale, us(clip.duration), base * z.end_scale)
            self.report.count("zoom_keyframes")
        for name in (clip.capcut_animation_in,):
            meta = self._lookup("video_intro", name)
            if meta:
                seg.add_animation(meta)
        meta = self._lookup("video_outro", clip.capcut_animation_out)
        if meta:
            seg.add_animation(meta)
        flt = self._lookup("filter", clip.capcut_filter)
        if flt:
            seg.add_filter(flt)
        return seg

    def _main_track(self) -> None:
        segments = []
        for clip in self.edit.main:
            seg = self._clip_segment(clip)
            segments.append((clip, seg))
        # CapCut stores a transition on the segment *before* the cut.
        for (prev_clip, prev_seg), (clip, _) in zip(segments, segments[1:]):
            if clip.transition_in:
                tr = clip.transition_in
                meta = self._lookup("transition", tr.capcut or tr.type)
                if meta:
                    prev_seg.add_transition(meta, duration=us(tr.duration))
                    self.report.count("transitions")
        for _, seg in segments:
            self.script.add_segment(seg, "main")
        self.report.count("main_clips", len(segments))

    def _broll_track(self) -> None:
        for clip in self.edit.broll:
            if clip.start is None:
                self.report.warn(f"b-roll {clip.id} has no start; skipped")
                continue
            self.script.add_segment(self._clip_segment(clip, mute=True), "broll")
            self.report.count("broll_clips")

    def _overlays(self) -> None:
        for ov in self.edit.overlays:
            if not ov.path or not Path(ov.path).exists():
                self.report.warn(f"overlay {ov.id} has no rendered file yet; skipped (run `vedit mg render`)")
                continue
            from ..mg import capcut_path
            path = capcut_path(ov, self.overlay_mode) or ov.path
            if self.overlay_mode == "chroma" and path.endswith("_key.mp4") and ov.chroma is None:
                ov = ov.model_copy(update={"chroma": "#00FF00"})
            scale = (self._fit_scale(path, ov.fit) if ov.fit != "none" else self._native_scale(path)) * ov.transform.scale
            settings = cc.ClipSettings(alpha=ov.transform.opacity, rotation=ov.transform.rotation, scale_x=scale,
                                       scale_y=scale, transform_x=ov.transform.x, transform_y=ov.transform.y)
            info = probe(path)
            limit = max(0.1, self.edit.duration - ov.start)     # never extend the project past the main track
            if info.kind == "image" or info.duration <= 0:
                seg = cc.VideoSegment(self._video_material(path), cc.Timerange(us(ov.start), us(min(ov.duration, limit))),
                                      clip_settings=settings)
            else:
                dur = min(ov.duration, info.duration, limit)
                seg = cc.VideoSegment(self._video_material(path), cc.Timerange(us(ov.start), us(dur)),
                                      source_timerange=cc.Timerange(0, us(dur)), volume=0.0, clip_settings=settings)
            if ov.chroma:
                color = ov.chroma.upper() if len(ov.chroma) == 9 else ov.chroma[:7].upper() + "FF"   # pyCapCut wants #RRGGBBAA
                seg.add_chroma(color, intensity=25.0, edge_smooth=10.0)
            self.script.add_segment(seg, f"overlay_{ov.layer}")
            self.report.count("overlays")

    def _text_segment(self, text: str, start: float, duration: float, style: dict, *, y: float, x: float = 0.0) -> Any:
        size = style.get("size", 0.06) * CAPCUT_TEXT_SIZE_PER_FRAC * style.get("capcut", {}).get("size_scale", 1.0)
        font = self._lookup("font", (style.get("capcut") or {}).get("font"))
        border = None
        if style.get("stroke"):
            border = cc.TextBorder(color=_rgb(style["stroke"]), width=max(10.0, style.get("stroke_width", 0.08) * 450))
        background = None
        if style.get("background"):
            bg = style["background"]
            background = cc.TextBackground(color=bg["color"][:7], alpha=bg.get("alpha", 0.6), round_radius=bg.get("radius", 0.2))
        shadow = cc.TextShadow(alpha=0.6, distance=4.0) if style.get("shadow") else None
        tstyle = cc.TextStyle(size=round(size, 2), bold=bool(style.get("bold")), color=_rgb(style.get("color", "#FFFFFF")),
                              align=1, auto_wrapping=True, max_line_width=0.86,
                              letter_spacing=int(style.get("letter_spacing", 0)))
        seg = cc.TextSegment(text, cc.Timerange(us(start), us(max(duration, 0.1))), font=font, style=tstyle,
                             clip_settings=cc.ClipSettings(transform_x=x, transform_y=y),
                             border=border, background=background, shadow=shadow)
        return seg

    def _texts(self) -> None:
        if not self.edit.texts:
            return
        self.script.add_track(cc.TrackType.text, "titles", relative_index=10)
        for item in self.edit.texts:
            style = {**caps.BASE_STYLE, "uppercase": False, **item.style}
            seg = self._text_segment(item.text, item.start, item.duration, style, y=item.transform.y, x=item.transform.x)
            for category, name in (("text_intro", item.capcut_intro), ("text_outro", item.capcut_outro),
                                   ("text_loop", item.capcut_loop)):
                meta = self._lookup(category, name)
                if meta:
                    seg.add_animation(meta)
            self.script.add_segment(seg, "titles")
            self.report.count("titles")

    def _captions(self) -> None:
        e = self.edit
        if not (e.captions.enabled and e.capcut.include_captions):
            return
        chunks = e.captions.chunks or caps.build_chunks(e)
        if not chunks:
            return
        style = caps.resolve_style(e.captions.style, e.captions.overrides)
        landscape = e.canvas.width > e.canvas.height
        y = style.get("y_landscape" if landscape else "y", style["y"])
        self.script.add_track(cc.TrackType.text, "captions", relative_index=11)
        intro = self._lookup("text_intro", (style.get("capcut") or {}).get("intro"))
        total = e.duration
        for chunk in chunks:
            if chunk.start >= total:
                continue
            text = caps._display(chunk.text, style)
            seg = self._text_segment(text, chunk.start, min(chunk.end, total) - chunk.start, style,
                                     y=chunk.y if chunk.y is not None else y)
            if intro:
                seg.add_animation(intro, duration=min(0.25, (chunk.end - chunk.start) / 2) * US)
            self.script.add_segment(seg, "captions")
        self.report.count("captions", len(chunks))

    def _speech_regions(self) -> list[tuple[float, float]]:
        """Timeline ranges with speech, from caption words (used for music ducking keyframes)."""
        chunks = self.edit.captions.chunks or (caps.build_chunks(self.edit) if self.edit.captions.enabled else [])
        regions: list[list[float]] = []
        for c in chunks:
            if regions and c.start - regions[-1][1] < 0.8:
                regions[-1][1] = max(regions[-1][1], c.end)
            else:
                regions.append([c.start, c.end])
        if not regions:
            regions = [[c.start or 0, c.end] for c in self.edit.main if not c.mute]
        return [(a, b) for a, b in regions]

    def _audio(self) -> None:
        e = self.edit
        if not e.audio:
            return
        roles = sorted({a.role for a in e.audio}, key=["vo", "music", "sfx", "ambience"].index)
        for i, role in enumerate(roles):
            self.script.add_track(cc.TrackType.audio, role, relative_index=i)
        speech = self._speech_regions()
        duck = 10 ** (e.output.audio.duck_db / 20)
        for a in e.audio:
            src = e.sources[a.source]
            info = probe(src.path)
            src_out = a.src_out if a.src_out is not None else info.duration
            total = e.duration
            length = min(src_out - a.src_in, max(0.1, total - a.start)) if a.role in ("music", "ambience") else src_out - a.src_in
            if length <= 0:
                continue
            seg = cc.AudioSegment(self._audio_material(src.path), cc.Timerange(us(a.start), us(length)),
                                  source_timerange=cc.Timerange(us(a.src_in), us(length)), volume=a.volume)
            if a.fade_in or a.fade_out:
                seg.add_fade(us(a.fade_in), us(a.fade_out))
            if a.ducks and speech:
                for s0, s1 in speech:
                    for t, v in ((s0 - 0.25, 1.0), (s0, duck), (s1, duck), (s1 + 0.35, 1.0)):
                        off = t - a.start
                        if 0 <= off <= length:
                            seg.add_keyframe(us(off), a.volume * v)
                self.report.count("duck_keyframes")
            self.script.add_segment(seg, a.role)
            self.report.count(f"audio_{a.role}")

    def _effects(self) -> None:
        if not self.edit.effects:
            return
        self.script.add_track(cc.TrackType.effect, "effects")
        for fx in self.edit.effects:
            meta = self._lookup("scene_effect", fx.capcut or fx.render)
            if meta:
                self.script.add_effect(meta, cc.Timerange(us(fx.start), us(fx.duration)), "effects", params=fx.capcut_params)
                self.report.count("effects")

    def _grade(self) -> None:
        g = self.edit.color
        name = g.capcut_filter or g.preset
        meta = self._lookup("filter", name) if name else None
        if meta:
            self.script.add_track(cc.TrackType.filter, "grade")
            self.script.add_filter(meta, cc.Timerange(0, us(self.edit.duration)), "grade", intensity=100 * g.intensity)
            self.report.count("filters")

    def _canvas_ratio(self) -> str:
        """CapCut's ratio key. "original" would make CapCut follow the first clip's shape."""
        w, h = self.edit.canvas.width, self.edit.canvas.height
        for key, (rw, rh) in {"9:16": (9, 16), "16:9": (16, 9), "1:1": (1, 1), "4:3": (4, 3), "3:4": (3, 4),
                              "4:5": (4, 5), "2:1": (2, 1), "21:9": (21, 9), "2.35:1": (2.35, 1)}.items():
            if abs(w / h - rw / rh) < 0.01:
                return key
        return "custom"

    def _export(self) -> dict:
        import json
        data = json.loads(self.script.dumps())
        canvas = dict(data.get("canvas_config") or {})
        canvas.update({"width": self.edit.canvas.width, "height": self.edit.canvas.height, "ratio": self._canvas_ratio()})
        return {
            "duration": data.get("duration", 0), "fps": data.get("fps", self.edit.canvas.fps),
            "canvas_config": canvas, "config": {"maintrack_adsorb": True},
            "materials": data.get("materials", {}), "tracks": data.get("tracks", []),
            "keyframes": data.get("keyframes"),
        }


def build(edit: Edit, *, pro_allowed: bool, overlay_mode: str = "alpha") -> tuple[dict, BuildReport]:
    return Builder(edit, pro_allowed=pro_allowed, overlay_mode=overlay_mode).build()
