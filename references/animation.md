# Animated pieces

Illustrated, procedurally drawn animation: one deterministic `<canvas>` page per piece, drawn and scored in
code. Use it for explainers, histories and timelines, little stories, product reels with the real screens,
inserts that act an idea out while the speaker keeps talking, and hand-drawn doodles over footage.

The drawing kit, the 7 styles, the templates and the story grammar are adapted from
[animate](https://github.com/cth9191/animate) (MIT, © 2026 cth9191; `anim/LICENSE-animate`). vedit adds:
- Bangla in every style, and its own fonts;
- its renderer (system Chrome, GPU, workers);
- its voices, which drive the timing;
- the Studio, a beat map that stays on the beat, and measured review;
- placing pieces in edits.

## Styles

| Style | The look | Best for | Moves on |
|---|---|---|---|
| `cut-paper` | torn paper, drop shadows, crayon, patterns, characters with faces | histories, stories, anything warm | 2s |
| `crosshatch` | sketchy ink that boils, hatch and pencil shading, warm paper or navy "inside the machine" | tech explainers, processes, doodles over footage | 2s |
| `riso` | a three-ink risograph print: halftones, overprints, misregistration | editorial, culture, soft brand pieces | 2s |
| `sketchbook` | graphite and one accent colour on a sketchbook page, hand lettering | tutorials, notes, journaling, doodles | 2s |
| `math` | a Manim-like stage: axes, graphs, colour-coded variables | anything with numbers, equations, graphs | 1s |
| `pixel` | low-resolution eras, nearest-neighbour, a bitmap font | computing and gaming history, retro | 1s or 2s |
| `isometric` | precise isometric line art, constant hairlines, one dark accent | products, devices, infrastructure | 1s |
| your own | a look matched from the owner's references (`anim/grammar/new-style.md`) | a brand or channel look | either |

To see them:
- `vedit anim styles` lists them.
- `vedit anim gallery --out styles.png` draws one sheet with every sample and a "your references" tile.

Show the gallery at intake.

**Proven so far** (from the original project):
- **Styles:** cut paper and crosshatch have carried full pieces; riso, sketchbook, math and pixel come from one or
  two pieces each; isometric only has its demo.
- **Story formats:** only F2 (chronology), F4 (mission) and F5 (fixed hero) are proven.

Say so when you pick something unproven.

## The flow, in vedit's modes

The story grammar lives in `anim/grammar/`:
- `FORMATS.md` (8 formats: the plot engine decides the format);
- `STORY.md`;
- `FRAME.md` (what every key frame holds);
- `craft.md` (the rules learned building pieces);
- `intake.md`.

It is for animated pieces only. Footage edits keep the director's own checklist.

1. **Intake.** Ask only the questions you can't infer from `anim/grammar/intake.md`: what it's about, formats,
   voice, the look (show the gallery), a hero, the owner's own music, the real product.
2. **Story check** (text, cheap). Give:
   - the one-line idea, and a device you can say in a sentence;
   - the format and why;
   - the style, length and BPM;
   - a numbered beat table: time, what happens, the bridge to the next beat, the sound's role.

   Check every factual claim on the web and list it with its source in `brief.md`. Plan mode: this is the
   creative direction.
3. **Look check.** Run `vedit anim new <p> <piece> --style <s>` (starts from the style's demo; `--from piece`
   gives the multi-format starter, `--from beat-cut` the hard-cut starter). Draw 2-4 of the most different beats
   full size: `vedit anim still <p> <piece> --at 2.25,9.75,16.5`. Show the image and ask for a thumbs up per
   frame.
4. **Storyboard.** Fill `TIMELINE.board` with one `{t, title, sound, next}` per beat.
   `vedit anim board <p> <piece> --panels` draws the board (the panels are the video's own frames) and one
   image per panel; show the board in chat. `--cards` adds one Studio card per panel (thumbs up or down; with
   the piece in the edit, a card jumps the live piece to its panel). Redraw what's down.
   **Don't animate before the board is approved.**
5. **Build.** Write the scenes (`src/scenes.js`: timed actions with `TT`, `ev(t, d)`, `popS(t)`, write-ons,
   springs), the bridges (`src/bridges.js`) and the score (`src/score.js`). While building:
   - check determinism with `vedit anim tile <p> <piece> --frames 0,25,72,121`;
   - tile across every morph and cut.

   Long pieces can split one scene file per era (`piece.json` `"scenes"`). Agents only when the owner asks.
6. **Render and review.**
   - `vedit anim render <p> <piece>` writes `renders/final.mp4`, the score stems and `final_share.mp4` (picture +
     sound at -14 LUFS for the owner to watch).
   - `vedit anim review <p> <piece>` gives the measured checks, a contact sheet per shot and `review/phone.jpg`.
   - Look at the sheets, then write a per-shot PASS table in `LOG.md` and name the weakest shot.
   - Trust the text check over your eye.
7. **Into the edit.** Run `vedit anim add <p> <piece> --as insert|short|overlay` (below), then render and QA as
   usual.

## Commands

```
vedit anim styles | gallery [--out f.png]
vedit anim new <p> <piece> --style <s> [--from demo|piece|beat-cut] [--formats 9:16,16:9] [--overlay]
vedit anim build|info <p> <piece>                     build the one-file page; size, duration, TIMELINE, GPU
vedit anim still <p> <piece> --at 1,4.5 [--format 16:9] [--scale 0.5]
vedit anim board <p> <piece> [--panels]                the storyboard (TIMELINE.board)
vedit anim tile <p> <piece> --frames 0,24,48           determinism: each frame rendered twice must match
vedit anim render <p> <piece> [--format 16:9] [--blur 4]   picture + score stems + share mix
vedit anim review <p> <piece>                         measured checks, sheets, phone.jpg
vedit anim voice <p> <piece> [--voice kokoro:af_heart] [--scratch]
vedit anim beats <p> <piece> --track song.mp3 [--start 12] [--dur 30] [--bpm 128]
vedit anim capture <p> <piece> --url https://owner.site [--out home.png] [--selector css] [--full] [--dark] [--hide css]
vedit anim add <p> <piece> --as insert|short|overlay [--at 12.5] [--music-db -12] [--no-score]
vedit anim measure <image|folder> [--accent] [--points x,y;x,y] | shotlog <video> | compare <p> <piece> --ref r.png --at 2.5
vedit anim save-style <p> <style> [--as-name name]     keep a look made in edit/anim/styles/<style>/ for every project
```

## Voice: the voice is the clock

- **The script** is one line per beat, in `<piece>/voice/script.json`:
  `{"voice": "kokoro:af_heart", "lead": 0.8, "tail": 1.5, "lines": [{"id": "open", "text": "...", "after": 0.45}]}`.
  - Write numbers and names the way they should be said.
  - Keep to 3.5 words/s or less in English.
  - Give a longer `after` where the picture needs time to land: a count, a caption, the silence before the payoff.
- **The voice:** `vedit anim voice` speaks the lines with any vedit voice (Kokoro, Edge Bangla, the owner's clone,
  ElevenLabs) and writes `voice.json`. `--scratch` gives an offline timing voice; never ship it.
- **Cues:** in the head and scenes, `VL('open')` is a line and `VW('open', 'machines', 1)` is when its first
  "machines" starts. Beats start about 0.3 s after the previous line ends.
- **Sound:** put the payoff hit in a pause before the line that names it; under speech it is ducked away.
- **Re-takes and edited lines** re-time the picture on the next build. A changed word orphans its cue:
  `VW` falls back to the line's start and warns in the page log.
- **The starter:** the multi-format head (`--from piece`) already takes its length from the voice and ducks its
  score under the lines.

## Music

- **The piece's own score:** composed in `src/score.js` with the synth: `pluck`, `pad`, `drone`, `bass`, `sub`,
  `noiseHit`, `sweep`, `riser`, `chime`, `blip`, and `to = 'm'` (music) or `'s'` (sfx).
  - The rules (from `craft.md`): silence before the payoff and the loudest hit on it; the busiest moment is not
    the loudest; balance by removing energy.
  - Notes are created about a second before they sound, so long scores render in time proportional to their notes.
- **The owner's track:** `vedit anim beats --track` maps its beats (`BEATS`: tempo, beats, bars, hits, the loudest
  moment, the drops).
  - Cut on `onBeat(t)`; put the turn on a drop and the payoff on its biggest hit.
  - The score keeps only its sound effects. In the edit, the track is the music clip, marked `sync: "beats"`.

## Assets: the real product

`vedit anim capture` screenshots the owner's own site:
- a page, an element (`--selector`) or the whole scroll (`--full`);
- `--dark`, and `--hide` for cookie banners.

It uses a fresh headless profile: no sign-ins, nothing typed. Ask before capturing a site the owner doesn't own.

Draw a capture with `drawAsset('home.png', x, y, w, h, { fit: 'cover' })` inside the style's own framing. Never
draw a fake screen as if it were the product. A piece with embedded screenshots plays in the Studio from its
rendered proxy (a database document holds about 200 KB).

## Formats

- Pieces started `--from piece` lay themselves out per format (`LX`, `LY`, `UNIT`, `PORTRAIT`, `WIDE`) and are
  never cropped. Render each format with `--format`.
- The style demos are 9:16 only.
- In an edit, the piece takes the edit's shape (the nearest of 9:16, 4:5, 1:1, 16:9).
- Pieces move on a 24 fps grid (the boil steps on 2s); compose converts to the edit's frame rate.

## Bangla

Every font stack ends in a bundled Bangla font:
- Atma (hand), Galada (marker), Hind Siliguri (sans), Tiro Bangla (serif);
- in the Studio, the same families come from Google Fonts.

Per-letter effects step by grapheme clusters, so a conjunct (ক্ষ) or a vowel sign stays whole:
- the typing line (`monoText`);
- sketchbook's `handLetter`;
- the math writer;
- the pixel style's typing.

Two more things to know:
- Bangla is never monospaced: its clusters keep their shaped widths, and handLetter keeps the headline (matra)
  joined.
- The pixel style sets Bangla at its low resolution and snaps it to whole pixels.

The stroke alphabet (`handwrite`) only has a few Latin letters; anything else is written with the hand font and
wiped on.

## Into an edit

`vedit anim add <p> <piece> --as ...` renders the piece where the engine looks for overlays, so the final render
reuses it. It also adds the score stems as music and sfx clips.

| `--as` | What happens | Score |
|---|---|---|
| `insert --at 12.5` | full-frame over the footage from 12.5 s; the speaker keeps talking | music at -12 dB, ducked under speech |
| `short` | the whole video: over a VO main track (`vedit voice vo --place main`), or the piece itself becomes the main track; the piece's own voice goes in as a VO clip, captions come from it | 0 dB when nothing is said, -12 dB under the voice |
| `overlay --at 9` | a transparent piece (`vedit anim new ... --overlay`): arrows, circles, underlines, notes in a style's ink over the footage; no backdrop, no morphs | as insert |

A piece up to about 200 KB plays live in the Studio (the same page, seeked). A bigger one plays its rendered
proxy. CapCut and the NLE hand-offs get the rendered video.

## What review measures

- **Cut grid:** every cut on its 8th (16ths inside `fastFrom`-`fastTo`), confirmed by the picture changing there;
  morph centres on the 8th grid.
- **Dead beats:** more than 3 s where the picture barely changes (`review.deadMax`; silence acts are exempt).
- **Narration:** words per second of each line.
- **Story arc** (`TIMELINE.acts` roles: journey, peak, silence, gift, goodbye):
  - the gift is the loudest and held;
  - the silence is 15 dB under the peak;
  - the goodbye decays.
- **Anchor:** how often the hero holds its screen spot (`TIMELINE.anchor`).
- **Text:** strings cut off by the frame, overlapping, or under the phone UI. Deliberate crowding goes in
  `piece.json` `review.textIgnore` with a reason.
- **Sound:** the loudest 100 ms and the silence before it (at least 0.4 s at -40 dBFS or quieter);
  -14 LUFS for the share mix.

You can't hear the score: report the numbers and ask the owner to listen.

## Notes

- **Licence:** everything a piece draws and plays is the owner's (generated in code). The adapted kit is MIT;
  `ATTRIBUTIONS.md` credits it.
- **References** (videos, stills) are other people's work: keep them in the project, uncommitted, and never
  name their artist in published output unless the owner asks to credit them.
- **Speed here** (Intel Core Ultra 5, Arc iGPU, WebGL on the GPU): see `docs/SPEC.md` (Phase 6) for the measured
  numbers.
