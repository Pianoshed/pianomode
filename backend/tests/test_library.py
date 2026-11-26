import base64
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.models.base import utcnow
from app.models.billing import Subscription
from app.models.library import LibraryItem
from app.models.user import User
from app.services.file_store import FileStore, get_file_store
from tests.conftest import ORIGIN

MIDI = b"MThd\x00\x00\x00\x06\x00\x01\x00\x01\x01\xe0MTrk\x00\x00\x00\x04\x00\xff\x2f\x00"
B64 = base64.b64encode(MIDI).decode()


@pytest.fixture
def limits() -> dict[str, int]:
    return {}


@pytest.fixture(autouse=True)
def library_setup(app: FastAPI, tmp_path: Path, limits: dict[str, int]) -> None:
    app.dependency_overrides[get_file_store] = lambda: FileStore(tmp_path)
    app.dependency_overrides[get_settings] = lambda: Settings(
        cors_origins=["http://localhost:3000"], **limits
    )


@pytest.fixture
def second(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, headers=ORIGIN) as c:
        yield c


def midi(c: TestClient, title: str = "Etude", **extra: object):
    return c.post(
        "/api/v1/library",
        json={
            "kind": "midi",
            "title": title,
            "data": {"v": 1, "edits": []},
            "file_name": "etude.mid",
            "file_base64": B64,
            **extra,
        },
    )


@pytest.fixture
def me(client: TestClient, make_user: Callable[..., User], sign_in) -> TestClient:
    make_user("a@example.com")
    sign_in("a@example.com")
    return client


# ------------------------------------------------------------------ saving and opening


def test_save_list_open_download_a_midi_project(me: TestClient) -> None:
    r = midi(me)
    assert r.status_code == 201, r.text
    item = r.json()
    assert (item["kind"], item["title"], item["file_size"], item["file_name"]) == (
        "midi",
        "Etude",
        len(MIDI),
        "etude.mid",
    )
    assert item["data"] == {"v": 1, "edits": []} and item["last_opened_at"] is None

    listing = me.get("/api/v1/library").json()
    assert [i["id"] for i in listing["items"]] == [item["id"]]
    assert "data" not in listing["items"][0]  # the list stays light
    assert listing["usage"]["items"] == 1 and listing["usage"]["bytes"] == len(MIDI)

    opened = me.get(f"/api/v1/library/{item['id']}").json()
    assert opened["data"] == {"v": 1, "edits": []} and opened["last_opened_at"] is not None

    f = me.get(f"/api/v1/library/{item['id']}/file")
    assert f.content == MIDI and f.headers["content-type"] == "audio/midi"
    assert 'filename="etude.mid"' in f.headers["content-disposition"]


def test_audio_and_progression_items_keep_only_settings(me: TestClient) -> None:
    a = me.post(
        "/api/v1/library",
        json={"kind": "audio", "title": "Take 3", "data": {"v": 1}, "file_name": "take3.wav"},
    )
    p = me.post(
        "/api/v1/library",
        json={"kind": "progression", "title": "ii-V-I", "data": {"slug": "ii-v-i", "tonic": "Bb"}},
    )
    assert a.status_code == 201 and p.status_code == 201
    assert a.json()["file_size"] == 0 and a.json()["file_name"] is None
    assert me.get(f"/api/v1/library/{a.json()['id']}/file").status_code == 404
    assert [
        i["kind"] for i in me.get("/api/v1/library", params={"kind": "progression"}).json()["items"]
    ] == ["progression"]


def test_rename_and_replace_settings(me: TestClient) -> None:
    item = midi(me).json()
    r = me.patch(
        f"/api/v1/library/{item['id']}",
        json={"title": "  Better   name ", "data": {"v": 1, "edits": [1]}},
    )
    assert (
        r.status_code == 200
        and r.json()["title"] == "Better name"
        and r.json()["data"]["edits"] == [1]
    )
    assert (
        me.get(f"/api/v1/library/{item['id']}/file").content == MIDI
    )  # the file itself is untouched


