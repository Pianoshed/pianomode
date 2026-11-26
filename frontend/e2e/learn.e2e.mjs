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
const waitText = (re, timeout = 8000) => page.waitForFunction((s) => new RegExp(s).test(document.body.textContent ?? ""), { timeout }, re.source);
const clickText = async (selector, label, root = "document") => {
  const h = await page.evaluateHandle((sel, l) => [...document.querySelectorAll(sel)].find((e) => (e.textContent ?? "").trim().startsWith(l)), selector, label);
  if (!h.asElement()) throw new Error(`no ${selector} starting with "${label}"`);
  await h.asElement().click();
};
// Marked keys on the keyboard of the first example on the page (every example has its own keyboard).
const markedKeys = async () => {
  const fig = await page.$("figure");
  return fig.$$eval("[data-midi]", (els) => els.map((e) => e.getAttribute("aria-label")).filter((l) => /root|chord tone|extra/.test(l ?? "")));
};

await page.goto("http://localhost:3000/login", { waitUntil: "networkidle0" });
await page.type('input[type="email"]', "learner@example.com");
await page.type('input[type="password"]', "correct horse battery");
await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.click('button[type="submit"]')]);

// ---- curriculum
await page.goto("http://localhost:3000/learn", { waitUntil: "networkidle0" });
await page.waitForSelector("a[href^='/learn/']");
const total = await page.$$eval("section ul li a[href^='/learn/']", (a) => a.length); // lesson cards only, not the "Start with" button
check("curriculum lists the lessons", total >= 12, String(total));
const headings = await page.$$eval("section h2", (h) => h.map((x) => x.textContent));
check("grouped by level, beginner first", headings[0] === "Beginner" && headings.includes("Advanced"), headings.join(","));
check("starts at 0 practised", new RegExp(`0 of ${total} lessons practised`).test(await body()));
check("suggests starting with the first lesson", /Start with Notes and the keyboard/.test(await body()));
check("later lessons say what they build on", /Builds on Notes and the keyboard/.test(await body()));
await page.screenshot({ path: `${SHOTS}/30-learn.png` });

// ---- a lesson with engine-built examples
await page.goto("http://localhost:3000/learn/triads", { waitUntil: "networkidle0" });
await page.waitForSelector("figure");
check("lesson shows objectives", /What you will learn/.test(await body()));
check("prerequisite advice is shown, not enforced", /This builds on/.test(await body()) && /You can still read on/.test(await body()));
const figs = await page.$$eval("figure", (f) => f.length);
check("lesson has its examples", figs >= 4, String(figs));
const first = await markedKeys();
check("first example marks C, E and G on the keyboard", first.length === 3 && /^C 4/.test(first.find((l) => /root/.test(l))), first.join(" | "));
await clickText("figure:first-of-type button", "Play");
await sleep(1200);
check("Play starts real audio", (await page.evaluate(() => window.__audio.started)) > 0);
await page.screenshot({ path: `${SHOTS}/31-lesson-triads.png`, fullPage: false });

// ---- items of a sequence: numerals come from the engine
await page.goto("http://localhost:3000/learn/diatonic-harmony", { waitUntil: "networkidle0" });
await page.waitForSelector("figure ol button");
const itemTexts = await page.$$eval("figure ol button", (b) => b.map((x) => x.textContent));
check("diatonic chords are labelled with engine Roman numerals", itemTexts.join(" ") === "CI Dmii Emiii FIV GV Amvi Bdimvii°", itemTexts.join(" "));
await clickText("figure ol button", "Dm");
await sleep(300);
const dm = await markedKeys();
check("clicking Dm shows D, F and A", dm.length === 3 && dm.some((l) => /^D 4/.test(l)) && dm.some((l) => /^F 4/.test(l)) && dm.some((l) => /^A 4/.test(l)), dm.join(" | "));

