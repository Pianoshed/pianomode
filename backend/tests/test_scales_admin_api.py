"""Administrator-defined scales: permissions, validation, lifecycle and effect on theory routes."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models.user import Role, User

A = "/api/v1/admin/scales"
T = "/api/v1/theory"
ADMIN = "admin@example.com"
EDUCATOR = "teacher@example.com"
LEARNER = "learner@example.com"

# Hungarian minor: a real scale that is not built in.
HUNGARIAN = {
    "id": "hungarian_minor",
    "name": "Hungarian minor",
    "family": "exotic",
    "formula": ["P1", "M2", "m3", "A4", "P5", "m6", "M7"],
    "aliases": ["gypsy_minor"],
}


def body(**over: Any) -> dict[str, Any]:
    return {**HUNGARIAN, **over}


@pytest.fixture
def users(make_user: Callable[..., User]) -> None:
    make_user(LEARNER)
    make_user(EDUCATOR, roles=(Role.EDUCATOR,))
    make_user(ADMIN, roles=(Role.ADMIN,))


@pytest.fixture
def admin(client: TestClient, users: None, sign_in: Callable[..., None]) -> TestClient:
    sign_in(ADMIN)
    return client


def create(c: TestClient, **over: Any) -> dict[str, Any]:
    r = c.post(A, json=body(**over))
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


def move(c: TestClient, rid: str, to: str, status: int = 200) -> dict[str, Any]:
    r = c.post(f"{A}/{rid}/status", json={"to": to})
    assert r.status_code == status, r.text
    data: dict[str, Any] = r.json()
    return data


def test_only_admins_can_manage_scales(
    client: TestClient, users: None, sign_in: Callable[..., None]
) -> None:
    assert client.get(A).status_code == 401
    for who in (LEARNER, EDUCATOR):
        sign_in(who)
        assert client.get(A).status_code == 403
        assert client.post(A, json=body()).status_code == 403


def test_create_returns_a_draft_with_history(admin: TestClient) -> None:
    d = create(admin)
    assert d["status"] == "draft" and d["revision"] == 1
    assert d["allowed_transitions"] == ["published", "archived"]
    assert d["history"][0]["action"] == "create"


def test_draft_is_invisible_to_theory_routes(admin: TestClient) -> None:
    create(admin)
    ids = [x["id"] for x in admin.get(f"{T}/scales").json()["scales"]]
    assert "hungarian_minor" not in ids
    r = admin.post(f"{T}/scales/generate", json={"root": "C", "scale": "hungarian_minor"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_scale"


def test_published_scale_appears_and_generates(admin: TestClient) -> None:
    move(admin, create(admin)["id"], "published")
    scales = admin.get(f"{T}/scales").json()["scales"]
    mine = next(x for x in scales if x["id"] == "hungarian_minor")
    assert mine["builtin"] is False
    assert all(x["builtin"] for x in scales if x["id"] == "major")
    g = admin.post(f"{T}/scales/generate", json={"root": "C", "scale": "hungarian_minor"}).json()
    assert g["notes"] == ["C", "D", "Eb", "F#", "G", "Ab", "B"]
    assert g["fingering"] is None
    alias = admin.post(f"{T}/scales/generate", json={"root": "A", "scale": "gypsy_minor"})
    assert alias.status_code == 200
    assert alias.json()["notes"] == ["A", "B", "C", "D#", "E", "F", "G#"]


def test_learners_see_published_scales(admin: TestClient, sign_in: Callable[..., None]) -> None:
    move(admin, create(admin)["id"], "published")
    sign_in(LEARNER)
    ids = [x["id"] for x in admin.get(f"{T}/scales").json()["scales"]]
    assert "hungarian_minor" in ids


def test_unpublish_and_archive_remove_it(admin: TestClient) -> None:
    rid = create(admin)["id"]
    move(admin, rid, "published")
    move(admin, rid, "draft")
    ids = [x["id"] for x in admin.get(f"{T}/scales").json()["scales"]]
    assert "hungarian_minor" not in ids
    move(admin, rid, "published")
    move(admin, rid, "archived")
    ids = [x["id"] for x in admin.get(f"{T}/scales").json()["scales"]]
    assert "hungarian_minor" not in ids
    assert move(admin, rid, "draft")["status"] == "draft"


def test_invalid_transitions_are_refused(admin: TestClient) -> None:
    rid = create(admin)["id"]
    move(admin, rid, "archived")
    r = admin.post(f"{A}/{rid}/status", json={"to": "published"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"


def test_cannot_redefine_a_builtin(admin: TestClient) -> None:
    r = admin.post(A, json=body(id="major", name="Mine"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "scale_id_builtin"


def test_alias_clash_with_builtin_blocks_publication(admin: TestClient) -> None:
    rid = create(admin, id="my_minor", name="My minor", aliases=["aeolian"])["id"]
    r = admin.post(f"{A}/{rid}/status", json={"to": "published"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "publication_blocked"
    assert "aeolian" in r.json()["error"]["details"]["blockers"][0]


def test_alias_must_be_identifier_form(admin: TestClient) -> None:
    r = admin.post(A, json=body(aliases=["gypsy minor"]))
    assert r.status_code == 422


def test_two_published_scales_cannot_share_an_alias(admin: TestClient) -> None:
    move(admin, create(admin)["id"], "published")
    other = create(admin, id="other_scale", name="Other", aliases=["gypsy_minor"])
    r = admin.post(f"{A}/{other['id']}/status", json={"to": "published"})
    assert r.status_code == 409


def test_duplicate_id_is_a_conflict(admin: TestClient) -> None:
    create(admin)
    r = admin.post(A, json=body())
    assert r.status_code == 409 and r.json()["error"]["code"] == "scale_id_taken"


@pytest.mark.parametrize(
    "bad",
    [
        {"formula": ["M2", "M3", "P5"]},  # must start with P1
        {"formula": ["P1", "M3", "M2"]},  # must rise
        {"formula": ["P1", "M2"]},  # too short
        {"formula": ["P1", "M2", "X3"]},  # not an interval
        {"formula": ["P1", "M2", "m3"], "descending": ["P1", "M2", "m3", "P4"]},  # length differs
        {"id": "Bad Id"},
        {"name": ""},
    ],
)
def test_malformed_definitions_are_rejected(admin: TestClient, bad: dict[str, Any]) -> None:
    r = admin.post(A, json=body(**bad))
    assert r.status_code == 422, r.text


def test_update_edits_a_draft_and_bumps_revision(admin: TestClient) -> None:
    d = create(admin)
    r = admin.put(f"{A}/{d['id']}", json=body(name="Hungarian minor (edited)", revision=1))
    assert r.status_code == 200
    assert r.json()["revision"] == 2 and r.json()["name"] == "Hungarian minor (edited)"


def test_stale_revision_is_a_conflict(admin: TestClient) -> None:
    d = create(admin)
    admin.put(f"{A}/{d['id']}", json=body(revision=1))
    r = admin.put(f"{A}/{d['id']}", json=body(revision=1))
    assert r.status_code == 409 and r.json()["error"]["code"] == "revision_conflict"
    assert r.json()["error"]["details"]["current_revision"] == 2


def test_published_scale_cannot_be_edited(admin: TestClient) -> None:
    d = create(admin)
    move(admin, d["id"], "published")
    r = admin.put(f"{A}/{d['id']}", json=body(revision=1))
    assert r.status_code == 409 and r.json()["error"]["code"] == "scale_published"


def test_edit_after_unpublish_takes_effect(admin: TestClient) -> None:
    d = create(admin)
    move(admin, d["id"], "published")
    move(admin, d["id"], "draft")
    admin.put(
        f"{A}/{d['id']}", json=body(formula=["P1", "M2", "m3", "P4", "P5", "m6", "M7"], revision=1)
    )
    move(admin, d["id"], "published")
    g = admin.post(f"{T}/scales/generate", json={"root": "C", "scale": "hungarian_minor"}).json()
    assert g["notes"] == ["C", "D", "Eb", "F", "G", "Ab", "B"]


def test_preview_reports_spelling_and_lookalikes(admin: TestClient) -> None:
    r = admin.post(f"{A}/preview", json=body())
    assert r.status_code == 200
    p = r.json()
    assert p["size"] == 7 and p["blockers"] == []
    c = next(x for x in p["roots"] if x["root"] == "C")
    assert c["notes"] == ["C", "D", "Eb", "F#", "G", "Ab", "B"]
    assert len(p["roots"]) == 12

    dup = admin.post(
        f"{A}/preview",
        json=body(id="dorian_copy", formula=["P1", "M2", "m3", "P4", "P5", "M6", "m7"], aliases=[]),
    )
    assert "dorian" in dup.json()["same_pattern_as"]
    assert any("same pitch pattern" in w for w in dup.json()["warnings"])


def test_preview_flags_blockers_without_saving(admin: TestClient) -> None:
    p = admin.post(f"{A}/preview", json=body(id="x_scale", aliases=["ionian"])).json()
    assert p["blockers"]
    assert admin.get(A).json()["total"] == 0


def test_list_filters_by_status(admin: TestClient) -> None:
    move(admin, create(admin)["id"], "published")
    create(admin, id="second", name="Second", aliases=[])
    assert admin.get(A).json()["total"] == 2
    assert admin.get(A, params={"status": "published"}).json()["total"] == 1


def test_history_records_every_change(admin: TestClient) -> None:
    d = create(admin)
    move(admin, d["id"], "published")
    h = admin.get(f"{A}/{d['id']}").json()["history"]
    assert [e["action"] for e in h] == ["create", "status"]
    assert h[1]["from_status"] == "draft" and h[1]["to_status"] == "published"


def test_unknown_id_is_404(admin: TestClient) -> None:
    r = admin.get(f"{A}/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404 and r.json()["error"]["code"] == "scale_not_found"


def test_builtin_scales_are_unaffected(admin: TestClient) -> None:
    before = admin.post(f"{T}/scales/generate", json={"root": "C", "scale": "major"}).json()
    move(admin, create(admin)["id"], "published")
    after = admin.post(f"{T}/scales/generate", json={"root": "C", "scale": "major"}).json()
    assert before["notes"] == after["notes"]
    assert after["fingering"]["right_hand"] == [1, 2, 3, 1, 2, 3, 4, 5]
