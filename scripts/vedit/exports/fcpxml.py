"""FCPXML 1.10 writer (DaVinci Resolve 18+, Final Cut Pro 10.6+), no dependencies.

Layout: the main track is the primary storyline (asset-clips with their own sound, dissolves between
them); b-roll, graphics and styled caption layers are connected clips on positive lanes; music,
voice-over and effects are connected audio clips on negative lanes with audio roles. Times are exact
frame multiples of the sequence rate. Positions use FCP's units (percent of the frame height, +y up).
Notes for things a timeline cannot hold go into markers on the storyline.
"""

from __future__ import annotations

import math
from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from . import Handoff, Item, MarkerOut, rate

DISSOLVE_UID = "FxPlug:4731E73A-8DAC-4113-9A30-AE85B1761265"      # Cross Dissolve
AUDIO_XFADE_UID = "FFAudioTransition"                            # Audio Crossfade


class _Time:
    def __init__(self, fps: float):
        self.r = rate(fps)

    def __call__(self, t: float, r: Fraction | None = None) -> str:
        r = r or self.r
        n = round(t * r)
        v = Fraction(n) / r
        if v == 0:
            return "0s"
        if v.denominator == 1:
            return f"{v.numerator}s"
        return f"{v.numerator}/{v.denominator}s"

    def snap(self, t: float) -> float:
        return float(Fraction(round(t * self.r)) / self.r)


def _attrs(**kw) -> str:
    return "".join(f" {k.rstrip('_').replace('__', '-')}={quoteattr(str(v))}" for k, v in kw.items() if v is not None)


def _db(gain: float) -> str:
    if gain <= 1e-4:
        return "-96dB"
    return f"{20 * math.log10(gain):.2f}dB"


