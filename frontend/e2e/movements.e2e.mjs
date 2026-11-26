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
  window.__audio = { oscillators: 0, started: 0 };
  const Real = window.AudioContext;
  window.AudioContext = class extends Real {
    constructor(...a) {
      super(...a);
      const co = this.createOscillator.bind(this);
      this.createOscillator = () => {
        const o = co(); window.__audio.oscillators++;
        const s = o.start.bind(o); o.start = (...x) => { window.__audio.started++; return s(...x); };
        return o;
      };
    }
  };
});

const text = (sel) => page.$eval(sel, (e) => e.textContent ?? "");
const login = async (email) => {
  await page.goto("http://localhost:3000/login", { waitUntil: "networkidle0" });
  await page.type('input[type="email"]', email);
  await page.type('input[type="password"]', "correct horse battery");
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.click('button[type="submit"]')]);
};
const clickText = async (selector, label) => {
  const handle = await page.evaluateHandle((sel, l) => [...document.querySelectorAll(sel)].find((e) => (e.textContent ?? "").trim().startsWith(l)), selector, label);
  const el = handle.asElement();
  if (!el) throw new Error(`no ${selector} starting with "${label}"`);
  await el.click();
};

// ---- learner ----
await login("learner@example.com");
check("learner signed in", !page.url().includes("/login"), page.url());

await page.goto("http://localhost:3000/progressions", { waitUntil: "networkidle0" });
await page.waitForSelector("ul li a[href^='/progressions/']");
const cards = await page.$$eval("a[href^='/progressions/']", (a) => a.length);
check("browse lists the 18 seeded movements", cards === 18, String(cards));
await page.screenshot({ path: `${SHOTS}/10-browse.png` });

await page.type('input[type="search"]', "blues");
await sleep(700);
const bluesCards = await page.$$eval("a[href^='/progressions/']", (a) => a.length);
check("search narrows the list", bluesCards >= 1 && bluesCards < 18, String(bluesCards));
await page.evaluate(() => { const i = document.querySelector('input[type="search"]'); i.value = ""; });
await page.click('input[type="search"]', { clickCount: 3 }); await page.keyboard.press("Backspace");
await sleep(700);

await page.goto("http://localhost:3000/progressions", { waitUntil: "networkidle0" });
await page.waitForSelector("a[href^='/progressions/']");
const href = await page.$$eval("a[href^='/progressions/']", (as) => as.find((a) => /ii.V.I$/.test(a.textContent.split("C major")[0]?.trim() ?? "") || a.getAttribute("href").includes("ii-v-i-c"))?.getAttribute("href"));
check("found the ii-V-I movement", Boolean(href), String(href));
await page.goto(`http://localhost:3000${href}`, { waitUntil: "networkidle0" });
await page.waitForSelector('ol button[aria-current]');

const chords = await page.$$eval("section[aria-label='Intermediate version'] ol > li > button span.text-lg", (e) => e.map((x) => x.textContent));
check("intermediate version is Dm7 G7 Cmaj7", chords.join(" ") === "Dm7 G7 Cmaj7", chords.join(" "));
const marks = await page.$$eval("[role='application'] [aria-label], [aria-label*='left hand'], [aria-label*='right hand']", (e) => e.length).catch(() => 0);
await page.screenshot({ path: `${SHOTS}/11-player-intermediate.png` });

await clickText("button", "Expert");
await sleep(300);
const expert = await page.$$eval("section[aria-label='Expert version'] ol > li > button span.text-lg", (e) => e.map((x) => x.textContent));
check("expert version shows the tritone substitute D♭7", expert.join(" ").includes("D♭7"), expert.join(" "));

await page.select("select:has(option[value=''])", "beginner").catch(() => {});
const compareSel = await page.evaluateHandle(() => [...document.querySelectorAll("select")].find((s) => [...s.options].some((o) => o.textContent === "Nothing")));
await compareSel.asElement().select("beginner");
await sleep(300);
const sections = await page.$$eval("section[aria-label$=' version']", (s) => s.map((x) => x.getAttribute("aria-label")));
check("compare shows two versions side by side", sections.length === 2, sections.join(","));
await page.screenshot({ path: `${SHOTS}/12-compare.png` });

// hand isolation: right hand only removes left-hand marks from the keyboard
const handMarks = () => page.evaluate(() => ({
  left: document.querySelectorAll('[aria-label*="left hand"]').length,
  right: document.querySelectorAll('[aria-label*="right hand"]').length,
}));
const both = await handMarks();
await clickText("button", "Right hand only");
await sleep(200);
const rOnly = await handMarks();
check("right hand only hides the left-hand notes", both.left > 0 && rOnly.left === 0 && rOnly.right > 0, JSON.stringify({ both, rOnly }));
await clickText("button", "Both hands");

