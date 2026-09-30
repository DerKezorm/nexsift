"""What nexsift knows about particular senders, pinned by samples shaped like the real thing.

When a sender changes its wording, a new sample goes next to the old one; both must keep working.
"""

import json

from fastapi.testclient import TestClient

from app.adapters import doors
from app.adapters.kinds import refine, shape
from tests.conftest import UI, add_source, inbox

KUMA_DOWN = {
    "heartbeat": {"monitorID": 7, "status": 0, "time": "2026-09-30 21:14:02.123", "msg": "timeout of 48000ms exceeded"},
    "monitor": {"id": 7, "name": "cloud", "url": "https://cloud.example.com", "type": "http"},
    "msg": "[cloud] [🔴 Down] timeout of 48000ms exceeded",
}
KUMA_UP = {
    "heartbeat": {"monitorID": 7, "status": 1, "time": "2026-09-30 21:26:02.123", "msg": "200 - OK"},
    "monitor": {"id": 7, "name": "cloud", "url": "https://cloud.example.com", "type": "http"},
    "msg": "[cloud] [✅ Up] 200 - OK",
}

WATCHTOWER_LOG = {
    "title": "Watchtower updates on docker-01",
    "message": (
        "Found new jellyfin/jellyfin:latest image (sha256:3f2a9c1d)\n"
        "Found new ghcr.io/immich-app/immich-server:release image (sha256:77ab12)\n"
        "Stopping /jellyfin (4c1d2e) with SIGTERM\nCreating /jellyfin\nRemoving image 3f2a9c1d"
    ),
    "priority": 0,
}
WATCHTOWER_REPORT = {
    "title": "Watchtower updates on docker-01",
    "message": "3 Scanned, 2 Updated, 0 Failed\n- redis (redis:7): 1a2b3c updated to 4d5e6f\n- grafana (grafana/grafana:latest): 9a8b updated to 7c6d",
    "priority": 0,
}


def _refine(kind: str, incoming_payload: tuple) -> list:
    incoming, payload = incoming_payload
    return refine(kind, incoming, payload)


def test_uptime_kuma_uses_the_status_number() -> None:
    [down] = _refine("uptimekuma", doors.webhook(json.dumps(KUMA_DOWN).encode(), "application/json"))
    assert (down.title, down.priority, down.group_key) == ("cloud is down", "crit", "monitor-7")
    [up] = _refine("uptimekuma", doors.webhook(json.dumps(KUMA_UP).encode(), "application/json"))
    assert (up.priority, up.resolves) == ("info", "monitor-7")
    assert up.links[0]["url"] == "https://cloud.example.com"


def test_uptime_kuma_test_button_is_understood() -> None:
    [event] = _refine("uptimekuma", doors.webhook(b'{"msg": "Uptime Kuma Testing"}', "application/json"))
    assert event.recognized is True
    assert event.title == "Uptime Kuma Testing"


def test_unknown_format_arrives_anyway_and_says_so() -> None:
    [event] = _refine(
        "uptimekuma", doors.webhook(b'{"title": "something new", "monitor": {"id": 1}}', "application/json")
    )
    assert event.recognized is False
    assert event.title == "something new"


def test_watchtower_log_lines_become_one_event_per_container() -> None:
    events = _refine("watchtower", doors.gotify(json.dumps(WATCHTOWER_LOG).encode(), {}, "application/json"))
    assert [event.title for event in events] == ["Updated jellyfin", "Updated immich-server"]
    assert all(event.group_key == "updates" for event in events)


def test_watchtower_session_report_is_understood_too() -> None:
    events = _refine("watchtower", doors.gotify(json.dumps(WATCHTOWER_REPORT).encode(), {}, "application/json"))
    assert [event.title for event in events] == ["Updated redis", "Updated grafana"]


def test_proxmox_severity_and_grouping() -> None:
    body = {
        "title": "vzdump backup status (pve01): backup failed",
        "message": "VM 104 failed",
        "severity": "error",
        "type": "vzdump",
        "host": "pve01",
    }
    [event] = _refine("proxmox", doors.webhook(json.dumps(body).encode(), "application/json"))
    assert (event.priority, event.group_key) == ("crit", "vzdump-pve01")


def test_syslog_formats() -> None:
    incoming, payload = doors.syslog(
        "<38>Sep 30 21:14:02 gw sshd[48211]: Failed password for invalid user admin from 203.0.113.47 port 51122 ssh2",
        "192.0.2.1",
    )
    assert payload["host"] == "gw" and incoming.title.startswith("sshd: Failed password")
    assert incoming.priority == "info"
    incoming, payload = doors.syslog("<11>1 2026-09-30T21:14:02Z nas01 kernel - - - disk error on sda", "192.0.2.2")
    assert (payload["host"], incoming.priority) == ("nas01", "crit")
    incoming, payload = doors.syslog("<12>just text", "192.0.2.3")
    assert (payload["host"], incoming.title, incoming.priority) == ("192.0.2.3", "just text", "warn")


def test_shape_ignores_numbers_addresses_and_ids() -> None:
    first = shape("sshd: Failed password for admin from 203.0.113.47 port 51122")
    second = shape("sshd: Failed password for admin from 198.51.100.2 port 40022")
    assert first == second