def write(h: Handoff, out: str | Path) -> Path:
    out = Path(out)
    T = _Time(h.fps)
    W, H = h.width, h.height
    unit = 100.0 / H                                         # FCP position unit: percent of frame height

    # ---------------------------------------------------------- resources
    res: list[str] = [f'<format{_attrs(id="r1", frameDuration=T(1 / float(T.r)), width=W, height=H, colorSpace="1-1-1 (Rec. 709)")}/>']
    assets: dict[str, str] = {}
    asset_rate: dict[str, Fraction] = {}
    n = [1]

    def rid() -> str:
        n[0] += 1
        return f"r{n[0]}"

    def asset_for(it: Item) -> str:
        if it.path in assets:
            return assets[it.path]
        fmt = None
        if it.media == "video":
            fmt = rid()
            ar = rate(it.src_fps or h.fps)
            res.append(f'<format{_attrs(id=fmt, frameDuration=T(1 / float(ar), ar), width=it.width or None, height=it.height or None)}/>')
            asset_rate[it.path] = ar
        elif it.media == "image":
            fmt = rid()
            res.append(f'<format{_attrs(id=fmt, name="FFVideoFormatRateUndefined", width=it.width or None, height=it.height or None)}/>')
        aid = rid()
        ar = asset_rate.get(it.path, T.r)
        dur = "0s" if it.media == "image" else T(it.src_duration, ar)
        has_audio = it.has_audio or it.media == "audio" or any(
            o.path == it.path and o.has_audio for t in h.tracks for o in t.items)
        res.append(f"<asset{_attrs(id=aid, name=Path(it.path).stem, start=T(it.tc_start, ar), duration=dur, hasVideo=1 if it.media != 'audio' else None, format=fmt, hasAudio=1 if has_audio else None, audioSources=1 if has_audio else None, audioChannels=2 if has_audio else None, audioRate=48000 if has_audio else None)}>"
                   f'<media-rep{_attrs(kind="original-media", src=Path(it.path).resolve().as_uri())}/></asset>')
        assets[it.path] = aid
        return aid

    uses_transitions = any(i.transition for i in h.tracks[0].items[1:]) if h.tracks else False
    if uses_transitions:
        res.append(f'<effect{_attrs(id="fxv", name="Cross Dissolve", uid=DISSOLVE_UID)}/>')
        res.append(f'<effect{_attrs(id="fxa", name="Audio Crossfade", uid=AUDIO_XFADE_UID)}/>')

    # ---------------------------------------------------------- clip bodies

    def local(it: Item) -> float:
        """Clip-local time of the item's first frame (asset time, timecode included)."""
        return 0.0 if it.media == "image" else it.tc_start + it.src_in

    def transform_xml(it: Item, start_local: float) -> list[str]:
        out_x: list[str] = []
        if it.fit == "cover" or it.fit == "stretch":
            out_x.append('<adjust-conform type="fill"/>')
        elif it.fit == "none":
            out_x.append('<adjust-conform type="none"/>')
        sk, pk = it.keys.get("scale"), it.keys.get("position")
        pos = (pk[0][1], pk[0][2]) if pk else (it.x, it.y)
        sc = sk[0][1] if sk else it.scale
        static = (abs(pos[0]) > 1e-3 or abs(pos[1]) > 1e-3 or abs(sc - 1) > 1e-4 or abs(it.rotation) > 1e-3)
        if static or sk or pk:
            params = []
            if pk:
                kf = "".join(f'<keyframe{_attrs(time=T(start_local + k[0]), value=f"{k[1] * unit:.4f} {k[2] * unit:.4f}")}/>' for k in pk)
                params.append(f'<param name="position"><keyframeAnimation>{kf}</keyframeAnimation></param>')
            if sk:
                kf = "".join(f'<keyframe{_attrs(time=T(start_local + k[0]), value=f"{k[1]:.5f} {k[1]:.5f}")}/>' for k in sk)
                params.append(f'<param name="scale"><keyframeAnimation>{kf}</keyframeAnimation></param>')
            out_x.append(f"<adjust-transform{_attrs(position=f'{pos[0] * unit:.4f} {pos[1] * unit:.4f}', scale=f'{sc:.5f} {sc:.5f}', rotation=f'{-it.rotation:g}' if it.rotation else None)}>"
                         + "".join(params) + "</adjust-transform>")
        if it.opacity < 0.999 or it.fade_in or it.fade_out:
            keys = []
            if it.fade_in:
                keys += [(0.0, 0.0), (it.fade_in, it.opacity)]
            if it.fade_out:
                keys += [(max(0.0, it.duration - it.fade_out), it.opacity), (it.duration, 0.0)]
            body = ""
            if keys:
                kf = "".join(f'<keyframe{_attrs(time=T(start_local + t), value=f"{v:.3f}")}/>' for t, v in keys)
                body = f'<param name="amount"><keyframeAnimation>{kf}</keyframeAnimation></param>'
            out_x.append(f'<adjust-blend{_attrs(amount=f"{it.opacity:.3f}")}>{body}</adjust-blend>')
        return out_x

    def volume_xml(it: Item, audio_fades: bool) -> list[str]:
        fades = ""
        if audio_fades and it.fade_in:
            fades += f'<fadeIn{_attrs(type="easeIn", duration=T(it.fade_in))}/>'
        if audio_fades and it.fade_out:
            fades += f'<fadeOut{_attrs(type="easeOut", duration=T(it.fade_out))}/>'
        if abs(it.volume - 1) < 1e-3 and not fades:
            return []
        body = f'<param name="amount">{fades}</param>' if fades else ""
        return [f"<adjust-volume{_attrs(amount=_db(it.volume))}>{body}</adjust-volume>"]

    def timemap_xml(it: Item, start_local: float) -> list[str]:
        if abs(it.speed - 1) < 1e-4 or it.media == "image":
            return []
        a, b = start_local, start_local + it.duration
        return [f'<timeMap><timept{_attrs(time=T(a), value=T(a), interp="linear")}/>'
                f'<timept{_attrs(time=T(b), value=T(a + it.duration * it.speed), interp="linear")}/></timeMap>']

    def marker_xml(m: MarkerOut, at_local: float) -> str:
        dur = T(max(m.duration, 1 / float(T.r)))
        if m.kind == "chapter":
            return f"<chapter-marker{_attrs(start=T(at_local), duration=dur, value=m.name, posterOffset='0s')}/>"
        return f"<marker{_attrs(start=T(at_local), duration=dur, value=m.name, completed='0' if m.kind == 'todo' else None, note=m.note or None)}/>"

    def element(it: Item, *, offset_s: float, lane: int | None, children: list[str], audio_only: bool = False) -> str:
        aid = asset_for(it)
        start_local = T.snap(local(it))
        dur = T(it.duration)
        body: list[str] = []
        if it.note:
            body.append(f"<note>{escape(it.note)}</note>")
        body += timemap_xml(it, start_local)
        if not audio_only:
            body += transform_xml(it, start_local)
        if it.media != "image":
            body += volume_xml(it, audio_fades=audio_only)
        body += children
        tag = "video" if it.media == "image" else "asset-clip"
        attrs = dict(ref=aid, lane=lane, offset=T(offset_s), name=it.name, start=T(start_local) if it.media != "image" else None,
                     duration=dur)
        if tag == "asset-clip":
            if audio_only:
                attrs["audioRole"] = {"music": "music", "effects": "effects", "vo": "dialogue.voiceover"}.get(it.role, "dialogue")
            else:
                attrs["videoRole"] = {"graphics": "titles", "titles": "titles"}.get(it.role, "video")
                if it.has_audio:
                    attrs["audioRole"] = "dialogue"
                elif it.media == "video":
                    attrs["srcEnable"] = "video"
            if it.tc_start:
                attrs["tcFormat"] = "NDF"
        else:
            attrs["start"] = "0s"
        return f"<{tag}{_attrs(**attrs)}>" + "".join(body) + f"</{tag}>"

    # ---------------------------------------------------------- storyline + connected items
    main = list(h.tracks[0].items) if h.tracks and h.tracks[0].role == "video" else []
    connected: list[tuple[int, Item, bool]] = []
    lane_v, lane_a = 0, 0
    for tr in h.tracks[1:]:
        if tr.kind == "video":
            lane_v += 1
            connected += [(lane_v, it, False) for it in tr.items]
        elif tr.role != "dialogue":               # dialogue = the main clips' own sound, already inside them
            lane_a -= 1
            connected += [(lane_a, it, True) for it in tr.items]

    spine_offsets = [T.snap(it.start) for it in main]
    if main:
        spans = [(spine_offsets[i], spine_offsets[i + 1] if i + 1 < len(main) else T.snap(main[i].end)) for i in range(len(main))]
    else:
        spans = [(0.0, T.snap(h.duration))]

    def parent_of(t: float) -> int:
        for i, (a, b) in enumerate(spans):
            if t < b - 1e-6:
                return i
        return len(spans) - 1

    kids: list[list[str]] = [[] for _ in spans]
    marks: list[list[str]] = [[] for _ in spans]

    def parent_local(i: int, t: float) -> float:
        base = T.snap(local(main[i])) if main else 0.0
        if main and abs(main[i].speed - 1) > 1e-4:
            return base + (t - spans[i][0])            # retimed parents keep timeline-rate local time (see timeMap)
        return base + (t - spans[i][0])

    for lane, it, audio_only in sorted(connected, key=lambda x: (x[1].start, x[0])):
        i = parent_of(it.start)
        kids[i].append(element(it, offset_s=parent_local(i, T.snap(it.start)), lane=lane, children=[], audio_only=audio_only))
    for m in h.markers:
        i = parent_of(m.t)
        marks[i].append(marker_xml(m, parent_local(i, T.snap(m.t))))

    spine: list[str] = []
    if main:
        for i, it in enumerate(main):
            tr = it.transition
            if i > 0 and tr and uses_transitions:
                d = T.snap(min(tr["duration"], main[i - 1].duration, it.duration))
                spine.append(f"<transition{_attrs(name='Cross Dissolve', offset=T(spine_offsets[i] - d / 2), duration=T(d))}>"
                             f'<filter-video ref="fxv" name="Cross Dissolve"/><filter-audio ref="fxa" name="Audio Crossfade"/>'
                             f"</transition>")
            spine.append(element(it, offset_s=spine_offsets[i], lane=None, children=kids[i] + marks[i]))
    else:
        spine.append(f"<gap{_attrs(name='Gap', offset='0s', start='0s', duration=T(h.duration))}>" + "".join(kids[0] + marks[0]) + "</gap>")

    seq_dur = T(max(h.duration, spans[-1][1]))
    project = (f"<project{_attrs(name=h.name)}><sequence{_attrs(format='r1', duration=seq_dur, tcStart='0s', tcFormat='NDF', audioLayout='stereo', audioRate='48k')}>"
               f"<spine>{''.join(spine)}</spine></sequence></project>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.10">\n'
           f"<resources>\n{chr(10).join(res)}\n</resources>\n"
           f"<library><event{_attrs(name=f'vedit {h.name}')}>{project}</event></library>\n</fcpxml>\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")
    return out


