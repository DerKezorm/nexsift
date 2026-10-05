"""The about page and the update check, as in nexlore.

The check is a side matter: when GitHub is slow, gone or answers rubbish, the page shows no answer and nothing else
changes. No test here reaches GitHub; the conftest points the address at a port that refuses.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.services import icons, updates
from tests.conftest import UI


def answers(monkeypatch: pytest.MonkeyPatch, tag: str | None) -> list[int]:
    asked: list[int] = []

    def ask() -> str | None:
        asked.append(1)
        return tag

    monkeypatch.setattr(updates, "_ask", ask)
    return asked


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("v0.8.0", "0.7.3", True),
        ("0.7.3", "0.7.3", False),
        ("v0.7.0", "0.8.0", False),
        # What a comparison of text gets wrong, exactly once: at the tenth minor version.
        ("v0.10.0", "0.9.0", True),
        ("v0.9.0", "0.10.0", False),
        ("v1.0.0", "0.99.0", True),
        ("not-a-tag", "0.1.0", False),
        ("", "0.1.0", False),
    ],
)
def test_versions_are_compared_as_numbers(latest: str, current: str, expected: bool) -> None:
    assert updates.is_newer(latest, current) is expected


def test_the_about_page_names_version_licence_and_where_it_comes_from(client: TestClient, operator: dict) -> None:
    about = client.get("/api/about").json()
    assert about["version"] == __version__
    assert about["license"] == "AGPL-3.0"
    assert about["repo_url"] == "https://github.com/DerKezorm/nexsift"
    assert about["releases_url"] == "https://github.com/DerKezorm/nexsift/releases"
    assert about["project_url"] == ""
    assert "ports" in about and "doors" in about, "the sources page still reads the doors from here"


def test_the_answer_needs_a_session(client: TestClient, operator: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    answers(monkeypatch, "v99.0.0")
    seen = client.get("/api/about/updates").json()
    assert (seen["update_check"], seen["checked"], seen["latest"], seen["newer"]) == (True, True, "v99.0.0", True)
    assert seen["release_url"] == "https://github.com/DerKezorm/nexsift/releases/tag/v99.0.0"
    client.post("/api/auth/logout", headers=UI)
    assert client.get("/api/about/updates").status_code == 401
    assert client.post("/api/about/updates/check", headers=UI).status_code == 401


def test_on_by_default_asked_once_a_day_and_again_when_a_day_is_over(
    client: TestClient, operator: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = answers(monkeypatch, "v0.0.1")
    first = client.get("/api/about/updates").json()
    assert (first["update_check"], first["checked"], first["newer"]) == (True, True, False)
    client.get("/api/about/updates")
    client.get("/api/about/updates")
    assert len(asked) == 1
    old = updates._known
    assert old is not None and old.checked_at is not None
    updates._known = updates.State(
        current=old.current, latest=old.latest, checked_at=old.checked_at - timedelta(hours=25)
    )
    client.get("/api/about/updates")
    assert len(asked) == 2


def test_off_means_not_by_itself_and_the_button_still_asks(
    client: TestClient, operator: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = answers(monkeypatch, "v99.0.0")
    off = client.put("/api/about/updates", json={"update_check": False}, headers=UI).json()
    assert (off["update_check"], off["checked"], off["latest"]) == (False, False, None)
    assert client.get("/api/about/updates").json()["checked"] is False
    assert asked == []
    now = client.post("/api/about/updates/check", headers=UI).json()
    assert (now["update_check"], now["checked"], now["newer"]) == (False, True, True)
    assert len(asked) == 1
    assert client.put("/api/about/updates", json={"update_check": True}, headers=UI).json()["update_check"] is True


def test_a_failed_check_keeps_what_the_last_good_one_found(
    client: TestClient, operator: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers(monkeypatch, "v99.0.0")
    client.post("/api/about/updates/check", headers=UI)
    answers(monkeypatch, None)
    again = client.post("/api/about/updates/check", headers=UI).json()
    assert (again["latest"], again["newer"]) == ("v99.0.0", True)


def test_a_refused_question_shows_no_answer_and_breaks_nothing(client: TestClient, operator: dict) -> None:
    # The real _ask, against the port the conftest names: it refuses.
    seen = client.post("/api/about/updates/check", headers=UI).json()
    assert (seen["checked"], seen["latest"], seen["newer"]) == (True, None, False)


def test_only_a_version_counts_as_an_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    real = httpx.Client
    for tag, expected in (("v1.2.3", "v1.2.3"), ("<script>", None), (123, None), ("v1.2", None)):

        def handler(request: httpx.Request, tag: object = tag) -> httpx.Response:
            return httpx.Response(200, json={"tag_name": tag})

        monkeypatch.setattr(
            httpx,
            "Client",
            lambda *args, handler=handler, **kwargs: real(
                *args, **{**kwargs, "transport": httpx.MockTransport(handler)}
            ),
        )
        assert updates._ask() == expected, tag
        monkeypatch.setattr(httpx, "Client", real)


def test_the_icon_switch_keeps_nexsift_from_fetching_logos(client: TestClient, operator: dict) -> None:
    asked: list[str] = []

    def cdn(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nfake", headers={"content-type": "image/png"})

    icons.reset_for_tests()
    icons.transport_for_tests = httpx.MockTransport(cdn)
    try:
        assert client.put("/api/settings", json={"values": {"icons_from_web": False}}, headers=UI).status_code == 200
        listing = client.get("/api/icons").json()
        assert listing and all(entry["icon"].startswith("nexapps/") for entry in listing)
        assert client.get("/api/icons/dashboard-icons/proxmox.png").status_code == 404
        assert client.get("/api/icons/nexapps/nexsift.png").status_code == 200, "the family ships with nexsift"
        assert asked == []
        assert client.put("/api/settings", json={"values": {"icons_from_web": True}}, headers=UI).status_code == 200
        assert client.get("/api/icons/dashboard-icons/proxmox.png").status_code == 200
        assert len(asked) == 1
    finally:
        icons.transport_for_tests = None
        icons.reset_for_tests()
