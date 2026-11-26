# 0014 Account lifecycle, admin tools, two-factor, billing extras and a load test

## Accounts: export, change email, delete

- **Export my data** (`GET /api/v1/account/export`): one JSON file with the profile, plan, payments, saved library (settings, not the MIDI files), practice and theory results, sign-ins, and (for a manager) the institution's logins. Password hashes, two-factor keys and session tokens are never included.
- **Change email**: the person gives their password; a one-time link goes to the NEW address and the email changes only when it is opened. The answer is the same whether or not the address is already registered, so it cannot reveal who has an account. On confirming, every device is signed out, any unused reset or other links sent to the old address are cancelled, and the old address is told.
- **Delete my account** (`POST /api/v1/account/delete`, needs the password, the word DELETE, and a two-factor code if that is on). It erases the name, email, saved library and its files, practice and theory results, sign-ins and subscription. **The user row is kept, blanked** ("Deleted account"), because payment records (plan, amount, date, reference) must be kept for tax and accounting law and they point at it. The email address becomes free to register again. Refused for: institution logins (their manager closes them), the only administrator, and the manager of an institution whose plan is still running (people would lose access). An institution manager whose plan has ended can delete; their logins are closed.

## Administrators

- **People** screen: search by name, email or login ID, filter by role; view a person's plan, institution, saved-work size, devices and payments; close/reopen an account, sign them out everywhere, give or remove the educator and admin roles, reset two-factor for a non-admin who lost their phone. Guards: nobody can close themselves, change their own roles, or remove the last admin; institution logins cannot be closed here or made staff; deleted accounts are hidden.
- **Audit log** (`admin_actions`, add-only): who did what to whom and when, for roles, closing, sign-outs, two-factor resets, payments recorded outside Paystack, and refunds. Actions Paystack triggers are logged as "system (Paystack)". A failed action leaves no log line.
- **Two-factor sign-in** (authenticator app, RFC 6238, checked against the RFC's published test values). The key is stored encrypted (Fernet, keyed from `PIANO_SECRET_KEY`); ten one-time recovery codes are stored as hashes; a code cannot be used twice. **Administrators must have it on to use any admin tool**: on by default in production, off elsewhere (`PIANO_ADMIN_REQUIRE_TWO_FACTOR`). Without it an admin still works as a learner and sees a banner. A lost phone is fixed on the server: `python -m scripts.make_admin EMAIL --reset-2fa` (the screen refuses to reset another admin, so one admin cannot quietly lift another's protection).

## Billing

- **Receipts** are emailed when a payment is confirmed (once, whichever of the return page or webhook arrives first). An email problem never undoes a payment.
- **Upgrades**: an institution manager with a running plan can move to a bigger one and pay only the monthly difference for the time left (rounded up to the next kobo); the end date does not change. The price is computed on the server (the browser's "months" is ignored). Moving to a smaller plan still waits for the period to end.
- **Refunds**: Billing Admin and People have "Take back access" (needs a reason, written to the audit log). It removes the months that payment bought (never earlier than now), or returns an upgrade to the earlier plan if the institution has no more active logins than that plan allows. **It does not return money**: refund in the Paystack dashboard. A *full* refund processed there arrives as a `refund.processed` webhook and takes the access back automatically; partial or unclear refunds are only logged ("needs review") for a person to decide. The shape of Paystack's refund event was taken from its documentation and **has not been tried against Paystack**: test one refund in test mode.

## Library and storage

Search by name (percent and underscore are treated as ordinary characters). `scripts/cleanup_storage.py` lists files with no database row and items whose file is missing; `--delete` removes only the stray files.

## Load test (`scripts/loadtest.py`)

Fifty pretend people signing in at once and then browsing, against the real API on PostgreSQL, on a **one-core 4 GB machine that also ran the load generator**, so these show relative cost and faults, not capacity:

- 52 to 58 requests per second with **zero errors**; typical pages answered in 24 to 39 ms (median), 250 to 330 ms (95th percentile), under 1.1 s (99th).
- A sign-in alone takes 60 to 90 ms; 50 at once took a median of about 3.6 s on one core.
- **Found and fixed: memory.** Every password hash holds about 19 MB while it runs, and all 50 ran together, so the API peaked near **915 MB**. Now each server process hashes at most `PIANO_MAX_CONCURRENT_HASHES` (default 4) at a time and the rest queue (peak 597 MB). Setting `MALLOC_ARENA_MAX=2` (in the Docker image) stops the allocator keeping a pool per worker thread (peak **330 MB**, sign-in time unchanged). A bug in the first version of the limiter (several threads each creating their own on the first burst) was caught by its test and fixed.
- Raise `PIANO_MAX_CONCURRENT_HASHES` on a machine with more cores per process. The idle API is about 120 MB.

## Not done

- Automatic card renewal (Paystack recurring plans), partial refunds, and multi-currency.
- Staging site, a formal penetration test, log shipping, database replication.
- Two-factor with a hardware key (WebAuthn); a QR code for setup (the key and an `otpauth://` link are shown instead).
- Practice time in minutes (the system does not record how long someone practised).
- Load testing at your real size on your real server, from another machine.
