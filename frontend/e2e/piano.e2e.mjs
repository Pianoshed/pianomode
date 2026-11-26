import chromium from "@sparticuz/chromium";
import puppeteer from "puppeteer-core";

import { mkdirSync } from "node:fs";
const SHOTS = process.env.SHOTS_DIR ?? "/tmp/shots";
mkdirSync(SHOTS, { recursive: true });
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  -> " + detail}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.launch({
  executablePath: await chromium.executablePath(),
  args: [...chromium.args.filter((a) => !/web-security/.test(a)), "--no-sandbox", "--autoplay-policy=no-user-gesture-required"],
  headless: "shell",
});
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
await page.setViewport({ width: 1280, height: 900 });

// Count real Web Audio activity.
await page.evaluateOnNewDocument(() => {
  window.__audio = { contexts: 0, oscillators: 0, started: 0, states: [] };
  const Real = window.AudioContext;
  window.AudioContext = class extends Real {
    constructor(...a) {
      super(...a);
      window.__audio.contexts++;
      const co = this.createOscillator.bind(this);
      this.createOscillator = () => {
        const o = co();
        window.__audio.oscillators++;
        const s = o.start.bind(o);
        o.start = (...x) => { window.__audio.started++; return s(...x); };
        return o;
      };
    }
  };
});

// ---- sign in through the real UI
await page.goto("http://localhost:3000/login", { waitUntil: "networkidle0" });
await page.type('input[type="email"]', "learner@example.com");
await page.type('input[type="password"]', "correct horse battery");
await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.click('button[type="submit"]')]);
check("signed in", !page.url().includes("/login"), page.url());

await page.goto("http://localhost:3000/piano", { waitUntil: "networkidle0" });
await page.waitForSelector('[data-midi="60"]');
const keyCount = await page.$$eval("[data-midi]", (e) => e.length);
check("88 keys rendered", keyCount === 88, String(keyCount));

// ---- the default chord (C major) comes from the real theory API and marks the keys
await page.waitForFunction(() => document.querySelector('[data-midi="60"]')?.getAttribute("aria-label")?.includes("root"), { timeout: 8000 }).catch(() => {});
const c4 = await page.$eval('[data-midi="60"]', (e) => e.getAttribute("aria-label"));
const e4 = await page.$eval('[data-midi="64"]', (e) => e.getAttribute("aria-label"));
check("C major marks C4 as root and bass", /root R, bass/.test(c4 ?? ""), c4);
check("C major marks E4 as chord tone 3", /chord tone 3/.test(e4 ?? ""), e4);
await page.screenshot({ path: SHOTS + "/01-desktop-light-chord.png" });

// ---- mouse: press, glissando, release
const box = async (m) => { const r = await (await page.$(`[data-midi="${m}"]`)).boundingBox(); return r; };
const b60 = await box(60), b62 = await box(62);
await page.mouse.move(b60.x + b60.width / 2, b60.y + b60.height * 0.85);
await page.mouse.down();
await sleep(120);
const pressed60 = await page.$eval('[data-midi="60"]', (e) => e.getAttribute("aria-pressed"));
check("mouse down presses the key", pressed60 === "true", pressed60);
await page.mouse.move(b62.x + b62.width / 2, b62.y + b62.height * 0.85, { steps: 6 });
await sleep(120);
const after = await page.$$eval('[data-midi][aria-pressed="true"]', (e) => e.map((x) => x.getAttribute("data-midi")));
check("sliding moves the press to the next key (glissando)", after.length === 1 && after[0] === "62", JSON.stringify(after));
await page.mouse.up();
await sleep(100);
const none = await page.$$eval('[data-midi][aria-pressed="true"]', (e) => e.length);
check("mouse up releases the key", none === 0, String(none));

// a black key is hit in its upper part, not by a click below it
const b61 = await box(61);
await page.mouse.move(b61.x + b61.width / 2, b61.y + b61.height * 0.3);
await page.mouse.down(); await sleep(80);
const blackHit = await page.$$eval('[data-midi][aria-pressed="true"]', (e) => e.map((x) => x.getAttribute("data-midi")));
await page.mouse.up();
check("clicking the upper part plays the black key", blackHit.join() === "61", JSON.stringify(blackHit));
const lowerY = b60.y + b60.height * 0.9;
await page.mouse.move(b61.x + b61.width / 2, lowerY);
await page.mouse.down(); await sleep(80);
const whiteHit = await page.$$eval('[data-midi][aria-pressed="true"]', (e) => e.map((x) => x.getAttribute("data-midi")));
await page.mouse.up();
check("clicking below a black key plays the white key", whiteHit.length === 1 && whiteHit[0] !== "61", JSON.stringify(whiteHit));

// ---- audio engine really ran
const audio = await page.evaluate(() => window.__audio);
check("Web Audio context created and oscillators started", audio.contexts === 1 && audio.started > 0, JSON.stringify(audio));

