# VFX and 3D

Everything here runs on this PC for free. Tracking, cut-outs and depth work in **source space**: they are
measured on the source frames and stored with source times, so they survive re-cuts, reframes, zooms and
ratio changes. The render merges them at decode, before framing, like stabilize and redaction.

`--at` is a SOURCE time (what `vedit view <source>` shows); `--at-timeline` takes a timeline time.
Boxes and corners are SOURCE pixels. Look before claiming: `vedit vfx sheet <p> --track <id>`, then
`vedit render <p> --preview` and read frames.

## What to reach for

| Need | Command | Notes (measured here) |
|---|---|---|
| A 3D title, Bangla included | overlay `mg.template: title_3d` | Latin: real extruded, bevelled glyphs. Bangla and any other script: shaped "slab" text, correct conjuncts. ~5 frames/s at 1080x1920 |
| Logo sting with thickness | `logo_3d` | SVG extruded path by path in its own colours; PNG as a die-cut slab; no logo: the name in 3D |
| Product hero | `product_spin` (cut-out PNG) · Blender `product_turntable` (a .glb/.obj/.fbx/.stl or the PNG) | `vedit vfx cutout photo.jpg` first |
| App / site / screen recording on a device | `device_mockup` (phone, tablet, laptop) | video plays frame-exact on the screen |
| Atmosphere, celebration | `particles` (dust, bokeh, snow, stars, sparks, confetti) | deterministic: any frame renders the same |
| Montage intro, lists, portfolios | `camera_flythrough` (images and/or words) | lands on the last card |
| Numbers | `chart_3d` | bars grow with counting values, highlight glows |
| Places, travel, reach | `globe` (pins, arcs, focus) | pass `texture` (land white, sea black) to draw continents |
| A label that follows a thing | `vedit vfx track` + `vedit vfx attach` | optical flow + VitTrack: 2.4 px mean error on the synthetic test |
| Blur faces that move | `vedit vfx faces <p> --clip c3 --blur` (`--pixelate`, `--keep-largest`) | YuNet every frame, gaps up to 1 s filled; check the sheet |
| Blur a plate / logo / screen that moves | `vedit vfx track ...` then `vedit vfx blur <p> --clip c3 --track id` | box or ellipse, padded |
| Replace a phone screen, sign, poster | `vedit vfx screen <p> --clip c3 --suggest --at 12.4`, then `--corners ... --media file` | planar homography: 0.43 px mean corner error; `--keep-light 0.3` keeps reflections |
| Text behind the person | `vedit vfx subject <p> --clip c3 --above 1`, title on overlay layer 0 | MODNet matte, ~3 frames/s here |
| Background blur / swap / darken | `vedit vfx subject <p> --clip c3 --background blur:14` (`#hex`, `darken:0.5`, `desaturate`, `image:<path>`, `video:<path>`) | |
| Sticker outline, glow | `--outline "#ffffff:8"` · `--glow "#ffd400:30"` | |
| Cut-out still (stickers, thumbnails) | `vedit vfx cutout photo.jpg --out x.png` | people: MODNet (2 s); objects: BiRefNet (~1 min per still, if downloaded); or Canva |
| Make a photo move in 3D | `vedit vfx parallax photo.jpg --project <p> --at 12 --duration 5 --move dolly_in` | moves: dolly_in, dolly_out, pan_left, pan_right, rise, orbit, zoom_through |
| Depth of field | `vedit vfx dof <p> --clip c3` (focus auto = the face) · `vedit vfx dof-image` | `--pull 0,0.8,2,0.3` pulls focus over time (clip-local s, depth) |
| Whip pan / zoom-blur cut | `transition_in: {"type": "whip_left", "duration": 0.4}` (whip_right, whip_up, whip_down, zoom_blur) | a clip with no handle holds its edge frame, so timing never changes |
| Motion blur, handheld drift, shake | `effects: [{"render": "motion_blur"\|"handheld"\|"whip"\|"shake", ...}]` | |
| Real light, bevels, metal (heroes) | Blender: overlay `mg: {engine: "blender", template: "title_3d"\|"logo_3d"\|"product_turntable"}` | ~2 s per frame at 540p here: heroes, not every graphic. `references/blender.md` |

Paid or uploading routes (Higgsfield VFX, Veo / Kling / Runway shots, Fusion on Resolve Studio) are in the
route planner (`vedit route plan vfx|3d`); ask first.

## Tracks

