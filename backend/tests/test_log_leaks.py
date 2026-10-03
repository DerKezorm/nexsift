"""What really lands in the log file after a run with tokens through every door, at the most talkative level.

``test_log_secrets.py`` reads the code; this one reads the file. Sources of every door with their tokens and
topics, targets with credentials, a Web Push device, a password sign-in, an API key, an OIDC return with a code,
pushes that go out, an exception that carries a webhook address: afterwards none of the secrets may stand in the
log, on the level ``trace`` too. What a message said may (only there); that it does shows the file was read.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from secrets import randbelow, token_hex

import httpx
import pytest
from fastapi.testclient import TestClient

from app.services import logs, push
from tests.conftest import PASSWORD, UI, add_source

# Made up anew on every run, distinctive enough to be found anywhere in the file. Not written out: a fixed value in
# the shape of a real token is what secret scanners are there to stop.
NTFY_TARGET_TOPIC = f"alarm-{token_hex(8)}"
NTFY_TARGET_TOKEN = f"tk_{token_hex(12)}"
GOTIFY_TARGET_TOKEN = f"A{token_hex(7)}"
TELEGRAM_BOT_SECRET = f"AA{token_hex(16)}"
TELEGRAM_TOKEN = f"{100000000 + randbelow(899999999)}:{TELEGRAM_BOT_SECRET}"
PUSHOVER_TOKEN = f"a{token_hex(14)}"
PUSHOVER_USER = f"u{token_hex(14)}"
WEBPUSH_DEVICE = token_hex(16)
WEBPUSH_ENDPOINT = f"https://push.example.net/push/{WEBPUSH_DEVICE}"
WEBPUSH_AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
WEBPUSH_P256DH = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
STRANGER_TOPIC = "unknown-topic-Zx81LeakQ"
OIDC_CODE = "oidcLeakCodeR4nd0m77"
SAID_AT_NORMAL = "contentAtNormalQuiet42"
SAID_AT_TRACE = "contentAtTraceLoud42"


@pytest.fixture(autouse=True)
def fresh_log() -> Iterator[None]:
    yield
    logs.apply_mode(logs.DEFAULT_MODE)
    push.transport_for_tests = None


def _log_text() -> str:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return logs.log_file().read_text(encoding="utf-8")


def _run(client: TestClient, gotify_client: TestClient, ntfy_client: TestClient, said: str) -> list[str]:
    """Everything that touches a secret once. Returns the secrets that came into being."""
    secrets: list[str] = [PASSWORD]
    sent: list[httpx.Request] = []
    push.transport_for_tests = httpx.MockTransport(lambda request: sent.append(request) or httpx.Response(200))

    gotify = add_source(client, "gotify", "Watchtower")["connection"]
    ntfy = add_source(client, "ntfy", "Home Assistant")["connection"]
    webhook = add_source(client, "webhook", "nexcrate")["connection"]
    discord = add_source(client, "discord", "Uptime")["connection"]
    discord_token = discord["url"].rsplit("/", 1)[1]
    secrets += [gotify["token"], ntfy["topic"], webhook["token"], discord_token]

    # Targets with credentials of every kind; every critical message goes to each of them.
    targets = [
        {
            "kind": "ntfy",
            "name": "phone ntfy",
            "url": f"https://ntfy.example.com/{NTFY_TARGET_TOPIC}",
            "token": NTFY_TARGET_TOKEN,
        },
        {"kind": "gotify", "name": "gotify box", "url": "https://gotify.example.com", "token": GOTIFY_TARGET_TOKEN},
        {"kind": "telegram", "name": "telegram", "token": TELEGRAM_TOKEN, "chat_id": "4242"},
        {"kind": "pushover", "name": "pushover", "token": PUSHOVER_TOKEN, "user": PUSHOVER_USER},
    ]
    for target in targets:
        assert client.post("/api/targets", json={**target, "min_priority": "info"}, headers=UI).status_code == 201
    values = {"webpush_enabled": True, "storm_enabled": False}
    assert client.put("/api/settings", json={"values": values}, headers=UI).status_code == 200
    push.reset_for_tests()
    device = {
        "kind": "webpush",
        "name": "this phone",
        "url": WEBPUSH_ENDPOINT,
        "p256dh": WEBPUSH_P256DH,
        "auth": WEBPUSH_AUTH,
        "min_priority": "info",
    }
    assert client.post("/api/targets", json=device, headers=UI).status_code == 201
    secrets += [
        NTFY_TARGET_TOPIC,
        NTFY_TARGET_TOKEN,
        GOTIFY_TARGET_TOKEN,
        TELEGRAM_TOKEN,
        WEBPUSH_ENDPOINT,
        WEBPUSH_AUTH,
    ]
    secrets += [WEBPUSH_P256DH, WEBPUSH_DEVICE, TELEGRAM_BOT_SECRET, PUSHOVER_TOKEN, PUSHOVER_USER]

    # Through every door, with the permission where each sender puts it.
    title = f"Disk failed {said}"
    assert (
        gotify_client.post(
            f"/message?token={gotify['token']}", json={"title": title, "message": said, "priority": 8}
        ).status_code
        == 200
    )
    assert (
        gotify_client.post(
            "/message", json={"title": "via header", "message": said}, headers={"X-Gotify-Key": gotify["token"]}
        ).status_code
        == 200
    )
    assert (
        gotify_client.post(
            "/message", json={"title": "via bearer"}, headers={"Authorization": f"Bearer {gotify['token']}"}
        ).status_code
        == 200
    )
    assert (
        ntfy_client.post(
            f"/{ntfy['topic']}", content=f"backup failed {said}".encode(), headers={"Priority": "5"}
        ).status_code
        == 200
    )
    assert ntfy_client.get(f"/{ntfy['topic']}/publish?message={said}").status_code == 200
    assert ntfy_client.get(f"/{ntfy['topic']}/auth").status_code == 200
    assert ntfy_client.post(f"/{STRANGER_TOPIC}", content=b"who am I").status_code == 403
    assert (
        client.post(
            webhook["url"].split(":8490", 1)[-1], json={"title": title, "message": said, "priority": "crit"}
        ).status_code
        == 202
    )
    assert client.post(discord["url"].split(":8490", 1)[-1], json={"content": f"down {said}"}).status_code == 204
    assert client.post("/api/v1/hook/notAtokenLeakXYZ123", json={"title": "x"}).status_code == 401
    secrets.append("notAtokenLeakXYZ123")
    asyncio.run(push.deliver_due())
    assert sent, "the pushes went out through httpx"

    # A sign-in with the password, an OIDC return with a code, an API key in use.
    signed_in = TestClient(client.app, base_url="http://testserver")
    login = signed_in.post("/api/auth/login", json={"name": "admin", "password": PASSWORD}, headers=UI)
    assert login.status_code == 200, login.text
    secrets.append(signed_in.cookies.get("nexsift_session"))
    client.get(f"/api/oidc/callback?code={OIDC_CODE}&state=xyz", follow_redirects=False)
    secrets.append(OIDC_CODE)
    assert client.put("/api/settings", json={"values": {"api_keys_allowed": True}}, headers=UI).status_code == 200
    key = client.post("/api/api-keys", json={"name": "nexdeck"}, headers=UI).json()["key"]
    assert client.get("/api/v1/status", headers={"Authorization": f"Bearer {key}"}).status_code == 200
    assert client.get("/api/v1/status", headers={"Authorization": f"Bearer {key}x"}).status_code == 401
    secrets.append(key[len("nxs_") :])

    # A source token renewed, and an error that carries an address with a token in it.
    renewed = client.post(f"/api/sources/{add_source(client, 'webhook', 'second')['id']}/token", headers=UI).json()
    secrets.append(renewed["connection"]["token"])
    try:
        raise RuntimeError(f"posting to http://192.0.2.5:8490/api/v1/hook/{webhook['token']} failed")
    except RuntimeError:
        logging.getLogger("nexsift.probe").exception("Probe error with an address")
    # uvicorn's access log, should anyone switch it on (and an operator lift the seal by hand).
    access = logging.getLogger("uvicorn.access")
    access.warning('%s - "%s %s HTTP/%s" %d', "192.0.2.9", "POST", f"/message?token={gotify['token']}", "1.1", 200)
    access.warning('%s - "%s %s HTTP/%s" %d', "192.0.2.9", "POST", f"/api/v1/hook/{webhook['token']}", "1.1", 202)
    return [secret for secret in secrets if secret]


def test_no_secret_lands_in_the_log_at_any_level(
    client: TestClient, gotify_client: TestClient, ntfy_client: TestClient, operator: dict
) -> None:
    logs.apply_mode("normal")
    found = _run(client, gotify_client, ntfy_client, SAID_AT_NORMAL)
    text = _log_text()
    assert SAID_AT_NORMAL not in text, "what a message said stays out of the log below trace"

    client.delete("/api/logs", headers=UI)
    logs.apply_mode("trace")
    for model in ("sources", "targets"):
        for row in client.get(f"/api/{model}").json():
            client.delete(f"/api/{model}/{row['id']}", headers=UI)
    found += _run(client, gotify_client, ntfy_client, SAID_AT_TRACE)
    text = _log_text()

    # The run really was logged: request lines, masked paths, what the messages said.
    assert SAID_AT_TRACE in text, "trace writes what a message said; without it this test reads an empty file"
    assert "/api/v1/hook/***" in text and "/api/webhooks/" in text and "Unhandled" not in text
    assert "POST /*** -> 200" in text, "the ntfy door logs its requests with the topic masked"
    assert "Taken in source_id=" in text and "Push sent to phone ntfy" in text
    assert "Probe error with an address" in text and "RuntimeError" in text

    leaked = sorted({secret for secret in found if secret in text})
    assert not leaked, "Secrets in the log:\n" + "\n".join(
        line for line in text.splitlines() if any(secret in line for secret in leaked)
    )


def test_the_scrubber_masks_the_shapes_of_secrets() -> None:
    assert logs.scrub("POST /api/v1/hook/abcDEF123 -> 202") == "POST /api/v1/hook/*** -> 202"
    assert logs.scrub("/api/webhooks/1234/abc-DEF_9?wait=true") == "/api/webhooks/1234/***?wait=true"
    assert (
        logs.scrub("https://api.telegram.org/bot123:AAbc-d_e/sendMessage")
        == "https://api.telegram.org/bot***/sendMessage"
    )
    assert logs.scrub("/message?token=Axyz&x=1") == "/message?token=***&x=1"
    assert logs.scrub("/api/oidc/callback?state=s1&code=c2") == "/api/oidc/callback?state=***&code=***"
    assert logs.scrub("Authorization: Bearer abcdefgh123") == "Authorization: Bearer ***"
    assert logs.scrub("{'X-Gotify-Key': 'Aabcdef'}") == "{'X-Gotify-Key': '***'}"
    assert logs.scrub("key nxs_abcdefghij used") == "key nxs_*** used"
    assert logs.scrub("Cookie: nexsift_session=abc123; other=1") == "Cookie: nexsift_session=***; other=1"
    assert (
        logs.scrub("Source created id=3 name=Watchtower door=gotify")
        == "Source created id=3 name=Watchtower door=gotify"
    )


def test_the_ntfy_door_masks_the_topic_but_not_its_own_paths() -> None:
    assert logs.mask_path("/alarm-xyz", logs.NTFY) == "/***"
    assert logs.mask_path("/alarm-xyz/ws", logs.NTFY) == "/***/ws"
    assert logs.mask_path("/alarm-xyz/publish", logs.NTFY) == "/***/publish"
    assert logs.mask_path("/v1/account", logs.NTFY) == "/v1/account"
    assert logs.mask_path("/", logs.NTFY) == "/"
    assert logs.mask_path("/message", logs.GOTIFY) == "/message"
    assert logs.mask_path("/settings", logs.WEB) == "/settings", "interface paths stay readable on the main port"
