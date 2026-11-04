#!/usr/bin/env node
// Capture the owner's own product for an animated product reel: a page, a part of it, or the logo.
//   usage: node capture.mjs --url <url> --out <png> [--width 1280] [--height 800] [--scale 2] [--selector "css"]
//                           [--full] [--wait 1500] [--dark] [--hide "css, css"] [--chrome path]
//   --selector  just that element (a hero section, a pricing card, the logo: e.g. "header img")
//   --full      the whole scrolling page      --dark  prefers-color-scheme: dark
//   --hide      elements to hide first (cookie banners, chat bubbles)
// A fresh headless profile: no cookies, no sign-ins, nothing typed. Only for sites the owner owns or may show.
// Adapted from animate's tools/capture.mjs (MIT, (c) 2026 cth9191), on vedit's puppeteer-core + system Chrome.
import fs from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer-core";

const argv = process.argv.slice(2), args = {};
for (let i = 0; i < argv.length; i++) {
  if (!argv[i].startsWith("--")) continue;
  const k = argv[i].slice(2), v = argv[i + 1];
  if (v === undefined || v.startsWith("--")) args[k] = true; else { args[k] = v; i++; }
}
if (!args.url || !args.out) { console.error("usage: capture.mjs --url <url> --out <png> [--selector css] [--full] [--dark] [--hide css]"); process.exit(2); }
const pf = process.env.ProgramFiles || "C:\\Program Files", pf86 = process.env["ProgramFiles(x86)"] || "C:\\Program Files (x86)";
const exe = [args.chrome, process.env.VEDIT_CHROME, path.join(pf, "Google/Chrome/Application/chrome.exe"),
  path.join(pf86, "Google/Chrome/Application/chrome.exe"), path.join(process.env.LOCALAPPDATA || "", "Google/Chrome/Application/chrome.exe"),
  path.join(pf86, "Microsoft/Edge/Application/msedge.exe"), path.join(pf, "Microsoft/Edge/Application/msedge.exe"),
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium"].find((c) => c && fs.existsSync(c));
if (!exe) { console.error("No Chrome/Edge found; set VEDIT_CHROME"); process.exit(3); }
const width = Number(args.width || 1280), height = Number(args.height || 800), scale = Number(args.scale || 2), wait = Number(args.wait || 1500);
const browser = await puppeteer.launch({ executablePath: exe, headless: true, args: ["--hide-scrollbars", "--mute-audio"] });
let code = 0;
try {
  const page = await browser.newPage();
  await page.setViewport({ width, height, deviceScaleFactor: scale });
  await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: args.dark ? "dark" : "light" }]);
  await page.goto(args.url, { waitUntil: "networkidle2", timeout: 60000 }).catch(() => page.goto(args.url, { waitUntil: "load", timeout: 60000 }));
  await new Promise((r) => setTimeout(r, wait));
  if (args.hide) await page.addStyleTag({ content: `${args.hide} { visibility: hidden !important; }` });
  const out = path.resolve(args.out);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  if (args.selector) {
    const el = await page.$(args.selector);
    if (!el) throw new Error(`no element matches ${args.selector}`);
    await el.screenshot({ path: out, omitBackground: true });
  } else await page.screenshot({ path: out, fullPage: !!args.full });
  console.log(JSON.stringify({ url: args.url, out, selector: args.selector || null, bytes: fs.statSync(out).size, width, height, scale }));
} catch (e) { console.error(String(e && e.message || e)); code = 1; }
finally { await browser.close().catch(() => {}); }
process.exit(code);
