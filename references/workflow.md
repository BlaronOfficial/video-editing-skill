# Workflow in detail

`<p>` is the project: the footage folder, its `edit/` folder, or `edit/edit.json`. This is the command
reference for each step; how to think about each one is in `references/director.md`, and which steps
run when is in `references/modes.md`.

## 1. Intake

Ask in one AskUserQuestion call (skip what the user already said):
- **Platform / ratio**: Shorts/Reels/TikTok 9:16, YouTube 16:9, square/4:5 feed, or several (auto-reframe).
- **Transcription engine**: `whisper` (local, free, slower here, weaker on Bangla/Banglish) or `scribe`
  (ElevenLabs key, best word timing, audio events, diarisation). Ask every project.
- **Language** if not obvious: en, bn, mixed (pass `--language bn|en`; omit for auto).
- **Style**: a preset (`vedit style list`), a brand kit (`vedit brand list`), a cloned creator, or "your call".
- **Mode**: plan (default, Studio first), step-by-step, or auto.
- **Hand-offs**: none, CapCut, DaVinci Resolve, Premiere, Final Cut, Kdenlive, Shotcut, OTIO/EDL, LosslessCut
  (`vedit handoffs <p> resolve premiere ...` records the choice; Execute writes them; `references/handoffs.md`).
  **CapCut Pro allowed?** only if CapCut (`--pro yes|no`).
- Anything the plan needs that costs money or big downloads (with sizes), asked once here.
- Optional: music preference, CTA/handle, things to avoid, deadline-driven "fast mode".

## 2. Create the project

```
vedit project init "D:/shoots/2026-10-26" --ratio 9:16 --name reel_ai_editing
```
Every media file in the folder becomes a source with an id (slug of the file name). Outputs go to
`<footage>/edit/`. Add b-roll/music later with `vedit project add-source <p> --file <path> --origin library`.

## 3. Transcribe and read

```
vedit transcribe <p> --engine whisper --language en        # or --engine scribe
vedit pack <p>
```
Read `edit/takes_packed.md` fully. It lists phrases `P#` with times, pauses `‖1.2s‖`, fillers `~um~`,
soft fillers `°so`, low-confidence words `word?`, and `⟲ redone in P#` (prefer the later take).
For ambiguous spots, look instead of guessing:
```
vedit view <source-file> --start 41 --end 49 --transcript edit/transcripts/<id>.json --out edit/qa/look.png
```

## 4. Cut

Write `edit/keeps.json` in final order (you can reorder to move the best line to the front as a hook):
```json
[
  {"source": "a_roll", "from": "P14", "to": "P14", "label": "hook"},
  {"source": "a_roll", "from": "P2", "to": "P6", "zoom": {"end_scale": 1.12, "ease": "out"}},
  {"source": "a_roll", "from": 63.2, "to": 71.9, "label": "proof", "transition": {"type": "dissolve", "duration": 0.3}}
]
```
`vedit plan apply <p> edit/keeps.json` snaps every boundary to word edges (add `"exact": true` to skip).
A rough automatic cut is available as a starting point: `vedit plan auto <p>` → `edit/keeps_auto.json`.
Report what was removed (the command prints kept/removed per source).

## 5. Design

Edit `edit/edit.json` directly (schema: `references/edit-json.md`, or `vedit plan schema`).
- Captions: `vedit captions build <p> --style hormozi`, then fix names/spellings and add `emphasis`
  indices or `emoji` on chunks inside `captions.chunks`.
- Graphics: add `overlays` with `mg` specs (templates or your own compositions in `edit/mg/`).
- B-roll: `broll` clips with `start` (timeline seconds). Use `vedit assets search "<words>" --kind broll`.
- Music/SFX/VO: `audio` clips (`role: music|sfx|vo|ambience`). Music ducks under speech automatically.
  SFX: library, CapCut library (screen control) or `vedit sfx whoosh --out edit/assets/sfx/whoosh1.wav`.
- Grade: `color.preset` (render) and `color.capcut_filter` (CapCut). Effects: `effects` with `render`
  (our approximation) and/or `capcut` (CapCut effect name, see `vedit capcut resources scene_effect`).
- Apply the style profile: pacing (`max_pause`, punch-in rhythm), caption style, palette, SFX density,
  and its `learned` block (from past CapCut diffs).

## 6. Studio (or storyboard)

Plan and step mode review happens in the Studio (`references/studio.md`): `vedit studio build <p>`,
upload, `vedit studio register`, `vedit studio docs`, sync, then give the owner the link. Summarise in
chat: length, hook, structure, graphics, music, the cards you left for them.
Where Artifacts are unavailable: `vedit studio-local <p>` (same Studio on localhost), or the static
`vedit storyboard <p> --open`.

## 7. Assets

```
vedit mg render <p>                       # renders every overlay with an mg spec (alpha video)
vedit mg sheet --comp edit/mg/<file>.webm --out edit/qa/mg_<id>.png   # look at it over slate
```
Higgsfield: `references/higgsfield.md` (estimate → approval → generate → `vedit higgsfield import`).
Assets and ideas: `references/sourcing.md`; web AI tools: `references/webai.md`.

## 8. Render and QA

```
vedit render <p> --preview     # 540p, fast: check timing and layout (allowed in plan mode)
vedit execute <p>              # after approval: graphics + custom FX + final render + QA
vedit render <p>               # final only (refuses in plan/step mode until approved)
vedit qa <p>                   # issues + frame sheets in edit/qa/
```
Open the QA sheets (Read the PNGs) and fix: flash frames, bad cuts, captions covering faces, overlays
off-screen, pops, loudness. Re-render (max ~3 rounds) before presenting.

## 9. Hand-offs (only those chosen at intake)

CapCut:
```
vedit capcut build <p> --pro no            # add --close only after the user agreed to close CapCut
vedit capcut launch
```
The project is first in CapCut's list. If screen control is available and the user wants, open it and
export from CapCut (`references/screen-control.md`). Captions are editable CapCut text; graphics are
layers; music has the same ducking keyframes as the render.

## 10. Learn

When the user says they tweaked it in CapCut: `vedit capcut diff <p> --learn <style-or-brand-name>`.
Tell them what was learned ("captions 15% bigger, music lower") and that the next edit will apply it.

## Batch ("a week of reels")

Init one project per clip folder (or per clip), run steps 3-5 for each, show one combined storyboard
summary, then render all and build CapCut projects with sequential names. Keep one style for coherence.
