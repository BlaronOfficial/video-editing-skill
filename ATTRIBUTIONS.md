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
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / Silero VAD | transcription, no-speech gate | MIT | core dependency |
| [vtracer](https://github.com/visioncortex/vtracer) | icon vectorizing | MIT | isolated venv on first use |
| [GSAP](https://gsap.com), [three.js](https://threejs.org), [lottie-web](https://github.com/airbnb/lottie-web) | motion graphics runtime | GSAP standard licence (free), MIT, MIT | loaded from CDNs / npm |
| Google Fonts families in `setup.py` | caption and graphics fonts | OFL / Apache-2.0 | downloaded by `vedit setup` |
| [Openverse](https://openverse.org), [Wikimedia Commons](https://commons.wikimedia.org), [Pexels](https://www.pexels.com/api/), [Pixabay](https://pixabay.com/api/docs/) | asset search | per item (logged) | public APIs |
