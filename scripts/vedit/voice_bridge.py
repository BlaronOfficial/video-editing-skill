"""Runs inside the voice tool venv (sherpa-onnx + edge-tts; never imported by vedit).

    python -I voice_bridge.py <command> <request.json> <result.json>

tts:    {"kind": "kokoro"|"vits"|"pocket", "model_dir", "texts": [str], "outs": [wav], "sid", "speed", "lang",
         "reference": wav (pocket), "steps", "threads"} -> [{"out", "sample_rate", "duration"}]
         One model load for every sentence of a voiceover.
edge:   {"voice", "texts": [str], "outs": [mp3], "rate", "pitch"} -> [{"out", "words": [{w, s, e}]}]
         Word boundaries come from the service (offsets in seconds inside each file).
voices: {} -> Edge voice list (online).
embed:  {"model", "wavs": [wav]} -> [[float]] speaker embeddings (3D-Speaker ERes2Net) for similarity checks.
"""

import asyncio
import json
import os
import sys
import wave

import numpy as np


def _read_wav(path):
    with wave.open(path, "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch)[:, 0]
    return x, sr


def _write_wav(path, samples, sr):
    x = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes((x * 32767.0).astype(np.int16).tobytes())


def _first(d, *patterns):
    names = sorted(os.listdir(d))
    for p in patterns:
        for n in names:
            if p(n):
                return os.path.join(d, n)
    return ""


def _model(req):
    import sherpa_onnx as so
    d = req["model_dir"]
    threads = int(req.get("threads") or 4)
    kind = req["kind"]
    if kind == "kokoro":
        model = req.get("model_file") or _first(d, lambda n: n.endswith(".int8.onnx"), lambda n: n.endswith(".onnx"))
        accent = (req.get("lang") or "en-us").lower()
        lex = []
        for name in (("lexicon-gb-en.txt",) if accent == "en-gb" else ("lexicon-us-en.txt",)) + ("lexicon-zh.txt",):
            if os.path.exists(os.path.join(d, name)):
                lex.append(os.path.join(d, name))
        kw = dict(model=model, voices=os.path.join(d, "voices.bin"), tokens=os.path.join(d, "tokens.txt"),
                  data_dir=os.path.join(d, "espeak-ng-data"), lexicon=",".join(lex) if accent.startswith("en") or accent == "zh" else "")
        if os.path.isdir(os.path.join(d, "dict")):
            kw["dict_dir"] = os.path.join(d, "dict")
        if not accent.startswith("en") and accent != "zh":
            kw["lang"] = accent                       # espeak-ng phonemes for es / fr / hi / it / ja / pt
        try:
            cfg = so.OfflineTtsKokoroModelConfig(**kw)
        except TypeError:                             # older bindings without `lang` / `dict_dir`
            kw.pop("lang", None)
            kw.pop("dict_dir", None)
            cfg = so.OfflineTtsKokoroModelConfig(**kw)
        mc = so.OfflineTtsModelConfig(kokoro=cfg, num_threads=threads, provider="cpu")
        fsts = ",".join(os.path.join(d, f) for f in ("phone-zh.fst", "date-zh.fst", "number-zh.fst")
                        if accent == "zh" and os.path.exists(os.path.join(d, f)))
        return so.OfflineTts(so.OfflineTtsConfig(model=mc, rule_fsts=fsts, max_num_sentences=1))
    if kind == "vits":
        model = _first(d, lambda n: n.endswith(".onnx"))
        kw = dict(model=model, tokens=os.path.join(d, "tokens.txt"))
        if os.path.isdir(os.path.join(d, "espeak-ng-data")):
            kw["data_dir"] = os.path.join(d, "espeak-ng-data")
        if os.path.exists(os.path.join(d, "lexicon.txt")):
            kw["lexicon"] = os.path.join(d, "lexicon.txt")
        mc = so.OfflineTtsModelConfig(vits=so.OfflineTtsVitsModelConfig(**kw), num_threads=threads, provider="cpu")
        return so.OfflineTts(so.OfflineTtsConfig(model=mc, max_num_sentences=1))
    if kind == "pocket":
        f = lambda name: os.path.join(d, name)
        pm = so.OfflineTtsPocketModelConfig(lm_flow=f("lm_flow.int8.onnx"), lm_main=f("lm_main.int8.onnx"),
                                            encoder=f("encoder.onnx"), decoder=f("decoder.int8.onnx"),
                                            text_conditioner=f("text_conditioner.onnx"), vocab_json=f("vocab.json"),
                                            token_scores_json=f("token_scores.json"))
        mc = so.OfflineTtsModelConfig(pocket=pm, num_threads=threads, provider="cpu")
        return so.OfflineTts(so.OfflineTtsConfig(model=mc))
    raise ValueError(f"unknown kind {kind}")


def tts(req):
    import sherpa_onnx as so
    engine = _model(req)
    out = []
    ref = None
    if req.get("reference"):
        ref = _read_wav(req["reference"])
    for text, path in zip(req["texts"], req["outs"]):
        gc = so.GenerationConfig()
        gc.sid = int(req.get("sid") or 0)
        gc.speed = float(req.get("speed") or 1.0)
        if ref is not None:
            gc.reference_audio = ref[0]
            gc.reference_sample_rate = ref[1]
            gc.num_steps = int(req.get("steps") or 5)
        audio = engine.generate(text, gc)
        if len(audio.samples) == 0:
            raise RuntimeError(f"no audio generated for: {text[:60]}")
        _write_wav(path, audio.samples, audio.sample_rate)
        out.append({"out": path, "sample_rate": audio.sample_rate, "duration": len(audio.samples) / audio.sample_rate,
                    "num_speakers": getattr(engine, "num_speakers", None)})
    return out


async def _edge_one(text, voice, path, rate, pitch):
    import edge_tts
    words = []
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    with open(path, "wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                s = chunk["offset"] / 1e7
                words.append({"w": chunk["text"], "s": round(s, 3), "e": round(s + chunk["duration"] / 1e7, 3),
                              "kind": chunk["type"]})
    return {"out": path, "words": [w for w in words if w["kind"] == "WordBoundary"] or words}


def edge(req):
    async def go():
        res = []
        for text, path in zip(req["texts"], req["outs"]):
            for attempt in range(3):              # the service drops connections now and then
                try:
                    res.append(await _edge_one(text, req["voice"], path, req.get("rate", "+0%"), req.get("pitch", "+0Hz")))
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1.5 * (attempt + 1))
        return res
    return asyncio.run(go())


def voices(req):
    import edge_tts
    vs = asyncio.run(edge_tts.list_voices())
    return [{"name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"]} for v in vs]


def embed(req):
    import sherpa_onnx as so
    cfg = so.SpeakerEmbeddingExtractorConfig(model=req["model"], num_threads=4, provider="cpu")
    ex = so.SpeakerEmbeddingExtractor(cfg)
    out = []
    for path in req["wavs"]:
        x, sr = _read_wav(path)
        st = ex.create_stream()
        st.accept_waveform(sr, x)
        st.input_finished()
        out.append([float(v) for v in ex.compute(st)])
    return out


if __name__ == "__main__":
    cmd, req_path, res_path = sys.argv[1:4]
    with open(req_path, encoding="utf-8") as f:
        req = json.load(f)
    res = {"tts": tts, "edge": edge, "voices": voices, "embed": embed}[cmd](req)
    with open(res_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
