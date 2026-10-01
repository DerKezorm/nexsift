"""Where the setup hints send the senders. Behind a reverse proxy the browser's address is not the one the devices
at home can use: syslog, SMTP and the Gotify door do not go through a proxy (seen on a Synology, 01.10.2026)."""

from fastapi.testclient import TestClient

from tests.conftest import UI, add_source


def _settings(client: TestClient, **values: object):
    return client.put("/api/settings", json={"values": values}, headers=UI)


def test_the_sender_address_wins_over_the_public_one(client: TestClient, operator: dict) -> None:
    assert _settings(client, public_url="https://nexsift.example.com").status_code == 200
    assert _settings(client, sender_host="http://192.0.2.10/").json()["sender_host"] == "192.0.2.10"
    webhook = add_source(client, "webhook")["connection"]
    gotify = add_source(client, "gotify")["connection"]
    assert webhook["url"].startswith("http://192.0.2.10:")
    assert gotify["server"].startswith("http://192.0.2.10:")
    assert webhook["host_from"] == "sender"


def test_without_a_sender_address_the_public_one_is_used_and_said(client: TestClient, operator: dict) -> None:
    _settings(client, public_url="https://nexsift.example.com")
    webhook = add_source(client, "webhook")["connection"]
    assert webhook["url"].startswith("https://nexsift.example.com/api/v1/hook/")
    assert webhook["host_from"] == "public"


def test_a_sender_address_with_a_port_or_path_is_refused(client: TestClient, operator: dict) -> None:
    for value in ("192.0.2.10:8490", "nas.example.com/nexsift", "two words"):
        response = _settings(client, sender_host=value)
        assert response.status_code == 422, value
        assert response.json()["detail"]["code"] == "sender_host_invalid"
