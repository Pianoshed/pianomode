"""Plans, checkout, Paystack return/webhook, and institution seat management."""

import json
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep, SettingsDep, require_roles
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.rate_limit import rate_limited
from app.models.base import utcnow
from app.models.billing import Payment, SavedCard
from app.models.user import Role, User
from app.schemas import billing as s
from app.schemas.errors import ErrorResponse
from app.services import admin_service, billing_service, expiry_service, institution_service
from app.services.email import EmailSender, get_email_sender
from app.services.paystack import PaystackClient, get_paystack_client, signature_is_valid
from app.services.plans import CURRENCY, MAX_MONTHS, PLANS

logger = logging.getLogger("app.billing")
HOUR = 3600
PaystackDep = Annotated[PaystackClient, Depends(get_paystack_client)]
SenderDep = Annotated[EmailSender, Depends(get_email_sender)]

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])
institution = APIRouter(
    prefix="/api/v1/institution",
    tags=["institution"],
    dependencies=[Depends(rate_limited("institution", 120, 60, by_session=True))],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
_admin_dep = Depends(require_roles(Role.ADMIN))
AdminActor = Annotated[User, _admin_dep]
admin = APIRouter(
    prefix="/api/v1/admin/billing",
    tags=["billing-admin"],
    dependencies=[_admin_dep],
)


def _entitlement_out(ent: billing_service.Entitlement) -> s.EntitlementOut:
    days: int | None = None
    if ent.ends_at is not None and ent.has_access:
        days = max(0, (ent.ends_at - utcnow()).days)
    return s.EntitlementOut(
        has_access=ent.has_access,
        source=ent.source,
        plan_code=ent.plan_code,
        ends_at=ent.ends_at,
        days_left=days,
        institution_name=ent.institution_name,
        reason=ent.reason,
    )


def _payment_out(p: Payment) -> s.PaymentOut:
    return s.PaymentOut(
        reference=p.reference,
        kind=p.kind,
        plan_code=p.plan_code,
        months=p.months,
        amount_kobo=p.amount_kobo,
        currency=p.currency,
        status=p.status,
        refunded_kobo=p.refunded_kobo,
        created_at=p.created_at,
        paid_at=p.paid_at,
    )


# ------------------------------------------------------------------ billing


@router.get("/plans", response_model=s.PlansOut)
def plans() -> s.PlansOut:
    """What is on sale. Public, so a sign-up page can show prices."""
    return s.PlansOut(
        currency=CURRENCY,
        max_months=MAX_MONTHS,
        plans=[
            s.PlanOut(
                code=p.code, name=p.name, kind=p.kind, seats=p.seats, monthly_kobo=p.monthly_kobo
            )
            for p in PLANS.values()
        ],
    )


@router.get("/status", response_model=s.StatusOut, responses={401: {"model": ErrorResponse}})
def status(user: CurrentUser, session: SessionDep, settings: SettingsDep) -> s.StatusOut:
    ent = billing_service.resolve_entitlement(session, user, settings)
    seat = billing_service.is_seat(session, user)
    owner = (not seat) and billing_service.owned_institution(session, user) is not None
    return s.StatusOut(
        entitlement=_entitlement_out(ent),
        can_purchase=not seat,
        institution_role="seat" if seat else "owner" if owner else None,
    )


@router.post(
    "/checkout",
    response_model=s.CheckoutOut,
    dependencies=[Depends(rate_limited("checkout", 15, HOUR, by_session=True))],
    responses={
        403: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def checkout(
    body: s.CheckoutIn,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    client: PaystackDep,
) -> s.CheckoutOut:
    """Start a Paystack payment. The browser then goes to `authorization_url`."""
    result = billing_service.create_checkout(
        session,
        user=user,
        plan_code=body.plan,
        months=body.months,
        institution_name=body.institution_name,
        client=client,
        settings=settings,
        save_card=body.save_card,
    )
    return s.CheckoutOut(
        reference=result.reference,
        authorization_url=result.authorization_url,
        amount_kobo=result.amount_kobo,
    )


def _card_out(card: SavedCard | None, settings: SettingsDep) -> s.CardOut:
    return s.CardOut(
        available=settings.auto_renewal_enabled,
        has_card=card is not None,
        brand=(card.brand or None) if card else None,
        last4=(card.last4 or None) if card else None,
        exp_month=(card.exp_month or None) if card else None,
        exp_year=(card.exp_year or None) if card else None,
        auto_renew=bool(card and card.auto_renew and settings.auto_renewal_enabled),
        failures=card.failures if card else 0,
    )


@router.get("/card", response_model=s.CardOut)
def card(user: CurrentUser, session: SessionDep, settings: SettingsDep) -> s.CardOut:
    """The saved card and whether the plan renews by itself."""
    return _card_out(billing_service.get_card(session, user.id), settings)


@router.post(
    "/auto-renew",
    response_model=s.CardOut,
    dependencies=[Depends(rate_limited("auto-renew", 30, HOUR, by_session=True))],
    responses={409: {"model": ErrorResponse}},
)
def auto_renew(
    body: s.AutoRenewIn, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> s.CardOut:
    if body.enabled and not settings.auto_renewal_enabled:
        raise ConflictError(
            "Automatic renewal is not available yet.", code="auto_renewal_unavailable"
        )
    return _card_out(billing_service.set_auto_renew(session, user, body.enabled), settings)


@router.delete(
    "/card",
    status_code=204,
    dependencies=[Depends(rate_limited("delete-card", 30, HOUR, by_session=True))],
)
def delete_card(user: CurrentUser, session: SessionDep) -> Response:
    """Forget the saved card. The plan then simply ends on its date."""
    billing_service.delete_card(session, user)
    return Response(status_code=204)


@router.get(
    "/upgrade-quote",
    response_model=s.UpgradeQuoteOut,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def upgrade_quote(
    plan: str, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> s.UpgradeQuoteOut:
    """The price of moving a running institution plan to a bigger one for the rest of the period."""
    q = billing_service.quote_upgrade(session, user, plan, settings)
    return s.UpgradeQuoteOut(
        plan=q.to_plan.code,
        amount_kobo=q.amount_kobo,
        days_left=q.days_left,
        from_plan=q.from_plan.code,
        seats=q.to_plan.seats or 0,
    )


@router.post(
    "/verify",
    response_model=s.VerifyOut,
    dependencies=[Depends(rate_limited("verify-payment", 60, HOUR, by_session=True))],
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def verify(
    body: s.VerifyIn,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    client: PaystackDep,
    sender: SenderDep,
) -> s.VerifyOut:
    """Called by the page Paystack sends the person back to. Asks Paystack, then updates access."""
    payment = billing_service.settle_payment(
        session,
        reference=body.reference,
        client=client,
        settings=settings,
        user_id=user.id,
        sender=sender,
    )
    ent = billing_service.resolve_entitlement(session, user, settings)
    return s.VerifyOut(payment=_payment_out(payment), entitlement=_entitlement_out(ent))


@router.get("/payments", response_model=s.PaymentsOut)
def payments(user: CurrentUser, session: SessionDep) -> s.PaymentsOut:
    return s.PaymentsOut(
        payments=[_payment_out(p) for p in billing_service.list_payments(session, user)]
    )


@router.post("/webhooks/paystack", status_code=200, include_in_schema=False)
async def paystack_webhook(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    client: PaystackDep,
    sender: SenderDep,
) -> Response:
    """Paystack tells us a charge succeeded. Authenticated by the HMAC signature, not a cookie."""
    raw = await request.body()
    if not signature_is_valid(
        raw, request.headers.get("x-paystack-signature"), settings.paystack_secret_key
    ):
        return Response(status_code=401)
    try:
        event: dict[str, Any] = json.loads(raw)
    except ValueError:
        return Response(status_code=400)
    data = event.get("data")
    kind = event.get("event")
    if (
        kind == "charge.success"
        and isinstance(data, dict)
        and isinstance(data.get("reference"), str)
    ):
        try:
            billing_service.settle_payment(
                session,
                reference=data["reference"],
                client=client,
                settings=settings,
                sender=sender,
            )
        except NotFoundError:
            logger.info("Webhook for a reference we did not create; ignored")
    elif kind == "refund.processed" and isinstance(data, dict):
        _handle_refund_event(session, settings, data)
    # A ServiceUnavailableError propagates as 503, so Paystack retries the webhook later.
    return Response(status_code=200)


def _handle_refund_event(session: SessionDep, settings: SettingsDep, data: dict[str, Any]) -> None:
    """Paystack finished a refund. A full refund takes the access back automatically.

    Anything we cannot be sure refunds all that is left of one of our payments (a partial amount,
    a missing amount, an unknown reference) is only written to the audit log for an administrator
    to decide.
    """
    ref = data.get("transaction_reference")
    if not isinstance(ref, str):
        txn = data.get("transaction")
        ref = txn.get("reference") if isinstance(txn, dict) else None
    payment = session.scalar(select(Payment).where(Payment.reference == ref)) if ref else None
    if payment is None or payment.status != "success":
        return
    try:
        amount = int(float(data.get("amount")))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        amount = None
    if (
        data.get("status") not in (None, "processed")
        or amount != payment.amount_kobo - payment.refunded_kobo
    ):
        admin_service.record(
            session, None, "refund_needs_review", None, reference=payment.reference, amount=amount
        )
        session.commit()
        return
    try:
        billing_service.reverse_payment(session, payment, settings)
    except AppError:
        session.rollback()
        admin_service.record(
            session, None, "refund_needs_review", None, reference=payment.reference
        )
        session.commit()
        return
    admin_service.record(session, None, "payment_refunded", None, reference=payment.reference)
    session.commit()


@admin.post("/grant", response_model=s.PaymentOut, responses={404: {"model": ErrorResponse}})
def grant(
    body: s.AdminGrantIn, actor: AdminActor, session: SessionDep, settings: SettingsDep
) -> s.PaymentOut:
    """Record a bank transfer or cash payment and give the access it covers."""
    user = session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        raise NotFoundError("No account has that email.", code="user_not_found")
    payment = billing_service.admin_grant(
        session,
        user=user,
        plan_code=body.plan,
        months=body.months,
        institution_name=body.institution_name,
        settings=settings,
    )
    admin_service.record(
        session,
        actor,
        "payment_recorded",
        user,
        reference=payment.reference,
        plan=body.plan,
        months=body.months,
    )
    session.commit()
    return _payment_out(payment)


def _check_out(check: billing_service.RefundCheck) -> s.RefundCheckOut:
    return s.RefundCheckOut(
        days_since_paid=check.days_since_paid,
        window_days=check.window_days,
        outside_window=check.outside_window,
        prior_refunds=check.prior_refunds,
        repeat=check.repeat,
        needs_override=check.needs_override,
    )


@admin.get(
    "/payments/{reference}/refund-check",
    response_model=s.RefundCheckOut,
    responses={404: {"model": ErrorResponse}},
)
def refund_check(
    reference: str, actor: AdminActor, session: SessionDep, settings: SettingsDep
) -> s.RefundCheckOut:
    """Is this refund late, or is the person a repeat? Ask before recording it."""
    payment = session.scalar(select(Payment).where(Payment.reference == reference))
    if payment is None:
        raise NotFoundError("Payment not found.", code="payment_not_found")
    return _check_out(billing_service.refund_check(session, payment, settings))


@admin.post(
    "/payments/{reference}/refund",
    response_model=s.PaymentOut,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def refund_payment(
    reference: str, body: s.RefundIn, actor: AdminActor, session: SessionDep, settings: SettingsDep
) -> s.PaymentOut:
    """Take back access after a refund. Refund the money itself in the Paystack dashboard (a full
    refund there also does this by itself). For a partial refund give `amount_kobo`."""
    payment = session.scalar(
        select(Payment).where(Payment.reference == reference).with_for_update()
    )
    if payment is None:
        raise NotFoundError("Payment not found.", code="payment_not_found")
    check = billing_service.refund_check(session, payment, settings)
    if check.needs_override and not body.override:
        if check.outside_window:
            raise ConflictError(
                f"This was paid {check.days_since_paid} days ago; refunds are normally made within "
                f"{check.window_days} days. Confirm to refund it anyway.",
                code="outside_refund_window",
            )
        raise ConflictError(
            f"This person has already had {check.prior_refunds} other payments refunded. "
            "Confirm to refund this one too.",
            code="repeat_refunds",
        )
    billing_service.reverse_payment(
        session, payment, settings, amount_kobo=body.amount_kobo, cut_days=body.cut_days
    )
    payer = session.get(User, payment.user_id)
    admin_service.record(
        session,
        actor,
        "payment_refunded",
        payer,
        reference=reference,
        reason=body.reason,
        amount_kobo=body.amount_kobo,
        cut_days=body.cut_days,
        override=check.needs_override,
        days_since_paid=check.days_since_paid,
        prior_refunds=check.prior_refunds,
    )
    session.commit()
    return _payment_out(payment)


@admin.get("/lookup", response_model=s.AdminLookupOut)
def lookup(email: str, session: SessionDep, settings: SettingsDep) -> s.AdminLookupOut:
    """Who is this customer and what do they have? Does not start a trial for them."""
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        return s.AdminLookupOut(found=False)
    ent = billing_service.resolve_entitlement(session, user, settings, start_trial=False)
    inst = billing_service.owned_institution(session, user)
    inst_out = None
    if inst is not None:
        o = institution_service.overview(session, user)
        inst_out = s.AdminInstitutionOut(
            name=inst.name,
            code=inst.code,
            plan_code=o.plan_code,
            seats_allowed=o.seats_allowed,
            seats_used=o.seats_used,
            ends_at=o.ends_at,
        )
    return s.AdminLookupOut(
        found=True,
        user=s.AdminUserOut(
            name=user.display_name,
            email=user.email or "",
            roles=sorted(user.role_names),
            is_active=user.is_active,
        ),
        entitlement=_entitlement_out(ent),
        institution=inst_out,
    )


@admin.get("/payments", response_model=s.AdminPaymentsOut)
def all_payments(session: SessionDep, limit: int = 30) -> s.AdminPaymentsOut:
    rows = billing_service.recent_payments(session, max(1, min(limit, 100)))
    return s.AdminPaymentsOut(
        payments=[
            s.AdminPaymentOut(**_payment_out(p).model_dump(), email=u.email, name=u.display_name)
            for p, u in rows
        ]
    )


@admin.post("/send-reminders", response_model=s.ReminderRunOut)
def send_reminders(
    session: SessionDep, settings: SettingsDep, sender: SenderDep
) -> s.ReminderRunOut:
    """Run the plan-ending email job now. It already runs every morning; this is for checking."""
    r = expiry_service.send_expiry_reminders(session, sender, settings)
    return s.ReminderRunOut(sent=r.sent, failed=r.failed, skipped=r.skipped)


# -------------------------------------------------------------- institution


def _credentials(items: list[institution_service.NewSeat]) -> s.CredentialsOut:
    return s.CredentialsOut(
        credentials=[
            s.CredentialOut(id=i.seat_id, login_id=i.login_id, name=i.name, password=i.password)
            for i in items
        ]
    )


@institution.get("", response_model=s.InstitutionOut)
def institution_overview(user: CurrentUser, session: SessionDep) -> s.InstitutionOut:
    o = institution_service.overview(session, user)
    return s.InstitutionOut(
        name=o.institution.name,
        code=o.institution.code,
        plan_code=o.plan_code,
        seats_allowed=o.seats_allowed,
        seats_used=o.seats_used,
        ends_at=o.ends_at,
        subscription_live=o.subscription_live,
        seats=[
            s.SeatOut(
                id=r.seat_id,
                login_id=r.login_id,
                name=r.name,
                active=r.active,
                last_login_at=r.last_login_at,
            )
            for r in o.seats
        ],
    )


@institution.post(
    "/seats",
    response_model=s.CredentialsOut,
    status_code=201,
    responses={403: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_seats(body: s.CreateSeatsIn, user: CurrentUser, session: SessionDep) -> s.CredentialsOut:
    """Make one login per name. Passwords appear in this response only and cannot be read later."""
    return _credentials(institution_service.create_seats(session, user, body.names))


@institution.post("/seats/{seat_id}/reset-password", response_model=s.CredentialsOut)
def reset_seat_password(
    seat_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> s.CredentialsOut:
    return _credentials([institution_service.reset_password(session, user, seat_id)])


@institution.post("/seats/{seat_id}/deactivate", status_code=204)
def deactivate_seat(seat_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    institution_service.set_active(session, user, seat_id, False)


@institution.post(
    "/seats/{seat_id}/activate", status_code=204, responses={409: {"model": ErrorResponse}}
)
def activate_seat(seat_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    institution_service.set_active(session, user, seat_id, True)