```
vedit vfx track <p> --clip c3 --box 540,300,190,190 --at 12.4 [--id logo] [--method auto|flow|vit] [--range 10,16]
vedit vfx faces <p> [--clip c3 c5] [--blur|--pixelate] [--keep-largest] [--min-size 0.03]
vedit vfx sheet <p> --track logo              # six frames with the box drawn: read it
vedit vfx list <p>
```
The track covers the clip's source range plus half a second, forwards and backwards from `--at`. A track
JSON lives in `edit/vfx/tracks/`; `edit.json` lists it under `tracks`. Lost frames are filled between good
ones; when many are lost the command says so: give a tighter box, try another method, or split the range.

`vedit vfx attach <p> <overlay> --track logo [--offset 0,0.12] [--point top] [--smooth 0.2]` moves the
overlay's centre onto the tracked point every frame (offset in half-canvas units, +y up). It follows the
clip's framing (crop keys, fit, zoom, transform); rotation, 360 and stabilize are not modelled. The Studio
preview shows the overlay at its static position; the render follows the track.

## Screens and signs

1. `vedit vfx screen <p> --clip c3 --suggest --at 12.4` writes `qa/screen_candidates_<clip>.png` with
   numbered candidates and prints their corners. Read the image.
2. `vedit vfx screen <p> --clip c3 --at 12.4 --corners x1,y1,x2,y2,x3,y3,x4,y4 --media app.mp4 [--fit stretch]`
   (corners clockwise from top-left; any order is re-ordered). It tracks immediately.
3. In the Studio the owner can click four corners on a clip ("Replace a screen"); that arrives as a request:
   run `vedit vfx prepare <p>`, then ask which image or video goes on it and set `media` in `screen[]`.

The tracker holds on to the screen and its bezel (`grow`, default 0.25 of the quad). A blank black screen
with no bezel or reflections has nothing to track: pick a larger quad (the whole device) and set the media's
fit accordingly.

## Person cut-outs

`subject` on a clip: `{background, outline, glow, above}`. The matte (MODNet, people only) is computed
once per clip range and cached in the render folder; a 10 s clip takes ~1 minute here, so say so before
long clips. `above: N` re-composites the person over every overlay with `layer < N` (titles behind the
person); overlays at `layer >= N` and captions stay on top. The outline and glow sit behind those titles.
Hair edges are refined with a guided filter; fast hand motion can still lose fingers: look at a frame.

## Depth

Depth-Anything-V2-Small (Apache-2.0; the larger variants are non-commercial and never used) gives relative
depth, 1 = nearest. `focus` "auto" locks on the largest face (else the middle) on the first frame, so
focus never hunts; `range` (0.25) is the depth band kept sharp. 3D photos stretch the background behind
near objects; keep moves gentle (`--amount 0.5..1.2`) on busy foregrounds.

## In edit.json

```json
"tracks":   [{"id": "logo", "source": "a_roll", "kind": "object", "t0": 10.1, "t1": 16.4, "file": ".../logo.json"}],
"main": [{"id": "c3", "...": "...",
          "redact":  [{"track": "face_a_roll_1_1", "mode": "blur", "shape": "ellipse", "pad": 0.18}],
          "screen":  [{"track": "screen_c3", "media": "assets/app.mp4", "fit": "cover", "keep_light": 0.2}],
          "subject": {"background": "blur:14", "outline": {"color": "#ffffff", "width": 8}, "above": 1},
          "dof":     {"focus": "auto", "range": 0.25, "blur": 10}}],
"overlays": [{"id": "price", "attach": {"track": "logo", "offset": [0, 0.15]}, "...": "..."}]
```

Hand-offs (CapCut, NLEs) get these as clip notes: the effects exist only in vedit's render. When the owner
finishes in an editor, render the affected clips with vedit and hand those over instead.

## Writing your own 3D

A composition is an HTML file using `/__mg/three-kit.js` (import map in any shipped 3D template):
`stage()`, `run(st, draw, duration)` (draw is a pure function of t), `slabText` (any script), `ttfText`
(extruded Latin glyphs), `label`, `loadTexture`, `loadVideo` (`await vt.seek(t)` in draw), `softDisc`,
`roundedRect`, `ease`, `seg`, `rand(seed)`. Put it in `edit/custom/` and reference it as `mg.file`; save the
good ones with `vedit template save`. Bpy scripts follow `blender/common.py` and run as CustomFX
`kind: "blender"`.
