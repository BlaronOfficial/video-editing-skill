"""Runs inside the OpenVoice tool venv (PyTorch CPU + OpenVoice V2, MIT; never imported by vedit).

    python -I openvoice_bridge.py <command> <request.json> <result.json>

Only the tone-color converter is used: it moves any speech (an Edge Bangla voice, Kokoro, a recording) to the
timbre of a reference voice. The converter code paths mirror openvoice/api.py ToneColorConverter (MIT,
MyShell); the optional audio watermark (wavmark) is not loaded.

se:       {"config", "ckpt", "wavs": [wav], "out": .npy} -> {"out", "frames"}   mean speaker embedding
convert:  {"config", "ckpt", "src": [wav], "outs": [wav], "tgt_se": .npy, "src_se": .npy|null, "tau": 0.3}
          -> [{"out", "sample_rate", "duration"}]; without src_se each source's own embedding is used
"""

import json
import sys
import wave

import numpy as np


def _load(req):
    import torch
    from openvoice import utils
    from openvoice.models import SynthesizerTrn
    torch.set_num_threads(int(req.get("threads") or 8))
    hps = utils.get_hparams_from_file(req["config"])
    model = SynthesizerTrn(len(getattr(hps, "symbols", [])), hps.data.filter_length // 2 + 1,
                           n_speakers=hps.data.n_speakers, **hps.model).to("cpu")
    model.eval()
    ckpt = torch.load(req["ckpt"], map_location="cpu")
    model.load_state_dict(ckpt["model"], strict=False)
    return hps, model


def _spec(path, hps):
    import librosa
    import torch
    from openvoice.mel_processing import spectrogram_torch
    audio, _ = librosa.load(path, sr=hps.data.sampling_rate)
    y = torch.FloatTensor(audio).unsqueeze(0)
    return spectrogram_torch(y, hps.data.filter_length, hps.data.sampling_rate, hps.data.hop_length,
                             hps.data.win_length, center=False)


def _se(model, hps, wavs):
    import torch
    gs = []
    frames = 0
    for p in wavs:
        spec = _spec(p, hps)
        frames += spec.shape[-1]
        with torch.no_grad():
            gs.append(model.ref_enc(spec.transpose(1, 2)).unsqueeze(-1).detach())
    return torch.stack(gs).mean(0), frames


def se(req):
    hps, model = _load(req)
    g, frames = _se(model, hps, req["wavs"])
    np.save(req["out"], g.numpy())
    return {"out": req["out"], "frames": int(frames)}


def convert(req):
    import torch
    hps, model = _load(req)
    tgt = torch.from_numpy(np.load(req["tgt_se"]))
    fixed_src = torch.from_numpy(np.load(req["src_se"])) if req.get("src_se") else None
    out = []
    for src, path in zip(req["src"], req["outs"]):
        spec = _spec(src, hps)
        src_se = fixed_src if fixed_src is not None else _se(model, hps, [src])[0]
        with torch.no_grad():
            lengths = torch.LongTensor([spec.size(-1)])
            audio = model.voice_conversion(spec, lengths, sid_src=src_se, sid_tgt=tgt,
                                           tau=float(req.get("tau", 0.3)))[0][0, 0].data.cpu().float().numpy()
        x = np.clip(audio, -1.0, 1.0)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(hps.data.sampling_rate)
            w.writeframes((x * 32767.0).astype(np.int16).tobytes())
        out.append({"out": path, "sample_rate": hps.data.sampling_rate, "duration": len(x) / hps.data.sampling_rate})
    return out


if __name__ == "__main__":
    cmd, req_path, res_path = sys.argv[1:4]
    with open(req_path, encoding="utf-8") as f:
        req = json.load(f)
    res = {"se": se, "convert": convert}[cmd](req)
    with open(res_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
