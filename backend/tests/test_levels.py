"""What arrives from a source (issue #5): out of the box each target's minimum decides; a source can set its own
level in its place, up and down, and a rule can set one for the lines it matches, before the source's."""

import asyncio
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Thread, utcnow
from app.services import push
from tests.conftest import UI, add_source

SENT: list[str] = []


def _record(request: httpx.Request) -> httpx.Response:
    # Every target has its own ntfy topic, so the address says where a push went.
    SENT.append(request.url.path.strip("/"))
    return httpx.Response(200, json={})


def _target(client: TestClient, name: str, minimum: str = "crit") -> int:
    push.transport_for_tests = httpx.MockTransport(_record)
    body = {"kind": "ntfy", "name": name, "url": f"https://ntfy.example.com/{name}", "min_priority": minimum}
    response = client.post("/api/targets", json=body, headers=UI)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _level(client: TestClient, source: dict, level: str, **more: object) -> dict:
    body = {"name": source["name"], "min_priority": level, **more}
    response = client.put(f"/api/sources/{source['id']}", json=body, headers=UI)
    assert response.status_code == 200, response.text
    return response.json()


def _send(client: TestClient, source: dict, title: str, priority: str) -> None:
    response = client.post("/api/v1/hook/" + source["connection"]["token"], json={"title": title, "priority": priority})
    assert response.status_code < 300, response.text


def _run() -> list[str]:
    SENT.clear()
    with SessionLocal() as db:
        push.due_windows(db)
    asyncio.run(push.deliver_due())
    return sorted(SENT)


def test_out_of_the_box_the_targets_decide(client: TestClient, operator: dict) -> None:
    _target(client, "phone", "warn")
    _target(client, "telegram")
    source = add_source(client, "webhook", "Change watcher")
    assert source["min_priority"] == ""
    _send(client, source, "Page changed", "info")
    assert _run() == []
    _send(client, source, "Page gone", "warning")
    assert _run() == ["phone"]


def test_everything_lets_info_through_to_a_target_set_higher(client: TestClient, operator: dict) -> None:
    _target(client, "phone", "warn")
    _target(client, "telegram")
    source = add_source(client, "webhook", "Change watcher")
    other = add_source(client, "webhook", "Backup")
    assert _level(client, source, "info")["min_priority"] == "info"
    _send(client, source, "Page changed", "info")
    assert _run() == ["phone", "telegram"]
    _send(client, other, "Backup done", "info")
    assert _run() == [], "a source without a level of its own keeps the targets' minimum"


def test_only_critical_holds_back_what_a_target_would_take(client: TestClient, operator: dict) -> None:
    _target(client, "phone", "info")
    source = add_source(client, "webhook", "Chatty app")
    _level(client, source, "crit")
    _send(client, source, "Disk at 81 %", "warning")
    _send(client, source, "Cache cleared", "info")
    assert _run() == []
    _send(client, source, "Disk full", "critical")
    assert _run() == ["phone"]


def test_warnings_and_critical(client: TestClient, operator: dict) -> None:
    _target(client, "phone")
    source = add_source(client, "webhook", "Release watcher")
    _level(client, source, "warn")
    _send(client, source, "New release", "info")
    assert _run() == []
    _send(client, source, "Release withdrawn", "warning")
    assert _run() == ["phone"]


def test_back_to_the_targets_and_leaving_it_out_keeps_it(client: TestClient, operator: dict) -> None:
    _target(client, "phone")
    source = add_source(client, "webhook", "Change watcher")
    _level(client, source, "info")
    kept = client.put(f"/api/sources/{source['id']}", json={"name": "Watcher"}, headers=UI).json()
    assert kept["min_priority"] == "info"
    assert _level(client, source, "")["min_priority"] == ""
    _send(client, source, "Page changed", "info")
    assert _run() == []


