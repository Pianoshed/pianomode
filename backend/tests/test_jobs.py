import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.job import JobStatus
from app.models.user import Role, User
from app.services import job_service as svc
from app.services.job_service import InvalidJobTransitionError


def test_happy_path(session: Session) -> None:
    job = svc.create_job(session, "demo", {"a": 1})
    assert job.status is JobStatus.QUEUED and job.progress == 0
    svc.start_job(session, job)
    assert job.started_at is not None
    svc.update_progress(session, job, 40)
    svc.update_progress(session, job, 20)  # never goes backwards
    assert job.progress == 40
    svc.complete_job(session, job, {"ok": True})
    assert job.status is JobStatus.COMPLETED
    assert job.progress == 100 and job.finished_at is not None and job.result == {"ok": True}


def test_failure_records_error(session: Session) -> None:
    job = svc.start_job(session, svc.create_job(session, "demo"))
    svc.fail_job(session, job, "decode_error", "bad file")
    assert job.status is JobStatus.FAILED
    assert (job.error_code, job.error_message) == ("decode_error", "bad file")


@pytest.mark.parametrize("terminal", ["complete", "fail", "cancel"])
def test_terminal_states_are_final(session: Session, terminal: str) -> None:
    job = svc.start_job(session, svc.create_job(session, "demo"))
    {
        "complete": lambda: svc.complete_job(session, job, {}),
        "fail": lambda: svc.fail_job(session, job, "x", "y"),
        "cancel": lambda: svc.cancel_job(session, job),
    }[terminal]()
    with pytest.raises(InvalidJobTransitionError):
        svc.start_job(session, job)
    with pytest.raises(InvalidJobTransitionError):
        svc.cancel_job(session, job)


def test_cannot_complete_queued_job(session: Session) -> None:
    job = svc.create_job(session, "demo")
    with pytest.raises(InvalidJobTransitionError):
        svc.complete_job(session, job, {})


def test_progress_bounds(session: Session) -> None:
    job = svc.start_job(session, svc.create_job(session, "demo"))
    with pytest.raises(ValueError):
        svc.update_progress(session, job, 101)


def test_api_requires_sign_in(client: TestClient) -> None:
    r = client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert r.status_code == 401 and r.json()["error"]["code"] == "not_authenticated"


def test_api_get_and_cancel_own_job(
    client: TestClient,
    session: Session,
    make_user: Callable[..., User],
    sign_in: Callable[..., None],
) -> None:
    user = make_user()
    sign_in()
    job = svc.create_job(session, "demo", user_id=user.id)
    r = client.get(f"/api/v1/jobs/{job.id}")
    assert r.status_code == 200 and r.json()["status"] == "queued"
    r = client.post(f"/api/v1/jobs/{job.id}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    r = client.post(f"/api/v1/jobs/{job.id}/cancel")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "invalid_job_transition"


def test_jobs_are_private_to_their_owner_but_visible_to_admins(
    client: TestClient,
    session: Session,
    make_user: Callable[..., User],
    sign_in: Callable[..., None],
) -> None:
    owner = make_user("owner@example.com")
    make_user("other@example.com")
    make_user("admin@example.com", roles=(Role.ADMIN,))
    job = svc.create_job(session, "demo", user_id=owner.id)

    sign_in("other@example.com")
    r = client.get(f"/api/v1/jobs/{job.id}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "job_not_found"
    assert client.post(f"/api/v1/jobs/{job.id}/cancel").status_code == 404

    client.post("/api/v1/auth/logout")
    sign_in("admin@example.com")
    assert client.get(f"/api/v1/jobs/{job.id}").status_code == 200


def test_api_missing_job_has_stable_code(
    client: TestClient, make_user: Callable[..., User], sign_in: Callable[..., None]
) -> None:
    make_user()
    sign_in()
    r = client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "job_not_found"


def test_api_validation_error_shape(
    client: TestClient, make_user: Callable[..., User], sign_in: Callable[..., None]
) -> None:
    make_user()
    sign_in()
    r = client.get("/api/v1/jobs/not-a-uuid")
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error" and isinstance(body["details"], list)
