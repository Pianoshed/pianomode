# 0018 Partial refunds

Until now an administrator could only take back a payment's access in full. A refund of part of the money (a goodwill gesture, a plan used for part of its period) left the payment looking untouched.

## Behaviour

- Money is still refunded **in the Paystack dashboard**; the app records the refund and takes back the matching access (`reverse_payment`).
- On the Billing admin screen each paid row has **Refund the rest** and, for purchases and renewals, **Part refund**. Part refund asks for the naira amount returned; the API also takes `cut_days` to choose how many days of access come back.
- API: `POST /api/v1/admin/billing/payments/{reference}/refund` with `{reason}` (everything left, as before), or `{reason, amount_kobo, cut_days?}`.
- By default a partial refund takes back the **same share of the days** as the share of the price returned (a third of the money on a 3-month purchase: 30 of 90 days). With `cut_days` the admin decides; `0` means "money back, keep the access".
- The payment stays **paid** until all of the money has been refunded; then it becomes **refunded**. `refunded_kobo` and `refunded_days` track what has gone back, so "refund the rest" takes back only the days not already taken, and amounts and days beyond what is left are rejected.
- Access never goes earlier than now.
- **Upgrades can only be refunded in full** (`not_refundable_partly`): a plan change cannot be half undone.
- The Paystack `refund.processed` webhook automatically reverses only a refund of **all that is left**; any other amount is written to the audit log as "needs review" for an administrator to record, as before.
- Existing refunded payments are migrated as refunded in full (`0013_partial_refunds`). The audit log line records the amount and days.

## Guard rails: late and repeat refunds

Partial refunds make it easy to be generous, so two checks protect against drift (they apply to refunds an administrator records, not to money Paystack has already returned, which is always recorded):

- **Window.** `PIANO_REFUND_WINDOW_DAYS` (default **14**, matching the Refunds page; `0` turns the check off). A refund of a payment older than that is refused with `outside_refund_window` unless the administrator confirms an override.
- **Repeat refunds.** If the same person already has 2 or more other payments with money refunded, the refund is refused with `repeat_refunds` unless confirmed.
- On the Billing screen the check runs first (`GET .../refund-check`) and the administrator gets a plain-language warning and a yes/no before the amount and reason prompts. An override is sent as `override: true` and written to the audit log with the days since payment and the number of earlier refunds, so it can be reviewed later.
- Neither check stops a determined administrator (an override is one click); they make an exception a visible, logged decision rather than a habit. Look at the audit log's "Refunded a payment" lines occasionally.

## Not done

Refunding through the Paystack API from our own screen (you still press the button in Paystack); a customer-facing refund request form.
