"""Which targets a push goes to (issue #4): every target out of the box, some only per source, and a rule's
choice before the source's. A deleted target never leaves a source silent."""

import asyncio
from datetime import timedelta

import httpx
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


def _target(client: TestClient, name: str) -> int:
    push.transport_for_tests = httpx.MockTransport(_record)
    body = {"kind": "ntfy", "name": name, "url": f"https://ntfy.example.com/{name}", "min_priority": "crit"}
    response = client.post("/api/targets", json=body, headers=UI)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _route(client: TestClient, source: dict, targets: list[int]) -> dict:
    response = client.put(f"/api/sources/{source['id']}", json={"name": source["name"], "targets": targets}, headers=UI)
    assert response.status_code == 200, response.text
    return response.json()


def _send(client: TestClient, source: dict, **message: object) -> None:
    response = client.post("/api/v1/hook/" + source["connection"]["token"], json={"priority": "critical", **message})
    assert response.status_code < 300, response.text


def _run() -> list[str]:
    SENT.clear()
    with SessionLocal() as db:
        push.due_windows(db)
    asyncio.run(push.deliver_due())
    return sorted(SENT)


def test_out_of_the_box_every_source_reaches_every_target(client: TestClient, operator: dict) -> None:
    _target(client, "phone")
    _target(client, "telegram")
    source = add_source(client, "webhook", "Backup")
    assert source["targets"] == []
    _send(client, source, title="Backup failed")
    assert _run() == ["phone", "telegram"]


def test_a_source_sends_to_the_targets_it_chose(client: TestClient, operator: dict) -> None:
    _target(client, "phone")
    telegram = _target(client, "telegram")
    backup = add_source(client, "webhook", "Backup")
    other = add_source(client, "webhook", "Proxmox")
    assert _route(client, backup, [telegram])["targets"] == [telegram]
    _send(client, backup, title="Backup failed")
    assert _run() == ["telegram"]
    _send(client, other, title="VM 104 stopped")
    assert _run() == ["phone", "telegram"], "a source without a choice keeps every target"


def test_the_all_clear_goes_where_the_alarm_went(client: TestClient, operator: dict) -> None:
    from tests.test_senders import KUMA_DOWN, KUMA_UP

    _target(client, "phone")
    telegram = _target(client, "telegram")
    kuma = add_source(client, "uptimekuma", "Kuma")
    _route(client, kuma, [telegram])
    client.post("/api/v1/hook/" + kuma["connection"]["token"], json=KUMA_DOWN)
    assert _run() == ["telegram"]
    client.post("/api/v1/hook/" + kuma["connection"]["token"], json=KUMA_UP)
    assert _run() == ["telegram"]


def test_the_choice_does_not_lower_a_targets_minimum(client: TestClient, operator: dict) -> None:
    telegram = _target(client, "telegram")
    source = add_source(client, "webhook", "Backup")
    _route(client, source, [telegram])
    _send(client, source, title="Backup slow", priority="warning")
    assert _run() == [], "telegram takes critical only, choosing it does not change that"


def test_an_empty_choice_means_every_target_again(client: TestClient, operator: dict) -> None:
    _target(client, "phone")
    telegram = _target(client, "telegram")
    source = add_source(client, "webhook", "Backup")
    _route(client, source, [telegram])
    assert _route(client, source, [])["targets"] == []
    _send(client, source, title="Backup failed")
    assert _run() == ["phone", "telegram"]


def test_leaving_the_choice_out_keeps_it(client: TestClient, operator: dict) -> None:
    telegram = _target(client, "telegram")
    source = add_source(client, "webhook", "Backup")
    _route(client, source, [telegram])
    response = client.put(f"/api/sources/{source['id']}", json={"name": "Backups"}, headers=UI)
    assert response.json()["targets"] == [telegram]


