# Camera footage: making sources look right

`vedit project init` and `add-source` measure every video once (`vedit footage check <file|project>` re-runs
it) and store it on the source: `color` (what was found) and `notes` (one line each for you). Read the notes
before planning: they change what you can promise. The renderer, b-roll, Studio proxies and frozen frames
all start from the same per-source chain, so a fix applies everywhere.

| Found | What vedit does | What you do |
|---|---|---|
| HDR: PQ (HDR10), HLG, Dolby Vision (iPhone) | tone-mapped to SDR BT.709 at decode (zscale to linear light, mobius curve, reference white 100 nits) | Tell the owner once. For an HDR YouTube upload, export with `--preset youtube-hdr` from a master instead |
| BT.2020 primaries on an SDR curve | gamut converted to BT.709 (no tone map: that would darken it) | nothing |
| BT.601 matrix (older cameras, SD, some phones) | matrix converted to BT.709; every render is tagged BT.709 | nothing |
| Looks like Log (grey, flat, desaturated but tagged SDR: S-Log, V-Log, C-Log, D-Log) | flagged | Ask for or find the camera maker's conversion LUT, then `vedit footage lut <p> <source> <file.cube>` before grading. Never grade Log by eye without it |
| Interlaced (field order tt/bb) | deinterlaced first (bwdif) | nothing |
| Variable frame rate (phones, screen and game recorders, Zoom) | conformed to the canvas rate in every render; smart cut falls back to an accurate cut | Watch lip sync on long clips |
| Black bars (letterbox / pillarbox burned into the picture) | found | `vedit footage bars <p> --apply` crops them on every clip (`src_crop`) before reframing |
| 10-bit | nothing special | 10-bit is not HDR: trust `hdr`, not the bit depth |

## Devices (from `color.device`)
- **iPhone**: HDR (HLG + Dolby Vision 8.4) by default, variable frame rate, portrait by rotation tag, extra
  metadata tracks. HEVC "High Efficiency" uses open GOPs, so smart cuts re-encode.
- **Android**: HDR10/HDR10+ on newer phones, strongly variable frame rate, odd sizes from screen recording.
- **GoPro**: 10-bit HEVC that is usually SDR; wide lens; 50-60 fps; a telemetry track. Stabilize if it shakes.
- **DJI**: often no audio at all (drones), D-Log or HLG, HEVC 4K at high frame rates.
- **Insta360 / 360 cameras**: equirectangular; reframe a flat view per clip (`vedit clip set <p> <clip>
  --projection yaw,pitch,h_fov,v_fov`).
- **Zoom / Teams / OBS / screen recorders**: low bitrate, variable frame rate, sometimes several audio tracks
  (only the first is used); sharp text: avoid heavy denoise and blur.

## Speed and size
Tone-mapping 4K costs about real time on a laptop CPU, motion interpolation and non-local-means denoise far
more: cut first, then process the kept parts (the renderer only ever decodes kept ranges), and preview at
540p while iterating.

Detection techniques (signalstats for Log, packet timing for frame rate, zscale tone mapping) follow
kajisho5/ffmpeg-skill (MIT).
