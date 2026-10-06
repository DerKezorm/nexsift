"""What tapping a push to ntfy opens (issue #3): the message's link or the line in nexsift, chosen per source, and the
other one as a button under the notification."""

import asyncio

import httpx
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.services import push
from tests.conftest import UI, add_source

SENT: list[dict] = []
PUBLIC = "https://nexsift.example.com"


def _record(request: httpx.Request) -> httpx.Response:
    SENT.append({k.lower(): v for k, v in request.headers.items()})
    return httpx.Response(200, json={})


def _phone(client: TestClient, public: str = PUBLIC, language: str = "en") -> None:
    SENT.clear()
    push.transport_for_tests = httpx.MockTransport(_record)
    body = {"kind": "ntfy", "name": "Phone", "url": "https://ntfy.example.com/alerts", "min_priority": "crit"}
    assert client.post("/api/targets", json=body, headers=UI).status_code == 201
    values = {"public_url": public, "push_language": language}
    assert client.put("/api/settings", json={"values": values}, headers=UI).status_code == 200


def _send(client: TestClient, source: dict, **message: object) -> dict:
    client.post("/api/v1/hook/" + source["connection"]["token"], json={"priority": "critical", **message})
    with SessionLocal() as db:
        push.due_windows(db)
    asyncio.run(push.deliver_due())
    assert SENT, "nothing was pushed"
    return SENT[-1]


def _line(client: TestClient) -> int:
    return client.get("/api/threads").json()["items"][0]["id"]


def test_out_of_the_box_a_tap_opens_the_link_and_a_button_opens_nexsift(client: TestClient, operator: dict) -> None:
    _phone(client)
    source = add_source(client, "webhook", "Zabbix")
    assert source["tap"] == "link"
    headers = _send(client, source, title="Disk full", url="https://zabbix.example.com/problem/7")
    assert headers["click"] == "https://zabbix.example.com/problem/7"
    assert headers["actions"] == f"view, Open in nexsift, {PUBLIC}/?thread={_line(client)}"


def test_a_source_set_to_nexsift_opens_the_line_and_keeps_the_link_as_a_button(
    client: TestClient, operator: dict
) -> None:
    _phone(client)
    source = add_source(client, "webhook", "Zabbix")
    changed = client.put(f"/api/sources/{source['id']}", json={"name": "Zabbix", "tap": "nexsift"}, headers=UI).json()
    assert changed["tap"] == "nexsift"
    headers = _send(client, source, title="Disk full", url="https://zabbix.example.com/problem/7")
    assert headers["click"] == f"{PUBLIC}/?thread={_line(client)}"
    assert headers["actions"] == "view, Open link, https://zabbix.example.com/problem/7"


def test_without_a_link_the_tap_still_opens_nexsift(client: TestClient, operator: dict) -> None:
    _phone(client, language="de")
    source = add_source(client, "webhook", "Zabbix")
    client.put(f"/api/sources/{source['id']}", json={"name": "Zabbix", "tap": "nexsift"}, headers=UI)
    headers = _send(client, source, title="Disk full")
    assert headers["click"] == f"{PUBLIC}/?thread={_line(client)}"
    assert "actions" not in headers


def test_the_button_speaks_the_push_language(client: TestClient, operator: dict) -> None:
    _phone(client, language="de")
    source = add_source(client, "webhook", "Zabbix")
    headers = _send(client, source, title="Platte voll")
    assert headers["actions"].startswith("view, In nexsift ansehen, ")


def test_without_a_public_address_everything_stays_as_before(client: TestClient, operator: dict) -> None:
    _phone(client, public="")
    source = add_source(client, "webhook", "Zabbix")
    client.put(f"/api/sources/{source['id']}", json={"name": "Zabbix", "tap": "nexsift"}, headers=UI)
    headers = _send(client, source, title="Disk full", url="https://zabbix.example.com/problem/7")
    assert headers["click"] == "https://zabbix.example.com/problem/7"
    assert "actions" not in headers


def test_a_link_that_would_break_the_button_header_stays_out(client: TestClient, operator: dict) -> None:
    _phone(client)
    source = add_source(client, "webhook", "Zabbix")
    client.put(f"/api/sources/{source['id']}", json={"name": "Zabbix", "tap": "nexsift"}, headers=UI)
    headers = _send(client, source, title="Disk full", url="https://zabbix.example.com/a,b;c")
    assert headers["click"] == f"{PUBLIC}/?thread={_line(client)}"
    assert "actions" not in headers


def test_an_unknown_tap_is_refused(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook", "Zabbix")
    response = client.put(f"/api/sources/{source['id']}", json={"name": "Zabbix", "tap": "elsewhere"}, headers=UI)
    assert response.status_code == 422