// playback
await clickText("button", "Play");
await sleep(1500);
const audio = await page.evaluate(() => window.__audio);
check("playback starts real audio oscillators", audio.started > 0, JSON.stringify(audio));
const playing = await page.$$eval("[aria-live='polite']", (e) => e.map((x) => x.textContent).join("|"));
check("readout says Playing", /Playing/.test(playing), playing);
await clickText("button", "Stop");
await sleep(200);

// transposition
const keySel = await page.evaluateHandle(() => [...document.querySelectorAll("select")].find((s) => [...s.options].some((o) => /original/.test(o.textContent))));
await keySel.asElement().select("Eb");
await page.waitForFunction(() => /Fm7/.test(document.body.textContent), { timeout: 8000 }).catch(() => {});
const body = await page.evaluate(() => document.body.textContent);
const expertEb = await page.$$eval("section[aria-label='Expert version'] ol > li > button span.text-lg", (e) => e.map((x) => x.textContent));
check("transposing to E♭: expert is Fm7 E7 E♭maj7 (tritone sub spelled E7)", expertEb.join(" ") === "Fm7 E7 E♭maj7", expertEb.join(" "));
check("transposed view is labelled as built just now", /Built just now/.test(body));
await page.screenshot({ path: `${SHOTS}/13-transposed.png` });

// learner may not see admin
await page.goto("http://localhost:3000/admin", { waitUntil: "networkidle0" });
check("learner gets not-found on /admin", /could not be found|not found|404/i.test(await page.evaluate(() => document.body.textContent)));
const adminApi = await page.evaluate(async () => (await fetch("/api/v1/admin/movements")).status);
check("API refuses learner on admin route (403)", adminApi === 403, String(adminApi));

// phone width
await page.setViewport({ width: 390, height: 800 });
await page.goto(`http://localhost:3000${href}`, { waitUntil: "networkidle0" });
await page.waitForSelector("ol button");
const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
check("no sideways page scroll on a phone", !overflow);
await page.screenshot({ path: `${SHOTS}/14-player-phone.png` });
await page.setViewport({ width: 1280, height: 900 });

// ---- educator ----
await page.evaluate(() => fetch("/api/v1/auth/logout", { method: "POST" }));
await login("teacher@example.com");
await page.goto("http://localhost:3000/admin", { waitUntil: "networkidle0" });
await page.waitForSelector("section[aria-label='Movements'] li");
const adminRows = await page.$$eval("section[aria-label='Movements'] li", (e) => e.length);
check("educator sees all 18 in Content Admin", adminRows === 18, String(adminRows));

await clickText("button", "New movement");
await page.waitForSelector("form[aria-label='New movement']");
await page.type("form[aria-label='New movement'] input[maxlength='120']", "Browser test ii-V-I");
await page.select("form[aria-label='New movement'] select", "ii_v_i");
await clickText("button", "Save");
await page.waitForSelector("section[aria-label='Selected movement']");
check("created movement starts as a draft", /Draft/.test(await text("section[aria-label='Selected movement']")));

await clickText("button", "Check");
await page.waitForFunction(() => /Not ready to publish/.test(document.body.textContent), { timeout: 8000 });
check("check lists what blocks publishing (tag and explanation)", /tag/i.test(await page.evaluate(() => document.body.textContent)));
await page.screenshot({ path: `${SHOTS}/15-admin-blockers.png` });

await clickText("button", "Edit");
await page.waitForSelector("form[aria-label='Edit movement']");
await page.type("form[aria-label='Edit movement'] input[placeholder='jazz, turnaround']", "jazz");
await page.type("form[aria-label='Edit movement'] textarea", "ii leads to V, which resolves to I.");
await clickText("button", "Save");
await page.waitForFunction(() => /revision 2/.test(document.body.textContent), { timeout: 8000 });
check("editing bumps the revision", true);

for (const label of ["Submit for review", "Approve", "Publish"]) {
  await clickText("button", label);
  const want = { "Submit for review": "In review ·", Approve: "Approved ·", Publish: "Published ·" }[label];
  await page.waitForFunction((w) => (document.querySelector("section[aria-label='Selected movement']")?.textContent ?? "").includes(w), { timeout: 8000 }, want);
}
check("walks draft -> review -> approved -> published", /Published · revision/.test(await text("section[aria-label='Selected movement']")));
await page.screenshot({ path: `${SHOTS}/16-admin-published.png` });

await page.goto("http://localhost:3000/progressions", { waitUntil: "networkidle0" });
await page.waitForSelector("a[href^='/progressions/']");
check("published movement now appears for learners (19)", (await page.$$eval("a[href^='/progressions/']", (a) => a.length)) === 19);

const real = errors.filter((e) => !/favicon|Failed to load resource.*(403|404)/.test(e));
check("no unexpected browser errors", real.length === 0, real.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
