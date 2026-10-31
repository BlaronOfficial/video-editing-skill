# Hand-offs to other editors

Every hand-off is made from the same neutral timeline (`vedit/exports`), so all of them agree with the
vedit render: the same cut, framing, graphics timing, sound placement and notes. Pick hand-offs at intake;
Execute writes them (`vedit handoffs <p> resolve premiere llc` records the choice). Make one any time:

```
vedit handoff make <p> --to resolve      # DaVinci Resolve (free or Studio): FCPXML 1.10 package
vedit handoff make <p> --to fcp          # Final Cut Pro: FCPXML 1.10
vedit handoff make <p> --to premiere     # Premiere Pro: FCP7 XML
vedit handoff make <p> --to kdenlive     # Kdenlive project (.kdenlive)
vedit handoff make <p> --to shotcut      # Shotcut / MLT (.mlt)
vedit handoff make <p> --to otio | edl   # OpenTimelineIO, CMX 3600 EDL (main cut only)
vedit handoff make <p> --to nle          # all of the above in one folder
vedit handoff make <p> --to losslesscut  # .llc per source (references/losslesscut.md)
CapCut: vedit capcut build <p> (references/capcut.md)
```
Options: `--collect` copies every source into the package (portable, can be large: say the size first),
`--no-stems`, `--no-graphics`, `--no-styled-captions` (skips the slowest part, ~2 min per minute of 1080p).

## What is in a package (`edit/handoff/<target>/`)

| File | What |
|---|---|
| `<name>.fcpxml` / `.xml` / `.otio` / `.edl` / `.kdenlive` / `.mlt` | the timeline. Main clips on V1 with their own sound, b-roll and graphics on tracks above, music / voice-over / SFX on audio tracks below (overlapping effects split across tracks), dissolves, zoom and reframe paths as keyframes, volumes and fades, markers |
| `graphics/*.mov` | every motion graphic as ProRes 4444 with alpha; `captions_styled.mov` and `titles.mov`: the captions and titles exactly as burned in the render, full length, alpha |
| `captions.srt` | editable captions |
| `stems/dialogue.wav, music.wav, effects.wav` | the vedit mix split three ways, 48 kHz 24-bit, sample-identical lengths, pre-master (music already ducked) |
| `look.cube` | the grade's colour as a 33-point 3D LUT (spatial parts like vignette or sharpening are listed in the README) |
| `reference.mp4` | the vedit render, when there is one (path in handoff.json) |
| `README.md` | import steps for that editor, the tracks, the markers, what did not translate |
| `handoff.json` | the neutral timeline as handed off: the base for `handoff diff` |

Markers carry what a timeline cannot: vedit effects (flash, shake, glitch...), non-dissolve transitions,
clip grades, the owner's open suggestion cards (to-dos) and your own notes (`vedit marker add <p> --t 12.4
--name "check the name spelling" --kind todo`). Chapter markers (`--kind chapter`) become FCP chapter
markers, YouTube chapters (`vedit cutlist export <p> --format chapters`) and file chapters.

## Verifying a hand-off (no editor needed)

- FCPXML: `vedit handoff validate <file.fcpxml>` checks it against Apple's DTD when the owner has one
  (inside Final Cut Pro, or put `FCPXMLv1_10.dtd` in `.cache/tools/otio/dtd/`); the tests use it.
- Any format: `vedit handoff read <file>` reads it back (OpenTimelineIO, or vedit's own readers for FCPXML
  and MLT) so you can compare clip counts, in-points and times with `handoff.json`.
- Look at the graphics layers like any render (`vedit frames`), and say which editor features you could
  not verify (Resolve, Premiere and Final Cut are not installed on every machine).

## Round trip: learn from the editor, bring trims back

When the owner (or their editor) has worked on the timeline, ask them to export it again (Resolve: File >
Export > Timeline as FCPXML or OTIO; Premiere: File > Export > Final Cut Pro XML; Final Cut: File > Export
XML; Kdenlive: OTIO; LosslessCut: save the project), then:

```
vedit handoff diff <p> <exported file> [--learn <style>] [--apply-cuts]
```
It reports the cut tightening, head/tail trims (median), removed or reordered clips, graphics and sounds
removed or added, music level changes and cleared markers; logs them as learning events and, with
`--learn`, folds them into the style. `--apply-cuts` makes the editor's main-track cut the new main track:
framing, labels and transitions carry over, and graphics, captions and sounds anchored to words follow.

## Smart cut and cut lists

```
vedit render <p> --lossless [--mode smart|keyframe|accurate]   # cuts-only edits, see below
vedit lossless cut <file> --keep 0-5.2,1:07-1:30 --out x.mp4    # frame-accurate, re-encodes only the joins
vedit lossless selects <p> [--handles 0.5]                       # every kept clip as its own file
vedit lossless split <file> --at 10:00,20:00 | merge a.mp4 b.mp4 --out all.mp4 | chapters <file> --chapters ch.txt
vedit cutlist export <p> --format csv|chapters|llc|srt|edl|otio|xml|fcpxml
vedit cutlist import <p> <file> [--source <id>] [--as main|markers]
```
Smart cut (H.264 and HEVC): the frames from a cut to the next keyframe and from the last keyframe to the
end are re-encoded with the source's codec, profile, pixel format and colour tags at 1.2x its bitrate;
whole GOPs in between are copied bit for bit; audio is cut sample-exact and encoded once (AAC 320k, or
`--audio pcm`). `keyframe` copies everything and moves cuts to keyframes (LosslessCut's default);
`accurate` re-encodes everything (any codec). `render --lossless` only accepts plain cuts of video
sources (no graphics, music, effects, grade, zoom, reframe, speed or transitions); captions go out as an
SRT next to the file, chapter markers into the file. The output keeps the source's size and frame rate.
