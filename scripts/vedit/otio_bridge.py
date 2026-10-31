"""Runs inside the otio tool venv (never imported by vedit): OpenTimelineIO and its adapters on vedit's
neutral hand-off timeline.

    python -I otio_bridge.py <command> <request.json> <result.json>

write:    {"handoff": {...}, "out": path, "adapter": "otio_json" | "fcp_xml" | "cmx_3600" | "kdenlive",
           "only_main": bool} -> {"out": path, "warnings": [...]}
read:     {"path": file, "rate": fps} -> {"tracks": [{name, kind, items: [{name, path, start, duration, src_in}]}],
           "markers": [...], "duration"} (any format OTIO reads: .otio .xml .fcpxml .edl .kdenlive)
validate: {"path": fcpxml, "dtd": file} -> {"valid": bool, "errors": [...]}   (lxml, DTD supplied by the owner)
"""

import json
import os
import sys
from urllib.parse import unquote, urlparse

ADAPTER_BY_EXT = {".otio": "otio_json", ".xml": "fcp_xml", ".fcpxml": "fcpx_xml", ".edl": "cmx_3600",
                  ".kdenlive": "kdenlive"}
COLOR = {"blue": "BLUE", "red": "RED", "green": "GREEN", "yellow": "YELLOW", "purple": "PURPLE", "cyan": "CYAN",
         "orange": "ORANGE", "pink": "PINK"}


def _uri(path):
    from pathlib import Path
    return Path(path).resolve().as_uri()


def _path(url):
    if not url:
        return ""
    p = unquote(urlparse(url).path) if "://" in url else url
    if len(p) > 2 and p[0] == "/" and p[2] == ":":        # /C:/... -> C:/...
        p = p[1:]
    return os.path.normpath(p)


def build(h, only_main=False):
    import opentimelineio as otio
    rate = h["fps_exact"]
    RT, TR = otio.opentime.RationalTime, otio.opentime.TimeRange

    def rt(sec, r=rate):
        return RT(round(sec * r), r)

    tl = otio.schema.Timeline(name=h["name"], global_start_time=RT(0, rate))
    tl.metadata["vedit"] = {"width": h["width"], "height": h["height"], "notes": h["notes"]}
    warnings = []
    for n, track in enumerate(h["tracks"]):
        if only_main and n > 0:              # EDL: one video track (the main storyline)
            continue
        kind = otio.schema.TrackKind.Video if track["kind"] == "video" else otio.schema.TrackKind.Audio
        ot = otio.schema.Track(name=track["name"], kind=kind)
        ot.metadata["vedit"] = {"role": track["role"]}
        cursor = 0
        for it in sorted(track["items"], key=lambda i: i["start"]):
            start_f, end_f = round(it["start"] * rate), round((it["start"] + it["duration"]) * rate)
            if start_f > cursor:
                ot.append(otio.schema.Gap(source_range=TR(RT(0, rate), RT(start_f - cursor, rate))))
            elif start_f < cursor:          # rounding overlap: trim the head by the overlap
                start_f = cursor
            tr = it.get("transition")
            if tr and len(ot) and isinstance(ot[-1], otio.schema.Clip) and track["kind"] == "video":
                half = max(1, round(tr["duration"] * rate / 2))
                ot.append(otio.schema.Transition(transition_type=otio.schema.TransitionTypes.SMPTE_Dissolve,
                                                 in_offset=RT(half, rate), out_offset=RT(half, rate)))
            src_rate = rate
            if it["media"] == "image":
                avail = TR(RT(0, src_rate), RT(round(max(it["duration"], 3600) * src_rate), src_rate))
                src_start = 0.0
            else:
                avail = TR(rt(it["tc_start"], src_rate), rt(max(it["src_duration"], it["src_in"] + it["duration"] * it["speed"]), src_rate))
                src_start = it["tc_start"] + it["src_in"]
            ref = otio.schema.ExternalReference(target_url=_uri(it["path"]), available_range=avail)
            clip = otio.schema.Clip(name=it["name"], media_reference=ref,
                                    source_range=TR(rt(src_start, src_rate), RT(end_f - start_f, rate)))
            if abs(it["speed"] - 1) > 1e-4:
                clip.effects.append(otio.schema.LinearTimeWarp(time_scalar=it["speed"]))
            clip.metadata["vedit"] = {k: it[k] for k in ("id", "ref", "role", "volume", "fit", "scale", "x", "y", "rotation",
                                                          "opacity", "fade_in", "fade_out", "keys", "note")}
            ot.append(clip)
            cursor = end_f
        tl.tracks.append(ot)
    for m in h["markers"]:
        mk = otio.schema.Marker(name=m["name"], marked_range=TR(rt(m["t"]), rt(max(m["duration"], 1 / rate))),
                                color=COLOR.get(m["color"], "BLUE"))
        mk.metadata["vedit"] = {"note": m["note"], "kind": m["kind"]}
        mk.comment = m["note"]
        tl.tracks.markers.append(mk)
    return tl, warnings