def read(path: str | Path) -> dict:
    """Minimal reader for our own FCPXML (and simple FCP/Resolve exports): spine clips + connected clips,
    in timeline seconds. Used by tests and by `handoff diff` when the otio tool is missing."""
    import xml.etree.ElementTree as ET
    from urllib.parse import unquote, urlparse

    def sec(v: str | None) -> float:
        if not v:
            return 0.0
        v = v.rstrip("s")
        if "/" in v:
            a, b = v.split("/")
            return float(Fraction(int(a), int(b)))
        return float(v)

    root = ET.parse(path).getroot()
    assets = {}
    for a in root.iter("asset"):
        rep = a.find("media-rep")
        src = rep.get("src") if rep is not None else a.get("src", "")
        p = unquote(urlparse(src).path)
        if len(p) > 2 and p[0] == "/" and p[2] == ":":
            p = p[1:]
        assets[a.get("id")] = {"path": str(Path(p)), "start": sec(a.get("start"))}
    spine = root.find(".//sequence/spine")
    clips, connected, markers, transitions = [], [], [], []

    def visit(el, parent_offset: float, parent_start: float, lane: int | None):
        off = sec(el.get("offset"))
        tl = off if lane is None else parent_offset + (off - parent_start)
        start = sec(el.get("start"))
        a = assets.get(el.get("ref"), {"path": "", "start": 0.0})
        vol = el.find("adjust-volume")
        db = vol.get("amount", "0dB") if vol is not None else "0dB"
        rec = {"name": el.get("name", ""), "path": a["path"], "start": round(tl, 4), "duration": round(sec(el.get("duration")), 4),
               "src_in": round(start - a["start"], 4), "lane": int(el.get("lane", "0")), "tag": el.tag,
               "audio_role": el.get("audioRole"), "video_role": el.get("videoRole"),
               "volume_db": float(db.replace("dB", "") or 0), "enabled": el.get("enabled", "1") != "0"}
        (clips if lane is None else connected).append(rec)
        for child in el:
            if child.get("lane") is not None:
                visit(child, tl, start, int(child.get("lane")))
            elif child.tag in ("marker", "chapter-marker"):
                markers.append({"t": round(tl + sec(child.get("start")) - start, 4), "name": child.get("value", ""),
                                "note": child.get("note", ""), "kind": "chapter" if child.tag == "chapter-marker" else "note"})

    for el in spine:
        if el.tag == "transition":
            transitions.append({"offset": sec(el.get("offset")), "duration": sec(el.get("duration"))})
        elif el.tag in ("asset-clip", "video", "clip", "gap", "audio"):
            visit(el, 0.0, 0.0, None)
    return {"clips": clips, "connected": connected, "markers": markers, "transitions": transitions}
