"""Movement library API: permissions, lifecycle, visibility and the publish gate."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models.user import Role, User

A = "/api/v1/admin/movements"
L = "/api/v1/movements"
EDUCATOR = "teacher@example.com"
LEARNER = "learner@example.com"


def body(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Jazz ii-V-I",
        "key": {"tonic": "C", "mode": "major"},
        "template_id": "ii_v_i",
        "tags": ["jazz"],
        "theory_explanation": "ii leads to V, which resolves to I.",
        "tempo": 90,
    }
    return {**base, **over}


@pytest.fixture
def users(make_user: Callable[..., User]) -> None:
    make_user(LEARNER)
    make_user(EDUCATOR, roles=(Role.EDUCATOR,))


@pytest.fixture
def staff(client: TestClient, users: None, sign_in: Callable[..., None]) -> TestClient:
    sign_in(EDUCATOR)
    return client


def create(c: TestClient, **over: Any) -> dict[str, Any]:
    r = c.post(A, json=body(**over))
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


def move(c: TestClient, mid: str, to: str, status: int = 200, note: str = "") -> dict[str, Any]:
    r = c.post(f"{A}/{mid}/status", json={"to": to, "note": note})
    assert r.status_code == status, r.text
    data: dict[str, Any] = r.json()
    return data


def publish(c: TestClient, **over: Any) -> dict[str, Any]:
    m = create(c, **over)
    for to in ("under_review", "approved", "published"):
        m = move(c, m["id"], to)
    return m


# ------------------------------------------------------------------ permissions


def test_anonymous_is_rejected(client: TestClient) -> None:
    assert client.get(L).status_code == 401
    assert client.get(A).status_code == 401
    assert client.post(A, json=body()).status_code == 401


def test_learner_cannot_use_admin_routes(
    client: TestClient, users: None, sign_in: Callable[..., None]
) -> None:
    sign_in(LEARNER)
    assert client.get(A).status_code == 403
    assert client.post(A, json=body()).status_code == 403
    assert client.post(f"{A}/preview", json=body()).status_code == 403
    assert client.get(L).status_code == 200


# ------------------------------------------------------------------ create / edit


def test_create_is_a_draft_with_history_and_defaults_the_author(staff: TestClient) -> None:
    m = create(staff)
    assert m["status"] == "draft" and m["revision"] == 1
    assert m["slug"] == "jazz-ii-v-i"
    assert m["definition"]["author"] == "Test User"
    assert [h["action"] for h in m["history"]] == ["create"]
    assert m["allowed_transitions"] == ["under_review", "archived"]


def test_slugs_stay_unique(staff: TestClient) -> None:
    assert create(staff)["slug"] == "jazz-ii-v-i"
    assert create(staff)["slug"] == "jazz-ii-v-i-2"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"template_id": "nope"}, None),
        ({"template_id": None}, "invalid_source"),
        ({"custom_chords": [{"symbol": "C"}]}, "invalid_source"),
        ({"template_id": None, "custom_chords": [{"symbol": "Cmaj"}]}, None),
        ({"key": {"tonic": "C", "mode": "minor"}}, "key_mode_mismatch"),
    ],
)
def test_a_definition_that_cannot_be_built_is_refused(
    staff: TestClient, change: dict[str, Any], code: str | None
) -> None:
    r = staff.post(A, json=body(**change))
    assert r.status_code == 422, r.text
    if code:
        assert r.json()["error"]["code"] == code
    assert staff.get(A).json()["total"] == 0


def test_unknown_fields_are_rejected(staff: TestClient) -> None:
    assert staff.post(A, json=body(tempoo=100)).status_code == 422


def test_edit_bumps_revision_and_needs_the_current_one(staff: TestClient) -> None:
    m = create(staff)
    r = staff.put(f"{A}/{m['id']}", json=body(name="Renamed", revision=1))
    assert r.status_code == 200 and r.json()["revision"] == 2
    stale = staff.put(f"{A}/{m['id']}", json=body(name="Again", revision=1))
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"
    assert stale.json()["error"]["details"]["current_revision"] == 2


def test_editing_after_approval_returns_to_draft(staff: TestClient) -> None:
    m = create(staff)
    move(staff, m["id"], "under_review")
    move(staff, m["id"], "approved")
    r = staff.put(f"{A}/{m['id']}", json=body(tempo=100, revision=1))
    assert r.json()["status"] == "draft"
    assert "returned to draft" in r.json()["history"][-1]["note"]


# ------------------------------------------------------------------ lifecycle


def test_cannot_skip_review(staff: TestClient) -> None:
    m = create(staff)
    r = move(staff, m["id"], "published", status=422)
    assert r["error"]["code"] == "invalid_transition"
    assert staff.get(f"{L}/{m['slug']}").status_code == 404


def test_publish_requires_the_publication_checks(staff: TestClient) -> None:
    m = create(staff, tags=[], theory_explanation="")
    move(staff, m["id"], "under_review")
    move(staff, m["id"], "approved")
    check = staff.post(f"{A}/{m['id']}/validate").json()
    assert check["publishable"] is False and check["can_publish_now"] is False
    assert any("tag" in b for b in check["blockers"])
    r = move(staff, m["id"], "published", status=409)
    assert r["error"]["code"] == "publication_blocked"
    assert r["error"]["details"]["blockers"]
    assert staff.get(f"{A}/{m['id']}").json()["status"] == "approved"


def test_full_lifecycle_and_history(staff: TestClient) -> None:
    m = publish(staff)
    assert m["status"] == "published" and m["published_at"]
    actions = [h["action"] for h in m["history"]]
    assert actions == ["create", "submit", "approve", "publish"]
    assert m["history"][-1]["from_status"] == "approved"
    gone = move(staff, m["id"], "approved", note="found a typo")
    assert gone["published_at"] is None
    assert gone["history"][-1]["action"] == "unpublish"
    assert gone["history"][-1]["note"] == "found a typo"
    archived = move(staff, m["id"], "archived")
    assert archived["allowed_transitions"] == ["draft"]
    assert move(staff, m["id"], "draft")["history"][-1]["action"] == "restore"


def test_published_movement_cannot_be_edited(staff: TestClient) -> None:
    m = publish(staff)
    r = staff.put(f"{A}/{m['id']}", json=body(name="Sneaky", revision=m["revision"]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "movement_published"


def test_archived_movement_cannot_be_edited(staff: TestClient) -> None:
    m = create(staff)
    move(staff, m["id"], "archived")
    r = staff.put(f"{A}/{m['id']}", json=body(revision=1))
    assert r.json()["error"]["code"] == "movement_archived"


def test_unknown_movement(staff: TestClient) -> None:
    ghost = "00000000-0000-0000-0000-000000000000"
    assert staff.get(f"{A}/{ghost}").json()["error"]["code"] == "movement_not_found"
    assert staff.post(f"{A}/{ghost}/status", json={"to": "approved"}).status_code == 404


def test_bad_status_value_is_a_validation_error(staff: TestClient) -> None:
    m = create(staff)
    assert staff.post(f"{A}/{m['id']}/status", json={"to": "live"}).status_code == 422


# ------------------------------------------------------------------ preview


def test_preview_does_not_save(staff: TestClient) -> None:
    r = staff.post(f"{A}/preview", json=body())
    assert r.status_code == 200
    out = r.json()
    assert [v["level"] for v in out["movement"]["versions"]] == [
        "beginner", "intermediate", "advanced", "expert",
    ]  # fmt: skip
    assert out["validation"]["publishable"] is True
    assert staff.get(A).json()["total"] == 0


def test_preview_of_stored_movement_reports_publish_readiness(staff: TestClient) -> None:
    m = create(staff)
    assert staff.get(f"{A}/{m['id']}/preview").json()["validation"]["can_publish_now"] is False
    move(staff, m["id"], "under_review")
    move(staff, m["id"], "approved")
    assert staff.get(f"{A}/{m['id']}/preview").json()["validation"]["can_publish_now"] is True


# ------------------------------------------------------------------ what learners see


def test_learners_see_only_published(staff: TestClient, sign_in: Callable[..., None]) -> None:
    draft = create(staff, name="Secret draft")
    live = publish(staff, name="Live one")
    sign_in(LEARNER)
    names = [i["name"] for i in staff.get(L).json()["items"]]
    assert names == ["Live one"]
    assert staff.get(f"{L}/{draft['slug']}").status_code == 404
    got = staff.get(f"{L}/{live['slug']}").json()
    assert got["live"] is False
    versions = got["movement"]["versions"]
    assert [s["symbol"] for s in versions[1]["steps"]] == ["Dm7", "G7", "Cmaj7"]
    assert [s["symbol"] for s in versions[3]["steps"]] == ["Dm7", "Db7", "Cmaj7"]


def test_unpublished_movement_disappears_for_learners(
    staff: TestClient, sign_in: Callable[..., None]
) -> None:
    m = publish(staff)
    move(staff, m["id"], "approved")
    sign_in(LEARNER)
    assert staff.get(L).json()["total"] == 0
    assert staff.get(f"{L}/{m['slug']}").status_code == 404


def test_published_content_is_a_frozen_snapshot(
    staff: TestClient, session_factory: Any, sign_in: Callable[..., None]
) -> None:
    from sqlalchemy import select

    from app.models.movement import Movement

    m = publish(staff)
    with session_factory() as s:
        row = s.scalar(select(Movement).where(Movement.slug == m["slug"]))
        row.definition = {**row.definition, "tempo": 200}  # definition drifts after publication
        s.commit()
    sign_in(LEARNER)
    assert staff.get(f"{L}/{m['slug']}").json()["movement"]["tempo"] == 90


def test_filters(staff: TestClient, sign_in: Callable[..., None]) -> None:
    publish(staff, name="Major one", tags=["jazz", "turnaround"])
    publish(
        staff,
        name="Minor one",
        template_id="minor_ii_v_i",
        key={"tonic": "A", "mode": "minor"},
        tags=["jazz"],
    )
    publish(staff, name="Pop one", template_id="pop_i_v_vi_iv", tags=["pop"])
    sign_in(LEARNER)

    def names(**params: str) -> list[str]:
        return [i["name"] for i in staff.get(L, params=params).json()["items"]]

    assert names() == ["Major one", "Minor one", "Pop one"]
    assert names(mode="minor") == ["Minor one"]
    assert names(tag="pop") == ["Pop one"]
    assert names(tag="JAZZ") == ["Major one", "Minor one"]
    assert names(q="turnaround") == ["Major one"]
    assert names(level="expert") == ["Major one", "Minor one", "Pop one"]
    assert names(q="zzz") == []
    assert staff.get(L, params={"level": "wizard"}).status_code == 422


def test_summary_lists_the_chords(staff: TestClient, sign_in: Callable[..., None]) -> None:
    publish(staff)
    sign_in(LEARNER)
    item = staff.get(L).json()["items"][0]
    assert item["chords"] == ["Dm7", "G7", "Cmaj7"]
    assert item["romans"] == ["ii7", "V7", "Imaj7"]
    assert item["key"] == "C major"


def test_transposed_view_is_live_and_correct(
    staff: TestClient, sign_in: Callable[..., None]
) -> None:
    m = publish(staff)
    sign_in(LEARNER)
    got = staff.get(f"{L}/{m['slug']}", params={"key": "Eb"}).json()
    assert got["live"] is True
    assert [s["symbol"] for s in got["movement"]["versions"][1]["steps"]] == [
        "Fm7", "Bb7", "Ebmaj7",
    ]  # fmt: skip
    assert [s["symbol"] for s in got["movement"]["versions"][3]["steps"]][1] == "E7"
    same = staff.get(f"{L}/{m['slug']}", params={"key": "C"}).json()
    assert same["live"] is False  # the home key is the reviewed snapshot


def test_transposing_to_a_note_that_is_not_a_note_is_an_error(
    staff: TestClient, sign_in: Callable[..., None]
) -> None:
    m = publish(staff)
    sign_in(LEARNER)
    r = staff.get(f"{L}/{m['slug']}", params={"key": "H"})
    assert r.status_code == 422


def test_custom_chord_movement_publishes(staff: TestClient) -> None:
    m = publish(
        staff,
        name="My turnaround",
        template_id=None,
        custom_chords=[
            {"symbol": "Cmaj7", "beats": 2},
            {"symbol": "A7", "beats": 2},
            {"symbol": "Dm7", "beats": 2},
            {"symbol": "G7", "beats": 2},
        ],
    )
    assert m["status"] == "published"


def test_search_and_status_filter_in_admin_list(staff: TestClient) -> None:
    publish(staff, name="Alpha")
    create(staff, name="Beta", tags=["gospel"])
    assert staff.get(A, params={"status": "draft"}).json()["total"] == 1
    assert staff.get(A, params={"q": "gospel"}).json()["items"][0]["name"] == "Beta"
    assert staff.get(A).json()["total"] == 2


# ------------------------------------------------------------------ seeding


def test_seed_publishes_every_template_once(
    client: TestClient,
    make_user: Callable[..., User],
    sign_in: Callable[..., None],
    session_factory: Any,
) -> None:
    from app.services import movement_service
    from music_theory.progressions import default_library

    with session_factory() as s:
        first = movement_service.seed_default_movements(s)
        again = movement_service.seed_default_movements(s)
    ids = default_library().ids()
    assert first["failed"] == [] and sorted(first["created"]) == sorted(ids)
    assert again["created"] == [] and len(again["skipped"]) == len(ids)
    make_user(LEARNER)
    sign_in(LEARNER)
    items = client.get(L).json()["items"]
    assert len(items) == len(ids)
    assert all(i["levels"] == ["beginner", "intermediate", "advanced", "expert"] for i in items)
