"""The two doors that are not HTTP: SMTP for devices that only send email, and syslog.

SMTP accepts mail for ``<name>@<anything>`` without sign-in and without TLS: the devices that need this door
(UPS, printers, old routers) rarely manage more. The recipient's name is the permission; an unknown one is
refused at RCPT, before any content is taken, and shows up on the sources page as a sender without a source.

Syslog listens on UDP and TCP (newline-framed or with an octet count). The host name in the message, or the
sender's address when there is none, finds the source.
"""

from __future__ import annotations

import asyncio
import email
import email.policy
import logging
from email.message import EmailMessage
from typing import Any

from .adapters import doors
from .db import SessionLocal
from .services import ingest, strangers
from .services import sources as sources_service

logger = logging.getLogger("nexsift.listeners")

MAIL_MAX = 1024 * 1024
SYSLOG_LINE_MAX = 8192


# --- SMTP -------------------------------------------------------------------------------------------------- #


class MailHandler:
    async def handle_RCPT(self, server: Any, session: Any, envelope: Any, address: str, rcpt_options: list) -> str:
        local = address.split("@", 1)[0].strip().lower()

        def known() -> bool:
            with SessionLocal() as db:
                return sources_service.by_key(db, f"smtp:{local}") is not None

        if not await asyncio.get_running_loop().run_in_executor(None, known):
            peer = session.peer[0] if session.peer else ""
            strangers.knock("smtp", local, f"mail from {envelope.mail_from or '?'}", peer)
            return "550 5.1.1 No such source in nexsift"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        raw: bytes = envelope.original_content or envelope.content or b""
        if len(raw) > MAIL_MAX:
            return "552 5.3.4 Message too big"
        message = email.message_from_bytes(raw, policy=email.policy.default)
        if not isinstance(message, EmailMessage):
            return "554 5.6.0 Not a mail"
        locals_ = {address.split("@", 1)[0].strip().lower() for address in envelope.rcpt_tos}

        def take() -> None:
            with SessionLocal() as db:
                for local in locals_:
                    source = sources_service.by_key(db, f"smtp:{local}")
                    if source is None:
                        continue
                    incoming, payload = doors.email(message, raw)
                    ingest.accept(db, source, incoming, payload)

        await asyncio.get_running_loop().run_in_executor(None, take)
        return "250 Message accepted"


def start_smtp(host: str, port: int) -> Any:
    """Starts the SMTP door in its own thread (aiosmtpd's controller); returns it so the app can stop it."""
    from aiosmtpd.controller import Controller

    controller = Controller(
        MailHandler(),
        hostname=host,
        port=port,
        data_size_limit=MAIL_MAX,
        ident="nexsift",
        server_hostname="nexsift",
    )
    controller.start()
    logger.info("SMTP door listening on %s:%s", host, port)
    return controller


# --- Syslog ------------------------------------------------------------------------------------------------ #


def _take_syslog(line: str, peer: str) -> None:
    if not line.strip():
        return
    incoming, payload = doors.syslog(line[:SYSLOG_LINE_MAX], peer)
    host = str(payload.get("host", "") or peer).lower()
    with SessionLocal() as db:
        source = sources_service.by_key(db, f"syslog:{host}") or sources_service.by_key(db, f"syslog:{peer}")
        if source is None:
            strangers.knock("syslog", host, incoming.title, peer)
            return
        ingest.accept(db, source, incoming, payload)


class SyslogUdp(asyncio.DatagramProtocol):
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        line = data[:SYSLOG_LINE_MAX].decode("utf-8", errors="replace")
        asyncio.get_running_loop().run_in_executor(None, _take_syslog, line, addr[0])


async def _syslog_tcp(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = (writer.get_extra_info("peername") or ("", 0))[0]
    loop = asyncio.get_running_loop()
    try:
        while True:
            first = await reader.read(1)
            if not first:
                break
            if first.isdigit():
                # Octet counting (RFC 6587): "<length> <message>".
                digits = first + await reader.readuntil(b" ")
                length = int(digits.strip() or b"0")
                if length <= 0 or length > SYSLOG_LINE_MAX:
                    break
                data = await reader.readexactly(length)
            else:
                data = first + await reader.readuntil(b"\n")
            await loop.run_in_executor(None, _take_syslog, data.decode("utf-8", errors="replace"), peer)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError, ConnectionError):
        pass
    finally:
        writer.close()


async def start_syslog(host: str, port: int) -> list[Any]:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(SyslogUdp, local_addr=(host, port))
    server = await asyncio.start_server(_syslog_tcp, host, port, limit=SYSLOG_LINE_MAX + 64)
    logger.info("Syslog door listening on %s:%s (UDP and TCP)", host, port)
    return [transport, server]
