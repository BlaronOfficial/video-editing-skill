"""MLT XML for Shotcut (and anything MLT-based), written natively.

One producer per placed clip (so per-clip filters stay independent), one playlist per track with blanks
between clips, a tractor that stacks the tracks over a black background, `mix` transitions for audio and
`frei0r.cairoblend` for video layers above V1. Gain and fades are Shotcut's own filters (audioGain,
fadeInVolume / fadeOutVolume); sizes and positions use the "Size, Position & Rotate" filter (affine).
Dissolves are not rebuilt (Shotcut keeps them as nested tractors): they become markers.
Kdenlive reads its own format better: use the .kdenlive hand-off for it.
"""

from __future__ import annotations

import math
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from . import Handoff, Item, frames, rate

MARKER_RGB = {"blue": "#2f6fe0", "red": "#e0352f", "green": "#2fa84f", "yellow": "#e0c22f", "purple": "#8e44ad",
              "cyan": "#1fb5c9", "orange": "#e07b2f", "pink": "#e05fa8"}


def _clock(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 3600):02d}:{int(t // 60 % 60):02d}:{t % 60:06.3f}"


def _props(d: dict) -> str:
    return "".join(f"<property name={quoteattr(k)}>{escape(str(v))}</property>" for k, v in d.items() if v is not None)


def write(h: Handoff, out: str | Path) -> Path:
    out = Path(out)
    fps = h.fps
    r = rate(fps)
    W, H = h.width, h.height
    total = max(1, frames(h.duration, fps))
    producers: list[str] = []
    playlists: list[str] = []
    tracks: list[tuple[str, str]] = []            # (playlist id, hide)
    n = [0]

    def gid(prefix: str) -> str:
        n[0] += 1
        return f"{prefix}{n[0]}"

    def filters(it: Item, length: int, first: int, grade: bool) -> str:
        """Filters on a producer run in the producer's own frame numbers: in/out = the entry's source range,
        and keyframes count from that in point."""
        fl: list[str] = []
        if it.has_audio or it.media == "audio":
            if abs(it.volume - 1) > 1e-3:
                db = -60.0 if it.volume <= 1e-4 else 20 * math.log10(it.volume)
                fl.append(_props({"window": 75, "max_gain": "20dB", "level": f"{db:.2f}", "mlt_service": "volume",
                                  "shotcut:filter": "audioGain"}))
            if it.media == "audio" and it.fade_in:
                k = max(1, frames(it.fade_in, fps))
                fl.append(_props({"window": 75, "max_gain": "20dB", "level": f"0=-60;{k}=0", "mlt_service": "volume",
                                  "shotcut:filter": "fadeInVolume", "shotcut:animIn": _clock(it.fade_in)}))
            if it.media == "audio" and it.fade_out:
                k = max(1, frames(it.fade_out, fps))
                fl.append(_props({"window": 75, "max_gain": "20dB", "level": f"{length - k}=0;{length - 1}=-60",
                                  "mlt_service": "volume", "shotcut:filter": "fadeOutVolume",
                                  "shotcut:animOut": _clock(it.fade_out)}))
        if it.has_video and it.media != "audio":
            rect = _rects(it, W, H)
            if rect:
                fl.append(_props({"background": "color:#00000000", "mlt_service": "affine",
                                  "shotcut:filter": "affineSizePosition", "transition.fill": 1, "transition.distort": 0,
                                  "transition.rect": rect, "transition.valign": "middle", "transition.halign": "center",
                                  "shotcut:animIn": "00:00:00.000", "shotcut:animOut": "00:00:00.000",
                                  "transition.threads": 0, "transition.fix_rotate_x": f"{it.rotation:g}"}))
        if grade and h.lut:
            fl.append(_props({"mlt_service": "avfilter.lut3d", "av.file": Path(h.lut).as_posix(), "av.interp": "tetrahedral",
                              "shotcut:filter": "lut3d"}))
        return "".join(f'<filter id="{gid("filter")}" in="{first}" out="{first + length - 1}">{f}</filter>' for f in fl)

    def producer(it: Item, grade: bool = False) -> tuple[str, int, int]:
        pid = gid("producer")
        length = max(1, frames(it.duration, fps))
        if it.media == "image":
            src_in = 0
            props = {"length": total + length, "eof": "pause", "resource": Path(it.path).as_posix(), "ttl": 1,
                     "aspect_ratio": 1, "mlt_service": "qimage", "shotcut:caption": Path(it.path).name}
        else:
            src_in = frames(it.src_in, fps)
            props = {"length": max(frames(it.src_duration, fps), src_in + length), "eof": "pause",
                     "resource": Path(it.path).as_posix(), "mlt_service": "avformat-novalidate", "seekable": 1,
                     "audio_index": 1 if it.has_audio and it.media == "video" else (0 if it.media == "audio" else -1),
                     "video_index": 0 if it.media == "video" else -1, "mute_on_pause": 0,
                     "shotcut:caption": it.name}
            if abs(it.speed - 1) > 1e-4:
                props.update({"resource": f"{it.speed:g}:{Path(it.path).as_posix()}", "mlt_service": "timewarp",
                              "warp_speed": f"{it.speed:g}", "warp_resource": Path(it.path).as_posix()})
                src_in = frames(it.src_in / it.speed, fps)
        producers.append(f'<producer id="{pid}" in="0" out="{props["length"] - 1}">{_props(props)}'
                         f'{filters(it, length, src_in, grade)}</producer>')
        return pid, src_in, length

    def playlist(name: str, items: list[Item], kind: str, grade: bool = False) -> str:
        plid = gid("playlist")
        body = [_props({"shotcut:video" if kind == "video" else "shotcut:audio": 1, "shotcut:name": name})]
        cursor = 0
        for it in sorted(items, key=lambda i: i.start):
            start = frames(it.start, fps)
            if start > cursor:
                body.append(f'<blank length="{start - cursor}"/>')
            pid, src_in, length = producer(it, grade)
            if start < cursor:                       # frame rounding overlap: trim the head
                src_in, length = src_in + (cursor - start), length - (cursor - start)
                start = cursor
            if length <= 0:
                continue
            body.append(f'<entry producer="{pid}" in="{src_in}" out="{src_in + length - 1}"/>')
            cursor = start + length
        playlists.append(f'<playlist id="{plid}">{"".join(body)}</playlist>')
        return plid

    video = [t for t in h.tracks if t.kind == "video"]
    audio = [t for t in h.tracks if t.kind == "audio"]
    for n_v, t in enumerate(video):
        tracks.append((playlist(t.name, t.items, "video", grade=n_v == 0), ""))     # the grade sits under graphics
    for t in audio:
        tracks.append((playlist(t.name, t.items, "audio"), "video"))

    trans = []
    for i, (_pl, hide) in enumerate(tracks, start=1):
        trans.append(f'<transition id="{gid("transition")}">' + _props({"a_track": 0, "b_track": i, "mlt_service": "mix",
                                                                         "always_active": 1, "sum": 1}) + "</transition>")
        if not hide:
            trans.append(f'<transition id="{gid("transition")}">' + _props({
                "a_track": 0 if i == 1 else 1, "b_track": i, "version": "0.1", "mlt_service": "frei0r.cairoblend",
                "threads": 0, "disable": 1 if i == 1 else 0}) + "</transition>")
    marks = "".join(
        f'<properties name="{i}">' + _props({"text": m.name + (f": {m.note}" if m.note else ""), "start": _clock(m.t),
                                               "end": _clock(m.t + m.duration), "color": MARKER_RGB.get(m.color, "#2f6fe0")})
        + "</properties>" for i, m in enumerate(h.markers))
    gcd = math.gcd(W, H)
    xml = (f'<?xml version="1.0" standalone="no"?>\n<mlt LC_NUMERIC="C" version="7.24.0" title={quoteattr(h.name)} producer="main_bin">\n'
           f'<profile description="vedit {W}x{H} {fps:g}fps" width="{W}" height="{H}" progressive="1" sample_aspect_num="1" '
           f'sample_aspect_den="1" display_aspect_num="{W // gcd}" display_aspect_den="{H // gcd}" '
           f'frame_rate_num="{r.numerator}" frame_rate_den="{r.denominator}" colorspace="709"/>\n'
           f'<playlist id="main_bin">{_props({"xml_retain": 1})}</playlist>\n'
           f'<producer id="black" in="0" out="{total - 1}">' + _props({
               "length": total, "eof": "pause", "resource": 0, "aspect_ratio": 1, "mlt_service": "color",
               "mlt_image_format": "rgba", "set.test_audio": 0}) + "</producer>\n"
           f'<playlist id="background"><entry producer="black" in="0" out="{total - 1}"/></playlist>\n'
           + "\n".join(producers) + "\n" + "\n".join(playlists) + "\n"
           f'<tractor id="tractor0" title={quoteattr(h.name)} in="0" out="{total - 1}">'
           + _props({"shotcut": 1, "shotcut:projectAudioChannels": 2, "shotcut:projectFolder": 0})
           + (f'<properties name="shotcut:markers">{marks}</properties>' if marks else "")
           + '<track producer="background"/>'
           + "".join(f'<track producer="{pl}"' + (f' hide="{hide}"' if hide else "") + "/>" for pl, hide in tracks)
           + "".join(trans) + "</tractor>\n</mlt>\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")
    return out


def _rects(it: Item, W: int, H: int) -> str | None:
    """`transition.rect` for the affine filter ("x y w h opacity", keyframed when the clip moves)."""
    iw, ih = it.width or W, it.height or H
    if it.fit == "cover":
        base = max(W / iw, H / ih)
    elif it.fit == "contain":
        base = min(W / iw, H / ih)
    elif it.fit == "stretch":
        return None
    else:
        base = 1.0

    def rect(scale: float, x: float, y: float, op: float) -> str:
        w, hh = iw * base * scale, ih * base * scale
        return f"{W / 2 + x - w / 2:.1f} {H / 2 - y - hh / 2:.1f} {w:.1f} {hh:.1f} {op:.3f}"

    sk, pk = it.keys.get("scale"), it.keys.get("position")
    if not sk and not pk:
        if it.fit == "contain" and abs(it.scale - 1) < 1e-4 and abs(it.x) < 0.5 and abs(it.y) < 0.5 and it.opacity > 0.999:
            return None                            # Shotcut's default letterbox is "contain"
        if it.fit == "none" and iw == W and ih == H and abs(it.scale - 1) < 1e-4 and abs(it.x) < 0.5 and abs(it.y) < 0.5 \
                and it.opacity > 0.999:
            return None
        return rect(it.scale, it.x, it.y, it.opacity)
    times = sorted({k[0] for k in (sk or [])} | {k[0] for k in (pk or [])})

    def at(keys, t, idx):
        if not keys:
            return None
        if t <= keys[0][0]:
            return keys[0][idx]
        for a, b in zip(keys, keys[1:]):
            if a[0] <= t <= b[0]:
                u = (t - a[0]) / max(b[0] - a[0], 1e-6)
                return a[idx] + (b[idx] - a[idx]) * u
        return keys[-1][idx]

    fps_frames = []
    for t in times:
        s = at(sk, t, 1) or it.scale
        x = at(pk, t, 1) if pk else it.x
        y = at(pk, t, 2) if pk else it.y
        fps_frames.append(f"{_clock(t)}={rect(s, x, y, it.opacity)}")
    return ";".join(fps_frames)


def read(path: str | Path) -> dict:
    """Tracks back out of an MLT file (ours or Shotcut's): items with path, timeline start, duration, src_in."""
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    prof = root.find("profile")
    fps = int(prof.get("frame_rate_num", 30)) / int(prof.get("frame_rate_den", 1)) if prof is not None else 30.0

    def prop(el, name):
        p = el.find(f"property[@name='{name}']")
        return p.text if p is not None else None

    def fr(v: str | None) -> float:
        if v is None:
            return 0.0
        if ":" in v:
            hh, mm, ss = v.split(":")
            return int(hh) * 3600 + int(mm) * 60 + float(ss)
        return int(v) / fps

    prods = {}
    for el in [*root.findall("producer"), *root.findall("chain")]:
        res = prop(el, "warp_resource") or prop(el, "resource") or ""
        prods[el.get("id")] = {"path": res, "speed": float(prop(el, "warp_speed") or 1)}
    lists = {pl.get("id"): pl for pl in root.findall("playlist")}
    tractor = root.find("tractor")
    tracks = []
    for tr in tractor.findall("track"):
        pl = lists.get(tr.get("producer"))
        if pl is None or tr.get("producer") == "background":
            continue
        kind = "audio" if prop(pl, "shotcut:audio") else "video"
        t, items = 0.0, []
        for el in pl:
            if el.tag == "blank":
                t += fr(el.get("length"))
            elif el.tag == "entry":
                a, b = fr(el.get("in")), fr(el.get("out")) + 1 / fps
                p = prods.get(el.get("producer"), {"path": "", "speed": 1.0})
                items.append({"path": str(Path(p["path"])) if p["path"] else "", "start": round(t, 4),
                              "duration": round(b - a, 4), "src_in": round(a * p["speed"], 4), "speed": p["speed"]})
                t += b - a
        tracks.append({"name": prop(pl, "shotcut:name") or pl.get("id"), "kind": kind, "items": items})
    markers = []
    mk = tractor.find("properties[@name='shotcut:markers']")
    if mk is not None:
        for m in mk:
            markers.append({"t": fr(prop(m, "start")), "name": prop(m, "text") or ""})
    return {"fps": fps, "tracks": tracks, "markers": markers}
