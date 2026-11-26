import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Institution(Base, TimestampMixin):
    """A school, church or studio that pays for a block of seats.

    The owner manages seats but does not use one. Each seat is its own account (see
    InstitutionSeat), so one person = one login.
    """

    __tablename__ = "institutions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(8), unique=True, index=True)  # prefix of login IDs
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    seat_counter: Mapped[int] = mapped_column(Integer, default=0)  # login numbers are never reused


class InstitutionSeat(Base, TimestampMixin):
    """Links a seat account to its institution. Active or not is the account's `is_active`."""

    __tablename__ = "institution_seats"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )


class Subscription(Base, TimestampMixin):
    """Paid (or trial) access up to `current_period_end`. Belongs to a user or an institution."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) <> (institution_id IS NULL)", name="one_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=True
    )
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("institutions.id", ondelete="CASCADE"), unique=True, nullable=True
    )
    plan_code: Mapped[str] = mapped_column(String(32))  # a plans.py code, or "trial"
    seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Payment(Base, TimestampMixin):
    """One Paystack checkout. Access is only granted once it is verified as paid in full."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    plan_code: Mapped[str] = mapped_column(String(32))
    months: Mapped[int] = mapped_column(Integer)
    amount_kobo: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|success|failed
    # Institution plans: the name for a first purchase, or the institution being renewed.
    institution_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gateway_response: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "purchase" buys time; "upgrade" moves an institution to a bigger plan mid-period.
    kind: Mapped[str] = mapped_column(String(12), default="purchase", server_default="purchase")
    from_plan_code: Mapped[str | None] = mapped_column(String(32), nullable=True)  # upgrades only
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Money handed back so far (in the Paystack dashboard) and the days of access taken back for
    # it. Both stay 0 unless a refund was recorded. Status becomes "refunded" only when the whole
    # amount has been refunded.
    refunded_kobo: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    refunded_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # The person ticked "renew automatically" at checkout: keep the card if Paystack allows it.
    save_card: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class SavedCard(Base, TimestampMixin):
    """The card a person chose to have charged when their plan runs out (opt-in, one per person).

    `authorization_code` is Paystack's token for the card, not the card number (we never see
    that). It lets us charge the card, so it is stored encrypted (app/core/crypto.py).
    """

    __tablename__ = "saved_cards"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    authorization_code: Mapped[str] = mapped_column(String(512))  # encrypted
    brand: Mapped[str] = mapped_column(String(24), default="")
    last4: Mapped[str] = mapped_column(String(4), default="")
    exp_month: Mapped[str] = mapped_column(String(2), default="")
    exp_year: Mapped[str] = mapped_column(String(4), default="")
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    # Failed renewals in a row. At MAX_FAILURES auto_renew is switched off.
    failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class ExpiryNotice(Base):
    """Remembers which plan-ending email went out for which period, so none is sent twice.

    A renewal changes `period_end`, so the next period starts with a clean slate.
    """

    __tablename__ = "expiry_notices"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "period_end", "kind", name="uq_expiry_notices_once_per_period"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True
    )
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(8))  # d7, d3, d1, expired
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
