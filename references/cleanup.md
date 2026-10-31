# Clean-up and time FX

Two ways in, the same filters:

- **In an edit** (preferred): settings on a clip, rendered at decode before framing, shown as notes in every
  hand-off, previewed in renders (`--preview`).
  ```
  vedit clip set <p> <clip> --stabilize [--smoothing 30] --denoise light|medium|strong --reverse
                            --smooth interpolate|blend --crop x,y,w,h --redact x,y,w,h[:blur|pixelate|delogo]
                            --projection yaw,pitch,h_fov,v_fov --straighten -2.5 [--clear]
  vedit clip ramp <p> <clip> --segment 0-2:1 --segment 2-3:0.25 --segment 3-6:1     # speed sections
  vedit clip freeze <p> --at 12.4 --hold 2                                            # hold a frame
  vedit kenburns <p> photo.jpg --at 12 --duration 6 --zoom in --pan right             # a still that moves
  ```
- **On a file** (one-off jobs, never overwrites the input, `--dry-run` prints the plan):
  ```
  vedit fix stabilize|denoise|deinterlace|to_sdr|redact|crop|v360|reverse|straighten|loop|smooth <file> [opts] --out x.mp4
  ```

| Need | Setting | Notes |
|---|---|---|
| Shaky handheld | `--stabilize` | vidstab, two passes; smoothing 30 = 1 s each side at 30 fps (more = steadier, less = keeps intended moves); zooms slightly to hide edges. Measured: jitter on a shaken shot down by ~40 % |
| Grain / low light | `--denoise light\|medium\|strong` | light/medium = hqdn3d (fast; +0.8 / +3 dB), strong = non-local means (best detail, ~0.4 s per 720p frame: say so for long clips). Never heavy on screen recordings or text |
| Faces, plates, names, a logo | `--redact x,y,w,h:pixelate` (or blur, delogo) | source pixels; add `start`/`end` in edit.json for a time window. Moving faces need tracking (phase 4) |
| Black bars | `--crop` or `vedit footage bars <p> --apply` | crop before reframing |
| Tilted horizon | `--straighten -2.5` | rotates and zooms just enough to hide the corners |
| 360 camera | `--projection 90,0,100,60` | equirectangular to a flat view (yaw, pitch, horizontal / vertical field of view) |
| Slow motion | `vedit clip ramp` with a speed < 1 | sections under 1x get `smooth`: interpolate (motion-compensated new frames) from 0.2x, blend below |
| Speed ramp | `vedit clip ramp` | each section becomes its own clip, so CapCut, NLE hand-offs, anchors and the Studio all keep working |
| Hold a moment | `vedit clip freeze` | the frame becomes a still clip; everything after moves by the hold |
| Rewind | `--reverse` | sound reversed too; keep reversed clips short (decoded in memory) |
| Fill a length | `vedit fix loop <file> --duration 30` | stream copy, for backgrounds and loops |

Look at the result (`vedit render --preview`, then frames) before claiming it worked: stabilization can
warp faces, interpolation can smear fast hands, denoise can waxen skin.

Filter choices follow kajisho5/ffmpeg-skill (MIT).
