# 0016 Automatic card renewal (opt-in, off by default)

Until now every payment was a prepaid block and nothing renewed (ADR 0011). People asked for the option to have their card charged when the plan runs out. This adds it without changing the default.

## Decisions

- **Opt-in, per person, twice.** The server has `PIANO_AUTO_RENEWAL_ENABLED` (default **false**): while off, the checkbox is hidden, a ticked box is ignored and the daily job does nothing. When on, nobody is charged unless they ticked "Renew automatically" while paying by card. They can switch it off or forget the card on the Subscription page at any time.
- **We charge the saved card ourselves** (`POST /transaction/charge_authorization`), not Paystack's recurring Plans. That keeps one price list (`plans.py`), one payment path and the same refund handling. A renewal is an ordinary `Payment` with `kind = "renewal"`, one month, the current price of the same plan; the amount is verified with Paystack by the same `settle_payment` and the same receipt email goes out.
- **What is stored:** Paystack's `authorization_code` (a token, not the card number), brand, last four digits and expiry, in `saved_cards`. The token is **encrypted** like the two-factor keys (`app/core/crypto.py`, keyed from `PIANO_SECRET_KEY`: changing the key means the token cannot be read; the job then switches that person's renewal off instead of failing). It is never returned by the API, never in the data export, and deleted with the account. Only a *reusable card* authorization is kept; bank transfer and USSD payments are not renewable and save nothing.
- **When:** Celery beat, 06:00 UTC daily (before the 07:00 reminder emails). A plan is charged once it has a day or less left, and never if it ended more than 3 days ago. Trials are never charged. One attempt per plan per 20 hours, so a repeat run cannot double-charge.
- **Failure:** a declined or unreachable charge is recorded as a failed payment, the person is emailed, and the next day's run tries again. After 3 failures in a row automatic renewal switches itself off and the email says so. If Paystack was unreachable while the charge actually went through, its `charge.success` webhook settles the same reference later (a failed payment can still become successful).
- **Warning before charging:** for people with renewal on, the 7-, 3- and 1-day reminder emails say what will be charged, to which card ending, and where to stop it. (A person who switched reminder emails off in Account Settings is still charged, and always gets the receipt.)
- **Refunds:** a renewal is refunded like any payment (Paystack dashboard, then "Take back access"; a full refund via webhook does it automatically). A refund does not switch renewal off; the person does that.
- Legal pages (terms, refunds, privacy) now describe the opt-in.

## Not verified against real Paystack

Written from Paystack's documentation and tested against a fake: the shape of `authorization` in the verify reply, `charge_authorization` and its `charge.success` webhook. **Before switching it on:** with test keys, pay with a Paystack test card with the box ticked, set that subscription's end to tomorrow in the database, run `docker compose -f docker-compose.prod.yml exec api python -m scripts.run_renewals`, and check the charge, the receipt and the new end date. Also test a declining card (Paystack documents test cards for this). Some cards need extra authentication for charges we start (the charge then does not succeed and is treated as failed; the person is emailed to pay by hand). Also check the migration on PostgreSQL (CI does: `alembic upgrade head`, `alembic check`, downgrade).

## Turning it on

Add `PIANO_AUTO_RENEWAL_ENABLED=true` to `.env` and restart `api`, `worker` and `beat`.

## Not done

Updating an expired card (the person pays once more with the box ticked), a separate admin view of who has renewal on, partial refunds, Paystack's own subscription Plans.
