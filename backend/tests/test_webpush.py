"""Web Push: encryption as RFC 8291 has it, the VAPID signature, signing a device up, sending, and a device that left."""

import asyncio
import hashlib
import json

import http_ece
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Target
from app.services import push, webpush
from tests.conftest import UI, add_source

# The example of RFC 8291, section 5 and appendix A.
RFC_PLAINTEXT = b"When I grow up, I want to be a watermelon"
RFC_AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
RFC_UA_PUBLIC = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
RFC_UA_PRIVATE = "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"
RFC_AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
RFC_SALT = "DGv6ra1nlYgDCS1FRnbzlw"
RFC_BODY = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
    "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
    "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
)

ENDPOINT = "https://push.example.net/push/JzLQ3raZJfFBR0aqvOMsLrt54w4rJUsV"
SENT: list[httpx.Request] = []


def _private(text: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(webpush.unb64url(text), "big"), ec.SECP256R1())


def test_encryption_matches_the_rfc_example_byte_for_byte() -> None:
    body = webpush.encrypt(
        RFC_PLAINTEXT,
        RFC_UA_PUBLIC,
        RFC_AUTH,
        sender=_private(RFC_AS_PRIVATE),
        salt=webpush.unb64url(RFC_SALT),
    )
    assert webpush.b64url(body) == RFC_BODY


def test_the_vapid_header_is_a_valid_es256_token_for_the_push_service() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    header = webpush.vapid_header(key, ENDPOINT, "https://nexsift.example.com", now=1_800_000_000)
    token = header.split("t=", 1)[1].split(",", 1)[0]
    public = header.split("k=", 1)[1]
    claims = jwt.decode(
        token,
        key.public_key(),
        algorithms=["ES256"],
        audience="https://push.example.net",
        options={"verify_exp": False},
    )
    assert claims == {
        "aud": "https://push.example.net",
        "exp": 1_800_000_000 + webpush.VAPID_SECONDS,
        "sub": "https://nexsift.example.com",
    }
    assert webpush.unb64url(public) == webpush._public_bytes(key)


def _device(client: TestClient, **extra: object) -> dict:
    SENT.clear()
    push.transport_for_tests = httpx.MockTransport(lambda request: SENT.append(request) or httpx.Response(201))
    body = {
        "kind": "webpush",
        "name": "Phone",
        "url": ENDPOINT,
        "p256dh": RFC_UA_PUBLIC,
        "auth": RFC_AUTH,
        "min_priority": "crit",
        **extra,
    }
    return client.post("/api/targets", json=body, headers=UI)


def _switch(client: TestClient, on: bool) -> None:
    assert client.put("/api/settings", json={"values": {"webpush_enabled": on}}, headers=UI).status_code == 200


def test_a_device_signs_up_and_shows_only_its_push_service(client: TestClient, operator: dict) -> None:
    response = _device(client)
    assert response.status_code == 201, response.text
    assert response.json()["url"] == "push.example.net"
    # The browser recognizes itself by this fingerprint; the address itself never goes back.
    assert response.json()["device"] == hashlib.sha256(ENDPOINT.encode()).hexdigest()[:16]
    assert response.json()["has_token"] is False


def test_an_incomplete_sign_up_is_refused(client: TestClient, operator: dict) -> None:
    for broken in ({"p256dh": "short"}, {"auth": ""}, {"url": "http://push.example.net/x"}):
        response = _device(client, **broken)
        assert response.status_code == 422, broken
        assert response.json()["detail"]["code"] in ("webpush_invalid", "target_field_missing")


def test_the_key_stays_the_same_and_the_switch_starts_off(client: TestClient, operator: dict) -> None:
    first = client.get("/api/targets/webpush/key").json()
    second = client.get("/api/targets/webpush/key").json()
    assert first["enabled"] is False
    assert first["key"] == second["key"]
    assert len(webpush.unb64url(first["key"])) == 65


def test_nothing_goes_out_while_switched_off(client: TestClient, operator: dict) -> None:
    target = _device(client).json()
    result = client.post(f"/api/targets/{target['id']}/test", headers=UI).json()
    assert result["ok"] is False and "switched off" in result["error"]
    assert SENT == []


def test_a_critical_message_reaches_the_device_encrypted_and_signed(client: TestClient, operator: dict) -> None:
    _switch(client, True)
    _device(client)
    source = add_source(client, "webhook", "Server")
    client.post(
        "/api/v1/hook/" + source["connection"]["token"], json={"title": "VM 104 stopped", "priority": "critical"}
    )
    asyncio.run(push.deliver_due())
    assert len(SENT) == 1
    request = SENT[0]
    assert str(request.url) == ENDPOINT
    assert request.headers["content-encoding"] == "aes128gcm"
    assert request.headers["urgency"] == "high"
    assert request.headers["authorization"].startswith("vapid t=")
    # What the device reads after decrypting with its own key.
    plain = http_ece.decrypt(
        request.content,
        private_key=_private(RFC_UA_PRIVATE),
        auth_secret=webpush.unb64url(RFC_AUTH),
        version="aes128gcm",
    )
    data = json.loads(plain)
    assert data["title"] == "Server: VM 104 stopped"
    assert data["priority"] == "crit"
    assert data["url"].startswith("/?thread=") and data["tag"].startswith("thread-")


def test_a_device_that_left_is_switched_off_and_says_why(client: TestClient, operator: dict) -> None:
    _switch(client, True)
    _device(client)
    push.transport_for_tests = httpx.MockTransport(lambda request: httpx.Response(410))
    source = add_source(client, "webhook", "Server")
    client.post(
        "/api/v1/hook/" + source["connection"]["token"], json={"title": "VM 104 stopped", "priority": "critical"}
    )
    asyncio.run(push.deliver_due())
    with SessionLocal() as db:
        target = db.query(Target).one()
        assert target.enabled is False
        assert "no longer signed up" in target.last_error


def test_switching_a_device_off_and_on_keeps_its_sign_up(client: TestClient, operator: dict) -> None:
    """The list shows only the push service's host; sending the target back must not overwrite the address."""
    target = _device(client).json()
    for enabled in (False, True):
        response = client.put(
            f"/api/targets/{target['id']}", json={**target, "token": "", "enabled": enabled}, headers=UI
        )
        assert response.status_code == 200, response.text
    with SessionLocal() as db:
        config = push.target_config(db.query(Target).one())
    assert config["url"] == ENDPOINT
    assert config["p256dh"] == RFC_UA_PUBLIC and config["auth"] == RFC_AUTH


def test_several_devices_are_several_targets_and_the_same_one_twice_is_one(client: TestClient, operator: dict) -> None:
    phone = _device(client, name="Phone").json()
    laptop = _device(client, name="Laptop", url=ENDPOINT + "-laptop").json()
    again = _device(client, name="Phone, again").json()
    assert phone["id"] != laptop["id"]
    assert again["id"] == phone["id"] and again["name"] == "Phone, again"
    with SessionLocal() as db:
        assert db.query(Target).count() == 2