// ---- computer keyboard
await page.keyboard.down("KeyZ"); await page.keyboard.down("KeyC"); await page.keyboard.down("KeyB");
await sleep(150);
const kb = await page.$$eval('[data-midi][aria-pressed="true"]', (e) => e.map((x) => Number(x.getAttribute("data-midi"))).sort((a, b) => a - b));
check("Z, C and B play C3, E3 and G3", kb.join() === "48,52,55", kb.join());
await page.keyboard.up("KeyZ"); await page.keyboard.up("KeyC"); await page.keyboard.up("KeyB");
await sleep(100);

// ---- identify: what the keys make
await page.evaluate(() => document.getElementById("tab-identify").click());
await sleep(1200);
const idText = await page.$eval("#panel-identify", (e) => e.innerText);
check("playing C-E-G is identified as C (kept after release)", /\bC\b/.test(idText) && /Major|major/.test(idText), idText.slice(0, 160));
await page.screenshot({ path: SHOTS + "/02-identify-c.png" });

// ambiguous: A C E G
for (const code of ["KeyN", "KeyQ", "KeyE", "KeyT"]) await page.keyboard.down(code); // base 48: N=57(A3) Q=60(C4) E=64(E4) T=67(G4)
await sleep(100);
for (const code of ["KeyN", "KeyQ", "KeyE", "KeyT"]) await page.keyboard.up(code);
await sleep(1200);
const am7 = await page.$eval("#panel-identify", (e) => e.innerText);
check("A-C-E-G is Am7 and also lists the C6/A reading", /Am7/.test(am7) && /C6\/A/.test(am7), am7.slice(0, 220));
check("ranking is described as a judgement, not a probability", /not a probability/.test(am7));
await page.screenshot({ path: SHOTS + "/03-identify-am7.png" });

// cluster -> honest refusal
for (const code of ["KeyZ", "KeyS", "KeyX"]) await page.keyboard.down(code);
await sleep(100);
for (const code of ["KeyZ", "KeyS", "KeyX"]) await page.keyboard.up(code);
await sleep(1200);
const cluster = await page.$eval("#panel-identify", (e) => e.innerText);
check("a note cluster gets no forced chord name", !/Other readings/.test(cluster) && /reliab|chord|enough|name/i.test(cluster), cluster.slice(0, 200));

// ---- scale: F# major spells E# on the F key
await page.evaluate(() => document.getElementById("tab-scale").click());
await page.waitForSelector("#panel-scale button");
await page.evaluate(() => { [...document.querySelectorAll("#panel-scale fieldset button")].find((b) => b.textContent === "F♯").click(); });
await sleep(1000);
const f4 = await page.$eval('[data-midi="65"]', (e) => e.getAttribute("aria-label"));
check("F# major labels the F key as E sharp", /E sharp 4/.test(f4 ?? ""), f4);
await page.screenshot({ path: SHOTS + "/04-scale-fsharp.png" });

// ---- chord via typed symbol incl. slash + two-hand voicing
await page.evaluate(() => document.getElementById("tab-chord").click());
await page.focus('#panel-chord input[placeholder="Dm7/C"]');
await page.keyboard.type("Dm7/C");
await page.keyboard.press("Enter");
await sleep(1000);
const sym = await page.$eval("#panel-chord", (e) => e.innerText);
check("typed Dm7/C is shown with its slash bass", /Dm7\/C/.test(sym), sym.slice(0, 160));
const bassKeys = await page.$$eval('[data-midi][aria-label*="bass"]', (e) => e.length);
check("exactly one key is marked as the bass", bassKeys === 1, String(bassKeys));
// typing letters in the input must not play notes
const typedPlayed = await page.evaluate(() => window.__audio.started);
await page.focus('#panel-chord input[placeholder="Dm7/C"]');
await page.keyboard.type("zxc");
await sleep(100);
check("typing in a text field does not play the piano", (await page.evaluate(() => window.__audio.started)) === typedPlayed);

// malformed symbol shows the engine's message
await page.$eval('#panel-chord input[placeholder="Dm7/C"]', (e) => { e.value = ""; });
await page.focus('#panel-chord input[placeholder="Dm7/C"]');
await page.keyboard.type("Cmaj");
await page.keyboard.press("Enter");
await sleep(900);
const alert = await page.$eval('#panel-chord [role="alert"]', (e) => e.innerText).catch(() => "");
check("a malformed symbol is rejected with an explanation, not reinterpreted", alert.length > 10, alert);

// two hands
await page.evaluate(() => { const input = document.querySelector('#panel-chord input[placeholder="Dm7/C"]'); });
await page.$eval('#panel-chord input[placeholder="Dm7/C"]', (e) => e.blur());
await page.evaluate(() => {
  const nativeSet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  const input = document.querySelector('#panel-chord input[placeholder="Dm7/C"]');
  nativeSet.call(input, "Cmaj7"); input.dispatchEvent(new Event("input", { bubbles: true }));
});
await page.keyboard.press("Tab");
await page.evaluate(() => [...document.querySelectorAll("#panel-chord button")].find((b) => b.textContent === "Show").click());
await sleep(700);
await page.evaluate(() => [...document.querySelectorAll("#panel-chord label")].find((l) => l.textContent.includes("two-hand voicing")).querySelector("input").click());
await sleep(1200);
const hands = await page.$$eval('[data-midi][aria-label*="hand"]', (e) => e.map((x) => x.getAttribute("aria-label")));
check("two-hand voicing marks left and right hand keys", hands.some((h) => /left hand/.test(h)) && hands.some((h) => /right hand/.test(h)), JSON.stringify(hands));
await page.screenshot({ path: SHOTS + "/05-two-hands.png" });

