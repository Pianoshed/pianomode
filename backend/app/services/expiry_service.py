"""Emails that warn people their plan is about to end (or just did).

Run once a day (Celery beat, or `python -m scripts.send_expiry_reminders` from cron). Safe to run
more often: each (plan period, reminder kind) is sent once, recorded in `expiry_notices`.

Who is written to: individuals (paid and trial) and institution owners. Seat logins have no email;
their manager is the one who must renew. People can switch the emails off in Account Settings.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.models.base import ensure_utc, utcnow
from app.models.billing import ExpiryNotice, Institution, SavedCard, Subscription
from app.models.user import Role, User
from app.services.email import EmailMessage, EmailSender
from app.services.plans import TRIAL_PLAN, get_plan

logger = logging.getLogger("app.expiry")

# (kind, send when this much time or less is left)
BEFORE = (("d1", timedelta(days=1)), ("d3", timedelta(days=3)), ("d7", timedelta(days=7)))
AFTER_WINDOW = timedelta(days=3)  # an "ended" email is only sent within 3 days of the end


def due_kind(period_end: datetime, now: datetime) -> str | None:
    """The one reminder that applies right now: the most urgent whose time has come."""
    left = ensure_utc(period_end) - now
    if left <= timedelta(0):
        return "expired" if -left <= AFTER_WINDOW else None
    for kind, within in BEFORE:
        if left <= within:
            return kind
    return None


@dataclass(frozen=True)
class RunResult:
    sent: int
    failed: int
    skipped: int


def _recipient(session: Session, sub: Subscription) -> tuple[User, str | None, bool] | None:
    """(who to write to, institution name or None, is it a trial)."""
    if sub.user_id is not None:
        user = session.get(User, sub.user_id)
        return (user, None, sub.plan_code == TRIAL_PLAN) if user else None
    inst = session.get(Institution, sub.institution_id) if sub.institution_id else None
    owner = session.get(User, inst.owner_id) if inst else None
    return (owner, inst.name, False) if owner and inst and inst.is_active else None


def _message(
    *,
    to: str,
    kind: str,
    end: datetime,
    institution: str | None,
    trial: bool,
    plan_name: str,
    web: str,
    renews_on_card: tuple[str, int] | None = None,  # (last 4 digits, kobo) when it will auto-renew
) -> EmailMessage:
    when = f"{end:%d %B %Y}"
    link = f"{web.rstrip('/')}/subscription"
    days = {"d7": "7 days", "d3": "3 days", "d1": "1 day"}.get(kind)
    what = (
        "free trial" if trial else (f"{institution} plan ({plan_name})" if institution else "plan")
    )
    if kind == "expired":
        subject = f"Your Piano Platform {'trial' if trial else 'plan'} has ended"
        lead = f"Your {what} ended on {when}."
        effect = (
            f"The logins you gave to the people at {institution} cannot be used until you renew."
            if institution
            else "Lessons, practice and the studio tools are locked until you pay again."
        )
    else:
        subject = f"Your Piano Platform {'trial' if trial else 'plan'} ends in {days}"
        lead = f"Your {what} ends in {days}, on {when}."
        effect = (
            f"When it ends, the logins you gave to the people at {institution} stop working."
            if institution
            else "After that, lessons, practice and the studio tools lock until you pay again."
        )
    if renews_on_card is not None and kind != "expired":
        last4, kobo = renews_on_card
        whole, rest = divmod(kobo, 100)
        amount = f"NGN {whole:,}" + (f".{rest:02d}" if rest else "")
        return EmailMessage(
            to=to,
            subject=f"Your Piano Platform plan renews in {days}",
            body=(
                f"Your {what} ends on {when}, and it is set to renew by itself.\n\n"
                f"About a day before, we will charge {amount} to the card ending {last4} for "
                "one more month. You will get a receipt.\n\n"
                f"To stop this, or to change the card, open the Subscription page:\n{link}\n\n"
                "You can turn these reminders off in Account Settings."
            ),
        )
    body = (
        f"{lead}\n\n{effect}\n\n"
        f"Plans do not renew by themselves. To keep going, pay on the Subscription page:\n{link}\n"
        "Paying before the end date adds the new time on top of what is left.\n\n"
        "You can turn these reminders off in Account Settings."
    )
    return EmailMessage(to=to, subject=subject, body=body)


def send_expiry_reminders(
    session: Session, sender: EmailSender, settings: Settings, now: datetime | None = None
) -> RunResult:
    now = now or utcnow()
    subs = session.scalars(
        select(Subscription).where(
            Subscription.current_period_end > now - AFTER_WINDOW,
            Subscription.current_period_end <= now + BEFORE[-1][1],
        )
    ).all()
    sent = failed = skipped = 0
    for sub in subs:
        kind = due_kind(sub.current_period_end, now)
        target = _recipient(session, sub)
        if kind is None or target is None:
            skipped += 1
            continue
        user, institution, trial = target
        end = ensure_utc(sub.current_period_end)
        if (
            user.email is None
            or not user.is_active
            or not user.reminder_emails
            or user.role_names & {Role.ADMIN, Role.EDUCATOR}
        ):
            skipped += 1
            continue
        already = session.scalar(
            select(ExpiryNotice.id).where(
                ExpiryNotice.subscription_id == sub.id,
                ExpiryNotice.period_end == end,
                ExpiryNotice.kind == kind,
            )
        )
        if already is not None:
            skipped += 1
            continue
        plan = get_plan(sub.plan_code)
        card = session.scalar(select(SavedCard).where(SavedCard.user_id == user.id))
        renews = (
            (card.last4, plan.monthly_kobo)
            if card is not None
            and card.auto_renew
            and settings.auto_renewal_enabled
            and plan is not None
            and not trial
            else None
        )
        message = _message(
            to=user.email,
            kind=kind,
            end=end,
            institution=institution,
            trial=trial,
            plan_name=plan.name if plan else sub.plan_code,
            web=settings.public_web_url,
            renews_on_card=renews,
        )
        try:
            sender.send(message)
        except AppError:
            failed += 1  # not recorded, so the next run tries again
            continue
        session.add(ExpiryNotice(subscription_id=sub.id, period_end=end, kind=kind, sent_at=now))
        try:
            session.commit()
            sent += 1
        except IntegrityError:  # another run sent it a moment ago
            session.rollback()
            skipped += 1
    logger.info("Expiry reminders: sent=%s failed=%s skipped=%s", sent, failed, skipped)
    return RunResult(sent, failed, skipped)
