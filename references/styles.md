# Styles, brand kits, creator cloning, learned preferences

## Aesthetic presets (shipped, `presets/aesthetics/`)
cool_girl · cool_dude · hormozi · cinematic · moody · clean_corporate · energetic · podcast ·
tech_explainer · bangla_creator. `vedit style show <name>` prints the profile:
captions style, colour grade (render + CapCut filter), pacing (max_pause, avg_shot_s, punch-in rhythm),
music mood/level, SFX density/kinds, graphics templates/palette/font, transitions, b-roll guidance, notes.
Apply every part of the profile when planning; the user can override anything ("cool girl but bold captions").

## Brand kits (per client, `personal/brands/<name>.json`)
```
vedit brand create arete --fields '{"colors": {"accent": "#00E0FF", "accent2": "#FF4D6D"},
  "fonts": {"display": "Poppins", "captions": "Poppins ExtraBold", "bangla": "Hind Siliguri"},
  "logo": "D:/brand/logo.png", "handle": "@arete.studio", "cta": "Follow for daily AI edits",
  "rules": ["no emoji", "always lower third on first appearance"]}'
```
Read it with `vedit brand show <name>` and pass its colours/fonts to every graphic as
`data.brand` = {accent, accent2, ink, paper, font, fontBangla}; set `"brand": "<name>"` in edit.json and
use the brand's caption font/accent in `captions.overrides`.
Logos: `logo_sting` intro/outro, small corner bug as an image overlay (opacity 0.8, safe area).

## Clone a creator's style
1. Get 1-3 reference videos (the user's files, or downloads they are entitled to use).
2. `vedit style analyze <name> ref1.mp4 ref2.mp4 --out edit/style_<name>` → measures cuts/min, shot
   length, loudness, colour (saturation/brightness/contrast/warmth) and writes frame sheets.
3. **Look at the frame sheets** and fill the `observations` (captions look, graphics, b-roll, transitions,
   sound, hook) in `personal/styles/<name>.json`, plus concrete settings (captions.style + overrides,
   color.preset, pacing, graphics palette/fonts). Save it with `vedit style save --file <json>`.
4. Use it like any preset. Never copy their logos, watermarks or brand assets; capture the *style*.

## Learned preferences
`vedit capcut diff <p> --learn <style>` turns the user's CapCut changes into `learned`:
`captions.size_scale`, `captions.y_delta`, `music_volume_scale`, `tightness`, and `notes`.
Apply them on the next edit: scale caption size, shift y, scale music volume, tighten max_pause by
`tightness`, and follow the notes ("removed most b-roll overlays" → use fewer).
