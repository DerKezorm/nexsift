"""What reaches the phone: at once, follow-ups, all-clear, storm guard, quiet hours, retries."""

import asyncio
import json
from datetime import timedelta

import httpx
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Delivery, Thread, utcnow
from app.services import push
from tests.conftest import UI, add_source

SENT: list[dict] = []


def _record(request: httpx.Request) -> httpx.Response:
    SENT.append({"url": str(request.url), "headers": dict(request.headers), "body": request.content.decode()})
    return httpx.Response(200, json={})


def _phone(client: TestClient, **extra: object) -> dict:
    SENT.clear()
    push.transport_for_tests = httpx.MockTransport(_record)
    body = {"kind": "ntfy", "name": "Phone", "url": "https://ntfy.example.com/alerts", "min_priority": "crit", **extra}
    response = client.post("/api/targets", json=body, headers=UI)
    assert response.status_code == 201, response.text
    return response.json()


def _run() -> None:
    with SessionLocal() as db:
        push.due_windows(db)
    asyncio.run(push.deliver_due())


def _hook(client: TestClient, preset: str = "webhook"):
    source = add_source(client, preset, "Server")
    path = "/api/v1/hook/" + source["connection"]["token"]
    return lambda **body: client.post(path, json=body)


def _end_windows() -> None:
    with SessionLocal() as db:
        for thread in db.query(Thread).all():
            if thread.window_until:
                thread.window_until = utcnow() - timedelta(seconds=1)
        db.commit()


def test_critical_goes_out_at_once_then_one_follow_up(client: TestClient, operator: dict) -> None:
    _phone(client)
    send = _hook(client)
    send(title="VM 104 stopped", priority="critical")
    _run()
    assert len(SENT) == 1
    assert SENT[0]["headers"]["title"] == "Server: VM 104 stopped"
    assert SENT[0]["headers"]["priority"] == "5"
    send(title="VM 104 stopped", priority="critical")
    send(title="VM 104 stopped", priority="critical")
    _run()
    assert len(SENT) == 1, "more of the same wait for the end of the window"
    _end_windows()
    _run()
    assert len(SENT) == 2
    assert SENT[1]["body"] == "+2 more since the first message"


def test_info_and_warnings_stay_quiet(client: TestClient, operator: dict) -> None:
    _phone(client)
    send = _hook(client)
    send(title="Backup done")
    send(title="Disk WARNING")
    _run()
    assert SENT == []


def test_all_clear_follows_the_alarm(client: TestClient, operator: dict) -> None:
    from tests.test_senders import KUMA_DOWN, KUMA_UP

    _phone(client)
    send = _hook(client, "uptimekuma")
    send(**KUMA_DOWN)
    _run()
    send(**KUMA_UP)
    _run()
    assert [entry["headers"]["title"] for entry in SENT] == [
        "Server: cloud is not reachable",
        "Server: cloud is reachable again",
    ]
    # The all-clear reaches the same phone, but quietly, and says how long it took.
    assert SENT[0]["headers"]["priority"] == "5"
    assert SENT[1]["headers"]["priority"] == "3"
    assert "white_check_mark" in SENT[1]["headers"]["tags"]
    assert SENT[1]["body"].startswith("Resolved after ")


def test_muted_source_does_not_ring(client: TestClient, operator: dict) -> None:
    _phone(client)
    source = add_source(client, "webhook", "Loud")
    client.post(f"/api/sources/{source['id']}/mute", json={"minutes": 60}, headers=UI)
    client.post("/api/v1/hook/" + source["connection"]["token"], json={"title": "x", "priority": "critical"})
    _run()
    assert SENT == []


def test_storm_guard_turns_many_into_one(client: TestClient, operator: dict) -> None:
    client.put("/api/settings", json={"values": {"storm_count": 3, "storm_minutes": 2}}, headers=UI)
    _phone(client)
    send = _hook(client)
    # Different names: "Service 1" and "Service 2" would be the same message to nexsift and land in one line.
    for name in ("mail", "cloud", "wiki", "dns", "vpn", "git", "chat", "photos"):
        send(title=f"{name} is down", priority="critical")
    _run()
    assert len(SENT) == 3
    push._storm_until = utcnow() - timedelta(seconds=1)
    _run()
    assert len(SENT) == 4
    assert SENT[3]["headers"]["title"] == "5 more critical messages from 1 sources"


