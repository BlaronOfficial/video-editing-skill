# Attributions

vedit is MIT-licensed. It builds on these projects; their licences apply to their code and data.

| Project | Used for | Licence | How |
|---|---|---|---|
| [earshot](https://github.com/Leonxlnx/earshot) by Leon Lin | sound kits (252 code-made sounds with measured sync points), kit mix rules, listening (timeline, sheet, critique) | MIT | installed into an isolated venv (`vedit setup earshot`), called as a subprocess; never vendored |
| [claude-real-video](https://github.com/HUANGCHIHHUNGLeo/claude-real-video) by LeoAido | scene frames + dedup, speaker diarization, link fetch; the footage-memory and no-speech-gate ideas | MIT | isolated venv (`vedit setup crv`), subprocess |
| [blader/humanizer](https://github.com/blader/humanizer) | the pattern list behind `vedit text check` | MIT | ideas only; our own wording and code |
| Wikipedia: [Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing) (WikiProject AI Cleanup) | the same | CC BY-SA 4.0 | ideas only |
| [LosslessCut](https://github.com/mifi/lossless-cut) | smart-cut approach, `.llc` format (phase 3) | GPL-2.0 | interoperability only: no code copied |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | downloading linked videos | Unlicense | inside claude-real-video's venv |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), pyannote segmentation 3.0, 3D-Speaker ERes2Net | speaker diarization models | Apache-2.0 / MIT | downloaded on first use (asked) |
| [OpenCV Zoo YuNet](https://github.com/opencv/opencv_zoo) | face detection | MIT | downloaded on first use |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / Silero VAD | transcription, no-speech gate | MIT | core dependency |
| [vtracer](https://github.com/visioncortex/vtracer) | icon vectorizing | MIT | isolated venv on first use |
| [GSAP](https://gsap.com), [three.js](https://threejs.org), [lottie-web](https://github.com/airbnb/lottie-web) | motion graphics runtime | GSAP standard licence (free), MIT, MIT | loaded from CDNs / npm |
| Google Fonts families in `setup.py` | caption and graphics fonts | OFL / Apache-2.0 | downloaded by `vedit setup` |
| [Openverse](https://openverse.org), [Wikimedia Commons](https://commons.wikimedia.org), [Pexels](https://www.pexels.com/api/), [Pixabay](https://pixabay.com/api/docs/) | asset search | per item (logged) | public APIs |
