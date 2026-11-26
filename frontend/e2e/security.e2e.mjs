// Visits every main page of the PRODUCTION build and fails on any Content-Security-Policy
// violation, console error or failed request. Run against `node .next/standalone/server.js`
// (build with NEXT_OUTPUT=standalone) and the e2e API server; see README.md.
import chromium from "@sparticuz/chromium";
import puppeteer from "puppeteer-core";
const BASE = process.env.BASE ?? "http://localhost:3000";
let failed = 0;
const check = (name, ok, detail = "") => { if (!ok) failed++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  -> " + detail}`); };
const browser = await puppeteer.launch({ executablePath: await chromium.executablePath(), args: [...chromium.args.filter((a) => !/web-security/.test(a)), "--no-sandbox"], headless: "shell" });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });
let problems = [];
page.on("console", (m) => { if (m.type() === "error" || /Content Security Policy|Refused to/i.test(m.text())) problems.push(`console: ${m.text().slice(0, 220)}`); });
page.on("pageerror", (e) => problems.push(`pageerror: ${String(e.message).slice(0, 220)}`));
page.on("requestfailed", (r) => /_rsc=/.test(r.url()) && /ABORTED/.test(r.failure()?.errorText ?? "") ? null : problems.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`));
page.on("response", (r) => { if (r.status() >= 500) problems.push(`HTTP ${r.status()}: ${r.url()}`); });

async function visit(path, extra) {
  problems = [];
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle0" });
  if (extra) await extra();
  await new Promise((r) => setTimeout(r, 400));
  check(`${path} loads with no CSP violations or errors`, problems.length === 0, problems.join(" | "));
}

try {
  const res = await page.goto(`${BASE}/login`, { waitUntil: "networkidle0" });
  const h = res.headers();
  const strict = /script-src [^;]*'nonce-/.test(h["content-security-policy"] ?? "");
  console.log(strict ? "  (strict nonce policy is enforced)" : "  (compat policy: inline scripts allowed; set CSP_ENFORCE_STRICT=true to test strict)");
  check("CSP header present", /default-src 'self'/.test(h["content-security-policy"] ?? ""));
  check("clickjacking blocked", h["x-frame-options"] === "DENY" && /frame-ancestors 'none'/.test(h["content-security-policy"] ?? ""));
  check("no X-Powered-By", !h["x-powered-by"]);

  await visit("/");
  await visit("/terms"); await visit("/privacy"); await visit("/refunds");
  await visit("/login", async () => {});
  await page.type('input[autocomplete="username"]', "learner@example.com");
  await page.type('input[type="password"]', "correct horse battery");
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.click('button[type="submit"]')]);
  check("sign-in works under the policy", page.url().includes("/dashboard"), page.url());

  await visit("/dashboard");
  await visit("/piano", async () => {
    await page.evaluate(() => document.querySelector("[data-note], [aria-label*='C4'], button[aria-label*='C']")?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true })));
  });
  await visit("/practice"); await visit("/learn"); await visit("/progressions"); await visit("/theory");
  await visit("/midi"); await visit("/audio");
  await visit("/subscription"); await visit("/settings"); await visit("/library");
  await visit("/confirm-email-change?token=not-a-real-token");
} catch (e) { failed++; console.log("FAIL  script error ->", e.message); }
await browser.close();
console.log(failed ? `${failed} FAILED` : "ALL PASSED");
process.exit(failed ? 1 : 0);
