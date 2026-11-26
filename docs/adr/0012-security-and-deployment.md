# 0012 Security hardening and deployment

Decisions behind the production setup. How to deploy is in `docs/deployment.md`.

## Problems found and fixed

- **Every user looked like the same IP address.** The API read the address straight from the connection, which behind a reverse proxy is the proxy. Per-IP limits (login attempts, sign-ups, payments) would have been shared by everybody. Fix: `app/core/net.py` takes the real address from `X-Forwarded-For`, trusting exactly `PIANO_TRUSTED_PROXIES` entries counted from the right (the entries further left can be written by the caller). With 0 the header is ignored, so it cannot be forged in development. Caddy overwrites the header with the true address (verified with a forged header), and the API port is not published, so nothing else can reach it. Server-rendered pages forward the visitor's address to the API (`frontend/lib/server-api.ts`); without that, all page loads would share the web server's address.
- **A school behind one internet connection shared one allowance.** Limits on routes that need sign-in now count per session (`rate_limited(..., by_session=True)`). Anonymous routes (login, sign-up, password reset) still count per address and per email, because a made-up cookie must never earn a fresh allowance.
- **No security headers.** Added: a Content-Security-Policy (own origin only; no outside scripts, frames, objects or form targets), `X-Frame-Options`, `nosniff`, a referrer policy and a permissions policy that still allows MIDI. Checked in a real browser on every page, including audio and MIDI, with no violations (`frontend/e2e/security.e2e.mjs`). The policy still allows inline scripts and styles because Next.js needs them; a stricter nonce-based policy is possible later at the cost of rendering every page dynamically.
- **API responses were cacheable** and server errors were plain text. Responses now carry `Cache-Control: no-store`, `nosniff` and an `X-Request-ID`; unexpected errors return the normal error format with that id and log the real cause without showing it to the caller. API docs are off in production.
- **A migration did not match its model** (a constraint name in `expiry_notices`), found only by running `alembic check` on real PostgreSQL. Fixed, and CI now runs that check, plus downgrade and upgrade.
- **Vulnerable dependencies.** Starlette (via FastAPI) had 14 known advisories; upgraded to FastAPI 0.162.7 / Starlette 1.10.0 with all tests passing. Next.js's bundled PostCSS was flagged; pinned to the patched version. Remaining `npm audit` findings are in Vitest (the test runner) and do not ship.
- **No way to create the first admin**, which would have left Billing Admin and Content Admin unreachable. Added `scripts/make_admin.py` (needs server access, by design).
- **The landing page said** "This is an early build. Most areas of the app are not available yet." Removed.

## Production design

- Caddy is the only public service: it gets and renews HTTPS certificates, sends `/api/*` to the API and everything else to the web app. The database, Redis, API and web ports are not published.
- Images run as a non-root user. The web image is the small Next.js "standalone" server; the API runs several worker processes. Migrations run when the API starts (one API container only).
- Logs are size-capped. One `beat` container runs the daily jobs; run exactly one.
- Startup refuses unsafe production settings: short or default secret, missing Paystack or Resend key, non-https site address, insecure cookies, no proxy configured, in-memory rate limiting.
- Backups: `pg_dump` custom format daily, verified readable before it is kept, 14 days kept. Restoring was tested on a real database: row counts and the schema version matched.
- Locking checks (`tests/test_postgres_concurrency.py`) run on real PostgreSQL in CI: four simultaneous confirmations of one payment grant time once; three simultaneous "add 6 people" requests on a 10-seat plan produce one success.

## Legal pages

`/terms`, `/privacy` and `/refunds` describe what this system actually does (prepaid periods that do not renew, Paystack and Resend as processors, one session cookie, institution logins and the institution's responsibility for its people, Nigeria Data Protection Act rights). They are **drafts**: the refund policy is a business decision made on your behalf as a sensible default, the retention wording is general, and they have not been reviewed by a lawyer. Until `NEXT_PUBLIC_COMPANY_NAME` and `NEXT_PUBLIC_SUPPORT_EMAIL` are set at build time, each page shows a red warning.

## Not done

(Written at phase 9. Two-factor sign-in, data export, self-service deletion and a load-test tool were added later: see `0014`. Automatic rollback and dependency updates: see `0015`.)

Staging environment, penetration test, log shipping, database replication, automatic rollback, and cookie-consent banner (not needed while the only cookie is the sign-in one).
