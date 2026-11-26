"""Locking checks that only mean something on real PostgreSQL (SQLite ignores row locks).

Skipped unless PIANO_TEST_POSTGRES_URL points at a database already migrated with
`alembic upgrade head`. CI does this in the `migrations` job. To run by hand:

    PIANO_TEST_POSTGRES_URL=postgresql+psycopg://piano:piano@localhost:5432/piano \
        python -m pytest tests/test_postgres_concurrency.py
"""

import os
import threading
import time
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import ConflictError
from app.core.security import hash_password
from app.models.base import ensure_utc, utcnow
from app.models.billing import Subscription
from app.models.user import Role, User, UserRole
from app.services import billing_service, institution_service
from app.services.paystack import CheckoutSession, VerifiedTransaction

URL = os.environ.get("PIANO_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not URL, reason="PIANO_TEST_POSTGRES_URL is not set")

SETTINGS = Settings()


class SlowPaystack:
    """Verifying takes a moment, so simultaneous requests really do overlap."""

    def __init__(self) -> None:
        self.amounts: dict[str, int] = {}

    def initialize(self, **kw) -> CheckoutSession:  # type: ignore[no-untyped-def]
        self.amounts[kw["reference"]] = kw["amount_kobo"]
        return CheckoutSession("https://pay.test", "code")

    def verify(self, reference: str) -> VerifiedTransaction:
        time.sleep(0.3)
        return VerifiedTransaction(reference, "success", self.amounts[reference], "NGN", "ok")


@pytest.fixture(scope="module")
def sf() -> sessionmaker[Session]:
    assert URL
    return sessionmaker(bind=create_engine(URL, pool_size=10), expire_on_commit=False)


def new_user(sf: sessionmaker[Session]) -> uuid.UUID:
    with sf() as s:
        user = User(
            email=f"{uuid.uuid4().hex[:10]}@pg.test",
            password_hash=hash_password("correct horse battery"),
            display_name="T",
            email_verified_at=utcnow(),
            roles=[UserRole(role=Role.LEARNER)],
        )
        s.add(user)
        s.commit()
        return user.id


def run_threads(target, count: int) -> None:  # type: ignore[no-untyped-def]
    threads = [threading.Thread(target=target, args=(n,)) for n in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_one_payment_confirmed_four_times_at_once_grants_time_once(sf) -> None:  # type: ignore[no-untyped-def]
    paystack = SlowPaystack()
    uid = new_user(sf)
    with sf() as s:
        ref = billing_service.create_checkout(
            s,
            user=s.get(User, uid),
            plan_code="individual",
            months=1,
            institution_name=None,
            client=paystack,
            settings=SETTINGS,
        ).reference

    def settle(_: int) -> None:
        with sf() as s:
            billing_service.settle_payment(s, reference=ref, client=paystack, settings=SETTINGS)

    run_threads(settle, 4)
    with sf() as s:
        sub = s.scalar(select(Subscription).where(Subscription.user_id == uid))
        left = ensure_utc(sub.current_period_end) - utcnow()
    assert timedelta(days=29, hours=23) < left <= timedelta(days=30), left


def test_simultaneous_seat_creation_never_goes_over_the_plan(sf) -> None:  # type: ignore[no-untyped-def]
    paystack = SlowPaystack()
    owner = new_user(sf)
    with sf() as s:
        ref = billing_service.create_checkout(
            s,
            user=s.get(User, owner),
            plan_code="institution_10",
            months=1,
            institution_name="Race School",
            client=paystack,
            settings=SETTINGS,
        ).reference
        billing_service.settle_payment(s, reference=ref, client=paystack, settings=SETTINGS)
    outcomes: list[str] = []

    def add(n: int) -> None:
        with sf() as s:
            try:
                institution_service.create_seats(
                    s, s.get(User, owner), [f"P{n}-{i}" for i in range(6)]
                )
                outcomes.append("ok")
            except ConflictError as exc:
                outcomes.append(exc.code)

    run_threads(add, 3)
    with sf() as s:
        used = institution_service.overview(s, s.get(User, owner)).seats_used
    assert sorted(outcomes) == ["ok", "seat_limit_reached", "seat_limit_reached"]
    assert used == 6


def test_library_settings_round_trip_through_postgres_json(sf, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import base64

    from app.services import library_service
    from app.services.file_store import FileStore

    data = {"v": 1, "edits": [{"type": "merge", "from": [1, 2], "into": 0}], "name": "Étude ♯"}
    uid = new_user(sf)
    with sf() as s:
        user = s.get(User, uid)
        item = library_service.create_item(
            s,
            FileStore(tmp_path),
            SETTINGS,
            user,
            kind="midi",
            title="Étude",
            data=data,
            file_name="e.mid",
            file_base64=base64.b64encode(b"MThd0000").decode(),
        )
        item_id = item.id
    with sf() as s:
        back = library_service.get_item(s, s.get(User, uid), item_id)
        assert back.data == data


def test_deleting_an_account_works_on_postgres_and_keeps_the_payment_record(sf, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import base64

    from sqlalchemy import select as sel

    from app.models.billing import Payment
    from app.models.exercise_attempt import ExerciseAttempt
    from app.models.library import LibraryItem
    from app.services import account_service, library_service
    from app.services.email import InMemoryEmailSender
    from app.services.file_store import FileStore

    store, mail = FileStore(tmp_path), InMemoryEmailSender()
    uid = new_user(sf)
    with sf() as s:
        user = s.get(User, uid)
        library_service.create_item(
            s,
            store,
            SETTINGS,
            user,
            kind="midi",
            title="x",
            data={"v": 1},
            file_name="x.mid",
            file_base64=base64.b64encode(b"MThd0000").decode(),
        )
        s.add(
            ExerciseAttempt(
                user_id=uid, exercise_id="e", kind="k", difficulty="d", status="s", correct=True
            )
        )
        s.commit()
        billing_service.admin_grant(
            s, user=user, plan_code="individual", months=1, institution_name=None, settings=SETTINGS
        )
    with sf() as s:
        account_service.delete_account(
            s, store, s.get(User, uid), password="correct horse battery", otp=None, sender=mail
        )
    with sf() as s:
        u = s.get(User, uid)
        assert u.email is None and u.deleted_at is not None and u.display_name == "Deleted account"
        assert s.scalars(sel(LibraryItem).where(LibraryItem.user_id == uid)).all() == []
        assert s.scalars(sel(ExerciseAttempt).where(ExerciseAttempt.user_id == uid)).all() == []
        assert len(s.scalars(sel(Payment).where(Payment.user_id == uid)).all()) == 1
    assert len(mail.messages) == 1 and "deleted" in mail.messages[0].subject