def write(req):
    import opentimelineio as otio
    h = req["handoff"]
    tl, warnings = build(h, only_main=req.get("only_main", False))
    adapter = req["adapter"]
    kw = {}
    if adapter == "cmx_3600":
        kw["style"] = "avid"
    otio.adapters.write_to_file(tl, req["out"], adapter_name=adapter, **kw)
    return {"out": req["out"], "warnings": warnings}


def read(req):
    import opentimelineio as otio
    path = req["path"]
    ext = os.path.splitext(path)[1].lower()
    adapter = ADAPTER_BY_EXT.get(ext)
    kw = {"rate": req["rate"]} if adapter == "cmx_3600" and req.get("rate") else {}
    tl = otio.adapters.read_from_file(path, adapter_name=adapter, **kw)
    if isinstance(tl, otio.schema.SerializableCollection):
        tl = next(iter(tl.find_children(descended_from_type=otio.schema.Timeline)), None) or tl[0]
    out = {"name": tl.name, "tracks": [], "markers": [], "duration": tl.duration().to_seconds()}
    for track in tl.tracks:
        items = []
        for child in track:
            if not isinstance(child, otio.schema.Clip):
                continue
            rng = child.trimmed_range_in_parent()
            ref = child.media_reference
            url = getattr(ref, "target_url", "") or ""
            avail = getattr(ref, "available_range", None)
            src_start = child.source_range.start_time.to_seconds() if child.source_range else 0.0
            if avail is not None and not req.get("absolute_src"):
                src_start -= avail.start_time.to_seconds()
            speed = 1.0
            for fx in child.effects:
                if isinstance(fx, otio.schema.LinearTimeWarp):
                    speed = fx.time_scalar
            items.append({"name": child.name, "path": _path(url), "start": round(rng.start_time.to_seconds(), 4),
                          "duration": round(rng.duration.to_seconds(), 4), "src_in": round(src_start, 4), "speed": speed,
                          "enabled": getattr(child, "enabled", True)})
            for m in child.markers:
                out["markers"].append({"t": round(rng.start_time.to_seconds() + m.marked_range.start_time.to_seconds()
                                                  - (child.source_range.start_time.to_seconds() if child.source_range else 0), 4),
                                       "name": m.name, "note": m.metadata.get("vedit", {}).get("note", "")})
        out["tracks"].append({"name": track.name, "kind": "video" if track.kind == otio.schema.TrackKind.Video else "audio",
                              "items": items,
                              "transitions": sum(1 for c in track if isinstance(c, otio.schema.Transition))})
    for m in tl.tracks.markers:
        out["markers"].append({"t": round(m.marked_range.start_time.to_seconds(), 4), "name": m.name,
                               "note": m.metadata.get("vedit", {}).get("note", "") or getattr(m, "comment", "")})
    return out


def validate(req):
    from lxml import etree
    with open(req["dtd"], "rb") as f:
        dtd = etree.DTD(f)
    doc = etree.parse(req["path"])
    ok = dtd.validate(doc)
    return {"valid": bool(ok), "errors": [str(e) for e in dtd.error_log.filter_from_errors()][:20]}


def main():
    cmd, req_path, out_path = sys.argv[1:4]
    with open(req_path, encoding="utf-8") as f:
        req = json.load(f)
    res = {"write": write, "read": read, "validate": validate}[cmd](req)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
