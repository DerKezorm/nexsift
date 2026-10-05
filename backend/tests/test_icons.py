"""An icon per source (issue #2): picked in the interface, sent to ntfy and web push, fetched by nexsift for the
interface. The sender's own icon wins over the source's."""

import asyncio
import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.services import icons, push, webpush
from tests.conftest import UI, add_source

SENT: list[dict] = []
PNG = b"\x89PNG\r\n\x1a\nfake"
DASHBOARD_PROXMOX = "https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/png/proxmox.png"


@pytest.fixture(autouse=True)
def _clean_icons(tmp_path, monkeypatch):
    icons.reset_for_tests()
    monkeypatch.setattr(icons, "_cache_dir", lambda: tmp_path)
    # Never the real internet: a test that forgets its own transport gets nothing.
    icons.transport_for_tests = httpx.MockTransport(lambda request: httpx.Response(404))
    yield
    icons.transport_for_tests = None
    icons.reset_for_tests()


def _record(request: httpx.Request) -> httpx.Response:
    SENT.append({"url": str(request.url), "headers": dict(request.headers), "body": request.content.decode()})
    return httpx.Response(200, json={})


def _phone(client: TestClient, source_icons: bool = True) -> None:
    """An ntfy target; with the switch for the source's logo on, unless a test asks for nexsift's."""
    SENT.clear()
    push.transport_for_tests = httpx.MockTransport(_record)
    body = {"kind": "ntfy", "name": "Phone", "url": "https://ntfy.example.com/alerts", "min_priority": "crit"}
    assert client.post("/api/targets", json=body, headers=UI).status_code == 201
    values = {"push_source_icons": source_icons}
    assert client.put("/api/settings", json={"values": values}, headers=UI).status_code == 200


def _run() -> None:
    with SessionLocal() as db:
        push.due_windows(db)
    asyncio.run(push.deliver_due())


def test_presets_bring_their_logo_and_doors_do_not(client: TestClient, operator: dict) -> None:
    proxmox = add_source(client, "proxmox")
    assert proxmox["icon"] == "dashboard-icons/proxmox"
    assert proxmox["icon_url"].startswith(f"/api/sources/{proxmox['id']}/icon?v=")
    script = add_source(client, "webhook")
    assert script["icon"] == ""
    assert script["icon_url"] is None


