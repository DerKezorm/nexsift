"""The entrances on the main port: nexsift's own webhook and the Discord webhook path.

No session here: the token in the address is the permission. Unknown tokens get the same short answer as a
missing one, so the entrance does not tell which tokens exist. A body larger than ``BODY_MAX`` is refused before
it is parsed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..adapters import doors
from ..db import SessionLocal
from ..services import ingest
from ..services import sources as sources_service

router = APIRouter(tags=["entrances"])

BODY_MAX = 256 * 1024


async def read_body(request: Request) -> bytes | None:
    """The body, or None when it is too large."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > BODY_MAX:
        return None
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > BODY_MAX:
            return None
    return body


def _take(token: str, protocol: str, parse: Any) -> bool:
    with SessionLocal() as db:
        source = sources_service.by_token(db, token, protocol)
        if source is None:
            return False
        incoming, payload = parse()
        ingest.accept(db, source, incoming, payload)
        return True


@router.post("/api/v1/hook/{token}", summary="nexsift's own webhook (JSON with title, message, priority)")
async def hook(token: str, request: Request) -> Response:
    body = await read_body(request)
    if body is None:
        return JSONResponse({"error": "too large"}, status_code=413)
    content_type = request.headers.get("content-type", "")
    ok = await run_in_threadpool(_take, token, "webhook", lambda: doors.webhook(body, content_type))
    if not ok:
        return JSONResponse({"error": "unknown token"}, status_code=401)
    return JSONResponse({"ok": True}, status_code=202)


@router.post("/api/webhooks/{hook_id}/{token}", summary="Answers like a Discord webhook")
async def discord(hook_id: str, token: str, request: Request) -> Response:
    body = await read_body(request)
    if body is None:
        return JSONResponse({"message": "Request entity too large", "code": 40005}, status_code=413)
    ok = await run_in_threadpool(_discord, hook_id, token, body)
    if not ok:
        # Discord's own answer for an unknown webhook, so senders log something they recognize.
        return JSONResponse({"message": "Unknown Webhook", "code": 10015}, status_code=404)
    if request.query_params.get("wait", "").lower() in ("1", "true"):
        return JSONResponse({"id": "0", "type": 0, "content": "", "channel_id": "0"}, status_code=200)
    return Response(status_code=204)


def _discord(hook_id: str, token: str, body: bytes) -> bool:
    with SessionLocal() as db:
        source = sources_service.by_token(db, token, "discord")
        if source is None or source.match_key != f"discord:{hook_id}":
            return False
        incoming, payload = doors.discord(body)
        ingest.accept(db, source, incoming, payload)
        return True
