import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.billing import AdminPaymentOut, EntitlementOut


class AdminUserRow(BaseModel):
    id: uuid.UUID
    name: str
    email: str | None
    login_id: str | None
    roles: list[str]
    is_active: bool
    email_verified: bool
    two_factor_enabled: bool
    kind: Literal["individual", "institution_owner", "seat"]
    created_at: datetime


class AdminUserList(BaseModel):
    users: list[AdminUserRow]
    total: int


class AdminUserDetail(AdminUserRow):
    entitlement: EntitlementOut
    institution_name: str | None  # the one they manage, or the one their login belongs to
    library_items: int
    library_bytes: int
    active_sessions: int
    payments: list[AdminPaymentOut]


class RoleChangeIn(BaseModel):
    role: Literal["educator", "admin"]
    grant: bool


class AuditRow(BaseModel):
    id: uuid.UUID
    actor_email: str
    action: str
    target_label: str
    target_user_id: uuid.UUID | None
    detail: dict[str, Any]
    created_at: datetime


class AuditOut(BaseModel):
    actions: list[AuditRow]