def test_window_mode_sends_one_summary(client: TestClient, operator: dict) -> None:
    client.put("/api/settings", json={"values": {"push_mode": "window"}}, headers=UI)
    _phone(client)
    send = _hook(client)
    send(title="Pool FAILED")
    send(title="Pool FAILED")
    _run()
    assert SENT == []
    _end_windows()
    _run()
    assert len(SENT) == 1 and SENT[0]["body"] == "2 messages"


def test_failed_push_is_retried_and_shown(client: TestClient, operator: dict) -> None:
    target = _phone(client)
    push.transport_for_tests = httpx.MockTransport(lambda request: httpx.Response(502))
    send = _hook(client)
    send(title="Pool FAILED")
    _run()
    with SessionLocal() as db:
        delivery = db.query(Delivery).one()
        assert delivery.status == "pending" and delivery.attempts == 1
        assert delivery.next_try_at > utcnow()
    listed = client.get("/api/targets").json()[0]
    assert listed["id"] == target["id"] and listed["last_error"] == "answered HTTP 502"


def test_target_secrets_never_come_back(client: TestClient, operator: dict) -> None:
    body = {
        "kind": "gotify",
        "name": "Old",
        "url": "https://gotify.example.com",
        "token": "AppToken123",
        "min_priority": "warn",
    }
    created = client.post("/api/targets", json=body, headers=UI).json()
    assert "AppToken123" not in json.dumps(created)
    assert created["has_token"] is True
    # Saving without the token keeps it.
    kept = client.put(f"/api/targets/{created['id']}", json={**body, "token": ""}, headers=UI)
    assert kept.status_code == 200 and kept.json()["has_token"] is True


def test_target_test_button_reports(client: TestClient, operator: dict) -> None:
    target = _phone(client)
    assert client.post(f"/api/targets/{target['id']}/test", headers=UI).json() == {"ok": True}
    push.transport_for_tests = httpx.MockTransport(lambda request: httpx.Response(401))
    assert client.post(f"/api/targets/{target['id']}/test", headers=UI).json() == {
        "ok": False,
        "error": "answered HTTP 401",
    }


def test_quiet_hours_hold_back_below_critical(client: TestClient, operator: dict) -> None:
    from datetime import datetime

    now = datetime.now().astimezone()
    # A quiet stretch around now, wrapping midnight if need be, so the test holds at any hour.
    start, end = (now - timedelta(hours=1)).strftime("%H:%M"), (now + timedelta(hours=1)).strftime("%H:%M")
    _phone(client, min_priority="warn", quiet_from=start, quiet_to=end)
    send = _hook(client)
    send(title="Disk WARNING")
    send(title="Pool FAILED")
    _run()
    assert [entry["headers"]["title"] for entry in SENT] == ["Server: Pool FAILED"]


def test_target_validation(client: TestClient, operator: dict) -> None:
    missing = client.post("/api/targets", json={"kind": "telegram", "name": "T", "token": "x"}, headers=UI)
    assert missing.status_code == 422 and missing.json()["detail"]["field"] == "chat_id"
    no_user = client.post("/api/targets", json={"kind": "pushover", "name": "P", "token": "x"}, headers=UI)
    assert no_user.status_code == 422 and no_user.json()["detail"]["field"] == "user"
    quiet = client.post(
        "/api/targets",
        json={"kind": "ntfy", "name": "n", "url": "https://x.example.com/a", "quiet_from": "23:00"},
        headers=UI,
    )
    assert quiet.json()["detail"]["code"] == "invalid_quiet_hours"


def test_all_clear_waits_out_quiet_hours(client: TestClient, operator: dict) -> None:
    from datetime import datetime

    from tests.test_senders import KUMA_DOWN, KUMA_UP

    now = datetime.now().astimezone()
    start, end = (now - timedelta(hours=1)).strftime("%H:%M"), (now + timedelta(hours=1)).strftime("%H:%M")
    _phone(client, quiet_from=start, quiet_to=end)
    send = _hook(client, "uptimekuma")
    send(**KUMA_DOWN)
    _run()
    send(**KUMA_UP)
    _run()
    assert [entry["headers"]["title"] for entry in SENT] == ["Server: cloud is not reachable"]


