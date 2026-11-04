# Extras

## Long video → shorts
```
vedit shorts candidates <p> --min 20 --max 60 --top 10     # ranked, sentence-aligned windows
```
Read the previews; pick windows that stand alone (setup + payoff), have a strong first line, and don't
depend on earlier context. Tighten each into keeps (drop pauses/fillers inside), optionally move the best
line first as the hook, then:
```
vedit shorts make <p> short_01 keeps_short_01.json --ratio 9:16
vedit reframe <p>/edit/shorts/short_01        # face-tracked vertical crop
```
Each short is a full project (`edit/shorts/<name>/`): captions, graphics, render, CapCut build as usual.

## Auto-reframe / multi-ratio
`vedit reframe <p>` adds crop paths to clips whose aspect differs from the canvas (face tracking, smooth
camera moves). `vedit reframe <p> --ratio 1:1` writes `edit_1x1.json` (render it with
`vedit render <that-json-path>`). CapCut gets the same motion as position keyframes. Check the preview:
two people → keep both in frame by setting crop keys manually (`cx` 0..1).

## Thumbnails and covers
```
vedit thumbnail frames <video> --out edit/thumbs --count 6       # sharp, face-forward candidates
vedit thumbnail make edit/thumbs/frame_0041.20.jpg --title "I let AI edit my video" \
      --highlight AI --emoji "🤯" --size youtube --out edit/thumbs/thumb_a.png
```
Make 2-3 variants (different frame/words/layout), look at them, recommend one. Covers: `--size cover`.
Higgsfield can generate background art when the footage has no good frame.

## Post copy
Write per platform from the transcript: title (YouTube ≤ 70 chars, curiosity + keyword), description
(first 2 lines matter, chapters from the edit for long-form: `0:00 Intro …`), 3-8 hashtags (mix broad
and niche), pinned comment/CTA. Bangla audiences: offer Bangla + English versions. Save to
`edit/render/post.md`.

## AI voiceover and voice clone

Free offline and online voices, Bangla, and the owner's cloned voice: `references/voices.md`
(`vedit voice ...`). ElevenLabs (paid) stays available directly:
```
vedit tts voices
vedit tts speak "Script text…" --voice <name-or-id> --language bn --out edit/assets/vo/vo1.mp3
vedit tts clone --name my_voice --files sample1.wav sample2.wav     # only with the speaker's consent
```
`speak` also writes `vo1.transcript.json` (word timings), so you can add the file as a source,
set its `transcript`, and build captions/cuts exactly like recorded speech. Faceless flow: script →
VO → b-roll/Higgsfield/graphics on top → captions → music.

## Batch
Edits: see `references/workflow.md` ("a week of reels"). Keep a shared style/brand; vary hooks and graphics.

The same mechanical job on every file of a folder (exports for three platforms, clean-up, chapters):
```
vedit batch <folder> --recipe recipe.json [--jobs auto] [--dry-run]
{"steps": [["delivery", "export", "{file}", "--preset", "reels", "--out", "{out_dir}/{stem}_reels.mp4", "--overwrite"]],
 "outputs": ["{out_dir}/{stem}_reels.mp4"], "out_dir": "{folder}/out"}
```
Each step is a vedit command line (`{file} {stem} {name} {folder} {out_dir}`). Files already done with the
same recipe are skipped (`.vedit_batch.json` in the folder); up to 4 run in parallel.

## Grids, audiograms, stills
- `vedit grid a.mp4 b.mp4 c.mp4 d.mp4 --cols 2 --out grid.mp4` (contain per cell; sound from the first or `--audio mix`).
- Podcast clip / audio-only post: `vedit audiogram ep.m4a --image cover.png --title "Episode 12" --out ep.mp4
  [--size 1080x1920] [--style line|bars|dots]`; `vedit waveform` is the plain version. Nothing is fetched.
- Ken Burns on a photo: `vedit kenburns <p> photo.jpg --at 12 --duration 6 --zoom in --pan right`.

## Report
`vedit report --after final.mp4 [--before raw.mov] [--platform reels] --out report.html [--step "..."]`:
a self-contained page with both files' facts, the delivery check and frames. Good for clients and for the
owner's records; publish it as an Artifact only when asked.
