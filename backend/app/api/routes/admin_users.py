"""Administrators: find people, see their plan, close accounts, change roles, read the audit log."""

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep, SettingsDep, require_roles
from app.api.routes.billing import _entitlement_out, _payment_out
from app.core.rate_limit import rate_limited
from app.models.audit import AdminAction
from app.models.billing import Institution
from app.models.user import Role, User
from app.schemas import admin_users as s
from app.schemas.billing import AdminPaymentOut
from app.schemas.errors import ErrorResponse
from app.services import admin_service, two_factor_service

AdminUser = Depends(require_roles(Role.ADMIN))

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin-users"],
    dependencies=[AdminUser, Depends(rate_limited("admin-users", 300, 60, by_session=True))],
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)


def _row(session: SessionDep, u: User) -> dict[str, object]:
    return {
        "id": u.id,
        "name": u.display_name,
        "email": u.email,
        "login_id": u.login_id,
        "roles": sorted(r.value for r in u.role_names),
        "is_active": u.is_active,
        "email_verified": u.email_verified_at is not None,
        "two_factor_enabled": two_factor_service.is_enabled(u),
        "kind": admin_service.kind_of(session, u),
        "created_at": u.created_at,
    }


@router.get("/users", response_model=s.AdminUserList)
def list_users(
    session: SessionDep,
    q: str | None = None,
    role: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> s.AdminUserList:
    users, total = admin_service.list_users(session, q=q, role=role, limit=limit, offset=offset)
    return s.AdminUserList(users=[s.AdminUserRow(**_row(session, u)) for u in users], total=total)


@router.get("/users/{user_id}", response_model=s.AdminUserDetail)
def user_detail(
    user_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> s.AdminUserDetail:
    target = admin_service.get_target(session, user_id)
    d = admin_service.detail(session, target, settings)
    inst_name = d["owns_institution"].name if d["owns_institution"] else None
    if inst_name is None and d["seat_of"] is not None:
        inst = session.get(Institution, d["seat_of"])
        inst_name = inst.name if inst else None
    return s.AdminUserDetail(
        **_row(session, target),
        entitlement=_entitlement_out(d["entitlement"]),
        institution_name=inst_name,
        library_items=d["library"][0],
        library_bytes=d["library"][1],
        active_sessions=d["active_sessions"],
        payments=[
            AdminPaymentOut(
                **_payment_out(p).model_dump(), email=target.email, name=target.display_name
            )
            for p in d["payments"]
        ],
    )


@router.post("/users/{user_id}/close", status_code=204)
def close_account(user_id: uuid.UUID, actor: User = AdminUser, *, session: SessionDep) -> None:
    admin_service.set_active(session, actor, admin_service.get_target(session, user_id), False)


@router.post("/users/{user_id}/reopen", status_code=204)
def reopen_account(user_id: uuid.UUID, actor: User = AdminUser, *, session: SessionDep) -> None:
    admin_service.set_active(session, actor, admin_service.get_target(session, user_id), True)


@router.post("/users/{user_id}/sign-out", status_code=204)
def sign_out(user_id: uuid.UUID, actor: User = AdminUser, *, session: SessionDep) -> None:
    admin_service.sign_out(session, actor, admin_service.get_target(session, user_id))


@router.post("/users/{user_id}/roles", status_code=204)
def change_role(
    user_id: uuid.UUID, body: s.RoleChangeIn, actor: User = AdminUser, *, session: SessionDep
) -> None:
    admin_service.set_role(
        session, actor, admin_service.get_target(session, user_id), Role(body.role), body.grant
    )


@router.post("/users/{user_id}/reset-two-factor", status_code=204)
def reset_two_factor(user_id: uuid.UUID, actor: User = AdminUser, *, session: SessionDep) -> None:
    admin_service.reset_two_factor(session, actor, admin_service.get_target(session, user_id))


@router.get("/audit", response_model=s.AuditOut)
def audit(session: SessionDep, limit: int = 100, user_id: uuid.UUID | None = None) -> s.AuditOut:
    rows: list[AdminAction] = admin_service.audit_log(session, limit=limit, target_id=user_id)
    return s.AuditOut(
        actions=[
            s.AuditRow(
                id=a.id,
                actor_email=a.actor_email,
                action=a.action,
                target_label=a.target_label,
                target_user_id=a.target_user_id,
                detail=a.detail,
                created_at=a.created_at,
            )
            for a in rows
        ]
    )
