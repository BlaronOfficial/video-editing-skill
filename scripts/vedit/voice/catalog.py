"""Every voice vedit can speak with, and what each is allowed for.

Backends
  kokoro     offline neural voices (sherpa-onnx, Kokoro-82M v1.0, Apache-2.0): English US/UK + 7 languages
  bn_coqui   offline Bangla, female (VITS, comprehensive-bangla-tts / Coqui; trained on IIT Madras Indic TTS)
  bn_mimic3  offline Bangla, multi-speaker (Mimic 3 voice, CC BY-SA 4.0: credit, share-alike for the model)
  edge       Microsoft Edge online voices via edge-tts (LGPL tool in its own venv; the service's terms for
             commercial use are unclear: flagged)
  pocket     offline voice cloning from a short reference clip (Kyutai Pocket TTS, CC-BY-4.0: credit Kyutai)
  openvoice  converts any voice track to a reference voice's timbre (OpenVoice V2, MIT; PyTorch CPU venv)
  eleven     ElevenLabs (paid, key in personal/secrets), multilingual incl. Bangla, instant clones

`commercial`: "yes" | "credit" (allowed with attribution) | "verify" (looks permissive, confirm before paid
work) | "unclear" | "no".
"""

from __future__ import annotations

from .. import models

# ------------------------------------------------------------------ models (asked before download)

for _m in [
    models.Model("kokoro_multi", "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
                 "kokoro-int8-multi-lang-v1_0.tar.bz2", 132.4, "Apache-2.0 (Kokoro-82M v1.0 by hexgrad; sherpa-onnx export)",
                 "offline voices: English US/UK, Hindi, Spanish, French, Italian, Japanese, Portuguese, Chinese",
                 "voice/kokoro-int8-multi-lang-v1_0.tar.bz2", archive="tar.bz2",
                 extracted="voice/kokoro-int8-multi-lang-v1_0"),
    # full-precision weights for the same Kokoro voices: the int8 model ran ~2.7x slower than real time here
    models.Model("kokoro_fp32", "https://huggingface.co/csukuangfj/kokoro-multi-lang-v1_0/resolve/main/model.onnx", 325.6,
                 "Apache-2.0 (Kokoro-82M v1.0; sherpa-onnx export)", "faster offline voices (same voices as kokoro_multi)",
                 "voice/kokoro-fp32/model.onnx"),
    models.Model("bn_coqui", "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
                 "vits-coqui-bn-custom_female.tar.bz2", 108.1,
                 "MIT code (comprehensive-bangla-tts); trained on IIT Madras Indic TTS (EULA: royalty-free, keep the "
                 "TTS Consortium / IIT Madras notice)", "offline Bangla narration (female)",
                 "voice/vits-coqui-bn-custom_female.tar.bz2", archive="tar.bz2",
                 extracted="voice/vits-coqui-bn-custom_female"),
    models.Model("bn_mimic3", "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
                 "vits-mimic3-bn-multi_low.tar.bz2", 79.9, "CC BY-SA 4.0 (Mimic 3 voice; CMU Indic + Google OpenSLR 37)",
                 "offline Bangla narration (several speakers)", "voice/vits-mimic3-bn-multi_low.tar.bz2",
                 archive="tar.bz2", extracted="voice/vits-mimic3-bn-multi_low"),
    models.Model("pocket_tts", "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
                 "sherpa-onnx-pocket-tts-int8-2026-01-26.tar.bz2", 98.3,
                 "CC BY 4.0 weights (Kyutai Pocket TTS, credit Kyutai; cloning only with consent)",
                 "offline voice cloning (English)",
                 "voice/sherpa-onnx-pocket-tts-int8-2026-01-26.tar.bz2", archive="tar.bz2",
                 extracted="voice/sherpa-onnx-pocket-tts-int8-2026-01-26"),
    models.Model("openvoice_v2", "https://huggingface.co/myshell-ai/OpenVoiceV2/resolve/main/converter/checkpoint.pth",
                 131.3, "MIT (OpenVoice V2, MyShell)", "voice conversion to a reference timbre (any language)",
                 "voice/openvoice_v2/converter/checkpoint.pth"),
    models.Model("openvoice_v2_config", "https://huggingface.co/myshell-ai/OpenVoiceV2/resolve/main/converter/config.json",
                 0.01, "MIT (OpenVoice V2, MyShell)", "voice conversion config", "voice/openvoice_v2/converter/config.json"),
]:
    models.register(_m)

# ------------------------------------------------------------------ voices

