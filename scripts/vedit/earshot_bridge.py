"""Runs inside earshot's own venv (never imported by vedit): model-free analysis vedit asks for.

    python -I earshot_bridge.py sync <request.json> <result.json>

sync: {"audio": path, "cues": [{"t", "kind", "id"}]} -> earshot.timeline.sync over the file's detected events:
for every cue, the event that answers it (offset_ms, status OK / near / swell / peak / no sound) and stats.
"""

import json
import sys


def sync(req):
    from earshot import audio
    from earshot.timeline import detect_events, level_envs
    from earshot.timeline import sync as _sync
    x = audio.load(req["audio"])
    events = detect_events(x)
    res = _sync(req["cues"], events, levels=level_envs(x))
    res["events"] = len(events)
    return res


def main():
    cmd, req_path, out_path = sys.argv[1:4]
    with open(req_path, encoding="utf-8") as f:
        req = json.load(f)
    res = {"sync": sync}[cmd](req)
    from earshot.report import to_json
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(to_json(res))


if __name__ == "__main__":
    main()
