// Helpers shared by motion-graphics compositions. Load after gsap:
//   <script src="/__vendor/gsap.min.js"></script><script src="/__mg/vedit.js"></script>
(function () {
  const V = {};

  // Template data with defaults: V.data({title: "Hello"}) merges window.__VEDIT_DATA__ over the defaults.
  V.data = (defaults = {}) => Object.assign({}, defaults, window.__VEDIT_DATA__ || {});

  V.isBangla = (s) => /[ঀ-৿]/.test(s || "");

  // Split text into word (and optionally char) spans for staggered animation. Bangla is split by
  // word only: splitting grapheme clusters into chars would break conjuncts.
  V.split = (el, { chars = false } = {}) => {
    const text = el.textContent;
    el.textContent = "";
    const words = [];
    text.split(/(\s+)/).forEach((tok) => {
      if (/^\s+$/.test(tok)) { el.appendChild(document.createTextNode(tok)); return; }
      const w = document.createElement("span");
      w.className = "word" + (V.isBangla(tok) ? " bn" : "");
      if (chars && !V.isBangla(tok)) {
        for (const ch of Array.from(tok)) {
          const c = document.createElement("span");
          c.className = "char";
          c.textContent = ch;
          w.appendChild(c);
        }
      } else {
        w.textContent = tok;
      }
      el.appendChild(w);
      words.push(w);
    });
    return { words, chars: el.querySelectorAll(".char") };
  };

  // Register a paused timeline with the renderer (HyperFrames-compatible).
  V.timeline = (id = "main", opts = {}) => {
    const tl = gsap.timeline({ paused: true, ...opts });
    window.__timelines = window.__timelines || {};
    window.__timelines[id] = tl;
    if (!window.__VEDIT_RENDERING__) setTimeout(() => tl.play(0), 300);   // live preview in a browser
    return tl;
  };

  // Fit text to a box by shrinking font-size until it no longer overflows.
  V.fit = (el, { max = 200, min = 20, width, height } = {}) => {
    let size = max;
    el.style.fontSize = size + "px";
    const W = width || el.parentElement.clientWidth;
    const H = height || Infinity;
    while (size > min && (el.scrollWidth > W || el.scrollHeight > H)) {
      size -= 2;
      el.style.fontSize = size + "px";
    }
    return size;
  };

  // Seeded random so renders are deterministic frame-to-frame.
  V.rand = (seed = 1) => () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;

  V.eases = { pop: "back.out(2.2)", snap: "expo.out", smooth: "power3.inOut", soft: "sine.inOut", bounce: "elastic.out(1, 0.5)" };

  // Apply brand colors/fonts passed in data.brand = {accent, accent2, ink, paper, font, fontBangla}.
  V.brand = (b = {}) => {
    const r = document.documentElement.style;
    if (b.accent) r.setProperty("--accent", b.accent);
    if (b.accent2) r.setProperty("--accent-2", b.accent2);
    if (b.ink) r.setProperty("--ink", b.ink);
    if (b.paper) r.setProperty("--paper", b.paper);
    if (b.font) r.setProperty("--font-display", `"${b.font}", "Hind Siliguri", sans-serif`);
    if (b.fontBangla) r.setProperty("--font-bangla", `"${b.fontBangla}", sans-serif`);
  };

  if (!window.__VEDIT_RENDERING__) document.addEventListener("DOMContentLoaded", () => document.body.classList.add("preview"));
  window.V = V;
})();
