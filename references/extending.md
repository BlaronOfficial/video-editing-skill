# Building what is missing

## Custom compositions (motion graphics)

Write HTML in `edit/custom/<name>.html` and point an overlay at it:
`{"id": "hook", "start": 0.1, "duration": 2.5, "mg": {"file": "custom/hook.html", "data": {...}}}`.
Same runtime as the templates (GSAP timeline registered with `V.timeline()`, or `window.__seek(t)` for
Canvas/Three.js), see `references/motion-graphics.md`. It renders with real alpha and plays live in the
Studio. Keep it: `vedit template save <p> <overlay-id> --name <name> --description "..."` copies it into
`personal/templates/`, where `vedit mg templates` and the Studio library list it as yours.

## Custom FX (edit.json `custom_fx`)

| kind | what you write | output |
|---|---|---|
| `python` | a script run as `python file --in <src> --out <file> --params <json> --width --height --fps --duration --start --project` in the vedit venv (numpy, OpenCV, Pillow) | `overlay` (alpha .mov placed like an overlay), `audio` (WAV on the mix), `source` (processed copy swapped into the clips in `params.targets`) |
| `ffmpeg` | one filter chain (no labels) at a hook: `video_pre_overlays`, `video_pre_captions`, `video_post`, `audio_voice`, `audio_master` | spliced into the final render |
| `html` | a composition file | rendered like an overlay |

```python
# edit/custom/sparkle.py  (output: overlay)
from vedit.fxkit import args, AlphaWriter, read_frames
import numpy as np
a = args()
with AlphaWriter(a.out, a.width, a.height, a.fps) as w:
    for i in range(a.frames):
        rgba = np.zeros((a.height, a.width, 4), np.uint8)
        # ... draw from a.params ...
        w.write(rgba)
```
```json
{"custom_fx": [{"id": "sparkle", "file": "custom/sparkle.py", "start": 4.2, "duration": 1.5,
                "anchor": {"source": "a_roll", "t": 151.3}, "params": {"count": 40}},
               {"id": "grain", "kind": "ffmpeg", "hook": "video_post", "filter": "noise=alls=6:allf=t"}]}
```
`vedit fx run <p>` renders them (cached by content); `vedit execute`/`vedit render` do it automatically.
They also land in the CapCut project as layers. Keep one: `vedit fx save <p> --id sparkle --name sparkle`
→ `"file": "personal:fx/sparkle.py"` works in any project.

## Techniques

Recipes for looks: `presets/techniques/*.md` (shipped) and `personal/techniques/*.md` (learned). Each has
front matter (`name`, `tags`, `description`) and says what it is, when to use it, the exact parameters and
engine. `vedit technique list --tag text`, `vedit technique show <name>`,
`vedit technique save <name> --file recipe.md`.

## Installing an open-source tool

Only with the owner's yes, and only through the vetting step:
```
vedit tools vet https://github.com/<owner>/<repo>      # shallow clone + inspection, nothing runs
vedit tools add <name> [--accept-caution]              # isolated venv (python) or npm --ignore-scripts
vedit tools list | remove <name>
```
`vet` blocks bundled executables, DLLs and large archives, and a deleted GitHub account; it flags shell
scripts, install hooks that download things, and unknown or non-commercial licences. Show the owner the
findings before `add`. Never disable antivirus, never run installers as admin, never `curl | sh`.

Wire a tool into vedit with a personal extension, `personal/extensions/<name>.py` (survives `git pull`):
```python
def register_cli(sp):            # optional: new `vedit <command>`
    s = sp.add_parser("mytool"); s.add_argument("path"); s.set_defaults(fn=lambda a: ...)
ROUTES = {"vfx": [{"id": "mytool", "label": "...", "requires": [], "cost": "free", "quality": 4,
                   "speed": 3, "licence": "own", "privacy": "local", "how": "vedit mytool <p>"}]}
ADDONS = [{"id": "mytool", "name": "My tool", "check": lambda: (True, "installed")}]
```
