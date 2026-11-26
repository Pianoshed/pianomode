# 0017 Strict Content-Security-Policy (nonce per request), off by default

The policy allowed `'unsafe-inline'` scripts because Next.js puts small inline scripts in every page. That means a script injected into a page (through some future bug) would run. The strict policy removes that: a script runs only if it carries the random **nonce** generated for that one request (`frontend/middleware.ts`).

## What changed

- The policy moved from `next.config.mjs` to `middleware.ts`, which generates a nonce per request, puts it in the policy (`script-src 'self' 'nonce-…' 'strict-dynamic'`), and hands it to Next.js, which puts it on its own scripts. The theme-setting script in `app/layout.tsx` carries it too.
- **Off by default.** `CSP_ENFORCE_STRICT` (web service, default false) chooses the policy. With it false, behaviour is as before (inline scripts allowed). With it true, the strict policy is enforced.
- Styles still allow `'unsafe-inline'`: React's `style=""` attributes cannot carry a nonce, and a style cannot run code. Everything else in the policy is unchanged (no other origins, no frames, no objects, same-origin forms).
- **Cost:** pages are now rendered on each request instead of being prebuilt (reading the nonce does that), including the terms and privacy pages. For this app (sign-in required almost everywhere) that is small, but the web container does a little more work per page view.

## Checked

Built the production app and requested pages with strict on: every `<script>` tag (15 to 18 per page) carried that request's nonce, and the nonce differed on each request. **Not checked: a real browser.** None was available here. A script without a nonce would be blocked in a browser, so before turning it on:

1. On a test copy, set `CSP_ENFORCE_STRICT=true` and restart `web`.
2. Run `frontend/e2e/security.e2e.mjs` against it (it opens every main page in a real browser and fails on any policy violation or console error), then click through sign-in, piano, MIDI import/export, practice and subscription.
3. If clean, set it in the production `.env` and run `docker compose -f docker-compose.prod.yml up -d web`. If anything breaks, set it back to false: no rebuild needed.

A Report-Only trial is not possible: Next.js attaches nonces only when the nonce is in the enforced header, so a report-only strict policy would report every Next.js script as a violation.

## Not done

Violation reporting (`report-to`) to a collector; nonces for styles; Subresource Integrity.
