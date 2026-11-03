# Blender (optional add-on)

Free, GPL as a separate app (vedit only runs it). Use it when a shot needs real light and geometry: a
bevelled metal title, an extruded logo with reflections, a product model turning. For Bangla text, live
preview in the Studio, or anything that must render fast, use the Three.js templates (`references/vfx.md`).

- Check: `vedit blender check` (version, templates). Installed here: Blender 5.2 LTS.
- Not installed: ask first (~350 MB), then `winget install BlenderFoundation.Blender`.
- Speed here (no NVIDIA GPU, EEVEE): ~2 s per frame at 540x960. A 3 s hero at 1080x1920 is several minutes.
  Say so, render a still first (`vedit blender still <template> --at 1.5`), then the animation.

## Templates (blender/)

| Template | Data |
|---|---|
| `title_3d` | text, subtitle, font (file in .cache/fonts or a path), color, side, depth, bevel, metallic, intro rise/flip/spin/zoom, outro, glint, y, width |
| `logo_3d` | logo (.svg extruded with its own fills, or .png as a thick card), depth, side, spin turn/flip/none, tagline, y, width |
| `product_turntable` | model (.glb/.gltf/.obj/.fbx/.stl) or image (cut-out PNG), turns, accent (rim light), floor disc/none, tilt, y, width |

```
vedit blender still title_3d --data '{"text": "LAUNCH", "color": "#ffd84d"}' --size 1080x1920 --at 1.5 --out look.png
vedit blender render logo_3d --data '{"logo": "C:/brand/logo.svg"}' --duration 3 --out edit/mg/logo3d --formats webm,prores
```

In an edit, an overlay renders with the other graphics (`vedit mg render`, Execute):
```json
{"id": "hero", "start": 0, "duration": 3,
 "mg": {"engine": "blender", "template": "title_3d", "data": {"text": "LAUNCH", "samples": 32}}}
```
`data.engine: "cycles"` switches to Cycles (CPU, slower, better glass and shadows). `data.samples` trades
speed for smoothness (EEVEE 16-64).

## Your own bpy script

Write `edit/custom/<name>.py` following `blender/common.py` (args, `reset`, lights, camera, `render`): it
must write RGBA PNG frames `f_00001.png ...` into `--out` with a transparent background. Run it as
`CustomFX {"kind": "blender", "file": "custom/<name>.py", "params": {...}, "start": 2, "duration": 3}` or
`vedit blender render custom/<name>.py`. Blender text objects do not shape Bangla: the template refuses it.
