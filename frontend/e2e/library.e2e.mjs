// My Library end to end, in a real browser against the production build: save a MIDI project,
// a progression and an audio analysis, reopen each from My Library, and check what came back.
import chromium from "@sparticuz/chromium";
import puppeteer from "puppeteer-core";
import { mkdirSync } from "node:fs";
const SHOTS = process.env.SHOTS_DIR ?? "/tmp/shots";
mkdirSync(SHOTS, { recursive: true });
const BASE = process.env.BASE ?? "http://localhost:3000";
let failed = 0;
const check = (name, ok, detail = "") => { if (!ok) failed++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  -> " + detail}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await puppeteer.launch({ executablePath: await chromium.executablePath(), args: [...chromium.args.filter((a) => !/web-security/.test(a)), "--no-sandbox"], headless: "shell" });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 1000 });
const text = () => page.evaluate(() => document.body.innerText);
const clickText = (sel, t) => page.evaluate((sel, t) => { const el = [...document.querySelectorAll(sel)].find((e) => e.innerText.trim().startsWith(t)); if (!el) throw new Error(`no ${sel} "${t}"`); el.click(); }, sel, t);
const waitName = (ms = 30000) => page.waitForFunction(() => [...document.querySelectorAll("label")].some((l) => l.innerText.trim().startsWith("Name") && l.querySelector("input")), { timeout: ms });
const waitText = (t, ms = 15000) => page.waitForFunction((t) => document.body.innerText.includes(t), { timeout: ms }, t);
const go = (p) => page.goto(`${BASE}${p}`, { waitUntil: "networkidle0" });
page.on("dialog", (d) => d.accept());

try {
  await go("/login");
  await page.type('input[autocomplete="username"]', "learner@example.com");
  await page.type('input[type="password"]', "correct horse battery");
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.click('button[type="submit"]')]);

  // ---------- empty library
  await go("/library");
  check("empty library explains itself", (await text()).includes("Nothing saved yet"));

  // ---------- MIDI: change a setting, save
  await go("/midi");
  await clickText("button", "Try an example");
  await waitName();
  await page.evaluate(() => { const l = [...document.querySelectorAll("label")].find((x) => x.innerText.includes("Chords every")); const s = l.querySelector("select"); s.value = "bar"; s.dispatchEvent(new Event("change", { bubbles: true })); });
  await page.evaluate(() => { const i = [...document.querySelectorAll("label")].find((l) => l.innerText.trim().startsWith("Name")).querySelector("input"); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set; set.call(i, "My etude in C"); i.dispatchEvent(new Event("input", { bubbles: true })); });
  await clickText("button", "Save to My Library");
  await waitText('Saved as "My etude in C"');
  check("MIDI project saved", true);
  await page.screenshot({ path: `${SHOTS}/lib-midi-saved.png`, fullPage: true });
  check("after saving, the button becomes Save changes", (await text()).includes("Save changes") && (await text()).includes("Save as a new copy"));

  // ---------- progression: change tempo, save
  await go("/progressions");
  const first = await page.evaluate(() => document.querySelector('a[href^="/progressions/"]')?.getAttribute("href"));
  await go(first);
  await waitName();
  await page.evaluate(() => { const r = document.querySelector('input[type="range"]'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set; set.call(r, "123"); r.dispatchEvent(new Event("input", { bubbles: true })); r.dispatchEvent(new Event("change", { bubbles: true })); });
  await page.evaluate(() => { const i = [...document.querySelectorAll("label")].find((l) => l.innerText.trim().startsWith("Name")).querySelector("input"); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set; set.call(i, "Fast version"); i.dispatchEvent(new Event("input", { bubbles: true })); });
  await clickText("button", "Save to My Library");
  await waitText('Saved as "Fast version"');
  check("progression saved", true);

  // ---------- audio: save
  await go("/audio");
  await clickText("button", "Try an example");
  await waitName(60000);
  await page.evaluate(() => { const i = [...document.querySelectorAll("label")].find((l) => l.innerText.trim().startsWith("Name")).querySelector("input"); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set; set.call(i, "Example take"); i.dispatchEvent(new Event("input", { bubbles: true })); });
  await sleep(500);
  await clickText("button", "Save to My Library");
  await waitText('Saved as "Example take"');
  check("audio analysis saved", true);

  // ---------- the library lists all three
  await go("/library");
  const lib = await text();
  check("library lists the three saved items", ["My etude in C", "Fast version", "Example take"].every((t) => lib.includes(t)), lib.slice(0, 400));
  check("kinds and file info are shown", lib.includes("MIDI project") && lib.includes("Audio analysis") && lib.includes("Chord progression") && /\(\d+(\.\d)? (B|KB)\)/.test(lib));
  check("usage line shown", /3 of 200 items/.test(lib));
  await page.screenshot({ path: `${SHOTS}/lib-list.png`, fullPage: true });

  // ---------- tabs
  await clickText('button[role="tab"]', "Progressions");
  const tabbed = await text();
  check("tab filters to one kind", tabbed.includes("Fast version") && !tabbed.includes("My etude in C"));
  await clickText('button[role="tab"]', "All");

  // ---------- dashboard
  await go("/dashboard");
  const dash = await text();
  check("dashboard shows recent projects and saved progression", dash.includes("My etude in C") && dash.includes("Example take") && dash.includes("Fast version"), dash.slice(0, 600));
  await page.screenshot({ path: `${SHOTS}/lib-dashboard.png`, fullPage: true });

  // ---------- reopen MIDI: setting restored
  await go("/library");
  const midiHref = await page.evaluate(() => [...document.querySelectorAll("li")].find((li) => li.innerText.includes("My etude in C")).querySelector('a[href^="/midi?project="]').getAttribute("href"));
  await go(midiHref);
  await waitText("Save changes", 20000);
  const grid = await page.evaluate(() => [...document.querySelectorAll("label")].find((x) => x.innerText.includes("Chords every")).querySelector("select").value);
  check("reopened MIDI project has its saved setting back", grid === "bar", grid);
  check("and shows the original file", (await text()).includes("C - Am - F - G7 (example).mid"));

  // ---------- reopen progression: tempo restored
  await go("/library");
  await clickText('button[role="tab"]', "Progressions");
  await clickText("button", "Open");
  await page.waitForFunction(() => location.pathname.startsWith("/progressions/"), { timeout: 15000 });
  await waitName();
  const tempo = await page.evaluate(() => document.querySelector('input[type="range"]').value);
  check("reopened progression has its saved tempo", tempo === "123", tempo);

  // ---------- reopen audio: asks for the recording
  await go("/library");
  const audioHref = await page.evaluate(() => [...document.querySelectorAll("li")].find((li) => li.innerText.includes("Example take")).querySelector('a[href^="/audio?project="]').getAttribute("href"));
  await go(audioHref);
  await waitText("Choose the same recording", 20000);
  check("reopened audio analysis asks for the same recording", true);
  await page.screenshot({ path: `${SHOTS}/lib-audio-reopen.png`, fullPage: true });

  // ---------- download and delete
  await go("/library");
  const dl = await page.evaluate(() => [...document.querySelectorAll("li")].find((li) => li.innerText.includes("My etude in C")).querySelector("a[download]")?.getAttribute("href"));
  const bytesOk = await page.evaluate(async (u) => { const b = new Uint8Array(await (await fetch(u)).arrayBuffer()); return String.fromCharCode(...b.slice(0, 4)); }, dl);
  check("downloaded file is a real MIDI file", bytesOk === "MThd", bytesOk);
  await page.evaluate(() => [...document.querySelectorAll("li")].find((li) => li.innerText.includes("Fast version")).querySelectorAll("button")[1].click());
  await sleep(300);
  await clickText("button", "Delete").catch(() => {});
  await page.waitForFunction(() => !document.body.innerText.includes("Fast version"), { timeout: 8000 }).then(() => check("delete removes the item", true), () => check("delete removes the item", false, "still listed"));
} catch (e) { failed++; console.log("FAIL  script error ->", e.message); await page.screenshot({ path: `${SHOTS}/lib-error.png`, fullPage: true }).catch(() => {}); }
await browser.close();
console.log(failed ? `${failed} FAILED` : "ALL PASSED");
process.exit(failed ? 1 : 0);
