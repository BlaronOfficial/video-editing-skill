# Voices

Narration for faceless videos, voiceovers on top of footage, and the owner's own voice in any language.
Every voice comes with a word-timed transcript, so captions, cuts and anchors treat it like a recording.

```
vedit voice list [--language bn] [--ready]            every voice with its licence and commercial flag
vedit voice say --voice <id> --file script.txt --out vo.wav
vedit voice vo <p> --voice <id> --file script.txt [--place main|audio] [--at 12] [--name vo1] [--speed 1.05]
vedit voice clone <name> --files a.wav b.wav --consent "I, <speaker>, agree to ..."   [--eleven]
vedit voice compare --files a.wav b.wav                speaker similarity (did the clone land?)
```

## Picking a voice

| Need | Voice | Notes (measured here, Intel Core Ultra 5 laptop, no GPU) |
|---|---|---|
| English narration, offline | `kokoro:af_heart`, `kokoro:am_michael`, `kokoro:bf_emma`, ... (54 voices) | Apache-2.0, commercial OK. With `kokoro_fp32` faster than real time here (RTF 0.87); the int8 file alone is 2.6-3.5x slower |
| Hindi, Spanish, French, Italian, Japanese, Portuguese, Chinese | `kokoro:hf_alpha`, `kokoro:ef_dora`, `kokoro:ff_siwis`, ... | same model |
| Bangla, best free quality | `edge:bn-BD-NabanitaNeural` (f), `edge:bn-BD-PradeepNeural` (m), `edge:bn-IN-TanishaaNeural`, `edge:bn-IN-BashkarNeural` | online (the script goes to Microsoft), exact word timings, ~8 s per paragraph; commercial terms unclear |
| Bangla offline | `bn_coqui:female` (natural), `bn_mimic3:0`..`15` (16 speakers, plainer) | coqui: IIT Madras data, licence looks permissive, verify before paid work; mimic3: CC BY-SA, credit "Mimic 3 (Mycroft)" |
| The owner's voice, English | `pocket:<name>` after `voice clone` | Pocket TTS from a 15 s reference; check `voice compare` (a clone scored 0.50 vs 0.13 for another voice) |
| The owner's voice, Bangla or any language | `openvoice:<name>@edge:bn-BD-PradeepNeural` (any base voice) | the base voice speaks, OpenVoice moves it to the owner's timbre (0.50 vs 0.38 for the base alone) |
| Premium, paid | `eleven:<name or id>` | ElevenLabs key; best Bangla prosody and clones |

Numbers in Bangla scripts are spelled out for the offline Bangla voices (২০২৬ -> দুই হাজার ছাব্বিশ); Edge and
ElevenLabs normalise numbers themselves. Captions show the script as written.

## Word timing

Sentences are spoken one by one and joined with pauses vedit places (0.28 s between sentences, 0.6 s
between paragraphs), so every sentence boundary is exact. Inside sentences:
- Edge and ElevenLabs: the service's own word times.
- English offline voices: Whisper (base.en) aligned to the script; the script's spelling always wins.
- Other offline voices: words spread inside the sentence by length (Whisper reads synthetic Bangla poorly).
`alignment.method` and `matched` in the result say which was used.

## Voiceover in an edit

- `--place main` (faceless videos): the voice becomes the main track. Its picture is the canvas colour, so
  put b-roll, stills (`vedit kenburns`, `vedit vfx parallax`) and graphics over it; captions come from it.
- `--place audio --at 12`: a VO clip over footage; captions include its words, music ducks under it.
The source carries the voice's licence in its notes and `assets/provenance.json`.

## Cloning (consent first)

Only the owner's voice, or a speaker who agreed in their own words. `--consent` is stored with the voice in
`personal/voices/<name>/voice.json` together with the samples (1-5 clean recordings, 30-120 s in total is
plenty; no music, little room echo). `--eleven` also uploads the samples to ElevenLabs: ask first, the voice
leaves the PC. Never present a cloned voice as a real recording of the person. Pocket TTS's terms forbid
cloning without explicit, lawful consent.

## Setup

`vedit setup voice` (~20 MB: sherpa-onnx 1.13.8 + edge-tts in their own venv; sherpa-onnx 2.x removed the
espeak step that Kokoro needs for names and non-English text) and `vedit setup openvoice` (~0.8 GB with
PyTorch CPU; ask first). Models download when asked: `kokoro_multi` 132 MB (+ `kokoro_fp32` 326 MB, the same voices 3-4x faster),
`bn_coqui` 108 MB, `bn_mimic3` 80 MB, `pocket_tts` 98 MB, `openvoice_v2` 131 MB (`vedit models get <id>`).
