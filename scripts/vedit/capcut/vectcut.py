"""Optional backend: build the CapCut draft through a running VectCutAPI server (sun-guannan/VectCutAPI).

This is the Atx-Guy/capcut-mcp-server idea with the parameter mapping fixed against VectCutAPI's
actual routes (/add_video_keyframe, effect_type, sticker_id, srt, transform_x/y, intro_animation ...).
The native backend (store.py + builder.py) is the default; use this when you already run VectCutAPI
(e.g. for its cloud preview/render) or want to compare results.
"""

from __future__ import annotations

from pathlib import Path

from .. import captions as caps
from ..timeline import Edit
from ..util import VeditError
from .store import drafts_root


class VectCut:
    def __init__(self, base_url: str = "http://localhost:9001"):
        self.base = base_url.rstrip("/")

    def _post(self, route: str, payload: dict) -> dict:
        import httpx
        try:
            r = httpx.post(f"{self.base}{route}", json=payload, timeout=300)
        except httpx.HTTPError as exc:
            raise VeditError(f"VectCutAPI not reachable at {self.base} ({exc}). Start it with `python capcut_server.py`.") from exc
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"success": False, "error": r.text}
        if not data.get("success", True):
            raise VeditError(f"VectCutAPI {route} failed: {data.get('error')}")
        return data.get("output", data)

    def build(self, edit: Edit, *, project_name: str) -> dict:
        e = edit.layout()
        W, H = e.canvas.width, e.canvas.height
        draft = self._post("/create_draft", {"width": W, "height": H})
        did = draft.get("draft_id")
        common = {"draft_id": did, "width": W, "height": H}
        for clip in e.main:
            src = e.sources[clip.source]
            route, key = ("/add_image", "image_url") if src.kind == "image" else ("/add_video", "video_url")
            payload = {**common, key: str(Path(src.path).resolve()), "start": clip.src_in, "end": clip.src_out,
                       "target_start": clip.start, "speed": clip.speed, "volume": 0.0 if clip.mute else clip.volume,
                       "track_name": "main", "transform_x": clip.transform.x, "transform_y": clip.transform.y,
                       "scale_x": clip.transform.scale, "scale_y": clip.transform.scale}
            if clip.transition_in and clip.transition_in.capcut:
                payload.update({"transition": clip.transition_in.capcut, "transition_duration": clip.transition_in.duration})
            self._post(route, payload)
            if clip.zoom:
                self._post("/add_video_keyframe", {**common, "track_name": "main", "property_types": ["uniform_scale", "uniform_scale"],
                                                   "times": [clip.start, clip.end],
                                                   "values": [str(clip.zoom.start_scale), str(clip.zoom.end_scale)]})
        for clip in e.broll:
            src = e.sources[clip.source]
            self._post("/add_video", {**common, "video_url": str(Path(src.path).resolve()), "start": clip.src_in, "end": clip.src_out,
                                      "target_start": clip.start, "volume": 0.0, "track_name": "broll", "relative_index": 1})
        for ov in e.overlays:
            if ov.path:
                self._post("/add_video", {**common, "video_url": str(Path(ov.path).resolve()), "start": 0, "end": ov.duration,
                                          "target_start": ov.start, "volume": 0.0, "track_name": f"overlay_{ov.layer}",
                                          "relative_index": 2 + ov.layer})
        for a in e.audio:
            src = e.sources[a.source]
            self._post("/add_audio", {**common, "audio_url": str(Path(src.path).resolve()), "start": a.src_in,
                                      "end": a.src_out, "target_start": a.start, "volume": a.volume, "track_name": a.role})
        for t in e.texts:
            st = {**caps.BASE_STYLE, **t.style}
            payload = {**common, "text": t.text, "start": t.start, "end": t.start + t.duration, "track_name": "titles",
                       "font_size": round(st["size"] * 160, 2), "font_color": st.get("color", "#FFFFFF"),
                       "transform_x": t.transform.x, "transform_y": t.transform.y}
            if t.capcut_intro:
                payload["intro_animation"] = t.capcut_intro
            if t.capcut_outro:
                payload["outro_animation"] = t.capcut_outro
            self._post("/add_text", payload)
        if e.captions.enabled:
            chunks = e.captions.chunks or caps.build_chunks(e)
            if chunks:
                tmp = Path(drafts_root()).parent / f"{project_name}.srt"
                caps.to_srt(chunks, tmp)
                style = caps.resolve_style(e.captions.style, e.captions.overrides)
                self._post("/add_subtitle", {**common, "srt": tmp.read_text(encoding="utf-8"), "track_name": "captions",
                                             "font_size": round(style["size"] * 160, 2), "font_color": style["color"],
                                             "border_color": style.get("stroke") or "#000000", "border_width": 20,
                                             "transform_y": style["y"]})
        for fx in e.effects:
            if fx.capcut:
                self._post("/add_effect", {**common, "effect_type": fx.capcut, "start": fx.start, "end": fx.start + fx.duration,
                                           "track_name": "effects", "params": fx.capcut_params})
        return self._post("/save_draft", {"draft_id": did, "draft_folder": str(drafts_root()), "project_name": project_name})
