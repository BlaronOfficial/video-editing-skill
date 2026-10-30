// Live sound: music, SFX and VO scheduled on Web Audio against the playhead, the main video's voice routed
// through gain nodes (levels above 1 work), music ducked under speech like the renderer's sidechain, and a
// limiter on the master. Sound starts only after a click (browser rule), so play() creates the context.

const DUCK_ATTACK = 0.025;
const DUCK_RELEASE = 0.45;

export class AudioMix {
  constructor() {
    this.ctx = null;
    this.buffers = new Map();     // url -> AudioBuffer | Promise
    this.playing = [];
    this.videoNodes = new Map();  // video element -> GainNode
  }

  ensure() {
    if (this.ctx) return this.ctx;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    this.ctx = new Ctx();
    this.master = this.ctx.createGain();
    this.limiter = this.ctx.createDynamicsCompressor();
    this.limiter.threshold.value = -2;
    this.limiter.ratio.value = 20;
    this.limiter.attack.value = 0.002;
    this.limiter.release.value = 0.08;
    this.master.connect(this.limiter).connect(this.ctx.destination);
    return this.ctx;
  }

  attachVideo(video) {
    if (!this.ensure() || this.videoNodes.has(video)) return;
    try {
      const src = this.ctx.createMediaElementSource(video);
      const g = this.ctx.createGain();
      src.connect(g).connect(this.master);
      this.videoNodes.set(video, g);
    } catch { /* cross-origin or already attached: falls back to element volume */ }
  }

  setVideoGain(video, gain) {
    const g = this.videoNodes.get(video);
    if (g) {
      g.gain.setTargetAtTime(gain, this.ctx.currentTime, 0.02);
      video.volume = 1;
    } else {
      video.volume = Math.max(0, Math.min(1, gain));
    }
  }

  async load(url) {
    if (!url) return null;
    if (this.buffers.has(url)) return this.buffers.get(url);
    const p = (async () => {
      if (!this.ensure()) return null;
      const res = await fetch(url);
      const data = await res.arrayBuffer();
      return await this.ctx.decodeAudioData(data);
    })().catch(() => null);
    this.buffers.set(url, p);
    const buf = await p;
    this.buffers.set(url, buf);
    return buf;
  }

  async preload(baked, media) {
    await Promise.all((baked.audio || []).map((a) => this.load(media?.sources?.[a.source]?.audio)));
  }

  stop() {
    for (const n of this.playing) { try { n.src.stop(); } catch { /* already stopped */ } }
    this.playing = [];
  }

  // speech: [[start, end], ...] on the timeline (merged words), used to duck music.
  async play(baked, media, t0, speech) {
    if (!this.ensure()) return;
    if (this.ctx.state === "suspended") await this.ctx.resume();
    this.stop();
    const now = this.ctx.currentTime + 0.05;
    const total = baked._duration || 0;
    const duck = Math.pow(10, (baked.output?.audio?.duck_db ?? -14) / 20);
    for (const a of baked.audio || []) {
      const buf = await this.load(media?.sources?.[a.source]?.audio);
      if (!buf) continue;
      const srcIn = a.src_in || 0;
      const srcOut = a.src_out ?? buf.duration;
      let length = srcOut - srcIn;
      if (a.loop || ["music", "ambience"].includes(a.role || "music")) length = a.loop ? total - a.start : Math.min(length, total - a.start);
      const end = a.start + length;
      if (end <= t0) continue;
      const into = Math.max(0, t0 - a.start);
      const when = now + Math.max(0, a.start - t0);
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      if (a.loop) { src.loop = true; src.loopStart = srcIn; src.loopEnd = srcOut; }
      const g = this.ctx.createGain();
      const vol = a.volume ?? 1;
      g.gain.setValueAtTime(vol, now);
      if (a.fade_in && into < a.fade_in) {
        g.gain.setValueAtTime(vol * (into / a.fade_in), when);
        g.gain.linearRampToValueAtTime(vol, when + (a.fade_in - into));
      }
      if (a.fade_out) {
        const fadeStart = when + Math.max(0, length - a.fade_out - into);
        g.gain.setValueAtTime(vol, fadeStart);
        g.gain.linearRampToValueAtTime(0, when + (length - into));
      }
      const ducks = a.duck ?? ["music", "ambience"].includes(a.role || "music");
      let out = g;
      if (ducks && speech?.length) {
        const d = this.ctx.createGain();
        d.gain.setValueAtTime(1, now);
        for (const [s, e] of speech) {
          if (e < t0 || s > end) continue;
          const at = now + Math.max(0, s - t0);
          const rel = now + Math.max(0, e - t0);
          d.gain.setTargetAtTime(duck, at, DUCK_ATTACK / 3);
          d.gain.setTargetAtTime(1, rel, DUCK_RELEASE / 3);
        }
        g.connect(d);
        out = d;
      }
      if (ducks) {
        // music stop-downs from placed effects (sound.dips): ease down before the hit, back on it
        const dips = musicDips(baked.audio);
        if (dips.length) {
          const sd = this.ctx.createGain();
          sd.gain.setValueAtTime(1, now);
          for (const [s, e, gain] of dips) {
            if (e < t0) continue;
            const at = now + Math.max(0, s - t0);
            sd.gain.setValueAtTime(1, at);
            sd.gain.linearRampToValueAtTime(gain, at + 0.08);
            sd.gain.setValueAtTime(gain, now + Math.max(0, e - t0));
            sd.gain.linearRampToValueAtTime(1, now + Math.max(0, e - t0) + 0.01);
          }
          out.connect(sd);
          out = sd;
        }
      }
      out.connect(this.master);
      src.connect(g);
      src.start(when, (a.loop ? srcIn + (into % Math.max(0.01, srcOut - srcIn)) : srcIn + into), a.loop ? undefined : Math.max(0.01, length - into));
      this.playing.push({ src, gain: g });
    }
  }
}

// Mirror of sound.dips(): [[start, end, gain]] from effects placed with a music stop-down.
export function musicDips(audio) {
  const out = [];
  for (const a of audio || []) {
    const d = a.sfx?.dip;
    if (!d || a.enabled === false) continue;
    const hit = a.start + (a.sfx.sync_s || 0) - (a.sfx.offset_ms || 0) / 1000;
    if (hit <= 0.05) continue;
    out.push([Math.max(0, hit - (d.length_s ?? 0.4)), hit, Math.pow(10, -(d.depth_db ?? 9) / 20)]);
  }
  return out.sort((x, y) => x[0] - y[0]);
}

// Merge kept words into speech intervals on the timeline (gaps under 0.3 s join).
export function speechIntervals(chunks) {
  const out = [];
  for (const c of chunks || []) {
    for (const w of c.words || []) {
      const last = out[out.length - 1];
      if (last && w.s - last[1] < 0.3) last[1] = Math.max(last[1], w.e);
      else out.push([w.s, w.e]);
    }
  }
  return out;
}