def _pushover(client: TestClient) -> dict:
    SENT.clear()
    push.transport_for_tests = httpx.MockTransport(_record)
    body = {"kind": "pushover", "name": "Pushover", "token": "AppTokenP1", "user": "UserKeyP1", "min_priority": "crit"}
    response = client.post("/api/targets", json=body, headers=UI)
    assert response.status_code == 201, response.text
    created = response.json()
    assert "AppTokenP1" not in json.dumps(created) and created["has_token"] is True
    assert created["user"] == "UserKeyP1"
    return created


def test_pushover_gets_alarm_and_all_clear(client: TestClient, operator: dict) -> None:
    from urllib.parse import parse_qs

    from tests.test_senders import KUMA_DOWN, KUMA_UP

    _pushover(client)
    send = _hook(client, "uptimekuma")
    send(**KUMA_DOWN)
    _run()
    send(**KUMA_UP)
    _run()
    assert [entry["url"] for entry in SENT] == [push.PUSHOVER_URL] * 2
    alarm, clear = ({key: value[0] for key, value in parse_qs(entry["body"]).items()} for entry in SENT)
    assert alarm["token"] == "AppTokenP1" and alarm["user"] == "UserKeyP1"
    assert alarm["title"] == "Server: cloud is not reachable" and alarm["priority"] == "1"
    # The all-clear comes with a normal sound, not the loud one.
    assert clear["title"] == "Server: cloud is reachable again" and clear["priority"] == "0"
    assert clear["message"].startswith("Resolved after ")


def test_pushover_says_what_is_wrong(client: TestClient, operator: dict) -> None:
    target = _pushover(client)
    refusal = {"token": "invalid", "errors": ["application token is invalid"], "status": 0}
    push.transport_for_tests = httpx.MockTransport(lambda request: httpx.Response(400, json=refusal))
    assert client.post(f"/api/targets/{target['id']}/test", headers=UI).json() == {
        "ok": False,
        "error": "Pushover: application token is invalid",
    }
    push.transport_for_tests = httpx.MockTransport(lambda request: httpx.Response(429, text="slow down"))
    assert client.post(f"/api/targets/{target['id']}/test", headers=UI).json()["error"] == "answered HTTP 429"


def test_pushes_speak_the_push_language(client: TestClient, operator: dict) -> None:
    from tests.test_senders import KUMA_DOWN, KUMA_UP

    assert client.put("/api/settings", json={"values": {"push_language": "fr"}}, headers=UI).status_code == 422
    assert client.put("/api/settings", json={"values": {"push_language": "de"}}, headers=UI).status_code == 200
    _phone(client)
    send = _hook(client, "uptimekuma")
    send(**KUMA_DOWN)
    _run()
    send(**KUMA_UP)
    _run()
    assert [entry["headers"]["title"] for entry in SENT] == [
        "Server: cloud ist nicht erreichbar",
        "Server: cloud ist wieder erreichbar",
    ]
    assert SENT[0]["body"].startswith("cloud.example.com\nAntwortet nicht rechtzeitig.")
    assert SENT[1]["body"].startswith("Erledigt nach ")
    # What a sender worded itself stays as it came: nexsift does not translate other people's sentences.
    plain = _hook(client)
    plain(title="VM 104 stopped", priority="critical")
    _run()
    assert SENT[2]["headers"]["title"] == "Server: VM 104 stopped"


def test_a_german_title_with_umlauts_reaches_ntfy(client: TestClient, operator: dict) -> None:
    from tests.test_senders import _kuma

    client.put("/api/settings", json={"values": {"push_language": "de"}}, headers=UI)
    _phone(client, min_priority="warn")
    send = _hook(client, "uptimekuma")
    send(**_kuma(2, "timeout of 48000ms exceeded"))
    _run()
    assert len(SENT) == 1
    title = SENT[0]["headers"]["title"]
    assert title.startswith("=?UTF-8?B?") or "prüft" in title
