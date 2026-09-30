"""The SMTP and syslog doors, driven through their handlers without opening ports."""

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.listeners import MailHandler, _take_syslog
from tests.conftest import add_source, inbox

MAIL = (
    b"From: nas01@example.com\r\nTo: synology@nexsift.local\r\nSubject: [nas01] Volume 1 is running out of space\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\nThe available capacity of Volume 1 is low.\r\n"
    b"Open https://nas01.example.com:5001/ to check.\r\n"
)


def _envelope() -> SimpleNamespace:
    return SimpleNamespace(rcpt_tos=[], mail_from="nas01@example.com", original_content=MAIL, content=MAIL)


def test_mail_to_a_known_recipient_arrives(client: TestClient, operator: dict) -> None:
    source = add_source(client, "synology", "Synology")
    assert source["connection"]["recipient"] == "synology@nexsift.local"
    assert source["connection"]["port"] == 25
    handler, session, envelope = MailHandler(), SimpleNamespace(peer=("192.0.2.9", 1)), _envelope()
    assert asyncio.run(handler.handle_RCPT(None, session, envelope, "synology@nexsift.local", [])).startswith("250")
    assert asyncio.run(handler.handle_DATA(None, session, envelope)).startswith("250")
    [thread] = inbox(client)
    # The host in brackets is taken out of the title; "running out" makes it a warning.
    assert thread["title"] == "Volume 1 is running out of space"
    assert thread["priority"] == "warn"
    assert thread["links"][0]["url"] == "https://nas01.example.com:5001/"


def test_mail_to_an_unknown_recipient_is_refused_and_offered(client: TestClient, operator: dict) -> None:
    handler, session, envelope = MailHandler(), SimpleNamespace(peer=("192.0.2.9", 1)), _envelope()
    assert asyncio.run(handler.handle_RCPT(None, session, envelope, "ups@nexsift.local", [])).startswith("550")
    [stranger] = client.get("/api/sources/strangers").json()
    assert (stranger["protocol"], stranger["key"]) == ("smtp", "ups")
    # Creating the source takes the stranger off the list.
    add_source(client, "ups", "ups")
    assert client.get("/api/sources/strangers").json() == []


def test_syslog_finds_the_source_by_host_name(client: TestClient, operator: dict) -> None:
    add_source(client, "syslog", "Router", "gw")
    for port in (51122, 51130, 40022):
        _take_syslog(
            f"<38>Sep 30 21:14:02 gw sshd[48211]: Failed password for invalid user admin from 203.0.113.47 port {port} ssh2",
            "192.0.2.1",
        )
    _take_syslog("<38>Sep 30 21:14:05 gw sshd[48212]: Invalid user oracle from 198.51.100.12 port 40410", "192.0.2.1")
    [thread] = inbox(client)
    assert thread["title"] == "sshd: 4 failed sign-ins"
    assert thread["priority"] == "warn"


def test_syslog_from_an_unknown_host_is_offered(client: TestClient, operator: dict) -> None:
    _take_syslog("<13>Sep 30 21:14:02 switch01 lldpd: new neighbor", "192.0.2.7")
    assert inbox(client) == []
    [stranger] = client.get("/api/sources/strangers").json()
    assert (stranger["protocol"], stranger["key"], stranger["peer"]) == ("syslog", "switch01", "192.0.2.7")


def test_a_generic_mail_source_also_takes_the_host_out_of_the_subject(client: TestClient, operator: dict) -> None:
    add_source(client, "email", "synology")
    handler, session, envelope = MailHandler(), SimpleNamespace(peer=("192.0.2.9", 1)), _envelope()
    asyncio.run(handler.handle_RCPT(None, session, envelope, "synology@nexsift.local", []))
    asyncio.run(handler.handle_DATA(None, session, envelope))
    assert inbox(client)[0]["title"] == "Volume 1 is running out of space"
