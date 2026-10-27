# Audio: voice, music, SFX

## Voice (automatic in the render)
High-pass 70 Hz → denoise (`afftdn`) → presence EQ (+2.5 dB at 3.2 kHz, -1.5 dB at 180 Hz) →
compressor → de-esser; 20 ms fades at every cut. Toggle with `output.audio.denoise` / `voice_enhance`.
Very noisy footage: CapCut's "Reduce noise"/"Enhance voice" (screen control) or ElevenLabs voice
isolation are stronger; the user decides.

## Music
- Sources: the user's library (`vedit assets search "<mood>" --kind music`), CapCut library (screen
  control; licence warning for commercial use), or tracks the user provides.
- Level: music `volume` 0.1-0.25; ducking under speech is automatic (`duck_db`, default -14 dB) in the
  render (sidechain compression) and in CapCut (volume keyframes).
- Fit: start on a downbeat; end with a fade or on a phrase end. `vedit beats <file>` gives BPM, beat and
  onset times: cut b-roll and land text_punch/emoji_pop on beats.
- Loop short tracks with `"loop": true`.

## SFX
- Library first (`--kind sfx`), then CapCut SFX (screen control), then procedural:
  `vedit sfx <kind> --out edit/assets/sfx/<name>.wav [--duration 0.5 --pitch 1.2 --seed 4]`
  kinds: whoosh, swoosh_up, swipe, pop, click, tick, riser, impact, bass_drop, glitch, ding, shutter.
- Register then place: `vedit project add-source <p> --file <wav> --origin generated`, add an `audio`
  clip with `role: "sfx"`, `volume` 0.4-0.8, starting ~0.05 s before the visual hit.
- Density by style: none (podcast) → low (cinematic, cool_girl) → very high (hormozi, energetic).

## Voiceover
Recorded VO: add as a source with `--origin vo`, transcribe it, cut it like A-roll (main track can be an
audio source with b-roll/graphics above), or place it as `role: "vo"`.
AI voiceover / voice clone: `references/extras.md`.

## Loudness targets
-14 LUFS integrated, -1.5 dBTP (default for all major platforms). Podcasts/Spotify video: -16 LUFS
(`output.audio.target_lufs`). QA reports the measured values.
