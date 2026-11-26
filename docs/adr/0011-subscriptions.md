# 0011 Subscriptions, institution logins and Paystack

## What a person can buy (prices in `backend/app/services/plans.py`)

| Plan | Price per month | Who it is for |
|---|---|---|
| Individual | ₦15,000 | One person |
| Institution, 10 people | ₦80,000 | A school, church or studio; 10 separate logins |
| Institution, 20 people | ₦150,000 | The same, 20 logins |

New individual accounts get a free trial (`PIANO_TRIAL_DAYS`, default 7; 0 turns it off). The trial starts the first time the account's access is checked, so accounts that existed before this change also get one.

## How access works

A person can use lessons, theory, practice, movements, piano, MIDI Studio and the Audio Analyzer when **any** of these is true: they are an educator or admin; they hold a login from an institution whose plan is running; they have a paid individual period that has not ended; their trial has not ended.

The API enforces this (HTTP 402, code `subscription_required`, with a `reason`) on `/theory`, `/lessons`, `/movements`, `/practice`. The web app also redirects those pages to `/subscription`. Dashboard, Subscription, Institution Logins, Settings and Admin stay open, so someone whose plan ended can always reach the page that fixes it.

## Payments (Paystack)

- **Prepaid blocks, not auto-charging.** Each payment buys `months` x 30 days (1 to 12). Paying again before the end date adds to it. Nothing is ever charged without the person doing it. Reason: many Nigerian customers pay by bank transfer or USSD, which cannot repeat automatically, and a surprise charge is a support problem. Paystack's recurring Plans (card only) can be added later as an option.
- **The server decides the price.** The browser sends only a plan code and a number of months.
- **Access only after verification.** We call Paystack's verify endpoint and require status `success` and exactly the amount and currency we asked for. An underpayment is recorded as failed and grants nothing.
- **Two ways in, one result.** The page Paystack sends people back to (`/subscription/verify`) and the webhook both call the same idempotent routine (row-locked, keyed by our unique `reference`), so a double delivery cannot add time twice.
- **Webhook authenticity.** `x-paystack-signature` is checked as HMAC-SHA512 of the raw body with the secret key, compared in constant time. If Paystack cannot be reached while verifying, the webhook answers 503 so Paystack retries.
- Card details never reach this system; payment happens on Paystack's page.

**Setup.** Put the secret key in `PIANO_PAYSTACK_SECRET_KEY`. In the Paystack dashboard (Settings > API Keys & Webhooks) set the webhook URL to `https://YOUR-DOMAIN/api/v1/billing/webhooks/paystack`. The return URL is built from `PIANO_PUBLIC_WEB_URL`. Test with `sk_test_` keys and Paystack's test cards before going live.

**Payments made outside Paystack** (bank transfer, cash): an admin calls `POST /api/v1/admin/billing/grant` with `{"email": "...", "plan": "institution_10", "months": 1, "institution_name": "..."}`. It records a `manual_` payment and grants the same access. Admins do this on the **Billing Admin** page (admin role only): find the customer by email, pick the plan and months, confirm. The page also lists recent payments (marked "Recorded by admin" or "Paystack") and has a button that runs the reminder emails now.

## Institutions: one person, one login

- Buying an institution plan creates the **institution** and makes the buyer its **owner**. The owner manages logins at `/institution` but does not take a seat; they can make one for themselves.
- The owner enters names, one per line. Each name becomes its own account with a **login ID** (`ABCD-001`, the institution's 4-letter code plus a number) and a random 12-character password. There is no email on a seat account. Passwords are shown once and only a hash is stored; a lost one is replaced with "New password".
- **Seat cap.** The number of *active* logins can never exceed the plan's seats (checked under a row lock, so two clicks at once cannot slip past). Closing a login frees a place; login numbers are never reused.
- **One device at a time.** Signing in with a seat login signs out every other session for it. A password handed to a friend works for only one of them at a time, and the first person is signed out each time. Ordinary accounts can still use several devices.
- Seat accounts cannot buy plans, close their own account, or manage logins. They can change their own password.
- When the institution's plan ends, every seat loses access at once. Renewing restores it. A different plan can be chosen only after the current one ends, and only if the active logins fit (no proration yet).

## Email (Resend) and plan-ending reminders

- Email goes through Resend when `PIANO_RESEND_API_KEY` is set (`app/services/email.py`). `PIANO_EMAIL_FROM` must be on a domain you have verified at resend.com/domains; until then Resend only delivers to your own address. With no key, development logs emails to the API console; production refuses to send. This also makes sign-up verification and password-reset emails work.
- A daily job (`app/services/expiry_service.py`) emails people **7, 3 and 1 days before** their plan or trial ends, and once **after it has ended** (only within 3 days of the end). Each reminder is recorded in `expiry_notices`, so running the job twice never sends twice, and a failed send is retried on the next run. Renewing changes the end date, so the next period gets its own reminders.
- It writes to individuals (paid and trial) and to institution **owners**. Seat logins have no email, so their manager is the one warned. Staff, closed accounts and people who switched reminders off in Account Settings are skipped.
- It runs at 07:00 UTC (08:00 in Nigeria) from the `beat` service in `docker-compose.yml`. Run exactly one `beat`. Without Celery, schedule `python -m scripts.send_expiry_reminders` from cron. Admins can run it by hand from Billing Admin.
- The pulsing **Subscribe** button appears under the menu (and in the top bar on phones) for people who can pay and are on a trial, have no plan, or are in the last 7 days of a paid plan. It never shows to staff, institution logins, or people with more than 7 days left. It pulses about once every two seconds and stops for people who ask their device for reduced motion.

## Limits to know about

- Sharing is limited, not prevented. Two people who take turns on one login are not detected. Binding a login to a device would be the next step; it has real downsides (a new phone locks the student out).
- No refunds, invoices or receipts yet. Payment history is listed on the Subscription page; refunds are done in the Paystack dashboard and then an admin must adjust access by hand.
- Prices are shown and charged in naira only.
- Not tested against Paystack itself: automated tests use a fake Paystack. Run a real test-mode payment and a test webhook before launch.

## Tests

`backend/tests/test_billing.py` (36 tests) and `backend/tests/test_expiry_emails.py` (23 tests: Resend, reminder timing, once-only sending, retries, opt-out, admin tools). `frontend/e2e/subscription.e2e.mjs` drives the real app in a browser (same setup as the other e2e scripts; the e2e API server now also creates `admin@example.com`). Billing:: trial and expiry, staff access, price and months, stacking, idempotent verify, underpayment, abandoned payments, Paystack down, someone else's reference, webhook signature and retries, institution purchase, seat cap, unique logins, one device at a time, closing and reopening logins, password reset, owner-only management, expiry and renewal, plan-change rules, admin grant. Frontend: `lib/billing/format.test.ts` and the nav test.


> Later: opt-in automatic card renewal was added (off by default). See `0016-automatic-renewal.md`. Everything above still holds when it is off.