def test_delete_removes_item_and_file(me: TestClient, tmp_path: Path) -> None:
    item = midi(me).json()
    assert list(tmp_path.rglob("*")) and any(p.is_file() for p in tmp_path.rglob("*"))
    assert me.delete(f"/api/v1/library/{item['id']}").status_code == 204
    assert me.get(f"/api/v1/library/{item['id']}").status_code == 404
    assert not any(p.is_file() for p in tmp_path.rglob("*"))


# ------------------------------------------------------------------ privacy


def test_nobody_can_see_or_touch_anyone_elses_items(
    me: TestClient, second: TestClient, make_user
) -> None:
    item = midi(me).json()
    make_user("b@example.com")
    second.post(
        "/api/v1/auth/login",
        json={"identifier": "b@example.com", "password": "correct horse battery"},
    )
    base = f"/api/v1/library/{item['id']}"
    assert second.get("/api/v1/library").json()["items"] == []
    assert second.get(base).status_code == 404
    assert second.get(base + "/file").status_code == 404
    assert second.patch(base, json={"title": "mine now"}).status_code == 404
    assert second.delete(base).status_code == 404
    assert me.get(base).status_code == 200  # still there


def test_signed_out_callers_are_refused(client: TestClient) -> None:
    assert client.get("/api/v1/library").status_code == 401
    assert client.get("/api/v1/dashboard").status_code == 401


# ------------------------------------------------------------------ validation and limits


