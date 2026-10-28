// Live captions in HTML, matching captions.to_ass(): centre at (W/2, H/2 - y*H/2), size = style.size *
// min(W, H), outline = stroke_width * size, karaoke highlight + pop on the active word, emphasis colour,
// intro animation (pop / fade / slide), background box. Bangla uses font_bangla and is never uppercased.

import { h, isBangla } from "./util.js";
import { chunkAt } from "./bake.js";

const WEIGHTS = { thin: 100, extralight: 200, light: 300, regular: 400, book: 400, medium: 500, semibold: 600,
                  bold: 700, extrabold: 800, black: 900, heavy: 900 };

export function fontFor(name) {
  // "Poppins ExtraBold" -> {family: "Poppins", weight: 800}; "Hind Siliguri SemiBold" -> 600
  const parts = String(name || "Poppins").trim().split(/\s+/);
  const last = parts[parts.length - 1].toLowerCase();
  if (parts.length > 1 && WEIGHTS[last]) return { family: parts.slice(0, -1).join(" "), weight: WEIGHTS[last] };
  return { family: parts.join(" "), weight: null };
}

const cssColor = (hex, alpha) => {
  const s = String(hex || "#000000").replace("#", "");
  const r = parseInt(s.slice(0, 2), 16), g = parseInt(s.slice(2, 4), 16), b = parseInt(s.slice(4, 6), 16);
  let a = s.length >= 8 ? parseInt(s.slice(6, 8), 16) / 255 : 1;
  if (alpha !== undefined) a = alpha;
  return `rgba(${r},${g},${b},${a})`;
};

export class CaptionLayer {
  constructor(layer) {
    this.layer = layer;
    this.key = null;
    this.box = null;
  }

  render(baked, t, scale) {
    const cap = baked.captions || {};
    if (!cap.enabled) return this.clear();
    const chunk = chunkAt(cap.chunks, t);
    if (!chunk) return this.clear();
    const style = baked._style || {};
    const W = baked.canvas.width, H = baked.canvas.height;
    const base = Math.min(W, H);
    const fontPx = Math.max(12, style.size * base);
    const bn = isBangla(chunk.text);
    const font = fontFor(bn ? style.font_bangla : style.font);
    const key = `${chunk.start}|${chunk.text}|${scale.toFixed(4)}|${JSON.stringify(style).length}`;
    if (key !== this.key) this.build(chunk, style, W, H, fontPx, font, bn, scale, key);
    this.animate(chunk, style, t, fontPx, scale);
  }

  build(chunk, style, W, H, fontPx, font, bn, scale, key) {
    this.clear();
    this.key = key;
    const landscape = W > H;
    const yUnits = chunk.y ?? (landscape ? style.y_landscape ?? style.y : style.y) ?? -0.42;
    const cy = H / 2 - yUnits * (H / 2);
    const outline = style.stroke ? style.stroke_width * fontPx : 0;
    const shadow = (style.shadow || 0) * fontPx;
    const words = chunk.words?.length ? chunk.words : chunk.text.split(" ").map((w) => ({ w, s: chunk.start, e: chunk.end }));
    const upper = style.uppercase && !bn;
    const box = h("div", { class: "cap-box" });
    Object.assign(box.style, {
      left: `${(W / 2) * scale}px`, top: `${cy * scale}px`, maxWidth: `${(W - 80) * scale}px`,
      fontFamily: `"${font.family}", "Hind Siliguri", "Noto Sans Bengali", sans-serif`,
      fontWeight: String(font.weight ?? (style.bold ? 700 : 400)), fontSize: `${fontPx * scale}px`,
      color: style.color || "#FFFFFF", letterSpacing: `${(style.letter_spacing || 0) * scale}px`,
    });
    if (style.background) {
      box.style.background = cssColor(style.background.color, style.background.alpha ?? 0.6);
      box.style.padding = `${fontPx * 0.12 * scale}px ${fontPx * 0.3 * scale}px`;
      box.style.borderRadius = `${fontPx * 0.12 * scale}px`;
    } else if (outline) {
      box.style.webkitTextStroke = `${outline * 2 * scale}px ${cssColor(style.stroke)}`;
      box.style.paintOrder = "stroke fill";
    }
    if (shadow) box.style.textShadow = `${shadow * scale}px ${shadow * scale}px 0 ${cssColor(style.shadow_color || "#000000AA")}`;
    const emph = new Set(chunk.emphasis || []);
    this.spans = words.map((w, i) => {
      const span = h("span", { class: "cap-word" }, upper ? w.w.toUpperCase() : w.w);
      if (emph.has(i)) span.style.color = style.highlight;
      return span;
    });
    this.spans.forEach((s, i) => { if (i) box.append(" "); box.append(s); });
    if (chunk.emoji) box.append(" ", h("span", { class: "cap-emoji" }, chunk.emoji));
    this.words = words;
    this.box = box;
    this.layer.append(box);
  }

  animate(chunk, style, t, fontPx, scale) {
    if (!this.box) return;
    const mode = style.mode || "karaoke";
    const since = t - chunk.start;
    const anim = style.animation || "pop";
    let s = 1, a = 1;
    if (mode === "sentence") {
      a = Math.min(1, since / 0.1, Math.max(0, (chunk.end - t) / 0.1));
    } else if (anim === "pop") {
      s = since < 0.09 ? 0.7 + 0.3 * (since / 0.09) : 1;
    } else if (anim === "fade") {
      a = Math.min(1, since / 0.12);
    } else if (anim === "slide") {
      a = Math.min(1, since / 0.12);
    }
    this.box.style.transform = `translate(-50%, -50%) scale(${s})`;
    this.box.style.opacity = String(a);
    if (mode === "karaoke" || mode === "word") {
      let active = 0;
      this.words.forEach((w, i) => { if (w.s <= t) active = i; });
      const emph = new Set(chunk.emphasis || []);
      const pop = style.pop_scale || 1.1;
      this.spans.forEach((span, i) => {
        const on = i === active;
        span.style.color = on || emph.has(i) ? style.highlight : style.color || "#FFFFFF";
        // font-size (not transform) so the line reflows around the bigger word, as libass does with scx
        span.style.fontSize = on && mode === "karaoke" ? `${pop}em` : "1em";
      });
    }
  }

  clear() {
    if (this.box) this.box.remove();
    this.box = null;
    this.key = null;
    this.spans = [];
  }
}
