"""VFX: tracking, planar screen replacement, person cut-outs, depth, and the render layers that use them.

Everything here works in SOURCE space: tracks, mattes and depth are computed on the source frames
(after the footage chain: deinterlace, HDR -> SDR, camera LUT) and stored with the source id and source
times. So they survive re-cuts, reframes, zooms and ratio changes; render.py merges them at decode,
before any framing, exactly like redaction and stabilization.

  track.py    object / face tracking (OpenCV VitTrack or optical flow, YuNet faces), smoothing,
              source -> canvas mapping for overlays that follow a track
  planar.py   four-corner plane tracking (homography) and screen / sign replacement
  matte.py    person matting (MODNet), still cut-outs (MODNet portraits, BiRefNet objects)
  depth.py    monocular depth (Depth-Anything-V2-Small): 3D photo parallax, fake depth of field
  layers.py   the filter pieces and cached layer files render.py splices into each clip
  frames.py   frame reader / writer pipes shared by all of the above
"""
