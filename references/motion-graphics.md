# Motion graphics

You design and animate graphics yourself. Pick the engine per moment and mix freely.

| Engine | When | Output |
|---|---|---|
| **Templates** (`vedit mg templates`) | Common beats: titles, lower thirds, lists, counters, CTAs, callouts | alpha video |
| **3D templates** (Three.js) | title_3d (Bangla too), logo_3d, product_spin, device_mockup, particles, camera_flythrough, chart_3d, globe (`references/vfx.md`) | alpha video, live in the Studio |
| **Blender** (optional add-on) | Hero shots needing real light: bevelled metal titles, extruded logos, product turntables (`references/blender.md`) | alpha video, slow |
| **Custom HTML** (GSAP/CSS/SVG/Canvas/Three.js/Lottie) | Anything bespoke: explainer diagrams, data viz, branded intros, kinetic type synced to words | alpha video |
| **Remotion** (`mg/remotion`) | React-based scenes, reusable compositions, heavy data-driven scenes | ProRes 4444 alpha |
| **HyperFrames** (`npx hyperframes`) | Full-screen HTML video scenes with embedded video | MP4 |
| **PIL fallback** | No Node/Chrome available | simple text card |
| **Higgsfield** (optional) | Photoreal/cinematic shots, 3D product, VFX, characters | MP4 clip (b-roll/overlay) |

`engine: auto` uses the renderer for templates and `.html`, Remotion for `.tsx/.jsx`.
Remotion's licence is free for individuals and companies with 3 or fewer employees; larger companies
need a company licence. Prefer HTML when unsure (Apache/MIT stack, no licence questions).

## Using a template
```json
{"id": "steps", "start": 4.2, "duration": 5,
 "mg": {"template": "list_reveal", "data": {"heading": "3 rules", "items": ["Hook fast", "Cut pauses", "Caption it"],
        "times": [0.5, 1.6, 2.7], "brand": {"accent": "#39FF6A"}}}}
```
Data keys per template are in `mg/templates/index.json`. All templates accept `brand`
{accent, accent2, ink, paper, font, fontBangla} and `duration`. Sync to speech: take word times from the
caption chunks and subtract the overlay `start` for `times`.

## Writing a custom composition (the real superpower)
Create `edit/mg/<name>.html`:
```html
<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/__mg/base.css">
<style>/* size with vmin/vw so it works at any ratio */</style></head>
<body><div id="stage" data-composition-id="main" data-duration="4"> ... </div>
<script src="/__vendor/gsap.min.js"></script><script src="/__mg/vedit.js"></script>
<script>
  const d = V.data({ title: "Default" });          // window.__VEDIT_DATA__ merged over defaults
  V.brand(d.brand || {});
  const tl = V.timeline("main");                     // paused, registered for frame-accurate seeking
  tl.from(".x", { y: 60, opacity: 0, duration: 0.6, ease: "expo.out" }, 0.1);
</script></body></html>
```
Contract: timelines are **seeked**, never played, so everything must be a pure function of time.
- GSAP: build everything on registered timelines; use `tl.eventCallback("onUpdate", ...)` for state
  that flips (see subscribe_cta). No `setTimeout`, no `Math.random()` (use `V.rand(seed)`).
- Canvas/WebGL/Three.js: define `window.__seek = (t) => { draw(t) }` and draw synchronously.
- CSS animations/WAAPI are driven automatically.
- Assets: put files next to the HTML (relative URLs) or use `/__abs/<absolute path>`.
- Libraries served locally: `/__vendor/gsap.min.js`, `/__vendor/gsap/<Plugin>.min.js` (SplitText,
  MotionPathPlugin, DrawSVGPlugin, MorphSVGPlugin, CustomEase - all free), `/__vendor/three.module.js`,
  `/__vendor/lottie.min.js`. Fonts: Poppins, Anton, Bebas Neue, Archivo Black, Luckiest Guy, Bangers,
  DM Serif Display, Instrument Serif, Permanent Marker, Caveat Brush, Rubik Mono One, Hind Siliguri,
  Tiro Bangla, Galada, Atma (declared in base.css).
- Bangla text: never split into characters (breaks conjuncts); `V.split` splits Bangla by word.
- Transparent background is automatic; only draw what should be on top of the video.

Preview while authoring: open the HTML in Chrome (it auto-plays and shows a checkerboard), then render:
```
vedit mg still --comp edit/mg/growth.html --t 1.2 --out edit/qa/growth.png --width 1080 --height 1920
vedit mg file --comp edit/mg/growth.html --out edit/mg/growth --duration 4 --formats webm,prores
vedit mg sheet --comp edit/mg/growth.webm --out edit/qa/growth_sheet.png
```
Look at the still/sheet before using it. Iterate on spacing, hierarchy, timing.

## Design principles
- Hierarchy: one focal element; supporting text at ≤ 50% size; max 2 typefaces.
- Motion: anticipate → act → settle. `expo.out`/`back.out` for entrances, `power2.in` for exits,
  60-90 ms staggers for words, 0.3-0.6 s entrances, exits shorter than entrances.
- Colour: brand accent for emphasis only; white/near-black for body; add soft shadows for legibility
  over busy footage.
- Leave the face clear. Use `callout`/`highlight_box` to point, not to cover.
- Consistency: same entrance language across a video (pick 1-2 easing families).

## Alpha formats and CapCut
Renders produce `.webm` (VP9 alpha, used by the MP4 render) plus `.mov` (ProRes 4444) and/or
`_key.mp4` (green screen) for CapCut, depending on `capcut.alpha_overlays` (set once with
`vedit capcut probe-alpha` → `vedit capcut set-alpha prores|webm|chroma`). With `chroma`, the CapCut
builder imports the green version with CapCut's chroma key applied.

## Remotion
`mg/remotion/` contains a ready project (`npm install` happens on first use). Write a component in
`mg/remotion/src/`, register it in `Root.tsx`, then reference it: `"mg": {"engine": "remotion",
"file": "<base>/mg/remotion/src/index.ts", "data": {"composition": "KineticTitle", ...props}}`.
