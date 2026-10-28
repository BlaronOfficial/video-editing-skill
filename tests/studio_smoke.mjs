// Headless check of the Studio UI against `vedit studio-local` (no claude.ai needed, never the owner's browser).
// usage: node tests/studio_smoke.mjs <url> <out dir> <chrome path>
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, "..", "mg", "renderer", "package.json"));
const puppeteer = require("puppeteer-core");
const [url, out, chrome] = process.argv.slice(2);
mkdirSync(out, { recursive: true });

const browser = await puppeteer.launch({ executablePath: chrome, headless: "new",
  args: ["--autoplay-policy=no-user-gesture-required", "--mute-audio", "--use-angle=swiftshader"] });
const page = await browser.newPage();
const logs = [];
page.on("console", async (m) => {
  if (!["error", "warning"].includes(m.type())) return;
  const parts = await Promise.all(m.args().map((a) => a.evaluate((v) => (v instanceof Error ? v.stack : String(v))).catch(() => "?")));
  logs.push(`${m.type()}: ${parts.join(" ") || m.text()} @ ${m.location()?.url?.split("/").pop() || ""}`);
});
page.on("pageerror", (e) => logs.push(`pageerror: ${e.message}`));
page.on("requestfailed", (r) => logs.push(`requestfailed: ${r.url().slice(0, 120)} ${r.failure()?.errorText}`));
const report = {};
const shot = (name) => page.screenshot({ path: join(out, `${name}.png`) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

await page.setViewport({ width: 1440, height: 900 });
await page.goto(url, { waitUntil: "networkidle2", timeout: 60000 });
await page.waitForFunction(() => document.getElementById("notice")?.hidden === true, { timeout: 30000 }).catch(() => {});
report.loaded = await page.$eval("#notice", (n) => n.hidden);
report.stage = await page.$eval(".stage", (s) => `${s.style.width} x ${s.style.height}`).catch(() => null);
report.timelineItems = await page.$$eval(".tl-item", (a) => a.length);
report.captionChunks = await page.$$eval(".tl-cap", (a) => a.length);
await sleep(2500);
await shot("01_loaded");

// seek to 5 s via the API surface the transport uses (keyboard: End/Home, arrows)
await page.focus("body");
await page.keyboard.down("Shift");
for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowRight");
await page.keyboard.up("Shift");
report.timeAfterSeek = await page.$eval("#tc", (e) => e.textContent);
await page.click("#play-btn");
await sleep(2500);
await page.click("#play-btn");
report.timeAfterPlay = await page.$eval("#tc", (e) => e.textContent);
report.captionVisible = await page.$eval(".caption-layer", (l) => l.textContent.trim()).catch(() => "");
report.mgFrames = await page.$$eval(".mg-frame", (a) => a.length);
await shot("02_played");

// transcript: select a kept word and cut it (live apply through the local server)
await page.click('[data-tab="transcript"]');
await sleep(400);
const before = await page.$eval("#status-chips", (e) => e.textContent);
const word = await page.$(".tx-w:not(.cut)");
if (word) {
  await word.click();
  await page.keyboard.press("Delete");
  await sleep(2500);
}
report.revBefore = before.match(/rev \d+/)?.[0];
report.revAfter = (await page.$eval("#status-chips", (e) => e.textContent)).match(/rev \d+/)?.[0];
report.cutWords = await page.$$eval(".tx-w.cut", (a) => a.length);
await shot("03_cut_word");

// knobs: set pace
await page.click('[data-tab="knobs"]');
await sleep(300);
const pace = await page.$("#knob-pace");
if (pace) {
  await page.$eval("#knob-pace", (el) => { el.value = "0.8"; el.dispatchEvent(new Event("input", { bubbles: true })); });
  await sleep(2500);
}
report.durationAfterPace = await page.$eval("#tc", (e) => e.textContent);
await shot("04_knobs");

// suggestions + library tabs render
await page.click('[data-tab="suggestions"]');
await sleep(300);
report.suggestionCards = await page.$$eval(".sug-card, .dir-card, .done-list", (a) => a.length);
await page.click('[data-tab="library"]');
await sleep(300);
report.libraryItems = await page.$$eval(".lib-item", (a) => a.length);
await shot("05_library");

// phone width
await page.setViewport({ width: 390, height: 844, isMobile: true });
await sleep(1200);
report.phoneOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
await shot("06_phone");

report.console = logs.slice(0, 30);
console.log(JSON.stringify(report, null, 2));
await browser.close();