// ---- secondary dominant numeral, and a movement link exists for the progressions lesson
await page.goto("http://localhost:3000/learn/secondary-dominants", { waitUntil: "networkidle0" });
await page.waitForSelector("figure ol button");
check("secondary dominant is named V7/V by the engine", /V7\/V/.test(await body()));
await page.goto("http://localhost:3000/learn/progressions", { waitUntil: "networkidle0" });
await page.waitForSelector("figure");
const link = await page.$$eval("a[href^='/progressions/']", (a) => a.map((x) => x.getAttribute("href")));
check("progressions lesson links to the movement library", link.length === 1, link.join(","));

// ---- lesson -> practice link opens the right exercise
await page.goto("http://localhost:3000/learn/notes-and-keyboard", { waitUntil: "networkidle0" });
await page.waitForSelector("a[href^='/theory?kind=']");
await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), clickText("a", "Practise")]);
check("practice link carries the exercise and level", page.url().includes("kind=note_name") && page.url().includes("level=beginner"), page.url());
await page.waitForSelector("form[aria-label='Exercise']", { timeout: 8000 });
check("the theory screen opened on that exercise by itself", /Name the highlighted key/.test(await body()));

// ---- really practise: answer 5 distinct exercises correctly through the UI
const answerOne = async () => {
  const label = await page.$$eval("[data-midi]", (els) => els.map((e) => e.getAttribute("aria-label")).find((l) => /chord tone|root|extra/i.test(l ?? "")) ?? "");
  const note = label.split(",")[0].replace(/ double sharp/, "##").replace(/ sharp/, "#").replace(/ double flat/, "bb").replace(/ flat/, "b").replace(/\s*-?\d+$/, "").trim();
  await page.$eval("form[aria-label='Exercise'] input[type='text']", (i) => (i.value = ""));
  await page.type("form[aria-label='Exercise'] input[type='text']", note);
  await clickText("form[aria-label='Exercise'] button", "Check answer");
  await waitText(/Correct|different spelling/);
  await clickText("form[aria-label='Exercise'] button", "Next exercise");
  await page.waitForFunction(() => !!document.querySelector("form[aria-label='Exercise'] button[type='submit']") && (document.querySelector("form[aria-label='Exercise'] input[type='text']")?.value ?? "") === "", { timeout: 8000 });
  await sleep(250);
};
for (let i = 0; i < 5; i++) await answerOne();
check("answered five exercises through the UI", true);

await page.goto("http://localhost:3000/learn/notes-and-keyboard", { waitUntil: "networkidle0" });
await page.waitForSelector("h2#practice");
check("practice goal shows 5 of 5", /5 of 5 correct/.test(await body()), (await body()).slice(0, 300));
check("lesson is now Practised", /Practised/.test(await page.$eval("article header", (h) => h.textContent ?? "")));
await page.screenshot({ path: `${SHOTS}/32-lesson-practised.png` });

await page.goto("http://localhost:3000/learn", { waitUntil: "networkidle0" });
await page.waitForSelector("a[href^='/learn/']");
check("curriculum counts 1 practised", new RegExp(`1 of ${total} lessons practised`).test(await body()));
check("next suggestion moves on to Intervals", /Continue with Intervals/.test(await body()), (await body()).slice(0, 200));
await page.goto("http://localhost:3000/learn/intervals", { waitUntil: "networkidle0" });
await page.waitForSelector("figure");
check("Intervals no longer warns about its prerequisite", !/This builds on/.test(await body()));

// ---- errors and phone layout
await page.goto("http://localhost:3000/learn/no-such-lesson", { waitUntil: "networkidle0" });
await waitText(/not found/i);
check("unknown lesson shows a clear error", true);
await page.setViewport({ width: 390, height: 800 });
await page.goto("http://localhost:3000/learn/seventh-chords", { waitUntil: "networkidle0" });
await page.waitForSelector("figure");
check("no sideways page scroll on a phone", !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
await page.screenshot({ path: `${SHOTS}/33-lesson-phone.png` });

const real = errors.filter((e) => !/favicon|Failed to load resource/.test(e));
check("no unexpected browser errors", real.length === 0, real.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
