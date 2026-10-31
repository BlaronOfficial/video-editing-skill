"""Runs in a child process with Resolve's scripting module on PYTHONPATH (see live.py). Add-only.

    python resolve_bridge.py <status|import> <request.json> <result.json>
"""

import json
import sys
import time


def connect():
    import DaVinciResolveScript as dvr      # noqa: N813 - Blackmagic's module name
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError("Resolve is not running, or external scripting is off (Preferences > System > General)")
    return resolve


def status(_req):
    r = connect()
    pm = r.GetProjectManager()
    proj = pm.GetCurrentProject()
    return {"product": r.GetProductName(), "version": r.GetVersionString(),
            "project": proj.GetName() if proj else None, "page": r.GetCurrentPage()}


def _unique(names, base):
    name, n = base, 2
    while name in names:
        name, n = f"{base} ({n})", n + 1
    return name


def do_import(req):
    r = connect()
    pm = r.GetProjectManager()
    if req.get("into_current") and pm.GetCurrentProject():
        proj = pm.GetCurrentProject()
    else:
        existing = set(pm.GetProjectListInCurrentFolder() or [])
        pname = _unique(existing, req.get("project") or f"vedit {req['name']}")
        proj = pm.CreateProject(pname)
        if not proj:
            raise RuntimeError(f"could not create project '{pname}'")
    mp = proj.GetMediaPool()
    tl_names = {proj.GetTimelineByIndex(i + 1).GetName() for i in range(proj.GetTimelineCount())}
    tl_name = _unique(tl_names, f"{req['name']} (vedit {time.strftime('%m-%d %H:%M')})")
    tl = mp.ImportTimelineFromFile(req["fcpxml"], {"timelineName": tl_name, "importSourceClips": True})
    if not tl:
        raise RuntimeError("Resolve refused the FCPXML (see Resolve's console: Workspace > Console)")
    proj.SetCurrentTimeline(tl)
    lut_applied = 0
    if req.get("lut"):
        for i in range(1, tl.GetTrackCount("video") + 1):
            if i > 1:
                break                      # the grade belongs on the footage, not on graphics layers
            for item in tl.GetItemListInTrack("video", i) or []:
                try:
                    if item.SetLUT(1, req["lut"]):
                        lut_applied += 1
                except Exception:          # noqa: BLE001 - older builds without SetLUT on items
                    pass
    srt = None
    if req.get("srt"):
        try:
            items = mp.ImportMedia([req["srt"]]) or []
            srt = bool(items)
        except Exception:                  # noqa: BLE001
            srt = False
    fps = float(tl.GetSetting("timelineFrameRate") or req["expect"]["fps"])
    start, end = tl.GetStartFrame(), tl.GetEndFrame()
    return {"project": proj.GetName(), "timeline": {
        "name": tl.GetName(), "video_tracks": tl.GetTrackCount("video"), "audio_tracks": tl.GetTrackCount("audio"),
        "main_clips": len(tl.GetItemListInTrack("video", 1) or []), "duration": (end - start + 1) / fps,
        "markers": len(tl.GetMarkers() or {})}, "lut_applied": lut_applied, "srt_in_media_pool": srt}


def main():
    cmd, req_path, out_path = sys.argv[1:4]
    with open(req_path, encoding="utf-8") as f:
        req = json.load(f)
    try:
        res = {"status": status, "import": do_import}[cmd](req)
    except Exception as exc:               # noqa: BLE001 - reported to vedit as data
        res = {"error": str(exc)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
