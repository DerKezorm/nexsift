import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from tests.conftest import PASSWORD, UI


def test_first_start_creates_the_operator_once(client: TestClient) -> None:
    assert client.get("/api/setup").json()["needs_setup"] is True
    response = client.post("/api/setup", json={"name": "admin", "password": PASSWORD}, headers=UI)
    assert response.status_code == 200
    assert client.get("/api/auth/me").json()["name"] == "admin"
    again = client.post("/api/setup", json={"name": "other", "password": PASSWORD}, headers=UI)
    assert again.status_code == 409
    assert client.get("/api/setup").json()["needs_setup"] is False


def test_setup_installs_the_general_rules(client: TestClient, operator: dict) -> None:
    names = [rule["name"] for rule in client.get("/api/rules").json()]
    assert "Words for failures make it critical" in names


def test_short_password_is_refused(client: TestClient) -> None:
    response = client.post("/api/setup", json={"name": "admin", "password": "short"}, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "password_too_short"


def test_changing_requests_need_the_header(client: TestClient, operator: dict) -> None:
    response = client.post("/api/sources", json={"preset": "webhook"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "missing_header"


def test_sign_in_and_out(client: TestClient, operator: dict) -> None:
    client.post("/api/auth/logout", headers=UI)
    assert client.get("/api/auth/me").status_code == 401
    wrong = client.post("/api/auth/login", json={"name": "admin", "password": "wrong-password-123"}, headers=UI)
    assert wrong.status_code == 401
    right = client.post("/api/auth/login", json={"name": "admin", "password": PASSWORD}, headers=UI)
    assert right.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_everything_else_needs_a_session(client: TestClient) -> None:
    for path in ("/api/threads", "/api/sources", "/api/rules", "/api/targets", "/api/settings", "/api/about"):
        assert client.get(path).status_code == 401, path


def test_password_cannot_be_switched_off_without_a_provider(client: TestClient, operator: dict) -> None:
    response = client.put("/api/settings", json={"values": {"password_login": False}}, headers=UI)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "password_needed"


def test_a_fresh_account_has_seen_this_version(client: TestClient, operator: dict) -> None:
    """Nothing is "new" on a fresh install: the "What's new" window starts with the next update."""
    from app import __version__

    assert client.get("/api/auth/me").json()["prefs"]["seen_version"] == __version__


def test_the_session_cookie_is_secure_by_the_rightmost_forwarded_scheme(
    client: TestClient, operator: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "cookie_secure", "auto")

    def cookie_with(proto: str) -> str:
        sent = client.post(
            "/api/auth/login",
            json={"name": "admin", "password": PASSWORD},
            headers={**UI, "X-Forwarded-Proto": proto},
        )
        assert sent.status_code == 200, sent.text
        return sent.headers["set-cookie"].lower()

    assert "secure" in cookie_with("HTTPS")
    assert "secure" in cookie_with("http, https")
    assert "secure" not in cookie_with("https, http")