def test_an_unknown_level_is_refused(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook", "Change watcher")
    response = client.put(
        f"/api/sources/{source['id']}", json={"name": source["name"], "min_priority": "loud"}, headers=UI
    )
    assert response.status_code == 422
    rule = {
        "name": "Releases",
        "conditions": [{"field": "any", "op": "word", "value": "release"}],
        "actions": {"min_priority": "loud"},
    }
    response = client.post("/api/rules", json=rule, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "rule_min_priority"


def test_a_rule_sets_the_level_for_its_lines_before_the_source(client: TestClient, operator: dict) -> None:
    """Several apps behind one source: the rule's level counts for what it matches, the source's for the rest."""
    _target(client, "phone")
    source = add_source(client, "webhook", "Docker host")
    _level(client, source, "crit")
    rule = {
        "name": "Releases arrive",
        "source_id": source["id"],
        "conditions": [{"field": "title", "op": "word", "value": "release"}],
        "actions": {"min_priority": "info"},
    }
    created = client.post("/api/rules", json=rule, headers=UI)
    assert created.status_code == 201, created.text
    assert created.json()["actions"] == {"min_priority": "info"}
    _send(client, source, "New release of redis", "info")
    assert _run() == ["phone"]
    _send(client, source, "Container redis restarted", "warning")
    assert _run() == [], "the source's level for everything the rule does not match"


def test_a_rule_that_keeps_lines_in_the_inbox_still_wins(client: TestClient, operator: dict) -> None:
    _target(client, "phone")
    source = add_source(client, "webhook", "Updates")
    _level(client, source, "info")
    rule = {
        "name": "Updates stay",
        "source_id": source["id"],
        "conditions": [{"field": "any", "op": "word", "value": "updated"}],
        "actions": {"push": "never"},
    }
    assert client.post("/api/rules", json=rule, headers=UI).status_code == 201
    _send(client, source, "Container updated", "info")
    assert _run() == []


def test_quiet_hours_still_hold_back_everything_below_critical(
    client: TestClient, operator: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    _target(client, "phone")
    source = add_source(client, "webhook", "Change watcher")
    _level(client, source, "info")
    monkeypatch.setattr(push, "_in_quiet_hours", lambda target, now=None: True)
    _send(client, source, "Page changed", "info")
    assert _run() == []
    _send(client, source, "Site down", "critical")
    assert _run() == ["phone"]


def test_with_chosen_targets_only_those_get_the_info(client: TestClient, operator: dict) -> None:
    _target(client, "phone")
    telegram = _target(client, "telegram")
    source = add_source(client, "webhook", "Change watcher")
    _level(client, source, "info", targets=[telegram])
    _send(client, source, "Page changed", "info")
    assert _run() == ["telegram"]


def test_follow_up_and_all_clear_use_the_level_too(client: TestClient, operator: dict) -> None:
    from tests.test_senders import KUMA_DOWN, KUMA_UP

    _target(client, "phone")
    source = add_source(client, "webhook", "Change watcher")
    _level(client, source, "info")
    _send(client, source, "Page changed", "info")
    _send(client, source, "Page changed", "info")
    assert _run() == ["phone"], "the first at once, the second counted"
    with SessionLocal() as db:
        thread = db.query(Thread).one()
        thread.window_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert _run() == ["phone"], "one follow-up with the count"

    # A monitor whose outages count as warnings: only the source's level gets them to a critical-only target.
    kuma = add_source(client, "uptimekuma", "Kuma")
    rule = {
        "name": "Kuma warns",
        "source_id": kuma["id"],
        "conditions": [{"field": "any", "op": "regex", "value": ".+"}],
        "actions": {"priority": "warn"},
    }
    assert client.post("/api/rules", json=rule, headers=UI).status_code == 201
    _level(client, kuma, "warn")
    client.post("/api/v1/hook/" + kuma["connection"]["token"], json=KUMA_DOWN)
    assert _run() == ["phone"]
    client.post("/api/v1/hook/" + kuma["connection"]["token"], json=KUMA_UP)
    assert _run() == ["phone"], "the all-clear goes where the alarm went"


def test_the_storm_summary_names_only_what_each_target_would_have_taken(client: TestClient, operator: dict) -> None:
    """Before 0.11.0 the summary went to every target with every swallowed line, a warning to a critical-only
    target too."""
    client.put("/api/settings", json={"values": {"storm_count": 2, "storm_minutes": 2}}, headers=UI)
    _target(client, "phone", "warn")
    _target(client, "telegram")
    proxmox = add_source(client, "webhook", "Proxmox")
    watcher = add_source(client, "webhook", "Change watcher")
    _level(client, watcher, "info")
    for name in ("mail", "cloud"):
        _send(client, proxmox, f"{name} is down", "critical")
    assert _run() == ["phone", "phone", "telegram", "telegram"]
    _send(client, proxmox, "wiki is slow", "warning")
    _send(client, watcher, "Page changed", "info")
    _send(client, proxmox, "dns is down", "critical")
    assert _run() == [], "the storm holds them back"

    bodies: dict[str, str] = {}

    def record(request: httpx.Request) -> httpx.Response:
        bodies[request.url.path.strip("/")] = request.content.decode()
        return httpx.Response(200, json={})

    push.transport_for_tests = httpx.MockTransport(record)
    push._storm_until = utcnow() - timedelta(seconds=1)
    _run()
    assert bodies == {
        "phone": "Proxmox: wiki is slow\nChange watcher: Page changed\nProxmox: dns is down",
        "telegram": "Change watcher: Page changed\nProxmox: dns is down",
    }
