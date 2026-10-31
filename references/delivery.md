# Delivery: platforms, checks, exports

One table per destination (`vedit delivery platforms`): frame, length limit, accepted aspects, frame rate,
codecs, size limit, loudness target and true-peak ceiling, and the **safe zones** the app's own UI covers.

| Platform | Frame | Max length | Loudness | UI covers (top / bottom / left / right) |
|---|---|---|---|---|
| tiktok | 1080x1920 | 10 min | -14 LUFS ±2 | 10 / 22 / 5 / 14 % |
| reels | 1080x1920 | 90 s | -14 ±2 | 8 / 20 / 5 / 12 % |
| shorts | 1080x1920 | 3 min | -14 ±2 | 6 / 18 / 5 / 12 % |
| youtube | 1920x1080 (keeps source size) | 12 h | -14 ±2 | 5 % title-safe |
| x, linkedin, facebook | 1280x720 / 1080x1080 / 1920x1080 | 140 s / 10 min / 4 h | -14 ±3 | 5 % |
| podcast | audio-first | - | -16 ±1 | - |
| broadcast | 1920x1080 | - | -23 ±1 (EBU R128) | 5 % |

Set the destination on the edit (`output.platform` in edit.json) and QA checks it on every render and
draws the safe zones on a frame (`qa/safe_<platform>.png`): look at it. Text, captions and faces belong
inside the clear area.

```
vedit delivery check <file> --platform reels [--compare master.mp4]
vedit delivery export <file> --preset reels [--fit pad|crop|blur] [--max-mb 25] [--out x.mp4] [--dry-run]
vedit delivery compare <a> <b>        # SSIM (mean, worst) and PSNR
vedit delivery repair <file>          # remux what is readable, count the damage
vedit delivery safe <file> --platform tiktok --at 3
```
Presets: tiktok, reels, shorts, x, linkedin, facebook, youtube, youtube-hdr (keeps HDR, HEVC 10-bit),
h265, prores (editing master), gif, podcast. `export` tone-maps HDR for SDR-only places, normalises
loudness with a measured two-pass loudnorm (ambience or near-silence under -40 LUFS is never pushed up to
a speech target), and checks the result. `--max-mb` runs a two-pass x264 encode at the bitrate that fits.

## Reading a check
Rows are PASS / WARN / FAIL. **Format rows** (codec, pixel format, colour tags, true peak, file size,
frame timing) are safe to fix by re-exporting. **Judgement rows** change the content: duration (cut loses
words, speed-up changes motion), aspect (crop loses edges), frame rate (drops motion), loudness of quiet
ambience. Fix those only when the request already implies the answer; otherwise say what it would cost and
let the owner choose.

## Repair
`repair` saves what a damaged recording still holds (cut-off downloads, recordings with a damaged middle).
A camera file whose index was never written (battery died) needs `untrunc` and a healthy file from the same
camera: say so, don't promise.

Platform numbers are the platforms' published limits as of Oct 2026 and conventional loudness targets;
check the platform's help page when something is rejected. The single-table design follows
kajisho5/ffmpeg-skill (MIT).
