import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class PlanOut(BaseModel):
    code: str
    name: str
    kind: Literal["individual", "institution"]
    seats: int | None
    monthly_kobo: int


class PlansOut(BaseModel):
    currency: str
    max_months: int
    plans: list[PlanOut]


class EntitlementOut(BaseModel):
    has_access: bool
    source: Literal["staff", "individual", "trial", "institution", "none"]
    plan_code: str | None
    ends_at: datetime | None
    days_left: int | None
    institution_name: str | None
    reason: str


class StatusOut(BaseModel):
    entitlement: EntitlementOut
    can_purchase: bool  # false for institution seat accounts
    institution_role: Literal["owner", "seat"] | None


class CheckoutIn(BaseModel):
    plan: str = Field(min_length=1, max_length=32)
    months: int = Field(default=1, ge=1, le=12)
    institution_name: Name | None = None
    save_card: bool = False  # "Renew automatically": keep the card (only if the server allows it)


class CheckoutOut(BaseModel):
    reference: str
    authorization_url: str
    amount_kobo: int


class VerifyIn(BaseModel):
    reference: str = Field(min_length=5, max_length=64)


class PaymentOut(BaseModel):
    reference: str
    plan_code: str
    months: int
    amount_kobo: int
    currency: str
    status: str
    kind: str = "purchase"
    refunded_kobo: int = 0
    created_at: datetime
    paid_at: datetime | None


class VerifyOut(BaseModel):
    payment: PaymentOut
    entitlement: EntitlementOut


class PaymentsOut(BaseModel):
    payments: list[PaymentOut]


class AdminGrantIn(BaseModel):
    email: EmailStr
    plan: str = Field(min_length=1, max_length=32)
    months: int = Field(default=1, ge=1, le=12)
    institution_name: Name | None = None


class SeatOut(BaseModel):
    id: uuid.UUID
    login_id: str
    name: str
    active: bool
    last_login_at: datetime | None


class InstitutionOut(BaseModel):
    name: str
    code: str
    plan_code: str | None
    seats_allowed: int
    seats_used: int
    ends_at: datetime | None
    subscription_live: bool
    seats: list[SeatOut]


class CreateSeatsIn(BaseModel):
    names: list[Name] = Field(min_length=1, max_length=20)


class CredentialOut(BaseModel):
    id: uuid.UUID
    login_id: str
    name: str
    password: str  # shown once; only a hash is stored


class CredentialsOut(BaseModel):
    credentials: list[CredentialOut]


class AdminUserOut(BaseModel):
    name: str
    email: str
    roles: list[str]
    is_active: bool


class AdminInstitutionOut(BaseModel):
    name: str
    code: str
    plan_code: str | None
    seats_allowed: int
    seats_used: int
    ends_at: datetime | None


class AdminLookupOut(BaseModel):
    found: bool
    user: AdminUserOut | None = None
    entitlement: EntitlementOut | None = None
    institution: AdminInstitutionOut | None = None


class AdminPaymentOut(PaymentOut):
    email: str | None
    name: str


class AdminPaymentsOut(BaseModel):
    payments: list[AdminPaymentOut]


class ReminderRunOut(BaseModel):
    sent: int
    failed: int
    skipped: int


class UpgradeQuoteOut(BaseModel):
    plan: str
    amount_kobo: int
    days_left: int
    from_plan: str
    seats: int


class RefundIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)
    # Leave both out to refund everything that is left. For a partial refund give the amount
    # returned (in kobo); the days of access taken back default to the same share of the plan.
    amount_kobo: int | None = Field(default=None, gt=0)
    cut_days: int | None = Field(default=None, ge=0, le=3650)
    # Needed when the refund is late or the person has been refunded before (see RefundCheckOut).
    # The override is kept in the audit log.
    override: bool = False


class RefundCheckOut(BaseModel):
    days_since_paid: int
    window_days: int  # 0 = no limit
    outside_window: bool
    prior_refunds: int
    repeat: bool
    needs_override: bool


class CardOut(BaseModel):
    available: bool  # false when the server has automatic renewal switched off
    has_card: bool
    brand: str | None = None
    last4: str | None = None
    exp_month: str | None = None
    exp_year: str | None = None
    auto_renew: bool = False
    failures: int = 0


class AutoRenewIn(BaseModel):
    enabled: bool
