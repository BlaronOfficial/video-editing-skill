  // =====================================================================
  //  kit/score-tail.js — render, fold the tail over the loop point, loudness stage
  //  (RMS-normalise to -17 dBFS, look-ahead limiter at -1 dBFS; stems share the mix gain curve)
  // =====================================================================
  // vedit: create the queued notes window by window (score-head's lazy scheduling); a note's nodes exist from
  // ~0.75-2.75 s before it sounds. A call made while flushing (sub -> noiseHit) runs in the same window.
  const WIN = 2.0, LEAD = 0.75;
  const flush = (end) => {
    for (;;) {
      const now = [], later = [];
      for (const q of _Q) (q[0] < end ? now : later).push(q);
      if (!now.length) return;
      _Q.length = 0; _Q.push(...later);
      for (const [, f] of now) f();
    }
  };
  flush(WIN + LEAD);
  for (let w = WIN; w < len / sampleRate - 0.01; w += WIN) {
    const at = w;
    ac.suspend(at).then(() => { flush(at + WIN + LEAD); ac.resume(); });
  }
  const buf = await ac.startRendering();
  const c0 = buf.getChannelData(0), c1 = buf.getChannelData(1);
  let N, L, Rr;
  if (typeof LOOP_AUDIO === 'undefined' || LOOP_AUDIO) {
    // fold the tail over the loop point so the loop is seamless
    N = Math.round(LOOP_T * sampleRate); L = new Float32Array(N); Rr = new Float32Array(N);
    for (let i = 0; i < N; i++) { L[i] = c0[i] + (i + N < len ? c0[i + N] : 0); Rr[i] = c1[i] + (i + N < len ? c1[i + N] : 0); }
  } else {
    // vedit: a piece placed in an edit doesn't loop: keep the ring-out after the end (trailing silence trimmed),
    // so the start never carries the end's reverb. The same length for every part, so stems still sum to the mix.
    const end = Math.round(LOOP_T * sampleRate);
    N = normIn?.n ?? (() => { let k = len - 1; while (k > end && Math.abs(c0[k]) < 0.001 && Math.abs(c1[k]) < 0.001) k--; return Math.min(len, k + Math.round(0.05 * sampleRate)); })();
    L = c0.slice(0, N); Rr = c1.slice(0, N);
    const fade = Math.min(Math.round(0.05 * sampleRate), N - end);
    for (let i = 0; i < fade; i++) { const k = N - fade + i, v = 1 - i / fade; L[k] *= v; Rr[k] *= v; }
  }
  // loudness for a phone (subagents-short): RMS-normalise to -17 dBFS, then a look-ahead limiter at -1 dBFS.
  // Stems reuse the mix's gain and gain curve, so they sum back to the mix.
  let k = normIn?.k, g = normIn?.g;
  if (!g) {
    let sum = 0; for (let i = 0; i < N; i++) sum += (L[i] * L[i] + Rr[i] * Rr[i]) / 2;
    k = 10 ** (-17 / 20) / Math.sqrt(sum / N || 1e-12);
    const ceil = 0.89; g = new Float32Array(N);
    for (let i = 0; i < N; i++) { const p = Math.max(Math.abs(L[i]), Math.abs(Rr[i])) * k; g[i] = p > ceil ? ceil / p : 1; }
    const att = Math.exp(-1 / (0.0015 * sampleRate)), rel = Math.exp(-1 / (0.09 * sampleRate));
    for (let i = N - 2; i >= 0; i--) g[i] = Math.min(g[i], 1 - (1 - g[i + 1]) * att);
    let r = 1; for (let i = 0; i < N; i++) { r = Math.min(g[i], 1 - (1 - r) * rel); g[i] = r; }
  }
  for (let i = 0; i < N; i++) { L[i] *= k * g[i]; Rr[i] *= k * g[i]; }
  return { left: L, right: Rr, sampleRate, norm: { k, g, n: N } };
}
function wavB64(s) {
  const bytes = encodeWav(s.left, s.right, s.sampleRate);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}
async function renderAudioWav() { return wavB64(await buildScore(48000, 'mix')); }
async function renderAudioStems() {
  const mix = await buildScore(48000, 'mix');
  const music = await buildScore(48000, 'music', mix.norm), sfx = await buildScore(48000, 'sfx', mix.norm);
  return { music: wavB64(music), sfx: wavB64(sfx) };
}
// vedit: the mix and the stems asked for (the mix is rendered once; the stems reuse its gain curve). Each part is
// a full offline render, so ask only for what is used (an edit's score needs the mix alone).
async function renderAudioAll(parts = ['mix', 'music', 'sfx']) {
  const mix = await buildScore(48000, 'mix'), out = {};
  if (parts.includes('mix')) out.mix = wavB64(mix);
  if (parts.includes('music')) out.music = wavB64(await buildScore(48000, 'music', mix.norm));
  if (parts.includes('sfx')) out.sfx = wavB64(await buildScore(48000, 'sfx', mix.norm));
  return out;
}
window.renderAudioWav = renderAudioWav;
window.renderAudioStems = renderAudioStems;
window.renderAudioAll = renderAudioAll;
</script>
</body>
</html>
