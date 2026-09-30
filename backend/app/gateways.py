"""The two doors that answer like somebody else, each as its own small app on its own port.

**Gotify** (``POST /message``): senders are told the address of a Gotify server and an app token. The token
comes as ``?token=``, as ``X-Gotify-Key`` or as ``Authorization: Bearer``, as with the real server. A few read
calls that clients make to check the server (``/version``, ``/health``, ``/current/user``) get plausible
answers.

**ntfy** (``POST``/``PUT /<topic>``, or JSON to ``/``): senders are told a server and a topic. The topic is the
permission: nexsift makes them long enough to not be guessed, and an unknown topic is refused instead of
silently created, as the real server would do.

Own ports because the paths collide: ``/message`` would be an ntfy topic called "message", and senders append
these paths to whatever server address they are given, so a prefix like ``/gotify`` does not survive in all of
them.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from . import __version__
from .adapters import doors
from .db import SessionLocal
from .middleware import RequestContextMiddleware
from .routers.ingress import read_body
from .services import ingest, strangers
from .services import sources as sources_service

# --- Gotify ------------------------------------------------------------------------------------------------- #

gotify = FastAPI(title="nexsift gotify door", docs_url=None, redoc_url=None, openapi_url=None)
gotify.add_middleware(RequestContextMiddleware)


def _gotify_error(status: int, description: str) -> JSONResponse:
    names = {400: "Bad Request", 401: "Unauthorized", 413: "Request Entity Too Large"}
    return JSONResponse(
        {"error": names.get(status, "Error"), "errorCode": status, "errorDescription": description}, status_code=status
    )


def _gotify_token(request: Request) -> str:
    token = request.query_params.get("token") or request.headers.get("x-gotify-key", "")
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    return token.strip()


@gotify.post("/message")
async def gotify_message(request: Request) -> Response:
    token = _gotify_token(request)
    body = await read_body(request)
    if body is None:
        return _gotify_error(413, "the message is too large")
    content_type = request.headers.get("content-type", "")
    form: dict[str, str] = {}
    if "form" in content_type:
        from urllib.parse import parse_qsl

        form = dict(parse_qsl(body.decode("utf-8", errors="replace")))

    def take() -> dict[str, Any] | None:
        with SessionLocal() as db:
            source = sources_service.by_token(db, token, "gotify")
            if source is None:
                return None
            incoming, payload = doors.gotify(body, form, content_type)
            ingest.accept(db, source, incoming, payload)
            return {
                "id": int(time.time() * 1000) % 2**31,
                "appid": source.id,
                "message": str(payload.get("message", "")),
                "title": str(payload.get("title", "")),
                "priority": payload.get("priority", 0),
                "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

    result = await run_in_threadpool(take)
    if result is None:
        return _gotify_error(401, "you need to provide a valid access token or user credentials to access this api")
    return JSONResponse(result)


@gotify.get("/version")
def gotify_version() -> dict[str, str]:
    return {"version": "2.6.0", "commit": f"nexsift-{__version__}", "buildDate": ""}


@gotify.get("/health")
def gotify_health() -> dict[str, str]:
    return {"health": "green", "database": "green"}


@gotify.get("/current/user")
def gotify_user() -> Response:
    # An app token may not read the user; the real server says the same.
    return _gotify_error(401, "you need to provide a valid access token or user credentials to access this api")


# --- ntfy --------------------------------------------------------------------------------------------------- #

ntfy = FastAPI(title="nexsift ntfy door", docs_url=None, redoc_url=None, openapi_url=None)
ntfy.add_middleware(RequestContextMiddleware)


def _ntfy_error(status: int, code: int, error: str) -> JSONResponse:
    return JSONResponse({"code": code, "http": status, "error": error}, status_code=status)


async def _ntfy_publish(request: Request, topic: str | None) -> Response:
    body = await read_body(request)
    if body is None:
        return _ntfy_error(413, 41301, "request entity too large")
    headers = {key.lower(): value for key, value in request.headers.items()}
    query = {key.lower(): value for key, value in request.query_params.items()}
    if not body and query.get("message"):
        body = query["message"].encode("utf-8")
    content_type = headers.get("content-type", "")
    json_topic = None
    if topic is None:
        import json

        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
            json_topic = str(data.get("topic", "")) if isinstance(data, dict) else None
        except ValueError:
            json_topic = None
        if not json_topic:
            return _ntfy_error(400, 40001, "invalid request: topic missing")
    name = (topic or json_topic or "").strip()

    def take() -> bool:
        with SessionLocal() as db:
            source = sources_service.by_key(db, f"ntfy:{name}")
            if source is None:
                strangers.knock(
                    "ntfy", name, body.decode("utf-8", errors="replace"), request.client.host if request.client else ""
                )
                return False
            incoming, payload = doors.ntfy(body, headers, query, content_type)
            ingest.accept(db, source, incoming, payload)
            return True

    if not await run_in_threadpool(take):
        return _ntfy_error(403, 40301, "forbidden: this topic is not set up in nexsift")
    return JSONResponse(
        {"id": hex(int(time.time() * 1000))[2:], "time": int(time.time()), "event": "message", "topic": name}
    )


@ntfy.get("/v1/health")
def ntfy_health() -> dict[str, bool]:
    return {"healthy": True}


@ntfy.get("/v1/account")
def ntfy_account() -> dict[str, str]:
    return {"username": "*", "role": "anonymous"}


@ntfy.post("/")
@ntfy.put("/")
async def ntfy_root(request: Request) -> Response:
    return await _ntfy_publish(request, None)


@ntfy.post("/{topic}")
@ntfy.put("/{topic}")
async def ntfy_topic(topic: str, request: Request) -> Response:
    return await _ntfy_publish(request, topic)


@ntfy.get("/{topic}/publish")
@ntfy.get("/{topic}/send")
@ntfy.get("/{topic}/trigger")
async def ntfy_get(topic: str, request: Request) -> Response:
    return await _ntfy_publish(request, topic)
