# Audio: voice, music, sound effects, listening

## Voice (automatic in the render)
High-pass 70 Hz → denoise (`afftdn`) → presence EQ (+2.5 dB at 3.2 kHz, -1.5 dB at 180 Hz) →
compressor → de-esser; 20 ms fades at every cut. Toggle with `output.audio.denoise` / `voice_enhance`.
Very noisy footage: CapCut's "Reduce noise"/"Enhance voice" (screen control) or ElevenLabs voice
isolation are stronger; the owner decides.

## Music
- Sources: the owner's library (`vedit assets search "<mood>" --kind music`), Openverse/Wikimedia
  (`vedit sources search "<mood>" --kind audio`), the browser (`references/sourcing.md`), the owner's
  logged-in Suno/Udio (`references/webai.md`; free tiers are non-commercial), or tracks the owner provides.
- Level: music `volume` 0.1-0.25; ducking under speech is automatic (`duck_db`, default -14 dB) in the
  render (sidechain compression), the Studio and CapCut.
- Stop-downs: effects placed from a kit on big moments (hit, drop, long whoosh, swell) dip the music for
  ~0.4 s before the hit and bring it back on it (earshot's mix rule: one gesture at a time, nothing ducks
  under every effect). Automatic; shown in the Studio's playback too.
- Fit: start on a downbeat; end with a fade or on a phrase end. Land text_punch/emoji_pop on beats.
- Loop short tracks with `"loop": true`.

### The beat map, and cuts on the beat

`vedit beats <file> [--start 12] [--dur 30] [--bpm 128 | --bpm 70-180]` maps a track. It returns:
- `bpm`, `offset` (the first beat) and `beats`;
- `downbeats` (bar starts);
- `hits` (the strongest onsets: where the big moments go);
- `loudest` (the loudest 100 ms) and `quiet` (drops);
- `other_tempos` and `confidence` (the share of beats with an onset on them).

How it works:
- It fits the grid to the onsets over the whole track, so it stays on the beat to the end. On 60 s test tracks
  at 87-174 BPM the worst error was 1-2 ms; the old map read 120 BPM as 117.5 and was a whole beat late after
  29 s.
- Constant tempo is assumed. Double or half time is the usual miss: check `other_tempos`, and pass `--bpm` when
  the owner knows the tempo.

Snapping cuts to the beat:
- Mark a music clip `"sync": "beats"` (or `"bars"`, `"8ths"`) when the cuts should sit on it. QA then reports how
  many cuts are on the grid (`beat_grid`).
- `vedit beats snap <p> --music <id> [--grid beats|bars|8ths] [--tolerance 0.12]` moves the cuts onto the grid.
  - It is a dry run first; add `--apply` to keep the moves.
  - A main-track cut lengthens or shortens the clip before it, and everything after moves with the picture.
    Music stays put.
  - A cut never moves into a word: no revealing a cut word, no clipping a kept one.

### Music made in code (a fallback bed)

`vedit score compose <p> --mood warm|tense|upbeat|lofi|epic|minimal|playful [--bpm] [--key] [--payoff 30]` writes
a bed shaped by the edit:
- its length;
- a sweep into each chapter marker;
- around the payoff (a `payoff` marker, or `--payoff`): a hard stop into a short silence, the loudest hit on the
  payoff, a held chord, then a decay.

How it is made and added:
- It is played by the synth from the animation kit (pad, pluck, bass, drums, risers, chimes, reverb) and
  rendered headless.
- It goes in as a music clip: 0 dB when nothing is said, -12 dB and ducked under speech.

Notes:
- **Licence:** it is the owner's, with no licence limits.
- **Ranking:** it ranks below the owner's tracks and good library music.
- **Listening:** Claude can't hear it. QA measures the silence before the payoff; the owner listens.
- **Moods:** `vedit score moods` lists them; a personal mood is a JSON in `personal/scores/`.

## Sound effects: kits, cues, placement

A **kit** is one sound per role: `tick`, `tock`, `pop`, `click`, `click.confirm`, `snap`, `land`,
`land.light`, `hit`, `drop`, `whoosh.short`, `whoosh.long`, `riser`, `swell`, `bell`, `text`, `key`.
With earshot installed (`vedit setup earshot`, ~70 MB, no models) the takes come from its 252-sound bank,
made in code, each with its measured onset / peak / end; without it the built-in `synth` kit stands in.

| Kit | Feel |
|---|---|
| `crisp` | Bright, short UI-style effects; talking-head shorts, tech, explainers (default with earshot) |
| `calm` | Soft, low, sparse; cinematic, aesthetic, vlog, documentary |
| `launch` | Music-led product films: effects set against the music bed, stop-downs before hits |
| `minimal` | Very few, very quiet |
| `synth` | Built-in procedural fallback (always available) |
| personal | `personal/sound/kits/<name>.json` in earshot's kit schema (copy a preset and change roles) |

