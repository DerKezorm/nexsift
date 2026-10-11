"""The entrances on the main port: nexsift's own webhook and the Discord webhook path.

No session here: the token in the address is the permission. Unknown tokens get the same short answer as a
missing one, so the entrance does not tell which tokens exist. A body larger than ``BODY_MAX`` is refused before
it is parsed.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException
from starlette.types import Message

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


async def form_fields(request: Request, body: bytes) -> dict[str, str]:
    """The text fields of a form, read from the body ``read_body`` already took: urlencoded, or multipart as
    ``curl -F`` sends it. Files are left out. Anything else, or a broken body, gives no fields."""
    kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if kind == "application/x-www-form-urlencoded":
        return dict(parse_qsl(body.decode("utf-8", errors="replace"), keep_blank_values=True))
    if kind != "multipart/form-data":
        return {}
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    try:
        form = await Request(request.scope, receive).form()
    except (HTTPException, MultiPartException):
        return {}
    try:
        return {key: value for key, value in form.items() if isinstance(value, str)}
    finally:
        await form.close()


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
    form = await form_fields(request, body)
    ok = await run_in_threadpool(_take, token, "webhook", lambda: doors.webhook(body, content_type, form))
    if not ok:
        return JSONResponse({"error": "unknown token"}, status_code=401)
    return JSONResponse({"ok": True}, status_code=202)


@router.post("/api/webhooks/{hook_id}/{token}", summary="Answers like a Discord webhook")
async def discord(hook_id: str, token: str, request: Request) -> Response:
    body = await read_body(request)
    if body is None:
        return JSONResponse({"message": "Request entity too large", "code": 40005}, status_code=413)
    form = await form_fields(request, body)
    ok = await run_in_threadpool(_discord, hook_id, token, body, form)
    if not ok:
        # Discord's own answer for an unknown webhook, so senders log something they recognize.
        return JSONResponse({"message": "Unknown Webhook", "code": 10015}, status_code=404)
    if request.query_params.get("wait", "").lower() in ("1", "true"):
        return JSONResponse({"id": "0", "type": 0, "content": "", "channel_id": "0"}, status_code=200)
    return Response(status_code=204)


def _discord(hook_id: str, token: str, body: bytes, form: dict[str, str]) -> bool:
    with SessionLocal() as db:
        source = sources_service.by_token(db, token, "discord")
        if source is None or source.match_key != f"discord:{hook_id}":
            return False
        incoming, payload = doors.discord(body, form)
        ingest.accept(db, source, incoming, payload)
        return True
