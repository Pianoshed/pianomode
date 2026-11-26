import chromium from "@sparticuz/chromium";
import puppeteer from "puppeteer-core";
import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const SHOTS = process.env.SHOTS_DIR ?? "/tmp/shots";
mkdirSync(SHOTS, { recursive: true });
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  -> " + detail}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- WAV files made here, independent of the app's own synthesiser
const hz = (m) => 440 * 2 ** ((m - 69) / 12);
function wav({ segments, rate, channels = 1, rightGain = 0.6 }) {
  const total = segments.reduce((n, s) => n + Math.round(s.seconds * rate), 0);
  const mono = new Float32Array(total);
  let at = 0;
  for (const s of segments) {
    const len = Math.round(s.seconds * rate);
    for (const [notes, amp, parts] of [[s.notes ?? [], 0.16, 6], [s.bass !== undefined ? [s.bass] : [], 0.22, 4]]) {
      for (const m of notes) for (let h = 1; h <= parts; h++) {
        const f = hz(m) * h; if (f > rate / 2 - 100) break;
        const w = (2 * Math.PI * f) / rate, a = amp / h, fade = Math.floor(0.01 * rate);
        for (let i = 0; i < len; i++) { const env = i < fade ? i / fade : i > len - fade ? (len - i) / fade : 1; mono[at + i] += a * env * Math.sin(w * i); }
      }
    }
    at += len;
  }
  const buf = Buffer.alloc(44 + total * 2 * channels);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + total * 2 * channels, 4); buf.write("WAVEfmt ", 8); buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20); buf.writeUInt16LE(channels, 22); buf.writeUInt32LE(rate, 24); buf.writeUInt32LE(rate * 2 * channels, 28);
  buf.writeUInt16LE(2 * channels, 32); buf.writeUInt16LE(16, 34); buf.write("data", 36); buf.writeUInt32LE(total * 2 * channels, 40);
  for (let i = 0; i < total; i++) for (let c = 0; c < channels; c++) buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, mono[i] * (c === 1 ? rightGain : 1))) * 32767), 44 + (i * channels + c) * 2);
  return buf;
}
const tmp = (name, data) => { const p = join(tmpdir(), name); writeFileSync(p, data); return p; };
const chord = (root, ints, seconds) => ({ notes: ints.map((i) => 60 + root + i), bass: 36 + root, seconds });

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
page.on("request", (r) => { if (r.method() === "POST" && r.url().includes("/audio/interpret")) requests.push(JSON.parse(r.postData())); });
await page.setViewport({ width: 1280, height: 900 });

const body = () => page.evaluate(() => document.body.textContent ?? "");
const waitText = (re, timeout = 25000) => page.waitForFunction((s) => new RegExp(s).test(document.body.textContent ?? ""), { timeout }, re.source);
const clickText = async (selector, label) => {
  const h = await page.evaluateHandle((sel, l) => [...document.querySelectorAll(sel)].find((e) => (e.textContent ?? "").trim().startsWith(l)), selector, label);
  if (!h.asElement()) throw new Error(`no ${selector} starting with "${label}"`);
  await h.asElement().scrollIntoView?.();
  await h.asElement().click();
};
const cells = () => page.$$eval("ol[aria-label='Chords in time order'] button", (b) => b.map((x) => x.getAttribute("aria-label")));
const waitCells = (n) => page.waitForFunction((k) => document.querySelectorAll("ol[aria-label='Chords in time order'] button").length >= k, { timeout: 30000 }, n);
const upload = async (path) => (await page.$("input[type=file]")).uploadFile(path);
const marked = () => page.$$eval("[data-midi]", (els) => els.map((e) => e.getAttribute("aria-label")).filter((l) => /root|chord tone|extra/.test(l ?? "")));
const details = () => page.$eval("section[aria-label='Chord details']", (s) => s.textContent ?? "");
const readout = () => page.$eval("[aria-live='polite']", (e) => e.textContent ?? "");
const setPosition = async (sec) => page.$eval("input[aria-label='Playback position']", (el, v) => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set; set.call(el, String(v)); el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); }, sec);
const clickCell = async (i) => { const bs = await page.$$("ol[aria-label='Chords in time order'] button"); await bs[i].evaluate((b) => b.scrollIntoView({ block: "center", inline: "center" })); await bs[i].click(); await sleep(250); };

await page.goto("http://localhost:3000/login", { waitUntil: "networkidle0" });
await page.type('input[type="email"]', "learner@example.com");
await page.type('input[type="password"]', "correct horse battery");
await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.click('button[type="submit"]')]);

