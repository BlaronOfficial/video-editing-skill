// Small DOM and math helpers shared by every Studio module.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// h("div", {class: "x", onclick: fn, style: {left: "3px"}}, child, "text")
export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === undefined || kid === null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
export const lerp = (a, b, t) => a + (b - a) * t;
export const round = (v, n = 3) => Math.round(v * 10 ** n) / 10 ** n;
export const isBangla = (s) => /[ঀ-৿]/.test(s || "");
export const clone = (o) => (o === undefined ? o : JSON.parse(JSON.stringify(o)));

// Timecode m:ss.ff (frames) - what editors read; tabular digits in CSS keep it steady.
export function tc(t, fps = 30) {
  t = Math.max(0, t || 0);
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  const f = Math.floor((t % 1) * fps);
  return `${m}:${String(s).padStart(2, "0")}.${String(f).padStart(2, "0")}`;
}

export function secs(t) {
  return `${(t || 0).toFixed(t >= 10 ? 1 : 2)} s`;
}

export function debounce(fn, ms) {
  let id;
  return (...args) => {
    clearTimeout(id);
    id = setTimeout(() => fn(...args), ms);
  };
}

export class Emitter {
  constructor() { this._h = {}; }
  on(name, fn) { (this._h[name] ||= []).push(fn); return () => this.off(name, fn); }
  off(name, fn) { this._h[name] = (this._h[name] || []).filter((f) => f !== fn); }
  emit(name, ...args) { for (const fn of this._h[name] || []) { try { fn(...args); } catch (e) { console.error(e); } } }
}

let _n = 0;
export const uid = (prefix = "id") => `${prefix}_${Date.now().toString(36)}${(_n++).toString(36)}`;

export function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem(`vedit.${key}`) ?? "null");
    localStorage.setItem(`vedit.${key}`, JSON.stringify(value));
  } catch { /* private window or blocked storage: conveniences only */ }
  return value;
}

// Easing used by zooms, mirroring render._ease_expr.
export function ease(p, kind) {
  p = clamp(p, 0, 1);
  switch (kind) {
    case "linear": return p;
    case "in": return p * p;
    case "out": return 1 - (1 - p) * (1 - p);
    case "inout": return p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
    case "hold": return 1;
    default: return 1 - (1 - p) * (1 - p);
  }
}

export function toast(msg, kind = "info", ms = 3200) {
  let host = document.getElementById("toasts");
  if (!host) {
    host = h("div", { id: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(host);
  }
  const el = h("div", { class: `toast ${kind}` }, msg);
  host.append(el);
  setTimeout(() => el.remove(), ms);
}
