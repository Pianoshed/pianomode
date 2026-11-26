"""Charge the saved card of people who chose "renew automatically", a day before their plan ends.

Rules (docs/adr/0016-automatic-renewal.md):
- Opt-in only: a person is charged only if they ticked the box when paying by card, and can switch
  it off or forget the card on the Subscription page at any time.
- One month at the current price of the same plan. The charge goes through the same Payment and
  `settle_payment` path as any other payment (so amounts are verified with Paystack, the receipt is
  sent, a refund is handled the same way), with kind "renewal".
- Once a day, at most one attempt per plan per day. A failed charge emails the person; after
  `MAX_FAILURES` failures in a row automatic renewal switches itself off.
- A plan that ended more than 3 days ago is never charged automatically.
- Everything is off unless PIANO_AUTO_RENEWAL_ENABLED is true.
"""

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import Settings
from app.core.errors import AppError
from app.models.base import ensure_utc, utcnow
from app.models.billing import Institution, Payment, SavedCard, Subscription
from app.models.user import User
from app.services import billing_service
from app.services.email import EmailMessage, EmailSender
from app.services.paystack import PaystackClient, PaystackError
from app.services.plans import CURRENCY, TRIAL_PLAN, get_plan

logger = logging.getLogger("app.renewal")

CHARGE_AHEAD = timedelta(days=1)  # charge when this much time or less is left
LATE_LIMIT = timedelta(days=3)  # do not charge a plan that ended longer ago than this
ONE_TRY_PER = timedelta(hours=20)


@dataclass(frozen=True)
class RenewalResult:
    charged: int
    failed: int
    skipped: int


def _targets(session: Session, user: User) -> list[tuple[Subscription, Institution | None]]:
    """The subscriptions this person pays for: their own, and their institution's."""
    out: list[tuple[Subscription, Institution | None]] = []
    own = billing_service._subscription_for_user(session, user.id)
    if own is not None:
        out.append((own, None))
    inst = billing_service.owned_institution(session, user)
    if inst is not None and inst.is_active:
        sub = billing_service.institution_subscription(session, inst.id)
        if sub is not None:
            out.append((sub, inst))
    return out


def _due(sub: Subscription, now: datetime) -> bool:
    if sub.plan_code == TRIAL_PLAN or get_plan(sub.plan_code) is None:
        return False
    end = ensure_utc(sub.current_period_end)
    return now - LATE_LIMIT < end <= now + CHARGE_AHEAD


def _tried_recently(
    session: Session, user: User, plan_code: str, inst_id: uuid.UUID | None, now: datetime
) -> bool:
    stmt = select(Payment.id).where(
        Payment.user_id == user.id,
        Payment.kind == "renewal",
        Payment.plan_code == plan_code,
        Payment.created_at > now - ONE_TRY_PER,
    )
    stmt = stmt.where(
        Payment.institution_id.is_(None) if inst_id is None else Payment.institution_id == inst_id
    )
    return session.scalar(stmt.limit(1)) is not None


def _tell_failed(
    sender: EmailSender, user: User, card: SavedCard, settings: Settings, switched_off: bool
) -> None:
    assert user.email is not None
    link = f"{settings.public_web_url.rstrip('/')}/subscription"
    tail = (
        "We tried several times, so automatic renewal is now off."
        if switched_off
        else "We will try once more tomorrow."
    )
    try:
        sender.send(
            EmailMessage(
                to=user.email,
                subject="We could not renew your Piano Platform plan",
                body=(
                    f"We tried to charge the card ending {card.last4} to renew your plan, and "
                    f"the payment did not go through. {tail}\n\n"
                    "To keep your access, pay on the Subscription page (you can use a different "
                    f"card):\n{link}\n"
                ),
            )
        )
    except AppError:
        logger.warning("Could not send a renewal-failed email")


def run_renewals(
    session: Session,
    client: PaystackClient,
    sender: EmailSender,
    settings: Settings,
    now: datetime | None = None,
) -> RenewalResult:
    if not settings.auto_renewal_enabled:
        return RenewalResult(0, 0, 0)
    now = now or utcnow()
    charged = failed = skipped = 0
    cards = session.scalars(select(SavedCard).where(SavedCard.auto_renew.is_(True))).all()
    for card in cards:
        user = session.get(User, card.user_id)
        if user is None or not user.is_active or user.email is None:
            skipped += 1
            continue
        code = crypto.decrypt(card.authorization_code)
        if code is None:  # the secret key changed: the token cannot be read
            card.auto_renew = False
            session.commit()
            skipped += 1
            continue
        for sub, inst in _targets(session, user):
            if not _due(sub, now):
                continue
            plan = get_plan(sub.plan_code)
            assert plan is not None
            institution_id = inst.id if inst else None
            if _tried_recently(session, user, plan.code, institution_id, now):
                skipped += 1
                continue
            payment = Payment(
                reference=f"pp_{secrets.token_hex(14)}",
                user_id=user.id,
                plan_code=plan.code,
                months=1,
                amount_kobo=plan.monthly_kobo,
                currency=CURRENCY,
                institution_name=inst.name if inst else None,
                institution_id=institution_id,
                kind="renewal",
            )
            session.add(payment)
            session.commit()
            try:
                client.charge_authorization(
                    email=user.email,
                    amount_kobo=payment.amount_kobo,
                    reference=payment.reference,
                    authorization_code=code,
                    metadata={"plan": plan.code, "months": 1, "kind": "renewal"},
                )
                payment = billing_service.settle_payment(
                    session,
                    reference=payment.reference,
                    client=client,
                    settings=settings,
                    sender=sender,
                )
            except (PaystackError, AppError):
                # Could not reach Paystack, or could not confirm. If the charge did go through,
                # Paystack's charge.success webhook settles this same reference later.
                session.rollback()
                payment = session.get(Payment, payment.id)  # type: ignore[assignment]
            assert payment is not None
            if payment.status == "success":
                card.failures = 0
                session.commit()
                charged += 1
                continue
            if payment.status == "pending":
                payment.status = "failed"
                payment.gateway_response = (payment.gateway_response or "not completed")[:255]
            failed += 1
            card.failures += 1
            off = card.failures >= billing_service.MAX_FAILURES
            if off:
                card.auto_renew = False
            session.commit()
            _tell_failed(sender, user, card, settings, off)
    logger.info("Renewals: charged=%s failed=%s skipped=%s", charged, failed, skipped)
    return RenewalResult(charged, failed, skipped)
