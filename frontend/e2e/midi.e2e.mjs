import chromium from "@sparticuz/chromium";
import puppeteer from "puppeteer-core";
import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const SHOTS = process.env.SHOTS_DIR ?? "/tmp/shots";
const FIX = new URL("../lib/midi/__fixtures__/", import.meta.url).pathname;
mkdirSync(SHOTS, { recursive: true });
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  -> " + detail}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- tiny SMF builder for the odd files
const vlq = (n) => { const o = [n & 127]; for (n >>= 7; n > 0; n >>= 7) o.push((n & 127) | 128); return o.reverse(); };
const str = (s) => [...s].map((c) => c.charCodeAt(0));
const u32 = (n) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255];
const u16 = (n) => [(n >> 8) & 255, n & 255];
const smf = (events, division = 480) => {
  const body = [...events, 0, 0xff, 0x2f, 0];
  return Buffer.from([...str("MThd"), ...u32(6), ...u16(0), ...u16(1), ...u16(division), ...str("MTrk"), ...u32(body.length), ...body]);
};
const tmp = (name, data) => { const p = join(tmpdir(), name); writeFileSync(p, data); return p; };

const browser = await puppeteer.launch({
  executablePath: await chromium.executablePath(),
  args: [...chromium.args.filter((a) => !/web-security/.test(a)), "--no-sandbox", "--autoplay-policy=no-user-gesture-required"],
  headless: "shell",
});
const page = await browser.newPage();
const errors = [];
const requests = [];
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
page.on("request", (r) => { if (r.method() === "POST" && r.url().includes("/midi/analyze")) requests.push(JSON.parse(r.postData())); });
await page.setViewport({ width: 1280, height: 900 });
await page.evaluateOnNewDocument(() => {
  window.__audio = { started: 0 };
  const Real = window.AudioContext;
  window.AudioContext = class extends Real {
    constructor(...a) {
      super(...a);
      const co = this.createOscillator.bind(this);
      this.createOscillator = () => { const o = co(); const s = o.start.bind(o); o.start = (...x) => { window.__audio.started++; return s(...x); }; return o; };
    }
  };
});

const body = () => page.evaluate(() => document.body.textContent ?? "");
const waitText = (re, timeout = 15000) => page.waitForFunction((s) => new RegExp(s).test(document.body.textContent ?? ""), { timeout }, re.source);
const clickText = async (selector, label) => {
  const h = await page.evaluateHandle((sel, l) => [...document.querySelectorAll(sel)].find((e) => (e.textContent ?? "").trim().startsWith(l)), selector, label);
  if (!h.asElement()) throw new Error(`no ${selector} starting with "${label}"`);
  await h.asElement().click();
};
const chordCells = () => page.$$eval("ol[aria-label='Chords in time order'] button", (b) => b.map((x) => x.getAttribute("aria-label")));
const waitChords = (n) => page.waitForFunction((k) => document.querySelectorAll("ol[aria-label='Chords in time order'] button").length >= k, { timeout: 20000 }, n);
const upload = async (path) => { const input = await page.$("input[type=file]"); await input.uploadFile(path); };
const markedKeys = () => page.$$eval("[data-midi]", (els) => els.map((e) => e.getAttribute("aria-label")).filter((l) => /root|chord tone|extra/.test(l ?? "")));

await page.goto("http://localhost:3000/login", { waitUntil: "networkidle0" });
await page.type('input[type="email"]', "learner@example.com");
await page.type('input[type="password"]', "correct horse battery");
await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.click('button[type="submit"]')]);

await page.goto("http://localhost:3000/midi", { waitUntil: "networkidle0" });
await page.waitForSelector("[data-testid='midi-file']");
check("starts with nothing loaded and says the file stays on the device", /read on your device/.test(await body()) && !(await page.$("canvas")));

// ---- the example
await clickText("button", "Try an example");
await waitText(/17 notes/);
const summary = await body();
check("file summary: format, notes, bars, tempo, time signature", /Format 1/.test(summary) && /17 notes/.test(summary) && /4 bars/.test(summary) && /100 BPM/.test(summary) && /4\/4/.test(summary));
await waitChords(4);
const cells = await chordCells();
check("timeline shows C, Am, F, G7 with Roman numerals", cells.length === 4 && /C, numeral I,/.test(cells[0]) && /Am, numeral vi,/.test(cells[1]) && /F, numeral IV,/.test(cells[2]) && /G7, numeral V7,/.test(cells[3]), cells.join(" | "));
check("key is C major and labelled as an estimate", /C major/.test(await body()) && /estimated/.test(await body()));
check("no probabilities are claimed", /ranked, not given probabilities/.test(await body()));
await page.screenshot({ path: `${SHOTS}/40-midi-analysis.png` });