def test_the_icon_is_changed_kept_and_removed(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook", "Server")
    path = f"/api/sources/{source['id']}"
    changed = client.put(path, json={"name": "Server", "icon": "selfhst/proxmox"}, headers=UI).json()
    assert changed["icon"] == "selfhst/proxmox"
    renamed = client.put(path, json={"name": "Server 2"}, headers=UI).json()
    assert renamed["icon"] == "selfhst/proxmox", "a rename without icon keeps it"
    assert renamed["icon_url"] == changed["icon_url"]
    own = client.put(path, json={"name": "Server", "icon": " https://example.com/logo.png "}, headers=UI).json()
    assert own["icon"] == "https://example.com/logo.png"
    assert own["icon_url"] != changed["icon_url"], "a new icon gets a new address, or the browser shows the old"
    assert client.put(path, json={"name": "Server", "icon": ""}, headers=UI).json()["icon"] == ""


@pytest.mark.parametrize(
    "icon",
    ["javascript:alert(1)", "data:image/png;base64,AAAA", "elsewhere/proxmox", "dashboard-icons/../x", "proxmox"],
)
def test_odd_icons_are_refused(client: TestClient, operator: dict, icon: str) -> None:
    source = add_source(client, "webhook")
    response = client.put(f"/api/sources/{source['id']}", json={"name": "Server", "icon": icon}, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "icon_invalid"


def test_ntfy_gets_the_logo_of_the_source(client: TestClient, operator: dict) -> None:
    _phone(client)
    source = add_source(client, "proxmox", "PVE")
    path = "/api/v1/hook/" + source["connection"]["token"]
    client.post(path, json={"title": "VM 104 stopped", "priority": "critical"})
    _run()
    assert len(SENT) == 1
    assert SENT[0]["headers"]["icon"] == DASHBOARD_PROXMOX


def test_without_an_icon_ntfy_gets_nexsifts(client: TestClient, operator: dict) -> None:
    _phone(client)
    source = add_source(client, "webhook", "Server")
    client.post("/api/v1/hook/" + source["connection"]["token"], json={"title": "Down", "priority": "critical"})
    _run()
    assert len(SENT) == 1
    assert SENT[0]["headers"]["icon"] == icons.NEXSIFT_LOGO


def test_out_of_the_box_every_push_shows_nexsifts_logo(
    client: TestClient, ntfy_client: TestClient, operator: dict
) -> None:
    """The source's logo goes to ntfy only with the switch on; even the sender's own icon stays out."""
    assert client.get("/api/settings").json()["push_source_icons"] is False
    SENT.clear()
    push.transport_for_tests = httpx.MockTransport(_record)
    body = {"kind": "ntfy", "name": "Phone", "url": "https://ntfy.example.com/alerts", "min_priority": "crit"}
    assert client.post("/api/targets", json=body, headers=UI).status_code == 201
    proxmox = add_source(client, "proxmox")
    client.post("/api/v1/hook/" + proxmox["connection"]["token"], json={"title": "Down", "priority": "critical"})
    topic = add_source(client, "homeassistant")["connection"]["topic"]
    ntfy_client.post(
        f"/{topic}", content=b"x", headers={"Title": "Washer", "Priority": "5", "Icon": "https://example.com/w.png"}
    )
    _run()
    assert len(SENT) == 2
    assert [sent["headers"]["icon"] for sent in SENT] == [icons.NEXSIFT_LOGO, icons.NEXSIFT_LOGO]


def test_the_senders_own_icon_wins(client: TestClient, ntfy_client: TestClient, operator: dict) -> None:
    _phone(client)
    source = add_source(client, "homeassistant")
    topic = source["connection"]["topic"]
    own = "https://example.com/washer.png"
    response = ntfy_client.post(
        f"/{topic}", content=b"Washer done", headers={"Title": "Washer", "Priority": "5", "Icon": own}
    )
    assert response.status_code == 200, response.text
    _run()
    assert len(SENT) == 1
    assert SENT[0]["headers"]["icon"] == own


def test_a_senders_icon_that_is_no_web_address_is_dropped(client: TestClient, operator: dict) -> None:
    _phone(client)
    source = add_source(client, "proxmox")
    path = "/api/v1/hook/" + source["connection"]["token"]
    client.post(path, json={"title": "Down", "priority": "critical", "icon": "javascript:alert(1)"})
    _run()
    assert SENT[0]["headers"]["icon"] == DASHBOARD_PROXMOX


def test_the_all_clear_carries_the_icon_too(client: TestClient, operator: dict) -> None:
    from tests.test_senders import KUMA_DOWN, KUMA_UP

    _phone(client)
    source = add_source(client, "uptimekuma")
    path = "/api/v1/hook/" + source["connection"]["token"]
    client.post(path, json=KUMA_DOWN)
    client.post(path, json=KUMA_UP)
    _run()
    assert len(SENT) == 2
    expected = "https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/png/uptime-kuma.png"
    assert [sent["headers"].get("icon") for sent in SENT] == [expected, expected]


def test_web_push_carries_no_icon() -> None:
    """Web push always shows nexsift's logo; the service worker may not load one from GitHub."""
    assert "icon" not in json.loads(webpush.payload("t", "b", "crit", "/", ""))


def test_the_interface_gets_the_picture_through_nexsift(client: TestClient, operator: dict) -> None:
    asked: list[str] = []

    def cdn(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    icons.transport_for_tests = httpx.MockTransport(cdn)
    source = add_source(client, "proxmox")
    for _ in range(2):
        response = client.get(source["icon_url"])
        assert response.status_code == 200
        assert response.content == PNG
        assert response.headers["content-type"] == "image/png"
        assert response.headers["x-content-type-options"] == "nosniff", "the middleware's, for every answer"
    assert asked == [DASHBOARD_PROXMOX], "the second time comes from the copy on disk"


def test_no_svg_and_nothing_too_large(client: TestClient, operator: dict) -> None:
    answers = {
        "https://example.com/a.svg": httpx.Response(200, content=b"<svg/>", headers={"content-type": "image/svg+xml"}),
        "https://example.com/big.png": httpx.Response(
            200, content=b"x" * (icons.IMAGE_MAX + 1), headers={"content-type": "image/png"}
        ),
        "https://example.com/page.png": httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}),
    }
    icons.transport_for_tests = httpx.MockTransport(lambda request: answers[str(request.url)])
    source = add_source(client, "webhook")
    for url in answers:
        icons.reset_for_tests()
        client.put(f"/api/sources/{source['id']}", json={"name": "S", "icon": url}, headers=UI)
        shown = client.get(f"/api/sources/{source['id']}").json()
        assert client.get(shown["icon_url"]).status_code == 404, url


def test_the_picture_needs_a_session(client: TestClient, operator: dict) -> None:
    source = add_source(client, "proxmox")
    assert client.post("/api/auth/logout", headers=UI).status_code == 204
    assert client.get(source["icon_url"]).status_code == 401
    assert client.get("/api/icons").status_code == 401


def test_the_picker_lists_png_logos_of_both_collections_once(client: TestClient, operator: dict) -> None:
    trees = {
        "homarr-labs": {"tree": [{"path": "png/proxmox.png"}, {"path": "svg/only-svg.svg"}, {"path": "png/a b.png"}]},
        "selfhst": {"tree": [{"path": "png/proxmox.png"}, {"path": "png/zabbix.png"}]},
    }

    def github(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(tree for key, tree in trees.items() if key in str(request.url)))

    icons.transport_for_tests = httpx.MockTransport(github)
    listing = client.get("/api/icons").json()
    family = [entry for entry in listing if entry["icon"].startswith("nexapps/")]
    assert listing[: len(family)] == family, "the nexapps family comes first"
    assert {"name": "nexsift", "icon": "nexapps/nexsift"} in family
    assert listing[len(family) :] == [
        {"name": "proxmox", "icon": "dashboard-icons/proxmox"},
        {"name": "zabbix", "icon": "selfhst/zabbix"},
    ]


NEXAPPS = (
    "nexbeat",
    "nexcanvas",
    "nexcrate",
    "nexdeck",
    "nexlore",
    "nexmail",
    "nexpulse",
    "nexsift",
    "nextrmnl",
    "nexview",
)


def test_the_nexapps_family_ships_with_nexsift() -> None:
    assert set(NEXAPPS) <= set(icons.bundled())
    for name in icons.bundled():
        assert (icons.BUNDLED / f"{name}.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", name


def test_a_nexapps_logo_comes_from_disk_and_goes_out_through_the_public_repository(
    client: TestClient, operator: dict
) -> None:
    _phone(client)
    source = add_source(client, "webhook", "nexcrate")
    path = f"/api/sources/{source['id']}"
    shown = client.put(path, json={"name": "nexcrate", "icon": "nexapps/nexcrate"}, headers=UI).json()
    # The default transport answers 404 for everything: the picture must not need the internet.
    picture = client.get(shown["icon_url"])
    assert picture.status_code == 200
    assert picture.content == (icons.BUNDLED / "nexcrate.png").read_bytes()
    assert client.get("/api/icons/nexapps/nexcrate.png").status_code == 200
    client.post("/api/v1/hook/" + source["connection"]["token"], json={"title": "Grab failed", "priority": "critical"})
    _run()
    assert SENT[0]["headers"]["icon"] == (
        "https://raw.githubusercontent.com/DerKezorm/nexsift/main/backend/app/bundled_icons/nexcrate.png"
    )


def test_a_nexapps_name_that_does_not_ship_is_refused(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook")
    response = client.put(f"/api/sources/{source['id']}", json={"name": "S", "icon": "nexapps/nope"}, headers=UI)
    assert response.status_code == 422
    assert client.get("/api/icons/nexapps/nope.png").status_code == 404


def test_the_picker_preview_refuses_made_up_paths(client: TestClient, operator: dict) -> None:
    assert client.get("/api/icons/elsewhere/proxmox.png").status_code == 404


def _rule(client: TestClient, icon: str, word: str = "Sonarr") -> dict:
    rule = {
        "name": f"{word} logo",
        "conditions": [{"field": "title", "op": "word", "value": word}],
        "actions": {"icon": icon},
    }
    response = client.post("/api/rules", json=rule, headers=UI)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_rule_gives_one_app_behind_a_shared_source_its_logo(client: TestClient, operator: dict) -> None:
    _phone(client)
    source = add_source(client, "proxmox", "Shared")
    _rule(client, "dashboard-icons/sonarr")
    path = "/api/v1/hook/" + source["connection"]["token"]
    client.post(path, json={"title": "Sonarr: download failed", "priority": "critical"})
    client.post(path, json={"title": "VM 104 stopped", "priority": "critical"})
    _run()
    icons_sent = sorted(sent["headers"]["icon"] for sent in SENT)
    sonarr = "https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/png/sonarr.png"
    assert icons_sent == [DASHBOARD_PROXMOX, sonarr]
    lines = {line["title"]: line for line in client.get("/api/threads").json()["items"]}
    assert lines["Sonarr: download failed"]["icon_url"].startswith(
        f"/api/threads/{lines['Sonarr: download failed']['id']}/icon?v="
    )
    assert lines["VM 104 stopped"]["icon_url"] is None, "without a rule the line shows the source's"


def test_the_senders_icon_beats_the_rules(client: TestClient, operator: dict) -> None:
    _phone(client)
    source = add_source(client, "webhook")
    _rule(client, "dashboard-icons/sonarr")
    own = "https://example.com/own.png"
    client.post(
        "/api/v1/hook/" + source["connection"]["token"],
        json={"title": "Sonarr: down", "priority": "critical", "icon": own},
    )
    _run()
    assert SENT[0]["headers"]["icon"] == own


def test_a_rule_with_an_odd_icon_is_refused(client: TestClient, operator: dict) -> None:
    rule = {
        "name": "x",
        "conditions": [{"field": "title", "op": "word", "value": "x"}],
        "actions": {"icon": "javascript:x"},
    }
    response = client.post("/api/rules", json=rule, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "icon_invalid"


def test_the_line_shows_the_rules_picture_through_nexsift(client: TestClient, operator: dict) -> None:
    asked: list[str] = []

    def cdn(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    icons.transport_for_tests = httpx.MockTransport(cdn)
    source = add_source(client, "webhook")
    _rule(client, "selfhst/sonarr")
    client.post("/api/v1/hook/" + source["connection"]["token"], json={"title": "Sonarr grabbed a file"})
    line = client.get("/api/threads").json()["items"][0]
    response = client.get(line["icon_url"])
    assert response.status_code == 200
    assert response.content == PNG
    assert asked == ["https://raw.githubusercontent.com/selfhst/icons/main/png/sonarr.png"]


def test_one_client_for_all_pictures() -> None:
    """A fresh client costs half a second on the event loop; thirty logos in the picker stalled the server."""
    assert icons._client() is icons._client()


def test_the_picker_gets_a_screenful_of_logos_in_one_answer(client: TestClient, operator: dict) -> None:
    asked: list[str] = []

    def cdn(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if "missing" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    icons.transport_for_tests = httpx.MockTransport(cdn)
    wanted = ["dashboard-icons/proxmox", "selfhst/zabbix", "dashboard-icons/missing", "nexapps/nexsift"]
    odd = ["https://example.com/x.png", "elsewhere/x", "dashboard-icons/proxmox"]
    response = client.get("/api/icons/batch", params={"icon": wanted + odd})
    assert response.status_code == 200
    found = response.json()
    assert set(found) == {"dashboard-icons/proxmox", "selfhst/zabbix", "nexapps/nexsift"}
    assert found["selfhst/zabbix"] == "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert found["nexapps/nexsift"].startswith("data:image/png;base64,iVBOR")
    assert len(asked) == 3, "own addresses are not fetched for the picker, and each logo once"


def test_a_batch_has_an_upper_bound(client: TestClient, operator: dict) -> None:
    too_many = [f"dashboard-icons/n{index}" for index in range(icons.BATCH_MAX + 1)]
    assert client.get("/api/icons/batch", params={"icon": too_many}).status_code == 422
    client.post("/api/auth/logout", headers=UI)
    assert client.get("/api/icons/batch", params={"icon": ["dashboard-icons/proxmox"]}).status_code == 401


def test_a_timeout_is_not_taken_for_a_missing_logo(client: TestClient, operator: dict) -> None:
    """jsdelivr timed out under load on 05.10.2026, and each slow logo stayed missing for an hour."""
    answers = [httpx.ReadTimeout("slow"), httpx.Response(503), None]
    asked: list[str] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer or httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    icons.transport_for_tests = httpx.MockTransport(flaky)
    assert client.get("/api/icons/dashboard-icons/proxmox.png").status_code == 404
    assert client.get("/api/icons/dashboard-icons/proxmox.png").status_code == 404
    assert client.get("/api/icons/dashboard-icons/proxmox.png").status_code == 200
    assert len(asked) == 3


def test_a_clear_not_found_is_remembered(client: TestClient, operator: dict) -> None:
    asked: list[str] = []

    def gone(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(404)

    icons.transport_for_tests = httpx.MockTransport(gone)
    for _ in range(3):
        assert client.get("/api/icons/dashboard-icons/nothing-here.png").status_code == 404
    assert len(asked) == 1
