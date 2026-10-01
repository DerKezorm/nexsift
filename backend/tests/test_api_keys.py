"""Read-only API keys for dashboards: behind the operator's switch, shown once, only the Authorization header, only
counts and titles."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import ApiKey, utcnow
from tests.conftest import UI, add_source


def _open(client: TestClient) -> None:
    assert client.put("/api/settings", json={"values": {"api_keys_allowed": True}}, headers=UI).status_code == 200


def _key(client: TestClient, name: str = "nexdeck") -> dict:
    response = client.post("/api/api-keys", json={"name": name}, headers=UI)
    assert response.status_code == 201, response.text
    return response.json()


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def test_a_key_is_shown_once_and_kept_only_as_a_hash(client: TestClient, operator: dict) -> None:
    created = _key(client, "  nexdeck   wall ")
    assert created["key"].startswith("nxs_") and len(created["key"]) > 40
    assert created["name"] == "nexdeck wall" and created["prefix"] == created["key"][:8]
    listed = client.get("/api/api-keys").json()
    assert listed["allowed"] is False, "closed until the operator opens it"
    assert [key["name"] for key in listed["keys"]] == ["nexdeck wall"]
    assert "key" not in listed["keys"][0] and created["key"] not in str(listed)
    with SessionLocal() as db:
        row = db.get(ApiKey, created["id"])
        assert row is not None and created["key"] not in (row.token_hash, row.prefix)


def test_the_switch_closes_the_door_without_deleting_a_key(client: TestClient, operator: dict) -> None:
    key = _key(client)["key"]
    closed = client.get("/api/v1/status", headers=_bearer(key))
    assert closed.status_code == 403 and closed.json()["detail"]["code"] == "api_keys_off"
    _open(client)
    assert client.get("/api/v1/status", headers=_bearer(key)).status_code == 200
    client.put("/api/settings", json={"values": {"api_keys_allowed": False}}, headers=UI)
    assert client.get("/api/v1/status", headers=_bearer(key)).status_code == 403
    assert len(client.get("/api/api-keys").json()["keys"]) == 1, "closing deletes nothing"


def test_only_a_valid_key_in_the_header_gets_in(client: TestClient, operator: dict) -> None:
    _open(client)
    key = _key(client)["key"]
    # The signed-in browser of the test client carries the session cookie: it does not count here.
    without = client.get("/api/v1/status")
    assert without.status_code == 401 and without.json()["detail"]["code"] == "api_key_missing"
    for wrong in (key + "x", "nxs_" + "a" * 43, key.removeprefix("nxs_"), "x" * 300):
        refused = client.get("/api/v1/status", headers=_bearer(wrong))
        assert refused.status_code == 401 and refused.json()["detail"]["code"] == "api_key_invalid", wrong[:10]
    assert client.get("/api/v1/status", headers={"Authorization": key}).status_code == 401, "Bearer is needed"
    # And a key opens nothing else.
    signed_out = TestClient(client.app, base_url="http://testserver")
    assert signed_out.get("/api/v1/status", headers=_bearer(key)).status_code == 200
    for path in ("/api/threads", "/api/sources", "/api/targets", "/api/settings", "/api/backups", "/api/logs"):
        assert signed_out.get(path, headers=_bearer(key)).status_code == 401, path


def test_a_deleted_key_stops_at_once(client: TestClient, operator: dict) -> None:
    _open(client)
    created = _key(client)
    assert client.delete(f"/api/api-keys/{created['id']}", headers=UI).status_code == 204
    assert client.get("/api/v1/status", headers=_bearer(created["key"])).status_code == 401
    assert client.delete(f"/api/api-keys/{created['id']}", headers=UI).status_code == 404


def test_names_and_the_limit_are_checked(client: TestClient, operator: dict) -> None:
    assert (
        client.post("/api/api-keys", json={"name": "   "}, headers=UI).json()["detail"]["code"]
        == "api_key_name_missing"
    )
    assert client.post("/api/api-keys", json={"name": "x" * 65}, headers=UI).status_code == 422
    for number in range(20):
        _key(client, f"dash {number}")
    full = client.post("/api/api-keys", json={"name": "one more"}, headers=UI)
    assert full.status_code == 422 and full.json()["detail"]["code"] == "api_key_limit"


def test_keys_are_managed_by_the_signed_in_operator_only(client: TestClient, operator: dict) -> None:
    signed_out = TestClient(client.app, base_url="http://testserver")
    assert signed_out.get("/api/api-keys").status_code == 401
    assert signed_out.post("/api/api-keys", json={"name": "x"}, headers=UI).status_code == 401
    assert client.post("/api/api-keys", json={"name": "x"}).status_code == 403, "no CSRF header"


def test_last_use_is_remembered_but_not_on_every_call(client: TestClient, operator: dict) -> None:
    _open(client)
    created = _key(client)
    assert client.get("/api/api-keys").json()["keys"][0]["last_used_at"] is None
    client.get("/api/v1/status", headers=_bearer(created["key"]))
    first = client.get("/api/api-keys").json()["keys"][0]["last_used_at"]
    assert first is not None
    client.get("/api/v1/status", headers=_bearer(created["key"]))
    assert client.get("/api/api-keys").json()["keys"][0]["last_used_at"] == first
    with SessionLocal() as db:
        row = db.get(ApiKey, created["id"])
        row.last_used_at = utcnow() - timedelta(minutes=5)
        db.commit()
    client.get("/api/v1/status", headers=_bearer(created["key"]))
    assert client.get("/api/api-keys").json()["keys"][0]["last_used_at"] > first


def test_status_and_threads_say_what_a_dashboard_needs_and_nothing_more(client: TestClient, operator: dict) -> None:
    _open(client)
    key = _key(client)["key"]
    source = add_source(client, "webhook", "nexcrate")
    path = source["connection"]["url"].split(":8490", 1)[-1]
    client.post(path, json={"title": "Disk failed on nas01", "message": "secret details here", "priority": "crit"})
    client.post(path, json={"title": "Backup done", "message": "all fine", "priority": "info"})

    status = client.get("/api/v1/status", headers=_bearer(key)).json()
    assert set(status) == {
        "version",
        "unread",
        "critical_open",
        "warnings_unread",
        "lines",
        "messages_today",
        "sources",
        "targets_failing",
        "last_message_at",
    }
    assert (status["unread"], status["critical_open"], status["lines"], status["sources"]) == (2, 1, 2, 1)
    assert status["messages_today"] == 2 and status["last_message_at"]

    lines = client.get("/api/v1/threads", headers=_bearer(key)).json()
    assert [line["title"] for line in lines] == ["Backup done", "Disk failed on nas01"]
    assert set(lines[0]) == {"id", "title", "source", "priority", "state", "count", "first_at", "last_at", "resolved"}
    assert lines[1]["source"] == "nexcrate" and lines[1]["priority"] == "crit"
    assert "secret details" not in str(lines), "no message text"
    assert source["connection"]["token"] not in str(lines) + str(status)
    critical = client.get("/api/v1/threads", params={"view": "crit", "limit": 5}, headers=_bearer(key)).json()
    assert [line["title"] for line in critical] == ["Disk failed on nas01"]
    assert client.get("/api/v1/threads", params={"view": "archived"}, headers=_bearer(key)).status_code == 422
    assert client.get("/api/v1/threads", params={"limit": 51}, headers=_bearer(key)).status_code == 422


def test_the_own_webhook_under_the_same_prefix_needs_no_key(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook", "nexcrate")
    path = source["connection"]["url"].split(":8490", 1)[-1]
    assert path.startswith("/api/v1/hook/")
    assert client.post(path, json={"title": "still arrives"}).status_code == 202