await page.goto("http://localhost:3000/audio", { waitUntil: "networkidle0" });
await page.waitForSelector("[data-testid='audio-file']");
check("starts empty, says how far to trust it and that nothing is saved", /How far to trust it/.test(await body()) && /nothing is saved/.test(await body()) && !(await page.$("canvas")));

// ---- the built-in example
await clickText("button", "Try an example");
await waitCells(4);
const c1 = await cells();
check("the example's chords are found in order: C, Am, F, G7", c1.length === 4 && /: C,/.test(c1[0]) && /: Am,/.test(c1[1]) && /: F,/.test(c1[2]) && /: G7,/.test(c1[3]), c1.join(" | "));
check("each is described as an estimate", c1.every((l) => /estimate/.test(l)), c1.join(" | "));
check("a key and numerals are given, the key marked as an estimate", /estimated/.test(await body()) && c1.some((l) => /numeral/.test(l)));
check("scores are said not to be probabilities", /not probabilities/.test(await body()));
await page.screenshot({ path: `${SHOTS}/50-audio-example.png` });
(await page.$("section[aria-label='Chords in the recording']")).screenshot({ path: `${SHOTS}/50b-audio-timeline.png` }).catch(() => {});

// ---- looking at one region
await clickCell(1);
await page.waitForSelector("section[aria-label='Chord details']");
check("details say the chord was heard, as an estimate", /heard, an estimate/.test(await details()) && /Estimated from the audio/.test(await details()));
await page.waitForFunction(() => /Heard \(estimate\): Am/.test(document.body.textContent ?? ""), { timeout: 8000 });
const am = await marked();
check("the keyboard shows Am (A, C, E) and says it is an estimate", am.length >= 3 && am.some((k) => /^A /.test(k)) && am.some((k) => /^C /.test(k)) && am.some((k) => /^E /.test(k)), am.join(" | "));
await (await page.$("section[aria-label='Chord details']")).screenshot({ path: `${SHOTS}/50c-audio-details.png` }).catch(() => {});
check("a correct Am shows all three of its pitches as evidence and no false 'too sparse' warning", /Strongest pitches\s*(A\s+C\s+E|C\s+A\s+E|A\s+E\s+C|E\s+A\s+C|C\s+E\s+A|E\s+C\s+A)/.test(await details()) && !/too sparse/.test(await details()), (await details()).slice(0, 500));
check("the details never show a confidence percentage", !/\d\s?%/.test(await details()) && !/confidence/i.test(await details()));

// ---- corrections
let n = requests.length;
await page.type("input[aria-label='New chord']", "Am7");
await clickText("section[aria-label='Chord details'] button", "Change");
await waitText(/set by you/);
check("changing a chord marks it as set by you and keeps the original", /set by you/.test(await details()) && /Originally heard as Am/.test(await details()));
check("the correction was checked by the server (relabel at the right index)", requests.length > n && requests.at(-1).corrections.some((c) => c.op === "relabel" && c.index === 1 && c.label === "Am7"), JSON.stringify(requests.at(-1)?.corrections));
check("the correction count is shown", /1 correction/.test(await body()));
await page.waitForFunction(() => /Your label: Am7/.test(document.body.textContent ?? ""), { timeout: 8000 });
check("the keyboard now says it is your label, not an estimate", true);
const cell = (await cells())[1];
check("the timeline marks it as set by you", /set by you/.test(cell), cell);

await clickText("section[aria-label='Chords in the recording'] button", "Undo");
await page.waitForFunction(() => /No corrections/.test(document.body.textContent ?? ""), { timeout: 8000 });
await sleep(400);
check("undo returns to the estimate", /: Am,/.test((await cells())[1]) && /estimate/.test((await cells())[1]));

// a label the server cannot read is refused and nothing is kept
await clickCell(1);
await page.type("input[aria-label='New chord']", "Xyz9");
await clickText("section[aria-label='Chord details'] button", "Change");
await waitText(/Xyz9/, 8000);
check("a chord the server cannot read is refused, naming it, and nothing is kept", /No corrections/.test(await body()) && /Xyz9/.test(await page.evaluate(() => [...document.querySelectorAll("p, div")].map((e) => e.textContent).find((t) => /Xyz9/.test(t) && !/New chord/.test(t) && t.length < 400) ?? "")), "");

