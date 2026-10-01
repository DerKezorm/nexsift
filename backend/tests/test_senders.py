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

# Recorded from a real Watchtower 1.7.1 sending through shoutrrr's Gotify service, 01.10.2026.
WATCHTOWER_LOG = {
    "message": "Found new busybox:latest image (fd7dc98638c8)\nStopping /nsx-test-target (bc10b34da82b) with SIGTERM\nCreating /nsx-test-target\n",
    "title": "Watchtower updates on docker01",
    "priority": 0,
}
WATCHTOWER_REPORT = {
    "message": "1 Scanned, 1 Updated, 0 Failed\n- /nsx-test-target (busybox:latest): 9e2bbca07938 updated to fd7dc98638c8",
    "title": "Watchtower updates on docker01",
    "priority": 0,
}
WATCHTOWER_STARTED = {
    "message": "Watchtower 1.7.1\nUsing notifications: gotify\nOnly checking containers using enable label\nRunning a one time update.\n",
    "title": "Watchtower updates on docker01",
    "priority": 0,
}
# Two containers in one run, in the same line shapes as the recording.
WATCHTOWER_LOG_TWO = {
    "message": (
        "Found new jellyfin/jellyfin:latest image (3f2a9c1d77ab)\n"
        "Found new ghcr.io/immich-app/immich-server:release image (77ab12cd34ef)\n"
        "Stopping /jellyfin (4c1d2e5f6a7b) with SIGTERM\nCreating /jellyfin\n"
        "Stopping /immich_server (9a8b7c6d5e4f) with SIGTERM\nCreating /immich_server\n"
    ),
    "title": "Watchtower updates on docker01",
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


def _watchtower(sample: dict) -> list:
    return _refine("watchtower", doors.gotify(json.dumps(sample).encode(), {}, "application/json"))


def test_watchtower_log_lines_name_the_containers() -> None:
    assert [event.title for event in _watchtower(WATCHTOWER_LOG)] == ["Updated nsx-test-target"]
    events = _watchtower(WATCHTOWER_LOG_TWO)
    assert [event.title for event in events] == ["Updated jellyfin", "Updated immich_server"]
    assert all(event.group_key == "updates" for event in events)


def test_watchtower_session_report_names_the_container_too() -> None:
    assert [event.title for event in _watchtower(WATCHTOWER_REPORT)] == ["Updated nsx-test-target"]


def test_watchtower_start_is_called_a_start() -> None:
    [event] = _watchtower(WATCHTOWER_STARTED)
    assert event.title == "Watchtower started on docker01"
    assert event.recognized is True


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
    gotify_client.post(f"/message?token={token}", json=WATCHTOWER_LOG_TWO)
    gotify_client.post(f"/message?token={token}", json=WATCHTOWER_REPORT)
    [thread] = inbox(client)
    assert thread["title"] == "Watchtower: 3 containers updated"
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


# Recorded from a real Uptime Kuma 1.23.17 with its Discord notification, 01.10.2026.
KUMA_DISCORD_DOWN = {
    "username": "Uptime Kuma",
    "embeds": [
        {
            "title": "❌ Your service testweb went down. ❌",
            "color": 16711680,
            "timestamp": "2026-10-01 05:25:57.339",
            "fields": [
                {"name": "Service Name", "value": "testweb"},
                {"name": "Service URL", "value": "http://192.0.2.54:3399/"},
                {"name": "Time (UTC)", "value": "2026-10-01 05:25:57"},
                {"name": "Error", "value": "connect ECONNREFUSED 192.0.2.54:3399"},
            ],
        }
    ],
}
KUMA_DISCORD_UP = {
    "username": "Uptime Kuma",
    "embeds": [
        {
            "title": "✅ Your service testweb is up! ✅",
            "color": 65280,
            "timestamp": "2026-10-01 05:26:37.375",
            "fields": [
                {"name": "Service Name", "value": "testweb"},
                {"name": "Service URL", "value": "http://192.0.2.54:3399/"},
                {"name": "Time (UTC)", "value": "2026-10-01 05:26:37"},
                {"name": "Ping", "value": "3 ms"},
            ],
        }
    ],
}


def test_kuma_through_discord_pairs_down_and_up(client: TestClient, operator: dict) -> None:
    source = add_source(client, "discord", "Kuma via Discord")
    path = source["connection"]["url"].split("testserver:8490", 1)[1]
    client.post(path, json=KUMA_DISCORD_DOWN)
    [problem] = inbox(client, "crit")
    assert problem["title"] == "testweb is down"
    client.post(path, json=KUMA_DISCORD_UP)
    [thread] = inbox(client)
    assert thread["resolved_at"] is not None and thread["resolved_by"] == "testweb is up again"
    assert inbox(client, "crit") == []


def test_kuma_webhook_format_is_recognized_on_a_plain_webhook_source(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook", "Kuma via plain webhook")
    path = "/api/v1/hook/" + source["connection"]["token"]
    client.post(path, json=KUMA_DOWN)
    client.post(path, json=KUMA_UP)
    [thread] = inbox(client)
    assert thread["title"] == "cloud is down" and thread["resolved_at"] is not None


def test_other_discord_messages_stay_as_they_are(client: TestClient, operator: dict) -> None:
    source = add_source(client, "discord", "Radarr")
    path = source["connection"]["url"].split("testserver:8490", 1)[1]
    client.post(
        path,
        json={"username": "Radarr", "embeds": [{"title": "Movie Downloaded", "description": "The Quiet Hour (2023)"}]},
    )
    assert inbox(client)[0]["title"] == "Movie Downloaded"


def test_synology_webhook_as_json_and_as_form(client: TestClient, operator: dict) -> None:
    """DSM 7.2, Notification, Webhooks, provider Custom: the message goes into the field "text"; JSON when
    Content-Type is set to application/json, a form otherwise. The subject prefix is taken out of the title."""
    source = add_source(client, "synology", "nas01")
    assert "/api/v1/hook/" in source["connection"]["url"]
    path = "/api/v1/hook/" + source["connection"]["token"]
    client.post(path, json={"text": "[nas01] The system has detected that Volume 1 is degraded."})
    client.post(
        path,
        content=b"text=%5Bnas01%5D+Scheduled+S.M.A.R.T.+test+on+Drive+3+failed.",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    titles = {thread["title"]: thread["priority"] for thread in inbox(client)}
    assert titles == {
        "The system has detected that Volume 1 is degraded.": "warn",
        "Scheduled S.M.A.R.T. test on Drive 3 failed.": "crit",
    }


def test_paperless_json_inside_a_json_string_is_read_as_the_object(client: TestClient, operator: dict) -> None:
    """Paperless with "send webhook payload as JSON" on wraps the body template into a JSON string (measured with
    Paperless-ngx 3.2.1 on 01.10.2026)."""
    source = add_source(client, "paperless")
    inner = '{"title": "New document: Offer", "message": "", "url": "http://paperless.example.com/documents/2/"}'
    client.post("/api/v1/hook/" + source["connection"]["token"], json=inner)
    (thread,) = inbox(client)
    assert thread["title"] == "New document: Offer"
