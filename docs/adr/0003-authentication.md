# ADR 0003 — Authentication and sessions

**Status:** accepted

- **Sessions, not JWTs.** Login creates a row in `user_sessions` and sets an opaque random cookie (`HttpOnly`, `SameSite=Lax`, `Secure` in production). Only the SHA-256 of the cookie is stored. Sessions can be revoked instantly (logout, password change/reset, account closure). Lifetime: 14 days absolute, 7 days idle.
- **Passwords:** Argon2id at the OWASP minimum cost (19 MiB, t=2, p=1), rehashed on login if parameters change. Policy is length-based (10–128). There is no breached-password check yet.
- **No account enumeration:** register, login and password-reset-request return the same responses whether or not the email exists (unknown emails still pay for a hash check). An existing address that is re-registered gets an email instead.
- **Email verification is required to sign in.** Verification and reset tokens are single-use, stored hashed, and expire (24 h / 1 h). Completing a reset also revokes every session.
- **CSRF:** `SameSite=Lax` plus an Origin check on every state-changing request (`enforce_same_origin`, applied app-wide). A request that carries the session cookie but no `Origin` is rejected.
- **Same-origin API access:** the browser calls `/api/*` on the web origin and Next forwards it to FastAPI, so the cookie never crosses origins.
- **Rate limits (per IP and per email):** register 5/h, login 20/15 min and 10/15 min per email, reset request 5/h, and so on. Production requires the Redis limiter, which fails closed (503) if Redis is down.
- **Authorization:** `require_roles(...)` in `app/api/deps.py` is the real gate. The frontend hides admin navigation and 404s the page, but that is presentation only. Jobs are owner-scoped; other users get a 404.

## Known limits
- Email delivery is a console logger in development. Production refuses to send until a real provider is implemented (`app/services/email.py`).
- Behind a reverse proxy, configure trusted forwarded headers on the ASGI server, or every client will share one rate-limit bucket.
- Next streams the page after `loading.tsx`, so a page-level `notFound()` (e.g. `/admin` for a learner) returns HTTP 200 with the not-found screen and a `noindex` tag, not a 404 status. No restricted content is sent.
- No MFA yet (optional in the brief).
- Auth routes run synchronous password hashing in the request thread pool; fine for now, revisit under load.
