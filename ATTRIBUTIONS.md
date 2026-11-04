# Attributions

vedit is MIT-licensed. It builds on these projects; their licences apply to their code and data.

| Project | Used for | Licence | How |
|---|---|---|---|
| [earshot](https://github.com/Leonxlnx/earshot) by Leon Lin | sound kits (252 code-made sounds with measured sync points), kit mix rules, listening (timeline, sheet, critique) | MIT | installed into an isolated venv (`vedit setup earshot`), called as a subprocess; never vendored |
| [claude-real-video](https://github.com/HUANGCHIHHUNGLeo/claude-real-video) by LeoAido | scene frames + dedup, speaker diarization, link fetch; the footage-memory and no-speech-gate ideas | MIT | isolated venv (`vedit setup crv`), subprocess |
| [blader/humanizer](https://github.com/blader/humanizer) | the pattern list behind `vedit text check` | MIT | ideas only; our own wording and code |
| Wikipedia: [Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing) (WikiProject AI Cleanup) | the same | CC BY-SA 4.0 | ideas only |
| [ffmpeg-skill](https://github.com/kajisho5/ffmpeg-skill) by kajisho5 | HDR/Log/VFR detection and tone-mapping approach, device notes, the platform table design (checks, presets, safe zones), clean-up and time FX filter choices, drift-corrected sync, dynamics, batch/report ideas, the end-of-job report and never-overwrite rules | MIT | ported into vedit's own modules (footage, delivery, fx, audiotools, extras); no code vendored |
| [LosslessCut](https://github.com/mifi/lossless-cut) | smart-cut approach, `.llc` format, HTTP API | GPL-2.0 | interoperability only: no code copied; the app is a separate optional install |
| [OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) + FCP XML, FCPX XML, CMX 3600 adapters (ASWF) and the [Kdenlive adapter](https://invent.kde.org/multimedia/kdenlive-opentimelineio) (KDE) | Premiere XML, OTIO, EDL, Kdenlive hand-offs and reading re-exports | Apache-2.0 / MIT | isolated venv (`vedit setup otio`), subprocess |
| [lxml](https://lxml.de) | FCPXML DTD validation | BSD-3 | inside the otio venv |
| Apple FCPXML 1.10 DTD | validating our FCPXML | Apple | not redistributed: read from the owner's Final Cut Pro or a local copy |
| [samuelgursky/davinci-resolve-mcp](https://github.com/samuelgursky/davinci-resolve-mcp) | Resolve scripting paths and import flow (reference) | MIT | ideas only; suggested to the owner as an interactive option |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | downloading linked videos | Unlicense | inside claude-real-video's venv |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), pyannote segmentation 3.0, 3D-Speaker ERes2Net | speaker diarization models | Apache-2.0 / MIT | downloaded on first use (asked) |
| [OpenCV Zoo YuNet](https://github.com/opencv/opencv_zoo) | face detection | MIT | downloaded on first use |
| [OpenCV Zoo VitTrack](https://github.com/opencv/opencv_zoo/tree/main/models/object_tracking_vittrack) | object tracking (with OpenCV optical flow) | Apache-2.0 | downloaded on first use (0.7 MB) |
| [MODNet](https://github.com/ZHKKKe/MODNet) by Ke et al., ONNX export by [Xenova](https://huggingface.co/Xenova/modnet) | person matting (cut-outs, text behind people, background swap) | Apache-2.0 | downloaded when asked (26 MB) |
| [Depth-Anything-V2-Small](https://github.com/DepthAnything/Depth-Anything-V2), ONNX by [onnx-community](https://huggingface.co/onnx-community/depth-anything-v2-small) | depth (3D photos, depth of field); only the Small model (the larger ones are non-commercial) | Apache-2.0 | downloaded when asked (27 MB) |
| [BiRefNet](https://github.com/ZhengPeng7/BiRefNet) lite, ONNX by [onnx-community](https://huggingface.co/onnx-community/BiRefNet_lite-ONNX) | object cut-outs for stills | MIT | optional download (224 MB) |
| [Blender](https://www.blender.org) | optional 3D renders (templates in `blender/`) | GPL (separate app) | run as a subprocess; never bundled |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) 1.13.8 (with espeak-ng) | offline speech synthesis runtime | Apache-2.0 (espeak-ng GPL-3.0 inside) | isolated venv (`vedit setup voice`), subprocess |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) by hexgrad (sherpa-onnx export) | offline voices | Apache-2.0 | downloaded when asked (132 MB) |
| [comprehensive-bangla-tts](https://github.com/mobassir94/comprehensive-bangla-tts) (Coqui VITS, female), trained on the [IIT Madras Indic TTS](https://www.iitm.ac.in/donlab/indictts/) database | offline Bangla voice | MIT code; data under the IIT Madras licence (keep the TTS Consortium / IIT Madras notice) | downloaded when asked (108 MB) |
| [Mimic 3](https://github.com/MycroftAI/mimic3-voices) Bangla voice (Mycroft; CMU Indic + Google OpenSLR 37 data) | offline Bangla voices (16 speakers) | CC BY-SA 4.0 | downloaded when asked (80 MB) |
| [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) by Kyutai (ONNX export by KevinAHM, sherpa-onnx) | voice cloning from a short reference | CC BY 4.0 weights + prohibited-use terms (consent required) | downloaded when asked (98 MB) |
| [OpenVoice V2](https://github.com/myshell-ai/OpenVoice) by MyShell | tone-colour conversion (the owner's voice in any language) | MIT | isolated PyTorch venv (`vedit setup openvoice`), subprocess; the watermark module is not loaded |
| [edge-tts](https://github.com/rany2/edge-tts) | Microsoft Edge online voices | LGPL-3.0 (service terms separate) | isolated venv, subprocess |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / Silero VAD | transcription, no-speech gate | MIT | core dependency |
| [vtracer](https://github.com/visioncortex/vtracer) | icon vectorizing | MIT | isolated venv on first use |
| [animate](https://github.com/cth9191/animate) by cth9191 | the animation kit (seeded hand-drawn lines, cameras, springs, shape-morph renderer, storyboard), the 7 styles, the templates, the 60 s example, the story grammar and craft rules, the synth and loudness stage; ideas for the beat map, the text / dead-beat / arc review, site capture, reference measuring | MIT (`anim/LICENSE-animate`) | adapted into `anim/` (Bangla-safe text, bundled fonts, overlay mode, lazy score scheduling, vedit adapter); the tools rebuilt in vedit (Python beat map, renderer passes, QA checks) |
| [GSAP](https://gsap.com), [three.js](https://threejs.org), [lottie-web](https://github.com/airbnb/lottie-web) | motion graphics runtime | GSAP standard licence (free), MIT, MIT | loaded from CDNs / npm |
| Google Fonts families in `setup.py` | caption and graphics fonts | OFL / Apache-2.0 | downloaded by `vedit setup` |
| [Openverse](https://openverse.org), [Wikimedia Commons](https://commons.wikimedia.org), [Pexels](https://www.pexels.com/api/), [Pixabay](https://pixabay.com/api/docs/) | asset search | per item (logged) | public APIs |