def test_uptime_kuma_all_clear_closes_the_problem(client: TestClient, operator: dict) -> None:
    source = add_source(client, "uptimekuma")
    path = "/api/v1/hook/" + source["connection"]["token"]
    client.post(path, json=KUMA_DOWN)
    client.post(path, json=KUMA_DOWN)
    [problem] = inbox(client)
    assert problem["title"] == "cloud is down" and problem["event_count"] == 2
    client.post(path, json=KUMA_UP)
    [thread] = inbox(client)
    assert thread["resolved_at"] is not None
    assert thread["resolved_by"] == "cloud is up again"
    assert inbox(client, "crit") == []


def test_watchtower_bundles_and_never_pushes(client: TestClient, gotify_client: TestClient, operator: dict) -> None:
    source = add_source(client, "watchtower")
    token = source["connection"]["token"]
    assert source["connection"]["shoutrrr"].startswith("gotify://testserver:8491/")
    gotify_client.post(f"/message?token={token}", json=WATCHTOWER_LOG)
    gotify_client.post(f"/message?token={token}", json=WATCHTOWER_REPORT)
    [thread] = inbox(client)
    assert thread["title"] == "Watchtower: 4 containers updated"
    detail = client.get(f"/api/threads/{thread['id']}").json()
    assert "Watchtower: bundle updates, never push them" in detail["rule_names"]
    assert detail["push_mode"] == "never"


def test_changed_format_counts_on_the_source(client: TestClient, operator: dict) -> None:
    source = add_source(client, "uptimekuma")
    path = "/api/v1/hook/" + source["connection"]["token"]
    for _ in range(3):
        client.post(path, json={"monitorName": "renamed field", "state": "down"})
    view = client.get(f"/api/sources/{source['id']}").json()
    assert view["unrecognized_streak"] == 3
    assert len(inbox(client)) == 1
    client.post(path, json=KUMA_DOWN)
    assert client.get(f"/api/sources/{source['id']}").json()["unrecognized_streak"] == 0


def test_rename_and_mute(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook")
    assert (
        client.put(f"/api/sources/{source['id']}", json={"name": "  My   script "}, headers=UI).json()["name"]
        == "My script"
    )
    muted = client.post(f"/api/sources/{source['id']}/mute", json={"minutes": 60}, headers=UI).json()
    assert muted["muted_until"] is not None
    assert (
        client.post(f"/api/sources/{source['id']}/mute", json={"minutes": 0}, headers=UI).json()["muted_until"] is None
    )


PROXMOX_ESCAPED = (
    b'{\n  "title": "vzdump backup status (pve01): backup successful",\n'
    b'  "message": "Details\\n=======\\nVMID  Name  Status\\n104   mail  ok\\n",\n'
    b'  "severity": "info",\n  "type": "vzdump",\n  "host": "pve01"\n}'
)


def test_proxmox_body_as_the_template_renders_it(client: TestClient, operator: dict) -> None:
    """What Proxmox sends with the body from the setup hint: no Content-Type, message with escaped line breaks."""
    source = add_source(client, "proxmox")
    response = client.post("/api/v1/hook/" + source["connection"]["token"], content=PROXMOX_ESCAPED)
    assert response.status_code == 202
    [thread] = inbox(client)
    assert thread["title"] == "vzdump backup status (pve01): backup successful"
    assert thread["priority"] == "info"
    detail = client.get(f"/api/threads/{thread['id']}").json()
    assert detail["events"][0]["recognized"] is True
    assert "104   mail  ok" in detail["events"][0]["body"]


def test_raw_line_breaks_inside_json_strings_are_tolerated(client: TestClient, operator: dict) -> None:
    """A template without escape (older Proxmox examples, own scripts) puts real line breaks into the JSON
    strings. Strict JSON refuses that; nexsift reads it anyway instead of losing the structure."""
    source = add_source(client, "proxmox")
    raw = PROXMOX_ESCAPED.replace(b"\\n", b"\n")
    assert raw != PROXMOX_ESCAPED
    client.post("/api/v1/hook/" + source["connection"]["token"], content=raw)
    [thread] = inbox(client)
    assert thread["title"] == "vzdump backup status (pve01): backup successful"
    detail = client.get(f"/api/threads/{thread['id']}").json()
    assert detail["events"][0]["recognized"] is True


def test_a_good_proxmox_backup_closes_the_failed_one(client: TestClient, operator: dict) -> None:
    """As it happened on 30.09.2026: the nightly job failed for one container, the repaired run went through."""
    source = add_source(client, "proxmox")
    path = "/api/v1/hook/" + source["connection"]["token"]
    failed = {
        "title": "vzdump backup status (pve01): backup failed",
        "message": "201 ollama err",
        "severity": "error",
        "type": "vzdump",
        "host": "pve01",
    }
    good = {
        "title": "vzdump backup status (pve01): backup successful",
        "message": "201 ollama ok",
        "severity": "info",
        "type": "vzdump",
        "host": "pve01",
    }
    client.post(path, json=failed)
    client.post(path, json=good)
    [thread] = inbox(client)
    assert thread["resolved_at"] is not None
    assert thread["resolved_by"] == good["title"]
    assert inbox(client, "crit") == []
    # The next night fails again: a new red line, not the closed one.
    client.post(path, json=failed)
    assert len(inbox(client, "crit")) == 1
    # A good backup without an open problem is just an info line.
    client.post(path, json={**good, "host": "pve02", "title": "vzdump backup status (pve02): backup successful"})
    assert any(t["title"].endswith("(pve02): backup successful") and t["resolved_at"] is None for t in inbox(client))