// moving a boundary: both neighbours move, in an order the server accepts
await clickCell(2); // F, 5.0 to 7.5 s
const before = requests.length;
await page.$eval("input[aria-label='Start time in seconds']", (el) => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set; set.call(el, "5.30"); el.dispatchEvent(new Event("input", { bubbles: true })); });
await clickText("section[aria-label='Chord details'] button", "Move");
await page.waitForFunction(() => /2 corrections/.test(document.body.textContent ?? ""), { timeout: 8000 });
const ops = requests.at(-1).corrections.map((c) => `${c.op}:${c.index}`);
check("moving a shared boundary sends two retimes, the earlier chord's end last", ops.join() === "retime:2,retime:1", ops.join());
await sleep(300);
const d2 = await details();
check("the chord now starts at 5.3 s", /0:05\.3/.test(d2), d2.slice(0, 120));
await clickText("section[aria-label='Chords in the recording'] button", "Reset all");
await page.waitForFunction(() => /No corrections/.test(document.body.textContent ?? ""), { timeout: 8000 });
await sleep(500);

// split at the playhead, then join
await setPosition(3.7); // inside Am (2.5 to 5.0)
await sleep(300);
await clickCell(1);
await setPosition(3.7);
await sleep(200);
await clickText("section[aria-label='Chord details'] button", "Split at");
await waitCells(5);
check("splitting makes five regions", (await cells()).length === 5);
await clickCell(1);
await clickText("section[aria-label='Chord details'] button", "Join with the next");
await page.waitForFunction(() => document.querySelectorAll("ol[aria-label='Chords in time order'] button").length === 4, { timeout: 8000 });
check("joining makes four again", (await cells()).length === 4);
await clickText("section[aria-label='Chords in the recording'] button", "Reset all");
await page.waitForFunction(() => /No corrections/.test(document.body.textContent ?? ""), { timeout: 8000 });
await sleep(500);

// remove a chord, then add one in the gap
await clickCell(3);
await clickText("section[aria-label='Chord details'] button", "Remove this chord");
await page.waitForFunction(() => document.querySelectorAll("ol[aria-label='Chords in time order'] button").length === 3, { timeout: 8000 });
await setPosition(9);
await sleep(300);
check("the app says a chord can be added at the playhead only in an empty stretch", /empty stretch/.test(await body()) || /Add a chord at the playhead/.test(await body()));
await page.type("input[name='label']", "G7");
await clickText("form button", "Add");
await waitCells(4);
check("adding a chord in the gap restores four regions", (await cells()).length === 4 && /: G7,/.test((await cells())[3]) && /set by you/.test((await cells())[3]), (await cells()).join(" | "));
await clickText("section[aria-label='Chords in the recording'] button", "Reset all");
await page.waitForFunction(() => /No corrections/.test(document.body.textContent ?? ""), { timeout: 8000 });

// settings: changing how it listens replaces corrections, but only after asking
await clickCell(1);
await page.type("input[aria-label='New chord']", "Am7");
await clickText("section[aria-label='Chord details'] button", "Change");
await waitText(/1 correction/);
await page.select("select:has(option[value='triads'])", "triads").catch(() => {});
const setSel = await page.evaluateHandle(() => [...document.querySelectorAll("select")].find((s) => [...s.options].some((o) => o.value === "triads")));
await setSel.asElement().select("triads");
await waitText(/replaces your 1 correction/);
check("changing how it listens asks before replacing a correction", true);
await clickText("button", "Keep my corrections");
await sleep(400);
check("keeping them leaves the correction in place", /1 correction/.test(await body()) && !/replaces your/.test(await body()));
await clickText("section[aria-label='Chords in the recording'] button", "Reset all");
await page.waitForFunction(() => /No corrections/.test(document.body.textContent ?? ""), { timeout: 8000 });
await setSel.asElement().select("triads");
await sleep(1500);
const triads = await cells();
check("with no corrections it applies at once; major and minor only has no seventh chord names", triads.length >= 3 && !triads.some((l) => /: G7,|7,/.test(l)), triads.join(" | "));
await setSel.asElement().select("sevenths");
await sleep(1500);