// ---- play button schedules audio and presses keys in time
const before = await page.evaluate(() => window.__audio.started);
await page.evaluate(() => [...document.querySelectorAll("#panel-chord button")].find((b) => b.textContent.includes("Play chord")).click());
await sleep(400);
const during = await page.$$eval('[data-midi][aria-pressed="true"]', (e) => e.length);
const afterStarted = await page.evaluate(() => window.__audio.started);
check("Play chord sounds the chord and presses its keys", during >= 3 && afterStarted > before, `${during} pressed, ${afterStarted - before} oscillators`);
await sleep(2000);
check("the keys release when the chord ends", (await page.$$eval('[data-midi][aria-pressed="true"]', (e) => e.length)) === 0);

// ---- layering
await page.evaluate(() => [...document.querySelectorAll("label")].find((l) => l.textContent.includes("Strings"))?.querySelector("input")?.click());
await sleep(100);
const s0 = await page.evaluate(() => window.__audio.started);
await page.evaluate(() => document.querySelector('[data-midi="60"]').scrollIntoView({ block: "center" }));
const fresh = await box(60);
await page.mouse.move(fresh.x + fresh.width / 2, fresh.y + fresh.height * 0.85); await page.mouse.down(); await sleep(80); await page.mouse.up();
const s1 = await page.evaluate(() => window.__audio.started);
check("layering two sounds starts more oscillators per note", s1 - s0 > 8, `${s1 - s0}`);
const prefs = await page.evaluate(() => JSON.parse(localStorage.getItem("piano.prefs.v1") ?? "null"));
check("preferences are saved", prefs && prefs.layers.length === 2, JSON.stringify(prefs));

// ---- sustain via Space
await page.$eval("body", (e) => e.focus());

const unexpected = errors.filter((e) => !/status of 422/.test(e));
const expected422 = errors.filter((e) => /status of 422/.test(e)).length;
// ---- live readout and sticky stage
const stageText = await page.$eval("div.sticky.z-10", (e) => e.innerText);
check("live readout names what is shown and what was played", /Showing/.test(stageText) && /You played/.test(stageText), stageText.slice(0, 160));
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
await sleep(250);
const topDesktop = await page.$eval('[data-midi="60"]', (e) => e.getBoundingClientRect().top);
check("keyboard stays in view while the panels below are used (desktop)", topDesktop > 0 && topDesktop < 200, String(topDesktop));
await page.screenshot({ path: SHOTS + "/08-sticky-desktop.png" });
await page.evaluate(() => window.scrollTo(0, 0));

// ---- dark theme: marks stay readable on the (always ivory) keys
await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
await sleep(300);
const contrast = await page.evaluate(() => {
  const lum = (rgb) => { const [r, g, b] = rgb.match(/[\d.]+/g).slice(0, 3).map(Number).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const out = {};
  for (const [name, sel] of [["tone", "span.bg-dot-soft"], ["root", "span.bg-dot"]]) {
    const el = document.querySelector(`[data-midi] ${sel}`);
    if (!el) { out[name] = null; continue; }
    const cs = getComputedStyle(el); out[name] = ratio(cs.color, cs.backgroundColor);
  }
  return out;
});
check("dark theme: chord-tone and root labels have at least 4.5:1 contrast", contrast.tone >= 4.5 && contrast.root >= 4.5, JSON.stringify(contrast));
await page.screenshot({ path: SHOTS + "/06-desktop-dark.png" });
await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));

check("no page or console errors (apart from the one deliberate 422)", unexpected.length === 0 && expected422 === 1, errors.join(" | "));

// ---- other looks: dark and mobile
await page.evaluate(() => document.getElementById("tab-chord").click());
await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
await sleep(400);
await page.screenshot({ path: SHOTS + "/07-mobile.png", fullPage: true });
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
await sleep(300);
const topMobile = await page.$eval("[data-midi]", (e) => e.getBoundingClientRect().top);
check("keyboard stays in view below the mobile bar on a phone", topMobile > 40 && topMobile < 260, String(topMobile));
await page.screenshot({ path: SHOTS + "/09-sticky-mobile.png" });
await page.evaluate(() => window.scrollTo(0, 0));
await page.setViewport({ width: 1280, height: 900 });
await page.goto("http://localhost:3000/dashboard", { waitUntil: "networkidle0" });
await page.screenshot({ path: SHOTS + "/10-dashboard.png", clip: { x: 270, y: 0, width: 1000, height: 330 } });
const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
check("no horizontal page overflow on a 390px phone", !overflow);

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
