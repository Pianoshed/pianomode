import chromium from "@sparticuz/chromium";
import puppeteer from "puppeteer-core";
import { mkdirSync } from "node:fs";
const SHOTS = process.env.SHOTS_DIR ?? "/tmp/shots";
mkdirSync(SHOTS, { recursive: true });
const BASE = "http://localhost:3000";
let failed = 0;
const check = (name, ok, detail = "") => { if (!ok) failed++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  -> " + detail}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await puppeteer.launch({
  executablePath: await chromium.executablePath(),
  args: [...chromium.args.filter((a) => !/web-security/.test(a)), "--no-sandbox"],
  headless: "shell",
});

async function signIn(page, who, pw = "correct horse battery") {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle0" });
  await page.type('input[autocomplete="username"]', who);
  await page.type('input[type="password"]', pw);
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.click('button[type="submit"]')]);
}

try {
  // --- learner on a trial
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await signIn(page, "learner@example.com");
  check("learner lands in the app", page.url().includes("/dashboard"), page.url());
  const btn = await page.$('a.animate-subscribe-pulse');
  check("Subscribe button is in the sidebar", !!btn);
  const anim = btn ? await page.evaluate((e) => getComputedStyle(e).animationName, btn) : "";
  check("it pulses", anim.includes("subscribe-pulse"), anim);
  await page.screenshot({ path: `${SHOTS}/sub-dashboard.png` });
  const txt = btn ? await page.evaluate((e) => e.textContent, btn) : "";
  check("label says Subscribe", txt.trim() === "Subscribe", txt);

  // reduced motion switches the pulse off
  await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
  const still = await page.evaluate((e) => getComputedStyle(e).animationName, await page.$('a.animate-subscribe-pulse'));
  check("reduced motion stops the pulse", still === "none", still);
  await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "no-preference" }]);

  // learning pages still open during the trial
  await page.goto(`${BASE}/theory`, { waitUntil: "networkidle0" });
  check("trial can open /theory", page.url().endsWith("/theory"), page.url());

  // subscription page
  await page.goto(`${BASE}/subscription`, { waitUntil: "networkidle0" });
  check("button hidden on the Subscription page", !(await page.$('a.animate-subscribe-pulse')));
  const body = await page.evaluate(() => document.body.innerText);
  check("shows trial status", /Free trial: \d+ days? left/.test(body));
  check("shows the three prices", body.includes("₦15,000") && body.includes("₦80,000") && body.includes("₦150,000"));
  await page.evaluate(() => [...document.querySelectorAll("label")].find((l) => l.innerText.includes("10 people")).click());
  await page.evaluate(() => { const i = document.querySelector('input[type="number"]'); i.focus(); });
  await page.keyboard.down("Control"); await page.keyboard.press("A"); await page.keyboard.up("Control");
  await page.keyboard.type("3");
  await sleep(200);
  const total = await page.evaluate(() => document.body.innerText.match(/Total ₦[\d,]+/)?.[0]);
  check("institution x 3 months totals ₦240,000", total === "Total ₦240,000", String(total));
  check("institution name asked for", (await page.evaluate(() => document.body.innerText)).includes("Institution name"));
  await page.screenshot({ path: `${SHOTS}/sub-page.png`, fullPage: true });

  // phone width
  await page.setViewport({ width: 390, height: 800 });
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle0" });
  const mobileBtn = await page.$('header > div > a.animate-subscribe-pulse');
  check("compact Subscribe button in the phone header", !!mobileBtn);
  await page.screenshot({ path: `${SHOTS}/sub-phone.png` });

  // --- admin
  const browser2 = await puppeteer.launch({
    executablePath: await chromium.executablePath(),
    args: [...chromium.args.filter((a) => !/web-security/.test(a)), "--no-sandbox"],
    headless: "shell",
  });
  const admin = await browser2.newPage();
  await admin.setViewport({ width: 1280, height: 900 });
  await signIn(admin, "admin@example.com");
  check("admin sees no Subscribe button", !(await admin.$('a.animate-subscribe-pulse')));
  await admin.goto(`${BASE}/billing-admin`, { waitUntil: "networkidle0" });
  await admin.type('input[type="email"]', "learner@example.com");
  await admin.click('button[type="submit"]');
  await admin.waitForFunction(() => document.body.innerText.includes("Test User"), { timeout: 8000 });
  check("lookup finds the customer", true);
  admin.on("dialog", (d) => d.accept());
  await admin.evaluate(() => [...document.querySelectorAll("button")].find((b) => b.innerText.includes("Record payment")).click());
  await admin.waitForFunction(() => document.body.innerText.includes("Recorded."), { timeout: 8000 });
  await admin.waitForFunction(() => document.body.innerText.includes("Recorded by admin"), { timeout: 8000 }).catch(() => {});
  const adminText = await admin.evaluate(() => document.body.innerText);
  check("bank transfer recorded", adminText.includes("Recorded by admin") && adminText.includes("₦15,000"));
  await admin.screenshot({ path: `${SHOTS}/sub-admin.png`, fullPage: true });
  await admin.evaluate(() => [...document.querySelectorAll("button")].find((b) => b.innerText.includes("Send plan-ending emails now")).click());
  await admin.waitForFunction(() => /Sent \d+\./.test(document.body.innerText), { timeout: 8000 });
  check("reminder run reports back", true);

  // learner now paid: button gone (30 days left)
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle0" });
  check("after payment the button is gone", !(await page.$('a.animate-subscribe-pulse')));
  check("dashboard says Individual plan", (await page.evaluate(() => document.body.innerText)).includes("Individual plan"));
  await page.goto(`${BASE}/billing-admin`, { waitUntil: "networkidle0" });
  check("learner cannot open Billing Admin", /not found|404/i.test(await page.evaluate(() => document.body.innerText)));
  await browser2.close();
} catch (e) {
  failed++;
  console.log("FAIL  script error ->", e.message);
}
await browser.close();
console.log(failed ? `${failed} FAILED` : "ALL PASSED");
process.exit(failed ? 1 : 0);
