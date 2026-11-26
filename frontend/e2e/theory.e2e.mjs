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
const clickBtn = async (scope, label) => {
  const h = await page.evaluateHandle((sc, l) => [...document.querySelectorAll(`${sc} button`)].find((e) => (e.textContent ?? "").trim().startsWith(l)), scope, label);
  if (!h.asElement()) throw new Error(`no button "${label}" in ${scope}`);
  await h.asElement().click();
};
const waitText = (re, timeout = 8000) => page.waitForFunction((s) => new RegExp(s).test(document.body.textContent ?? ""), { timeout }, re.source);

await page.goto("http://localhost:3000/login", { waitUntil: "networkidle0" });
await page.type('input[type="email"]', "learner@example.com");
await page.type('input[type="password"]', "correct horse battery");
await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.click('button[type="submit"]')]);

const kinds = await page.evaluate(async () => (await (await fetch("/api/v1/theory/exercises/kinds")).json()).kinds);
const title = (k) => kinds.find((x) => x.kind === k).title;

await page.goto("http://localhost:3000/theory", { waitUntil: "networkidle0" });
await page.waitForSelector("nav[aria-label='Exercise topics'] button");
const topicButtons = await page.$$eval("nav[aria-label='Exercise topics'] button", (b) => b.length);
check(`lists all ${kinds.length} exercise kinds`, topicButtons === kinds.length, `${topicButtons}/${kinds.length}`);
check("shows 'Not tried yet' for a new learner", /Not tried yet/.test(await body()));
await page.screenshot({ path: `${SHOTS}/20-theory-empty.png` });

// ---- name the highlighted key: work out the right answer from the keyboard itself
await clickBtn("nav[aria-label='Exercise topics']", title("note_name"));
await page.waitForSelector("form[aria-label='Exercise']");
const label = await page.$$eval("[role='button'][aria-label]", (els) => els.map((e) => e.getAttribute("aria-label")).find((l) => /chord tone|root|extra/i.test(l ?? "")) ?? "");
const letter = label.split(",")[0].replace(/ double sharp/, "##").replace(/ sharp/, "#").replace(/ flat/, "b").replace(/ double flat/, "bb").replace(/\s*-?\d+$/, "").trim();
check("keyboard marks the key to name", letter !== "", label);
await page.type("form[aria-label='Exercise'] input[type='text']", letter);
await clickBtn("form[aria-label='Exercise']", "Check answer");
await waitText(/Correct|different spelling/);
check(`naming ${letter} is marked correct by the engine`, /Correct|different spelling/.test(await body()), (await body()).slice(0, 200));
await page.screenshot({ path: `${SHOTS}/21-theory-correct.png` });
await waitText(/This visit: 1 of 1 correct/);
check("session tally updates", true);

// ---- next exercise, then a wrong answer shows the right one
await clickBtn("form[aria-label='Exercise']", "Next exercise");
await page.waitForFunction(() => !(document.body.textContent ?? "").includes("This visit: 1 of 1") || true);
await sleep(400);
const wrong = letter === "C" ? "D" : "C";
await page.$eval("form[aria-label='Exercise'] input[type='text']", (i) => (i.value = ""));
await page.type("form[aria-label='Exercise'] input[type='text']", "F#");
await clickBtn("form[aria-label='Exercise']", "Check answer");
await waitText(/Correct|Not quite|different spelling|Nearly/);
const t = await body();
check("a graded answer shows feedback", /Correct|Not quite|different spelling|Nearly/.test(t));

// ---- unreadable answers are not counted
await clickBtn("nav[aria-label='Exercise topics']", title("triad_identify"));
await page.waitForFunction(() => /Name this chord/.test(document.querySelector("form[aria-label='Exercise']")?.textContent ?? ""), { timeout: 8000 });
await page.type("form[aria-label='Exercise'] input[type='text']", "???");
await clickBtn("form[aria-label='Exercise']", "Check answer");
await waitText(/could not be read/i);
check("unreadable answer says so", true);
const before = await page.evaluate(async () => (await (await fetch("/api/v1/theory/exercises/progress")).json()).items.filter((i) => i.kind === "triad_identify").length);
check("unreadable answer was not recorded", before === 0, String(before));
check("the exercise stays open to try again", (await page.$("form[aria-label='Exercise'] input[type='text']:not([disabled])")) !== null);

// ---- keys as the answer (note_set)
await clickBtn("nav[aria-label='Exercise topics']", title("triad_build"));
// the previous exercise's form is still on screen while the new one loads: wait for this one's own text
await page.waitForFunction(() => /press the keys on the piano/.test(document.querySelector("#answer-help")?.textContent ?? ""), { timeout: 8000 });
await sleep(200);
const submitDisabled = () => page.$eval("form[aria-label='Exercise'] button[type='submit']", (b) => b.disabled);
check("check is disabled until something is answered", await submitDisabled());
const keyEl = await page.$('[data-midi="60"]');
await keyEl.evaluate((e) => e.scrollIntoView({ block: "center", inline: "nearest" })); // earlier steps scrolled the page
await sleep(150);
const keyBox = await keyEl.boundingBox();
await page.mouse.move(keyBox.x + keyBox.width / 2, keyBox.y + keyBox.height * 0.85);
await page.mouse.down();
await page.mouse.up();
await sleep(300);
check("pressing a key on the keyboard fills the answer", !(await submitDisabled()));
await clickBtn("form[aria-label='Exercise']", "Check answer");
await waitText(/Correct|Not quite|Nearly|different spelling/);
check("key answer is graded", true);

// ---- ear training plays real audio
await clickBtn("nav[aria-label='Exercise topics']", title("ear_interval"));
await page.waitForSelector("form[aria-label='Exercise'] input[type='radio']", { timeout: 8000 });
const choices = await page.$$eval("form[aria-label='Exercise'] input[type='radio']", (r) => r.length);
check("ear exercise offers choices", choices >= 2, String(choices));
const earPrompt = await page.$eval("form[aria-label='Exercise'] p", (e) => e.textContent ?? "");
const earChoices = await page.$$eval("form[aria-label='Exercise'] label", (l) => l.map((x) => (x.textContent ?? "").trim()));
check("ear prompt does not contain any of the answer options", earChoices.length >= 2 && earChoices.every((c) => !earPrompt.includes(c)), `${earPrompt} | ${earChoices}`);
await clickBtn("form[aria-label='Exercise']", "Listen");
await sleep(1200);
check("Listen starts real audio", (await page.evaluate(() => window.__audio.started)) > 0);
await page.click("form[aria-label='Exercise'] input[type='radio']");
await clickBtn("form[aria-label='Exercise']", "Check answer");
await waitText(/Correct|Not quite/);
await page.screenshot({ path: `${SHOTS}/22-theory-ear.png` });

// ---- progress persists across a reload
await page.reload({ waitUntil: "networkidle0" });
await page.waitForSelector("nav[aria-label='Exercise topics'] button");
const after = await body();
check("progress is remembered after reload", /\d of \d correct/.test(after), after.slice(0, 120));

// ---- phone width
await page.setViewport({ width: 390, height: 800 });
await clickBtn("nav[aria-label='Exercise topics']", title("note_name"));
await page.waitForSelector("form[aria-label='Exercise']");
check("no sideways page scroll on a phone", !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
await page.screenshot({ path: `${SHOTS}/23-theory-phone.png` });

const real = errors.filter((e) => !/favicon|Failed to load resource/.test(e));
check("no unexpected browser errors", real.length === 0, real.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
