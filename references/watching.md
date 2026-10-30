# Watching footage, speakers, multicam, memory, links

## Watch (eyes)
```
vedit watch <p>                       # every video source -> edit/watch/<source>/grids/*.jpg
vedit watch <p> --source a_roll --start 60 --end 120
vedit watch <p> --render              # the draft or final render (critique, QA)
vedit watch <file> --file             # any video, e.g. a fetched reference
```
Frames come at every scene change plus one per second, near-duplicates dropped (claude-real-video's
two-channel comparator: it still catches slides, text swaps and small on-screen changes), tiled 3x3 with
the source time on each cell. Read the grids with your eyes before cutting: where the speaker is, title
cards, photo inserts, crossfades, what could be b-roll, where the energy is. Cite times from the labels.
`frames.json` maps every frame to its time. Without claude-real-video installed (`vedit setup crv`,
~100 MB) a simpler native pass does the same job.

## Transcripts: faster and safer
- **No-speech gate**: Whisper is skipped on music-only or silent sources (no model load, no captions
  hallucinated over silence); the transcript says `no_speech: true`.
- **Existing captions**: `vedit transcribe <p> --engine subs` uses a sidecar `.srt`/`.vtt` (same file
  stem, e.g. from `vedit fetch`) or an embedded subtitle track. Word times are spread over each caption
  (`approx_timing`): good for finding and cutting sentences, rougher for word-by-word captions (run
  Whisper for those).

## Speakers
```
vedit speakers <p> <source> [--num 2]
```
Offline diarization (sherpa-onnx; models ~47 MB, asked first). Labels every transcript word with
`SPEAKER_00`, `SPEAKER_01`... (numbered by first appearance) and writes the turns to
`transcripts/<source>.speakers.json`. Use it for interviews and podcasts: per-speaker caption colours,
picking one person's best lines, and multicam. Name speakers for the owner ("SPEAKER_00 is the host") after
checking a frame where each one talks.

## Multicam by speaker
Two or more cameras recording the same conversation:
```
vedit project add-source <p> --file cam_b.mp4 --origin camera
vedit speakers <p> a_roll
vedit multicam <p> --angles cam_b --map SPEAKER_00=a_roll SPEAKER_01=cam_b [--min-shot 1.2]
```
Angles are synced to the main source by audio (cross-correlation; refuses when it cannot find a clear
match). Each main clip is split at speaker turns and shown from that speaker's angle; pauses hold the
current angle; shots shorter than `--min-shot` are not cut. Check the grids after, then add a wide shot
or reaction cutaways by hand where they help.

## Footage memory
```
vedit memory index <p>                # after transcribing: adds this project's footage
vedit memory ask "pricing"            # every line that says it, in any footage: file, time, speaker
```
A local SQLite full-text index in `personal/memory.db` (trigram: substrings and Bangla match). Use it to
find a clip you remember from an older shoot, or every time a guest mentioned a topic.

## Links
```
vedit fetch <url> --to <folder> [--project <p> --register] [--subs en]
```
yt-dlp (in claude-real-video's venv) downloads the video and the platform's captions when it has them.
Third-party videos are copyrighted: use them as reference (watch, study a technique, quote briefly with
commentary) unless the owner has the rights. The provenance log records the URL, title and uploader.
Never pass the owner's browser cookies unless they ask for a video only their account can see.

claude-real-video is MIT (github.com/HUANGCHIHHUNGLeo/claude-real-video); the memory index follows its
design.