// ---- playback of the recording
await setPosition(5.3);
await sleep(300);
const a0 = await page.$eval("[data-testid='recording']", (a) => a.currentTime);
await clickText("button", "Play recording");
await sleep(1300);
const st = await page.$eval("[data-testid='recording']", (a) => ({ paused: a.paused, t: a.currentTime }));
check("the recording plays and moves on", !st.paused && st.t > a0 + 0.5, JSON.stringify({ a0, st }));
await page.waitForFunction(() => /Heard \(estimate\): F/.test(document.body.textContent ?? ""), { timeout: 5000 }).catch(() => {});
check("while playing, the keyboard follows the chord being heard (F at 5.3 s)", /Heard \(estimate\): F/.test(await readout()), await readout());
const p1 = await page.$eval("[data-testid='playhead']", (e) => e.style.left);
await sleep(600);
const p2 = await page.$eval("[data-testid='playhead']", (e) => e.style.left);
check("the playhead moves", p1 !== p2, `${p1} -> ${p2}`);
await clickText("button", "Pause");
await sleep(200);
check("pausing pauses", await page.$eval("[data-testid='recording']", (a) => a.paused));

// ---- a real file: 44.1 kHz stereo, through the browser's own decoder and resampler
await upload(tmp("ii-v-i.wav", wav({ rate: 44100, channels: 2, segments: [chord(2, [0, 3, 7, 10], 2.5), chord(7, [0, 4, 7, 10], 2.5), chord(0, [0, 4, 7, 11], 2.5), chord(9, [0, 3, 7, 10], 2.5)] })));
await waitText(/ii-v-i\.wav/);
await waitCells(4);
const c2 = await cells();
check("a stereo 44.1 kHz file is decoded, mixed down and read: Dm7, G7, Cmaj7, Am7", /: Dm7,/.test(c2[0]) && /: G7,/.test(c2[1]) && /: Cmaj7,/.test(c2[2]) && /: Am7,/.test(c2[3]), c2.join(" | "));
check("the file facts say it was stereo and resampled", /2 channels, mixed to mono/.test(await body()) && /44\.1 kHz, analysed at 11\.0 kHz/.test(await body()));
check("this progression fits C major and A minor equally, so the key is honestly uncertain", /nearly as likely|uncertain/i.test(await body()), "");
const tonicSel = await page.evaluateHandle(() => [...document.querySelectorAll("select")].find((s) => s.getAttribute("aria-label") === "Tonic"));
await tonicSel.asElement().select("C");
await sleep(1800);
const c3 = await cells();
check("with the key set to C major the numerals are ii7, V7, Imaj7, vi7", /numeral ii7/.test(c3[0]) && /numeral V7/.test(c3[1]) && /numeral Imaj7/.test(c3[2]) && /numeral vi7/.test(c3[3]), c3.join(" | "));
check("and the key is now marked as chosen by you", /chosen by you/.test(await body()));
await page.screenshot({ path: `${SHOTS}/51-audio-file.png` });

// ---- files that should not produce chords or should be refused
await upload(tmp("silent.wav", wav({ rate: 22050, segments: [{ notes: [], seconds: 4 }] })));
await waitText(/silent\.wav/);
await waitCells(1);
const silent = await cells();
check("a silent recording is one 'no chord' region, not a made-up chord", silent.length === 1 && /no chord/.test(silent[0]), silent.join(" | "));

await upload(tmp("fake.wav", Buffer.from("this is certainly not audio data at all, just some text")));
await waitText(/could not be read as audio/);
check("a file that is not audio gets a clear message", true);
check("and the previous recording is cleared", !(await page.$("[data-testid='recording']")));

await upload(tmp("tiny.wav", wav({ rate: 8000, segments: [{ notes: [60], seconds: 0.2 }] })));
await waitText(/too short/);
check("a recording under half a second is refused with the reason", true);

await upload(tmp("long.wav", wav({ rate: 8000, segments: [{ notes: [60], seconds: 660 }] })));
await waitText(/10 minutes/, 60000);
check("a recording over ten minutes is refused with the reason", true);

// ---- cancelling a long analysis
await upload(tmp("nine-min.wav", wav({ rate: 11025, segments: [{ notes: [60, 64, 67], seconds: 540 }] })));
await page.waitForFunction(() => /Listening for chords|Reading the file/.test(document.body.textContent ?? ""), { timeout: 20000 });
await sleep(400);
await clickText("button", "Cancel");
await sleep(800);
check("an analysis can be cancelled, and nothing is shown for it", !/Listening for chords/.test(await body()) && !(await page.$("[data-testid='recording']")));

// ---- phone
await page.setViewport({ width: 390, height: 800 });
await page.goto("http://localhost:3000/audio", { waitUntil: "networkidle0" });
await clickText("button", "Try an example");
await waitCells(4);
check("no sideways page scroll on a phone", !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
await page.screenshot({ path: `${SHOTS}/52-audio-phone.png` });

const real = errors.filter((e) => !/favicon|Failed to load resource/.test(e));
check("no unexpected browser errors", real.length === 0, real.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