# Kokoro v1.0 speaker ids (sherpa-onnx kokoro-multi-lang-v1_0): name -> (sid, language, gender)
KOKORO = {
    "af_alloy": (0, "en-us", "f"), "af_aoede": (1, "en-us", "f"), "af_bella": (2, "en-us", "f"), "af_heart": (3, "en-us", "f"),
    "af_jessica": (4, "en-us", "f"), "af_kore": (5, "en-us", "f"), "af_nicole": (6, "en-us", "f"), "af_nova": (7, "en-us", "f"),
    "af_river": (8, "en-us", "f"), "af_sarah": (9, "en-us", "f"), "af_sky": (10, "en-us", "f"), "am_adam": (11, "en-us", "m"),
    "am_echo": (12, "en-us", "m"), "am_eric": (13, "en-us", "m"), "am_fenrir": (14, "en-us", "m"), "am_liam": (15, "en-us", "m"),
    "am_michael": (16, "en-us", "m"), "am_onyx": (17, "en-us", "m"), "am_puck": (18, "en-us", "m"), "am_santa": (19, "en-us", "m"),
    "bf_alice": (20, "en-gb", "f"), "bf_emma": (21, "en-gb", "f"), "bf_isabella": (22, "en-gb", "f"), "bf_lily": (23, "en-gb", "f"),
    "bm_daniel": (24, "en-gb", "m"), "bm_fable": (25, "en-gb", "m"), "bm_george": (26, "en-gb", "m"), "bm_lewis": (27, "en-gb", "m"),
    "ef_dora": (28, "es", "f"), "em_alex": (29, "es", "m"), "ff_siwis": (30, "fr", "f"), "hf_alpha": (31, "hi", "f"),
    "hf_beta": (32, "hi", "f"), "hm_omega": (33, "hi", "m"), "hm_psi": (34, "hi", "m"), "if_sara": (35, "it", "f"),
    "im_nicola": (36, "it", "m"), "jf_alpha": (37, "ja", "f"), "jf_gongitsune": (38, "ja", "f"), "jf_nezumi": (39, "ja", "f"),
    "jf_tebukuro": (40, "ja", "f"), "jm_kumo": (41, "ja", "m"), "pf_dora": (42, "pt-br", "f"), "pm_alex": (43, "pt-br", "m"),
    "pm_santa": (44, "pt-br", "m"), "zf_xiaobei": (45, "zh", "f"), "zf_xiaoni": (46, "zh", "f"), "zf_xiaoxiao": (47, "zh", "f"),
    "zf_xiaoyi": (48, "zh", "f"), "zm_yunjian": (49, "zh", "m"), "zm_yunxi": (50, "zh", "m"), "zm_yunxia": (51, "zh", "m"),
    "zm_yunyang": (52, "zh", "m"), "em_santa": (53, "es", "m"),
}

EDGE_BN = {"bn-BD-NabanitaNeural": ("bn", "f"), "bn-BD-PradeepNeural": ("bn", "m"),
           "bn-IN-TanishaaNeural": ("bn", "f"), "bn-IN-BashkarNeural": ("bn", "m")}
EDGE_EN = {"en-US-AvaNeural": ("en", "f"), "en-US-AndrewNeural": ("en", "m"), "en-US-EmmaNeural": ("en", "f"),
           "en-US-BrianNeural": ("en", "m"), "en-GB-SoniaNeural": ("en", "f"), "en-GB-RyanNeural": ("en", "m"),
           "en-IN-NeerjaNeural": ("en", "f"), "en-IN-PrabhatNeural": ("en", "m")}

LICENCE = {
    "kokoro": ("Apache-2.0", "yes", False),
    "bn_coqui": ("MIT code; IIT Madras Indic TTS data (royalty-free EULA, keep its notice)", "verify", False),
    "bn_mimic3": ("CC BY-SA 4.0 (Mimic 3)", "credit", False),
    "edge": ("Microsoft Edge read-aloud service via edge-tts (LGPL); service terms unclear for commercial use", "unclear", True),
    # the model card and LICENSE say CC BY 4.0 (+ Kyutai's prohibited uses: no cloning without consent, no
    # deception), but sherpa-onnx's README for this export says "for non-commercial": verify before paid work
    "pocket": ("CC BY 4.0 (Kyutai Pocket TTS, credit Kyutai) + consent-only cloning; sherpa-onnx's note says "
               "non-commercial: verify before paid work", "verify", False),
    "openvoice": ("MIT (OpenVoice V2)", "yes", False),
    "eleven": ("ElevenLabs plan terms (paid plans allow commercial use)", "yes", True),
}

MODEL_OF = {"kokoro": "kokoro_multi", "bn_coqui": "bn_coqui", "bn_mimic3": "bn_mimic3", "pocket": "pocket_tts"}


def builtin() -> list[dict]:
    rows = []
    for name, (sid, lang, g) in KOKORO.items():
        rows.append({"id": f"kokoro:{name}", "backend": "kokoro", "language": lang.split("-")[0], "accent": lang,
                     "gender": g, "sid": sid})
    rows.append({"id": "bn_coqui:female", "backend": "bn_coqui", "language": "bn", "gender": "f", "sid": 0})
    for sid in range(16):       # mimic3 bn multi_low: 16 speakers
        rows.append({"id": f"bn_mimic3:{sid}", "backend": "bn_mimic3", "language": "bn", "gender": "?", "sid": sid})
    for name, (lang, g) in {**EDGE_BN, **EDGE_EN}.items():
        rows.append({"id": f"edge:{name}", "backend": "edge", "language": lang, "accent": name[:5], "gender": g})
    for r in rows:
        lic, com, online = LICENCE[r["backend"]]
        r.update({"licence": lic, "commercial": com, "online": online, "model": MODEL_OF.get(r["backend"])})
    return rows