```
vedit sound kits                          # what is available
vedit sound cues <p>                      # proposes cues -> edit/sound/cues.json (edit it)
vedit sound place <p> [--kit crisp]       # cues -> anchored, levelled AudioClips
vedit sound find "soft wooden knock"      # search the bank by words (ids, kinds, notes)
vedit sound render knock/wood --out x.wav # one bank sound (or synth/<kind>)
```
`cues` reads the edit: graphics landing (by template: lower thirds whoosh, emoji pops, counters tick,
titles get a long whoosh, text punches land), hard transitions, b-roll swipes, effects (flash → hit,
shake → drop), and emphasised caption words (tick). It keeps the strongest cues within a density of
about 8 per 10 s. **Edit the list**: delete what feels busy, add cues for moments only you see
(`{"id": "reveal", "t": 12.4, "role": "hit", "why": "price reveal"}`; add `"anchor": {"source", "t"}` to
follow re-cuts). Density by style: none (podcast) → low (cinematic) → high (hormozi, energetic).

`place` does what a sound designer does by hand:
- the take's sync point (onset; peak for whooshes; end for risers) lands on the cue, shifted by the role's
  offset (taps and clicks lead the picture by 10-60 ms, pop-ins land ~30 ms after);
- each clip is anchored to the source moment, so re-cuts and the pace knob keep it on its word;
- the level is set against what plays under it: the effect's loudest 50 ms sits `bed_db` over the music
  bed (earshot's model), or a few dB under the voice when there is no music; never over -1 dBFS;
- takes rotate (no machine-gun repeats); runs keep the role's minimum spacing;
- the global SFX level stays a Studio knob (`sfx_level`).
Hand-placed effects still work: add an `audio` clip with `role: "sfx"` (no `sfx` block).

## Listening (verify before you claim)
- `vedit qa` checks every placed effect against the render: the event that answers each cue and its
  offset (`sfx_sync` issues for effects that are buried or off by more than 60 ms). Uses earshot's
  model-free detector when installed, a simple onset search otherwise.
- **Ears** (`vedit setup earshot --ears`, ~1.3 GB: torch CPU + CLAP + AST; ask first): QA adds earshot's
  timeline (what is heard, tagged), an annotated sheet (`qa/ears_sheet.png`: spectrogram, events, frames,
  cues) and a critique scorecard. Look at the sheet like the frame sheets. `vedit sound check <p> --ears`
  runs it alone. On a laptop CPU it takes a few minutes per 30 s (model load included): use
  `vedit qa <p> --no-ears` while iterating and let the final QA listen. The critique compares against
  earshot's bundled music-led launch films: for talking-head edits read its music and density notes as
  hints, not rules (`earshot profile` can build a profile from the owner's own reference videos).

## External recorders, second cameras, drift
```
vedit audio sync <reference> <other> [--drift]       # offset at the start (+ clock drift in ppm)
vedit audio replace <video> <recorder.wav> --drift   # the recorder's sound on the video, aligned, picture copied
```
Offsets are measured on several 30 s windows across the overlap (some passages, like music beds or silence,
correlate badly); with `--drift` a line through the confident windows gives the clock difference, and the
recorder is resampled to the camera's clock (no time-stretch artefacts). Measured: 200 ppm of injected drift
found within 12 ppm, start offset within 1 ms, a replaced track lines up at both ends. Confidence under 3:
the two files probably did not record the same moment; look and listen. Multicam angles: `references/watching.md`.

## Voice processing and dynamics
The render's voice chain (high-pass, denoise, presence EQ, compressor, de-esser) is on by default. More in
edit.json `output.audio`: `gate_db` (-45 removes room noise between words), `compress` ("-20:4"),
`limit_db`, `widen` (0..1, real stereo only). On a file: `vedit audio clean <f> --voice light|medium|strong`,
`vedit audio dynamics <f> --gate -45 --compress -20:4 --limit -1`, `vedit audio widen|downmix|extract <f>`.
5.1 sources are downmixed to stereo automatically in renders.

## Cutting pauses without cutting sentences
`vedit plan auto <p> --speech-aware` cuts a pause only after a sentence ends (or when it is very long), so a
breath in the middle of a thought stays: the natural default for interviews and explainers. Plain
`plan auto` cuts every pause over `--max-pause` (punchy shorts).

## Voiceover
Recorded VO: add as a source with `--origin vo`, transcribe it, cut it like A-roll (main track can be an
audio source with b-roll/graphics above), or place it as `role: "vo"`.
AI voiceover / voice clone: `references/voices.md` (`vedit voice vo <p> --voice <id> --file script.txt`).

## Loudness targets
-14 LUFS integrated, -1.5 dBTP (default for all major platforms). Podcasts/Spotify video: -16 LUFS
(`output.audio.target_lufs`). QA reports the measured values.

earshot is MIT (Leon Lin, github.com/Leonxlnx/earshot); its kit levels and offsets were measured by its
author on licensed reference films.
