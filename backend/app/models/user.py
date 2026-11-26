import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import true as sa_true

from app.models.base import Base, JsonType, TimestampMixin, utcnow


class Role(enum.StrEnum):
    LEARNER = "learner"
    EDUCATOR = "educator"
    ADMIN = "admin"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Stored lowercase. Null for institution seat accounts, which sign in with `login_id`.
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True, nullable=True)
    # Stored uppercase, e.g. "GRAC-014". Only institution seat accounts have one.
    login_id: Mapped[str | None] = mapped_column(String(24), unique=True, index=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Plan-ending reminder emails. People can turn them off in Account Settings.
    reminder_emails: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set when the person deleted their account: personal details are erased and the row is kept
    # only so payment records (which the law requires us to keep) still point at something.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Two-factor sign-in (authenticator app). The secret is stored encrypted; see core/crypto.py.
    totp_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    totp_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)  # blocks code reuse
    recovery_codes: Mapped[list[str]] = mapped_column(JsonType, default=list)  # hashes, one-time
    roles: Mapped[list["UserRole"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", back_populates="user"
    )

    @property
    def role_names(self) -> set[Role]:
        return {r.role for r in self.roles}


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e]),
        primary_key=True,
    )
    user: Mapped[User] = relationship(back_populates="roles")


class UserSession(Base):
    """Server-side session. Only a hash of the cookie value is stored."""

    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)


class OneTimeToken(Base):
    """Single-use tokens for email verification and password reset (hash stored)."""

    __tablename__ = "one_time_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # What the token is for, when it is more than "this person": the new address of an email change.
    payload: Mapped[str | None] = mapped_column(String(320), nullable=True)