@pytest.mark.parametrize(
    "body,code",
    [
        ({"kind": "midi", "title": "x", "data": {}}, "file_required"),
        ({"kind": "midi", "title": "x", "data": {}, "file_base64": "###"}, "bad_file"),
        (
            {
                "kind": "midi",
                "title": "x",
                "data": {},
                "file_base64": base64.b64encode(b"RIFFnotmidi").decode(),
            },
            "not_midi",
        ),
        ({"kind": "audio", "title": "x", "data": {}, "file_base64": B64}, "file_not_allowed"),
        ({"kind": "audio", "title": "x", "data": {"blob": "y" * 300_000}}, "data_too_large"),
    ],
)
def test_bad_items_are_refused(me: TestClient, body: dict, code: str) -> None:
    r = me.post("/api/v1/library", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == code


def test_unknown_kind_and_blank_title_are_refused(me: TestClient) -> None:
    assert me.post("/api/v1/library", json={"kind": "video", "title": "x"}).status_code == 422
    assert me.post("/api/v1/library", json={"kind": "audio", "title": "   "}).status_code == 422


@pytest.mark.parametrize("limits", [{"library_max_items": 2}])
def test_item_limit(me: TestClient) -> None:
    for n in range(2):
        assert (
            me.post("/api/v1/library", json={"kind": "audio", "title": f"t{n}"}).status_code == 201
        )
    r = me.post("/api/v1/library", json={"kind": "audio", "title": "third"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "library_full"


@pytest.mark.parametrize("limits", [{"library_max_file_bytes": 10}])
def test_file_size_limit(me: TestClient) -> None:
    r = midi(me)
    assert r.status_code == 422 and r.json()["error"]["code"] == "file_too_large"


@pytest.mark.parametrize("limits", [{"library_max_total_bytes": len(MIDI) + 5}])
def test_total_storage_limit(me: TestClient) -> None:
    assert midi(me, "one").status_code == 201
    r = midi(me, "two")
    assert r.status_code == 409 and r.json()["error"]["code"] == "library_storage_full"
    # Deleting frees the room.
    first = me.get("/api/v1/library").json()["items"][0]["id"]
    me.delete(f"/api/v1/library/{first}")
    assert midi(me, "two").status_code == 201


def test_a_hostile_file_name_cannot_escape_the_store(me: TestClient, tmp_path: Path) -> None:
    r = midi(me, file_name="../../../etc/passwd")
    assert r.status_code == 201 and r.json()["file_name"] == "passwd"
    assert all(tmp_path in p.resolve().parents or p == tmp_path for p in tmp_path.rglob("*"))


def test_file_store_refuses_bad_keys(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    for key in ("../x", "a/b", "/etc/passwd", "x" * 36 + "/" + "y" * 36):
        with pytest.raises(ValueError):
            store.write(key, b"x")


# ------------------------------------------------------------------ plan rules


def test_an_expired_plan_can_still_read_download_and_delete_but_not_save(
    me: TestClient, session_factory: sessionmaker[Session]
) -> None:
    item = midi(me).json()
    me.get("/api/v1/billing/status")  # starts the trial
    with session_factory() as s:
        s.scalar(select(Subscription)).current_period_end = utcnow() - timedelta(days=1)
        s.commit()
    assert me.get("/api/v1/library").status_code == 200
    assert me.get(f"/api/v1/library/{item['id']}").status_code == 200
    assert me.get(f"/api/v1/library/{item['id']}/file").content == MIDI
    assert midi(me, "new").status_code == 402
    assert me.patch(f"/api/v1/library/{item['id']}", json={"title": "x"}).status_code == 402
    assert me.delete(f"/api/v1/library/{item['id']}").status_code == 204


def test_institution_logins_can_save_too(
    client: TestClient, make_user, sign_in, paystack_owner
) -> None:
    owner, cred = paystack_owner
    r = client.post("/api/v1/library", json={"kind": "audio", "title": "student work"})
    assert r.status_code == 201


@pytest.fixture
def paystack_owner(client: TestClient, make_user, sign_in, app: FastAPI):
    from app.services.paystack import CheckoutSession, VerifiedTransaction, get_paystack_client

    class Fake:
        amounts: dict[str, int] = {}

        def initialize(self, **k):  # type: ignore[no-untyped-def]
            self.amounts[k["reference"]] = k["amount_kobo"]
            return CheckoutSession("u", "c")

        def verify(self, ref):  # type: ignore[no-untyped-def]
            return VerifiedTransaction(ref, "success", self.amounts[ref], "NGN", "ok")

    app.dependency_overrides[get_paystack_client] = lambda: Fake()
    make_user("owner@school.ng")
    sign_in("owner@school.ng")
    ref = client.post(
        "/api/v1/billing/checkout", json={"plan": "institution_10", "institution_name": "S"}
    ).json()["reference"]
    client.post("/api/v1/billing/verify", json={"reference": ref})
    cred = client.post("/api/v1/institution/seats", json={"names": ["Ada"]}).json()["credentials"][
        0
    ]
    client.post("/api/v1/auth/logout")
    r = client.post(
        "/api/v1/auth/login", json={"identifier": cred["login_id"], "password": cred["password"]}
    )
    assert r.status_code == 200
    return "owner", cred


# ------------------------------------------------------------------ dashboard


def test_dashboard_is_empty_for_a_new_person_and_recommends_a_start(me: TestClient) -> None:
    d = me.get("/api/v1/dashboard").json()
    assert (
        d["continue_learning"] == []
        and d["recent_projects"] == []
        and d["saved_progressions"] == []
    )
    assert len(d["activity"]) == 7 and d["activity_total"] == 0
    assert d["recommended"] is not None and d["recommended"]["reason"]


def test_dashboard_shows_recent_projects_progressions_and_activity(
    me: TestClient, session_factory: sessionmaker[Session]
) -> None:
    a = midi(me, "First").json()
    b = me.post("/api/v1/library", json={"kind": "audio", "title": "Second"}).json()
    me.post(
        "/api/v1/library",
        json={"kind": "progression", "title": "ii-V-I", "data": {"slug": "x", "tonic": "C"}},
    )
    me.get(f"/api/v1/library/{a['id']}")  # opening it makes it the most recent
    d = me.get("/api/v1/dashboard").json()
    assert [p["title"] for p in d["recent_projects"]] == ["First", "Second"]
    assert [p["kind"] for p in d["recent_projects"]] == ["midi", "audio"]
    assert (
        d["saved_progressions"][0]["title"] == "ii-V-I"
        and d["saved_progressions"][0]["data"]["tonic"] == "C"
    )

    assert b["id"]


def test_dashboard_activity_counts_todays_work(
    me: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from app.models.exercise_attempt import ExerciseAttempt

    with session_factory() as s:
        user = s.scalar(select(User).where(User.email == "a@example.com"))
        for correct in (True, False, True):
            s.add(
                ExerciseAttempt(
                    user_id=user.id,
                    exercise_id="x",
                    kind="k",
                    difficulty="d",
                    status="s",
                    correct=correct,
                )
            )
        s.add(
            ExerciseAttempt(
                user_id=user.id,
                exercise_id="x",
                kind="k",
                difficulty="d",
                status="s",
                correct=True,
                created_at=utcnow() - timedelta(days=30),
            )
        )
        s.commit()
    d = me.get("/api/v1/dashboard").json()
    assert d["activity_total"] == 3 and d["activity"][-1]["count"] == 3


def test_dashboard_items_belong_to_their_owner_only(
    me: TestClient, second: TestClient, make_user
) -> None:
    midi(me, "private")
    make_user("b@example.com")
    second.post(
        "/api/v1/auth/login",
        json={"identifier": "b@example.com", "password": "correct horse battery"},
    )
    assert second.get("/api/v1/dashboard").json()["recent_projects"] == []


def test_library_items_are_in_the_database_with_the_owner(me: TestClient, session_factory) -> None:
    midi(me)
    with session_factory() as s:
        item = s.scalar(select(LibraryItem))
        assert item.user_id is not None and item.data == {"v": 1, "edits": []}


# ------------------------------------------------------------------ search and cleanup


def test_search_finds_titles_ignoring_case_and_treats_symbols_literally(me: TestClient) -> None:
    for title in ("Moonlight Sonata", "Autumn Leaves", "100% focus", "a_b"):
        me.post("/api/v1/library", json={"kind": "audio", "title": title})

    def found(q: str) -> list[str]:
        items = me.get("/api/v1/library", params={"q": q}).json()["items"]
        return sorted(i["title"] for i in items)

    assert found("moon") == ["Moonlight Sonata"]
    assert found("LEAVES") == ["Autumn Leaves"]
    assert found("%") == ["100% focus"]  # a percent sign is just a character
    assert found("_") == ["a_b"]
    assert found("   ") != [] and found("zzz") == []
    me.post("/api/v1/library", json={"kind": "progression", "title": "Moon walk"})
    both = me.get("/api/v1/library", params={"q": "moon", "kind": "progression"}).json()["items"]
    assert [i["title"] for i in both] == ["Moon walk"]


def test_search_only_looks_in_your_own_items(me: TestClient, second: TestClient, make_user) -> None:
    me.post("/api/v1/library", json={"kind": "audio", "title": "Secret tune"})
    make_user("b@example.com")
    second.post(
        "/api/v1/auth/login",
        json={"identifier": "b@example.com", "password": "correct horse battery"},
    )
    assert second.get("/api/v1/library", params={"q": "secret"}).json()["items"] == []


def test_cleanup_finds_stray_files_and_missing_ones(
    me: TestClient, session_factory, tmp_path: Path
) -> None:
    from scripts.cleanup_storage import scan

    kept = midi(me, "kept").json()
    gone = midi(me, "gone").json()
    store = FileStore(tmp_path)
    stray_key = "11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222"
    store.write(stray_key, b"x")
    with session_factory() as s:
        owner = s.scalar(select(LibraryItem.user_id).where(LibraryItem.id == uuid.UUID(gone["id"])))
        store.delete(store.key(owner, uuid.UUID(gone["id"])))  # the file vanished, the row stayed
        stray, missing = scan(s, store)
    assert stray == [stray_key] and missing == [gone["id"]]
    assert kept["id"] not in missing
