# CapCut integration

CapCut desktop has no official editing API. The skill writes CapCut's own project files, seeded from a
blank project made by the user's installed CapCut, so version markers always match.

## Calibrate (once per machine and after every CapCut update)
1. Open CapCut → **Create project** → close CapCut (an empty project is enough).
2. `vedit capcut calibrate` (or `--project <name>` to pick one). The seed is stored in
   `personal/capcut/seed/` (it contains the user's device ids, so it is never shared or committed).
`vedit doctor` warns when the installed version differs from the calibrated one.

## Build
```
vedit capcut build <p> --pro yes|no [--name my_project] [--overwrite] [--close]
```
- CapCut must be closed while the project index is written. If it is open, the command stops; ask the
  user to let you close it (CapCut autosaves), then add `--close`.
- Writes tracks: main video, b-roll, overlay layers, captions (editable text), titles, music/SFX/VO
  (with the same ducking keyframes as the render), effects, filter. Zoom and auto-reframe become
  keyframes. A snapshot is saved in `edit/capcut/snapshot.json` for learn-from-edits.
- `--pro no` refuses Pro effects/filters/fonts/animations (warnings list what was skipped).
  The user's plan can vary per project: ask.

## Alpha overlays (one-time check)
`vedit capcut probe-alpha` creates `vedit_alpha_probe`: two white circles over magenta (top = ProRes
4444, bottom = WebM). Ask the user to open it (or look with screen control) and report which circles
have no black box, then `vedit capcut set-alpha prores|webm|chroma`. With `chroma`, overlays are
imported as green-screen MP4s with CapCut's chroma key applied.

## Resources (effects, filters, transitions, animations, fonts)
```
vedit capcut resources transition --query 推          # names, Pro flag, default duration
vedit capcut resources filter --pro no
vedit capcut aliases transition                       # English aliases -> CapCut names
```
Categories: transition, filter, scene_effect, character_effect, video_intro, video_outro, video_combo,
text_intro, text_outro, text_loop, font, mask, audio_effect, tone_effect. Many names are CapCut's
Chinese names (e.g. 叠化 dissolve, 闪白 white flash, 推近 push in, 模糊 blur); use them directly or via
aliases in `edit.json` (`transition_in.capcut`, `effects[].capcut`, `color.capcut_filter`,
`texts[].capcut_intro`). Not every catalogue entry exists in every CapCut build: if CapCut shows a
missing-resource marker, pick another.

## Versions
- Verified: CapCut 9.6.0 (Windows), plaintext drafts with nested `Timelines/`.
- 8.x-9.x: expected to work when calibrated from the installed app.
- 10.x: reported to reject tool-written projects. The MP4 render is unaffected; use screen control to
  rebuild in CapCut if needed, or keep a 9.x install with auto-update off.

## Learn from the user's CapCut edits
`vedit capcut diff <p>` compares the snapshot with the current project: caption size/position/text
changes, tightened cuts, removed/added layers, volume changes, added effects/filters.
`--learn <style>` folds this into the style's `learned` block (rolling average), which future edits apply.

## Alternative backend: VectCutAPI
If the user runs sun-guannan/VectCutAPI (`python capcut_server.py`, port 9001):
`vedit capcut vectcut <p> --url http://localhost:9001`. It uses the corrected parameter mapping
(the Atx-Guy/capcut-mcp-server idea, fixed). The native backend stays the default.

## Exporting from CapCut
Rendering inside CapCut needs the UI: see `references/screen-control.md`. The skill's own MP4 is
usually the deliverable; CapCut export is for when the user changed things in CapCut.
