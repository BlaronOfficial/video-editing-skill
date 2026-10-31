"""Import a hand-off package into Resolve (any edition) by driving its window, only with the owner's OK.

Prefer computer use (screenshots + clicks) when the session has it: this module is the fallback that sends
Resolve's own shortcut (File > Import > Timeline, Ctrl+Shift+I) and types the FCPXML path into the file
dialog. Every keystroke is refused unless Resolve owns the foreground window, and a screenshot is taken
after each step so Claude can look before going on. It never clicks dialogs that ask about the owner's
other projects, saving, or licences.
"""

from __future__ import annotations

import time
from pathlib import Path

from .. import screen
from ..util import VeditError, read_json

PROCESS = "Resolve"


def import_timeline(package_dir: str | Path, shots_dir: str | Path, *, confirm_load: bool = True) -> dict:
    package_dir = Path(package_dir)
    manifest = read_json(package_dir / "handoff.json") or {}
    fcpxml = manifest.get("files", {}).get("fcpxml")
    if not fcpxml:
        raise VeditError(f"{package_dir} has no FCPXML (make it with `vedit handoff make <project> --to resolve`).")
    shots_dir = Path(shots_dir)
    shots_dir.mkdir(parents=True, exist_ok=True)
    steps = []
    if not screen.focus(PROCESS):
        raise VeditError("Resolve is not open, or Windows kept another window in front. Ask the owner to open the "
                         "project they want the timeline in, then try again.")
    steps.append({"step": "focused Resolve", "shot": str(screen.screenshot(shots_dir / "01_focus.png"))})
    screen.send_keys("^+i", expect=PROCESS)                  # File > Import > Timeline...
    time.sleep(2.0)
    steps.append({"step": "import dialog", "shot": str(screen.screenshot(shots_dir / "02_dialog.png"))})
    screen.send_keys(str(Path(fcpxml).resolve()).replace("{", "{{}").replace("}", "{}}").replace("+", "{+}")
                     .replace("^", "{^}").replace("%", "{%}").replace("~", "{~}") + "{ENTER}", expect=PROCESS)
    time.sleep(3.0)
    steps.append({"step": "path entered", "shot": str(screen.screenshot(shots_dir / "03_load.png"))})
    if confirm_load:
        screen.send_keys("{ENTER}", expect=PROCESS)          # "Load XML" options dialog: OK with defaults
        time.sleep(4.0)
        steps.append({"step": "loaded", "shot": str(screen.screenshot(shots_dir / "04_done.png"))})
    return {"fcpxml": fcpxml, "steps": steps,
            "next": "Look at the screenshots: the new timeline should be open in the Edit page. If a dialog is "
                    "still showing, stop and tell the owner what it says."}
