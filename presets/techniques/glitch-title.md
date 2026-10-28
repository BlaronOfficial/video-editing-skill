---
name: glitch-title
tags: title, glitch, tech, energetic, transition
description: Short digital glitch on a title slam: RGB split, slice jitter, white flash, glitch hit
---
# Glitch title

**Use for**: tech, gaming, "plot twist" beats, one moment per video. Overuse looks cheap.

**Engines**: `text_punch` template (or a custom composition) + an ffmpeg custom FX + the glitch SFX.

**Recipe**
- Title: `text_punch` with `flash: true`, 1.0-1.4 s, on the word the speaker hits.
- Picture glitch for 0.25 s at the title's first frame:
  `{"id": "glitch1", "kind": "ffmpeg", "hook": "video_pre_captions", "filter": "rgbashift=rh=-8:bh=8,noise=alls=12:allf=t", "start": <t>, "duration": 0.25}`
  (an ffmpeg hook applies to the whole video; for a timed effect use `effects` with `render: "glitch"`
  and `render: "rgb_split"` at that time, or wrap the filter with `enable='between(t,<t>,<t+0.25>)'`).
- Sound: a glitch burst that hits first, then silence for 0.2 s before speech continues.
- Follow with a clean cut and a calm frame; contrast sells the glitch.
