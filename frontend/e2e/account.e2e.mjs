// Account and admin features in a real browser: two-factor, change email, export, delete account,
// the People admin screen, refunds, the upgrade offer, and library search.
import chromium from "@sparticuz/chromium";
import puppeteer from "puppeteer-core";
import { createHmac } from "node:crypto";
import { mkdirSync } from "node:fs";
const SHOTS = process.env.SHOTS_DIR ?? "/tmp/shots";
mkdirSync(SHOTS, { recursive: true });
const BASE = process.env.BASE ?? "http://localhost:3000";
const API = process.env.API ?? "http://localhost:8000";
const PW = "correct horse battery";
let failed = 0;
const check = (name, ok, detail = "") => { if (!ok) failed++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  -> " + detail}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// RFC 6238, the same codes an authenticator app makes
function totp(secret, stepOffset = 0) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = ""; for (const c of secret.replace(/\s/g, "").toUpperCase()) bits += alphabet.indexOf(c).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const step = Math.floor(Date.now() / 30000) + stepOffset;
  const buf = Buffer.alloc(8); buf.writeBigUInt64BE(BigInt(step));
  const h = createHmac("sha1", key).update(buf).digest();
  const o = h[h.length - 1] & 15;
  return String(((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000)).padStart(6, "0");
}

const browser = await puppeteer.launch({ executablePath: await chromium.executablePath(), args: [...chromium.args.filter((a) => !/web-security/.test(a)), "--no-sandbox"], headless: "shell" });
async function newSession() {
  const b = await puppeteer.launch({ executablePath: await chromium.executablePath(), args: [...chromium.args.filter((a) => !/web-security/.test(a)), "--no-sandbox"], headless: "shell" });
  const page = await b.newPage();
  await page.setViewport({ width: 1280, height: 1000 });
  page.on("dialog", async (d) => { await d.accept(d.type() === "prompt" ? "customer asked for it" : undefined); });
  return { b, page };
}
const text = (page) => page.evaluate(() => document.body.innerText);
const go = (page, p) => page.goto(`${BASE}${p}`, { waitUntil: "networkidle0" });
const waitText = (page, t, ms = 15000) => page.waitForFunction((t) => document.body.innerText.includes(t), { timeout: ms }, t);
const clickText = (page, sel, t) => page.evaluate((sel, t) => { const el = [...document.querySelectorAll(sel)].find((e) => e.innerText.trim().startsWith(t)); if (!el) throw new Error(`no ${sel} "${t}"`); el.click(); }, sel, t);
const setInput = (page, labelStart, value) => page.evaluate((labelStart, value) => {
  // Labels either wrap their input or point to it with for/id; handle both. Take the visible one.
  const found = [...document.querySelectorAll("label")].filter((x) => x.innerText.trim().startsWith(labelStart)).map((l) => l.control ?? l.querySelector("input,select")).filter(Boolean);
  const i = found.find((el) => el.offsetParent !== null) ?? found[0];
  if (!i) throw new Error(`no field "${labelStart}"`);
  const proto = i.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value").set.call(i, value);
  i.dispatchEvent(new Event(i.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
}, labelStart, value);
async function signIn(page, who, pw = PW) {
  await go(page, "/login");
  await page.type('input[autocomplete="username"]', who);
  await page.type('input[type="password"]', pw);
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.click('button[type="submit"]')]);
}

const L = await newSession(); // learner
const A = await newSession(); // admin
try {
  // ---------------------------------------------------------------- two-factor
  await signIn(L.page, "learner@example.com");
  await go(L.page, "/settings");
  await clickText(L.page, "button", "Set up two-factor");
  await waitText(L.page, "enter this key");
  const key = await L.page.evaluate(() => document.querySelector('[aria-label="Setup key"]').innerText);
  check("setup shows a key to type into an authenticator app", /^[A-Z2-7 ]{30,}$/.test(key), key);
  await setInput(L.page, "Code", totp(key));
  await clickText(L.page, "button", "Turn on two-factor");
  await waitText(L.page, "Save these recovery codes");
  const codes = await L.page.evaluate(() => [...document.querySelectorAll('[aria-label="Recovery codes"] li')].map((li) => li.innerText));
  check("ten recovery codes are shown once", codes.length === 10 && codes.every((c) => /^[a-z2-9]{5}-[a-z2-9]{5}$/.test(c)), codes.join(","));
  await L.page.screenshot({ path: `${SHOTS}/acct-recovery.png`, fullPage: true });
  await clickText(L.page, "button", "I have saved them");
  await waitText(L.page, "Two-factor sign-in is on");
  check("settings now say two-factor is on", true);

  // sign out, then sign in again: password, then the code
  await clickText(L.page, "button", "Sign out").catch(() => {});
  await L.page.waitForFunction(() => location.pathname === "/login" || location.pathname === "/", { timeout: 10000 }).catch(() => {});
  await go(L.page, "/login");
  await L.page.type('input[autocomplete="username"]', "learner@example.com");
  await L.page.type('input[type="password"]', PW);
  await L.page.click('button[type="submit"]');
  await waitText(L.page, "Enter the 6-digit code");
  check("signing in now asks for the code", true);
  await L.page.screenshot({ path: `${SHOTS}/acct-2fa-login.png` });
  await setInput(L.page, "Code", "000000");
  await L.page.click('button[type="submit"]');
  await waitText(L.page, "not right");
  check("a wrong code is refused", true);
  await setInput(L.page, "Code", totp(key, 1)); // next step: the enabling code is already used
  await Promise.all([L.page.waitForNavigation({ waitUntil: "networkidle0" }), L.page.click('button[type="submit"]')]);
  check("the right code signs in", L.page.url().includes("/dashboard"), L.page.url());

  // ---------------------------------------------------------------- export, email change
  await go(L.page, "/settings");
  const exported = await L.page.evaluate(async () => { const r = await fetch("/api/v1/account/export"); return { ok: r.ok, disp: r.headers.get("content-disposition"), body: await r.json() }; });
  check("export downloads my data as a file", exported.ok && /attachment/.test(exported.disp) && exported.body.profile.email === "learner@example.com" && !JSON.stringify(exported.body).includes("password_hash"));
  await setInput(L.page, "New email", "learner.new@example.com");
  await setInput(L.page, "Your password", PW);
  await clickText(L.page, "button", "Send confirmation link");
  await waitText(L.page, "we sent a link");
  check("change email says a link was sent", true);
  const mails = await (await fetch(`${API}/__e2e/outbox`)).json();
  const mail = mails.reverse().find((m) => m.to === "learner.new@example.com");
  const token = mail && /token=([\w-]+)/.exec(mail.body)?.[1];
  check("the link went to the NEW address", !!token);
  const confirmPage = await browser.newPage();
  await confirmPage.goto(`${BASE}/confirm-email-change?token=${token}`, { waitUntil: "networkidle0" });
  await clickText(confirmPage, "button", "Confirm my new email");
  await waitText(confirmPage, "Your email was changed");
  check("opening the link changes the email", true);
  await confirmPage.close();
  await go(L.page, "/settings");
  check("old session was signed out, so settings sends me to sign in", L.page.url().includes("/login"), L.page.url());
  // sign in with the new address (+ code)
  await L.page.type('input[autocomplete="username"]', "learner.new@example.com");
  await L.page.type('input[type="password"]', PW);
  await L.page.click('button[type="submit"]');
  await waitText(L.page, "Enter the 6-digit code");
  await setInput(L.page, "Code", codes[0]); // a recovery code works too
  await Promise.all([L.page.waitForNavigation({ waitUntil: "networkidle0" }), L.page.click('button[type="submit"]')]);
  check("the new email works, and a recovery code signs in", L.page.url().includes("/dashboard"), L.page.url());

  // ---------------------------------------------------------------- library search
  await go(L.page, "/midi");
  await clickText(L.page, "button", "Try an example");
  await L.page.waitForFunction(() => [...document.querySelectorAll("label")].some((l) => l.innerText.trim().startsWith("Name") && l.querySelector("input")), { timeout: 30000 });
  await setInput(L.page, "Name", "Moonlight etude");
  await clickText(L.page, "button", "Save to My Library");
  await waitText(L.page, 'Saved as "Moonlight etude"');
  await go(L.page, "/progressions");
  await go(L.page, await L.page.evaluate(() => document.querySelector('a[href^="/progressions/"]').getAttribute("href")));
  await L.page.waitForFunction(() => [...document.querySelectorAll("label")].some((l) => l.innerText.trim().startsWith("Name") && l.querySelector("input")), { timeout: 20000 });
  await setInput(L.page, "Name", "Autumn changes");
  await clickText(L.page, "button", "Save to My Library");
  await waitText(L.page, 'Saved as "Autumn changes"');
  await go(L.page, "/library");
  await setInput(L.page, "Search by name", "moon");
  await L.page.waitForFunction(() => document.body.innerText.includes("Moonlight etude") && !document.body.innerText.includes("Autumn changes"), { timeout: 8000 });
  check("library search narrows the list as you type", true);
  await setInput(L.page, "Search by name", "zzzz");
  await waitText(L.page, "Nothing matches that name");
  check("and says so when nothing matches", true);

  // ---------------------------------------------------------------- admin: people, payments, refund
  await signIn(A.page, "admin@example.com");
  await go(A.page, "/people");
  await waitText(A.page, "Find people");
  await setInput(A.page, "Name, email or login ID", "learner.new");
  await A.page.waitForFunction(() => document.querySelectorAll("tbody tr").length === 1 && document.body.innerText.includes("learner.new@example.com"), { timeout: 8000 });
  check("admin can search for a person", true);
  await clickText(A.page, "button", "View");
  await waitText(A.page, "Saved work");
  check("and see their plan and saved work", (await text(A.page)).includes("2 items"));
  await A.page.screenshot({ path: `${SHOTS}/acct-people.png`, fullPage: true });
  await clickText(A.page, "button", "Make educator"); // confirm dialog accepted by the handler
  await waitText(A.page, "Educator role given");
  check("admin can give a role", true);
  await clickText(A.page, "button", "Show");
  await waitText(A.page, "Gave a role (educator)");
  check("the audit log records it", (await text(A.page)).includes("admin@example.com"));

  // record a bank transfer for the learner, then take it back
  await go(A.page, "/billing-admin");
  await setInput(A.page, "Customer's email", "learner.new@example.com");
  await A.page.click('button[type="submit"]');
  await waitText(A.page, "2. Record the payment");
  await clickText(A.page, "button", "Record payment and give access");
  await waitText(A.page, "Recorded.");
  await waitText(A.page, "Recorded by admin");
  await clickText(A.page, "button", "Take back access");
  await waitText(A.page, "Access taken back");
  await A.page.waitForFunction(() => document.body.innerText.includes("Refunded"), { timeout: 8000 });
  check("a recorded payment can be refunded from Billing Admin", true);

  // institution plan -> upgrade offer for the learner
  await setInput(A.page, "Plan", "institution_10");
  await setInput(A.page, "Institution name", "Grace School");
  await clickText(A.page, "button", "Record payment and give access");
  await A.page.waitForFunction(() => (document.body.innerText.match(/Recorded\./g) || []).length >= 1 && document.body.innerText.includes("Institution, 10 people"), { timeout: 10000 });
  await go(L.page, "/subscription");
  await waitText(L.page, "Upgrade your institution plan", 15000);
  const up = await text(L.page);
  check("an institution manager is offered an upgrade at a prorated price", /Institution, 20 people/.test(up) && /₦(69,9\d\d|70,000)/.test(up), up.slice(0, 500));
  await L.page.screenshot({ path: `${SHOTS}/acct-upgrade.png`, fullPage: true });

  // ---------------------------------------------------------------- delete account (a throwaway account)
  const T = await newSession();
  await signIn(T.page, "teacher@example.com");
  await go(T.page, "/settings");
  // The page has several password fields; fill the ones inside the Delete account form.
  const fillDelete = (labelStart, value) => T.page.evaluate((labelStart, value) => {
    const f = [...document.querySelectorAll("form")].find((x) => x.innerText.includes("Type DELETE"));
    const el = [...f.querySelectorAll("label")].find((l) => l.innerText.trim().startsWith(labelStart)).control;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, labelStart, value);
  await fillDelete("Password", PW);
  const deleteButtonDisabled = await T.page.evaluate(() => [...document.querySelectorAll("button")].find((b) => b.innerText.includes("Delete my account")).disabled);
  check("delete stays disabled until DELETE is typed", deleteButtonDisabled === true);
  await fillDelete("Type DELETE", "DELETE");
  await T.page.evaluate(() => [...document.querySelectorAll("button")].find((b) => b.innerText.includes("Delete my account")).click());
  await T.page.waitForFunction(() => location.pathname === "/", { timeout: 15000 });
  check("deleting the account signs out and returns to the start page", true);
  const after = await fetch(`${API}/api/v1/auth/login`, { method: "POST", headers: { "Content-Type": "application/json", Origin: "http://localhost:3000" }, body: JSON.stringify({ identifier: "teacher@example.com", password: PW }) });
  check("that account can no longer sign in", after.status === 401, String(after.status));
  await T.b.close();
} catch (e) { failed++; console.log("FAIL  script error ->", e.message); for (const [n, s] of [["L", L], ["A", A]]) await s.page.screenshot({ path: `${SHOTS}/acct-error-${n}.png`, fullPage: true }).catch(() => {}); }
await L.b.close(); await A.b.close(); await browser.close();
console.log(failed ? `${failed} FAILED` : "ALL PASSED");
process.exit(failed ? 1 : 0);