def test_an_unknown_target_is_refused(client: TestClient, operator: dict) -> None:
    telegram = _target(client, "telegram")
    source = add_source(client, "webhook", "Backup")
    response = client.put(
        f"/api/sources/{source['id']}", json={"name": "Backup", "targets": [telegram, 999]}, headers=UI
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "target_unknown"
    rule = {
        "name": "Backups",
        "conditions": [{"field": "any", "op": "word", "value": "backup"}],
        "actions": {"targets": [999]},
    }
    response = client.post("/api/rules", json=rule, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "target_unknown"
    rule["actions"] = {"targets": ["phone"]}
    assert client.post("/api/rules", json=rule, headers=UI).json()["detail"]["code"] == "rule_targets"


def test_a_rule_routes_the_lines_it_matches_before_the_source_does(client: TestClient, operator: dict) -> None:
    phone = _target(client, "phone")
    telegram = _target(client, "telegram")
    _target(client, "gotify")
    docker = add_source(client, "webhook", "Docker host")
    _route(client, docker, [phone])
    rule = {
        "name": "Backups to Telegram",
        "source_id": docker["id"],
        "conditions": [{"field": "title", "op": "word", "value": "backup"}],
        "actions": {"targets": [telegram, telegram]},
    }
    created = client.post("/api/rules", json=rule, headers=UI)
    assert created.status_code == 201, created.text
    assert created.json()["actions"] == {"targets": [telegram]}
    _send(client, docker, title="Backup failed")
    assert _run() == ["telegram"]
    _send(client, docker, title="Container redis stopped")
    assert _run() == ["phone"]


def test_deleting_a_target_leaves_every_choice(client: TestClient, operator: dict) -> None:
    phone = _target(client, "phone")
    telegram = _target(client, "telegram")
    _target(client, "gotify")
    only = add_source(client, "webhook", "Backup")
    both = add_source(client, "webhook", "Proxmox")
    _route(client, only, [telegram])
    _route(client, both, [telegram, phone])
    rule = {
        "name": "Disks",
        "conditions": [{"field": "any", "op": "word", "value": "disk"}],
        "actions": {"targets": [telegram], "priority": "crit"},
    }
    rule_id = client.post("/api/rules", json=rule, headers=UI).json()["id"]
    listed = {target["name"]: target for target in client.get("/api/targets").json()}
    assert listed["telegram"]["chosen_by"] == {"sources": ["Backup", "Proxmox"], "rules": ["Disks"]}
    assert listed["gotify"]["chosen_by"] == {"sources": [], "rules": []}

    assert client.delete(f"/api/targets/{telegram}", headers=UI).status_code == 204
    sources = {source["name"]: source for source in client.get("/api/sources").json()}
    assert sources["Backup"]["targets"] == [], "its only target is gone: back to every target, not to none"
    assert sources["Proxmox"]["targets"] == [phone]
    rules = {rule["id"]: rule for rule in client.get("/api/rules").json()}
    assert rules[rule_id]["actions"] == {"priority": "crit"}
    _send(client, only, title="Backup failed")
    assert _run() == ["gotify", "phone"]


def test_a_line_whose_rule_targets_are_gone_falls_back_to_the_source(client: TestClient, operator: dict) -> None:
    """A line remembers its rule's choice. When those targets go before the line ends, the source's choice counts."""
    phone = _target(client, "phone")
    telegram = _target(client, "telegram")
    _target(client, "gotify")
    source = add_source(client, "webhook", "Docker host")
    _route(client, source, [phone])
    rule = {
        "name": "Backups",
        "conditions": [{"field": "any", "op": "word", "value": "backup"}],
        "actions": {"targets": [telegram]},
    }
    client.post("/api/rules", json=rule, headers=UI)
    _send(client, source, title="Backup failed")
    assert _run() == ["telegram"]
    with SessionLocal() as db:
        # As if the target had gone without the clean-up (an older database, a restore): only the line keeps it.
        thread = db.query(Thread).one()
        thread.targets = [telegram + 100]
        thread.window_until = utcnow() - timedelta(seconds=1)
        thread.since_push = 1
        db.commit()
    assert _run() == ["phone"]


def test_the_storm_summary_names_only_what_was_meant_for_each_target(client: TestClient, operator: dict) -> None:
    client.put("/api/settings", json={"values": {"storm_count": 2, "storm_minutes": 2}}, headers=UI)
    phone = _target(client, "phone")
    telegram = _target(client, "telegram")
    backup = add_source(client, "webhook", "Backup")
    proxmox = add_source(client, "webhook", "Proxmox")
    _route(client, backup, [telegram])
    _route(client, proxmox, [phone])
    SENT.clear()
    for name in ("mail", "cloud"):
        _send(client, proxmox, title=f"{name} is down")
    assert _run() == ["phone", "phone"]
    _send(client, backup, title="nightly backup failed")
    _send(client, proxmox, title="wiki is down")
    _send(client, proxmox, title="dns is down")
    assert _run() == [], "the storm holds them back"

    bodies: dict[str, str] = {}

    def record(request: httpx.Request) -> httpx.Response:
        bodies[request.url.path.strip("/")] = request.content.decode()
        return httpx.Response(200, json={})

    push.transport_for_tests = httpx.MockTransport(record)
    push._storm_until = utcnow() - timedelta(seconds=1)
    _run()
    assert bodies == {
        "phone": "Proxmox: wiki is down\nProxmox: dns is down",
        "telegram": "Backup: nightly backup failed",
    }