// ---- chord details and alternative readings on the keyboard
await clickText("ol[aria-label='Chords in time order'] button", "Am");
await page.waitForSelector("section[aria-label='Chord details']");
check("details show the bass, tones heard and the numeral", /Bass note/.test(await body()) && /Chord tones heard/.test(await body()));
let keys = await markedKeys();
check("Am is shown on the keyboard: A, C, E and the bass", keys.length >= 4 && keys.some((k) => /^A 2/.test(k) || /^A 3/.test(k)), keys.join(" | "));
check("the keyboard readout names the chord", /Showing Am/.test(await body()));
const altCount = await page.$$eval("fieldset button[aria-pressed]", (b) => b.length);
check("alternative readings are offered when there is more than one", altCount >= 2, String(altCount));
await clickText("fieldset button", "C6/A");
await sleep(300);
check("choosing an alternative updates the keyboard readout", /Showing C6\/A/.test(await body()), (await body()).slice(0, 400));

// ---- hand editing in the roll
const view = JSON.parse(await page.$eval("[data-testid='piano-roll']", (c) => c.getAttribute("data-view")));
const canvasEl = await page.$("[data-testid='piano-roll']");
await canvasEl.evaluate((c) => c.scrollIntoView({ block: "center", inline: "nearest" })); // the roll is below the fold
await sleep(200);
const canvasBox = await canvasEl.boundingBox();
const x = canvasBox.x + view.left + 0.5 * view.pxPerSec * 1; // half a second into the piece
const yOf = (m) => canvasBox.y + view.top + (view.hi - m) * view.rowH + view.rowH / 2;
await page.mouse.click(x, yOf(64)); // E4, right hand in the first bar
await page.waitForSelector("section[aria-label='Selected note']");
const sel1 = await page.$eval("section[aria-label='Selected note']", (s) => s.textContent);
check("clicking a note selects it and shows the Studio's guess", /E4|E 4/.test(sel1) && /right hand/.test(sel1) && /the Studio's guess/.test(sel1), sel1);
const before = requests.length;
await clickText("section[aria-label='Selected note'] button", "Left hand");
await sleep(400);
const sel2 = await page.$eval("section[aria-label='Selected note']", (s) => s.textContent);
check("setting the hand marks it as set by you", /left hand/.test(sel2) && /set by you/.test(sel2), sel2);
check("changing a hand does not ask the server again", requests.length === before, `${before} -> ${requests.length}`);
await page.select("select:has(option[value='half_bar'])", "bar").catch(() => {});
const gridSel = await page.evaluateHandle(() => [...document.querySelectorAll("select")].find((s) => [...s.options].some((o) => o.textContent === "half bar")));
await gridSel.asElement().select("bar");
await sleep(1500);
await waitChords(4).catch(() => {});
await page.waitForSelector("section[aria-label='Selected note']", { timeout: 3000 }).catch(() => {});
check("changing the grid re-analyses and sends bar grid", requests.at(-1)?.grid === "bar");
await (await page.$("[data-testid='piano-roll']")).evaluate((c) => c.scrollIntoView({ block: "center", inline: "nearest" }));
await sleep(200);
const box2 = await (await page.$("[data-testid='piano-roll']")).boundingBox();
await page.mouse.click(box2.x + view.left + view.pxPerSec * 0.5, box2.y + view.top + (view.hi - 64) * view.rowH + view.rowH / 2);
await page.waitForSelector("section[aria-label='Selected note']");
check("the hand you set survives re-analysis", /set by you/.test(await page.$eval("section[aria-label='Selected note']", (s) => s.textContent)));
await gridSel.asElement().select("beat");
await sleep(1200);

// keyboard use of the roll
await page.focus("[role='application']");
await page.keyboard.press("ArrowRight");
await page.keyboard.press("r");
await sleep(200);
check("the roll works from the keyboard (arrows choose, R sets the hand)", /right hand/.test(await page.$eval("section[aria-label='Selected note']", (s) => s.textContent)));

// ---- tracks
const trackNames = await page.$$eval("section[aria-label='Tracks'] li > div:first-child > span:first-child", (s) => s.map((x) => x.textContent));
check("two tracks are listed, the empty conductor track is not", trackNames.join(",") === "Right hand,Left hand", trackNames.join(","));
const n0 = requests.length;
await clickText("section[aria-label='Tracks'] li:nth-child(2) button", "Mute");
await page.waitForFunction((k) => true, {}, n0);
await sleep(1500);
const muted = requests.at(-1);
check("muting a track asks the server again with that track muted", requests.length > n0 && muted.track_states.find((t) => t.track === 2)?.muted === true, JSON.stringify(muted?.track_states));
await clickText("section[aria-label='Tracks'] li:nth-child(2) button", "Mute");
await sleep(1200);
const n1 = requests.length;
const handSel = await page.$("select[aria-label='Hand for Right hand']");
await handSel.select("R");
await sleep(600);
check("assigning a track to a hand does not ask the server again", requests.length === n1, `${n1} -> ${requests.length}`);
// a right-hand note (F4 in bar 3) that nobody has edited
await (await page.$("[data-testid='piano-roll']")).evaluate((c) => c.scrollIntoView({ block: "center", inline: "nearest" }));
await sleep(200);
const box3 = await (await page.$("[data-testid='piano-roll']")).boundingBox();
await page.mouse.click(box3.x + view.left + view.pxPerSec * 5, box3.y + view.top + (view.hi - 65) * view.rowH + view.rowH / 2);
await page.waitForFunction(() => /F4|F 4/.test(document.querySelector("section[aria-label='Selected note']")?.textContent ?? ""), { timeout: 4000 }).catch(() => {});
const trackNote = await page.$eval("section[aria-label='Selected note']", (s) => s.textContent);
check("notes from a track assigned to a hand say so", /from its track/.test(trackNote) && /right hand/.test(trackNote), trackNote);

const mergeSel = await page.$("select[aria-label='Merge Right hand into another track']");
await mergeSel.select("2");
await sleep(1800);
const merged = requests.at(-1);
check("merging sends every note on one track", new Set(merged.events.map((e) => e.track)).size === 1);
const mergedNames = await page.$$eval("section[aria-label='Tracks'] li > div:first-child > span:first-child", (s) => s.map((x) => x.textContent));
check("the merged track is labelled as merged", mergedNames.join(",") === "Left hand (merged)", mergedNames.join(","));
{
  const visible = await page.evaluate(() => {
    const b = [...document.querySelectorAll("section[aria-label='Tracks'] button")].find((e) => e.textContent.trim().startsWith("Undo"));
    b.scrollIntoView({ block: "start" }); // what the browser does when a control takes focus
    const r = b.getBoundingClientRect();
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return hit === b || b.contains(hit);
  });
  check("a control scrolled into view is not hidden behind the sticky keyboard panel", visible);
}
await clickText("section[aria-label='Tracks'] button", "Undo");
await sleep(1500);
const splitSel = await page.$("select[aria-label='Split Right hand at pitch']");
await splitSel.select("65");
await clickText("section[aria-label='Tracks'] li:nth-child(1) button", "Split");
await sleep(1800);
const split = requests.at(-1);
check("splitting makes a third track", new Set(split.events.map((e) => e.track)).size === 3, [...new Set(split.events.map((e) => e.track))].join());
const splitNames = await page.$$eval("section[aria-label='Tracks'] li > div:first-child > span:first-child", (s) => s.map((x) => x.textContent));
check("the new track is named after the one it came from", splitNames.includes("Right hand (upper part)"), splitNames.join(","));
await page.screenshot({ path: `${SHOTS}/41-midi-tracks.png` });
await clickText("section[aria-label='Tracks'] button", "Reset");
await sleep(1500);

// ---- playback
await page.evaluate(() => window.scrollTo(0, 0));
await clickText("button", "Play");
await sleep(1500);
check("Play starts real audio", (await page.evaluate(() => window.__audio.started)) > 0);
check("the readout says Playing and shows the chord", /Playing\s*C/.test(await body()) || /Playing/.test(await body()));
const h1 = await page.$eval("[data-testid='playhead']", (e) => e.style.left);
await sleep(700);
const h2 = await page.$eval("[data-testid='playhead']", (e) => e.style.left);
check("the playhead moves", h1 !== h2, `${h1} -> ${h2}`);
const startedBefore = await page.evaluate(() => window.__audio.started);
await page.select("select[aria-label='Which hand to hear']", "L");
await sleep(1200);
check("switching to one hand carries on playing", (await page.evaluate(() => window.__audio.started)) > startedBefore);
await clickText("button", "Stop");
await sleep(200);
check("Stop stops", /Play/.test(await page.$$eval("button", (b) => b.map((x) => x.textContent).join(" "))));
await page.select("select[aria-label='Which hand to hear']", "both");

// ---- other files
await upload(join(FIX, "single-track.mid"));
await waitText(/Format 0/);
await waitChords(4);
const cells0 = await chordCells();
check("a format 0 file with running status gives the same chords", /C, numeral I,/.test(cells0[0]) && /G7, numeral V7,/.test(cells0[3]), cells0.join(" | "));

await upload(tmp("notes.mid", Buffer.from("this is certainly not a midi file")));
await waitText(/not a standard MIDI file/);
check("a file that is not MIDI gets a clear message", true);
check("the previous file is cleared after a failed load", !(await page.$("canvas")));

await upload(tmp("smpte.mid", Buffer.from([...str("MThd"), ...u32(6), ...u16(0), ...u16(1), ...u16(0xe728), ...str("MTrk"), ...u32(4), 0, 0xff, 0x2f, 0])));
await waitText(/SMPTE/);
check("SMPTE timing is refused with an explanation", true);

// ---- a file with more notes than can be analysed at once
const events = [];
for (let n = 0; n < 12000; n++) {
  const key = 48 + (n % 24);
  events.push(...vlq(n === 0 ? 0 : 19), 0x90, key, 70, ...vlq(15), 0x80, key, 0);
}
await upload(tmp("big.mid", smf(events)));
await waitText(/analysed in sections/);
const sectionText = (await body()).match(/Showing bars (\d+) to (\d+) of (\d+)/);
check("a file over the limit is analysed in sections and says which bars", !!sectionText && Number(sectionText[1]) === 1 && Number(sectionText[2]) < Number(sectionText[3]), sectionText?.[0]);
await waitChords(1);
const bigCells = await chordCells();
check("noise that forms no chord is shown as 'no reliable label', not given a chord name", /no reliable label/.test(bigCells[0]), bigCells[0]);
const bigReq = requests.at(-1);
check("no request exceeds the 20,000-event limit", bigReq.events.length <= 20000 && bigReq.events.length > 15000, String(bigReq.events.length));
const beforeNext = requests.length;
await clickText("button", "Later section");
await page.waitForFunction(() => true);
for (let i = 0; i < 40 && requests.length <= beforeNext; i++) await sleep(250); // wait for the new request to go out
await waitText(new RegExp(`Showing bars ${Number(sectionText[2]) + 1} to`));
await waitChords(1);
await sleep(800);
const bigReq2 = requests.at(-1);
const firstTick = Math.min(...bigReq2.events.map((e) => e.tick));
check("the next section is timed from its own bar line (first note within one note-spacing of it)", firstTick >= 0 && firstTick < 34 && bigReq2.events.length > 0 && bigReq2.events.length <= 20000, `first tick ${firstTick}, ${bigReq2.events.length} events`);
await page.screenshot({ path: `${SHOTS}/42-midi-sections.png` });

// ---- the server asks for a pause: explain, retry by itself, recover
await upload(join(FIX, "c-am-f-g.mid"));
await waitChords(4);
let blocked = 0;
let intercepting = true;
await page.setRequestInterception(true);
page.on("request", (r) => {
  if (!intercepting || r.isInterceptResolutionHandled()) return;
  if (r.method() === "POST" && r.url().includes("/midi/analyze") && blocked === 0) {
    blocked++;
    r.respond({ status: 429, contentType: "application/json", headers: { "Retry-After": "5" }, body: JSON.stringify({ error: { code: "rate_limited", message: "slow down", details: {} } }) });
  } else r.continue();
});
const gridSel2 = await page.evaluateHandle(() => [...document.querySelectorAll("select")].find((s) => [...s.options].some((o) => o.textContent === "half bar")));
await gridSel2.asElement().select("half_bar");
await waitText(/short pause/, 6000);
check("a rate limit is explained in plain words, not as 'wait a few minutes'", /short pause/.test(await body()) && !/few minutes/.test(await body()));
await page.waitForFunction(() => !/short pause/.test(document.body.textContent ?? ""), { timeout: 15000 });
await waitChords(4);
check("the Studio retries by itself and recovers", blocked === 1 && requests.at(-1)?.grid === "half_bar");
intercepting = false;
await page.setRequestInterception(false);

// ---- phone
await page.setViewport({ width: 390, height: 800 });
await page.goto("http://localhost:3000/midi", { waitUntil: "networkidle0" });
await clickText("button", "Try an example");
await waitChords(4);
check("no sideways page scroll on a phone", !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
await page.screenshot({ path: `${SHOTS}/43-midi-phone.png` });

const real = errors.filter((e) => !/favicon|Failed to load resource/.test(e));
check("no unexpected browser errors", real.length === 0, real.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
