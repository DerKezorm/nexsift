"""The main app: interface, API, the own webhook and the Discord path, and everything that runs in the
background (push worker, housekeeping, SMTP and syslog doors). The Gotify and ntfy doors are separate apps on
their own ports, see ``gateways.py``; ``serve.py`` starts all of them together."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, housekeeping, listeners
from .config import get_settings
from .db import SessionLocal, init_db
from .meldungen import meldung
from .middleware import RequestContextMiddleware, unhandled_error
from .routers import (
    about,
    api_keys,
    api_v1,
    auth,
    backups,
    icons,
    ingress,
    logs,
    oidc,
    rules,
    sources,
    system,
    targets,
    threads,
)
from .services import backups as backup_service
from .services import bus, presets, push, settings_service
from .services import icons as icon_service
from .services import logs as log_service

logger = logging.getLogger("nexsift")


def _read_log_mode() -> tuple[str, datetime | None]:
    with SessionLocal() as db:
        mode = settings_service.get(db, "log_mode")
        raw = settings_service.get(db, "log_mode_until")
    until = datetime.fromisoformat(raw).astimezone(UTC) if raw else None
    return str(mode or log_service.DEFAULT_MODE), until


def _write_log_mode(mode: str, until: datetime | None) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"log_mode": mode, "log_mode_until": until.isoformat() if until else None})


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    log_service.setup()
    # ``serve`` swaps a waiting restore in before the doors open; this is for a start through uvicorn directly.
    try:
        backup_service.apply_pending()
    except Exception:
        logger.exception("Applying the pending restore failed")
    init_db()
    # The server secret is made now, not on first use: a backup taken before the first source would otherwise
    # carry KEY-MISSING.txt, and a restore would meet a key that did not exist yet.
    get_settings().resolved_secret_key()
    log_service.attach_store(_read_log_mode, _write_log_mode)
    log_service.apply_stored_mode()
    if backup_service.restored_at_start:
        # The sessions in the restored database are those of back then; nobody should come back in through them.
        with SessionLocal() as db:
            from sqlalchemy import delete

            from .models import AuthSession

            db.execute(delete(AuthSession))
            db.commit()
        backup_service.restored_at_start = False
        logger.info("Backup restored at start, all browser sessions ended")
    with SessionLocal() as db:
        from .services import accounts

        if accounts.count(db) > 0:
            presets.install_defaults(db)
    bus.attach(asyncio.get_running_loop())
    settings = get_settings()
    stop = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []
    closers: list[Any] = []
    if not settings.disable_background:
        tasks.append(asyncio.create_task(push.run_forever(stop)))
        tasks.append(asyncio.create_task(housekeeping.run_forever(stop)))
        tasks.append(asyncio.create_task(log_service.run_forever(stop)))
        tasks.append(asyncio.create_task(backup_service.run_forever(stop)))
        if settings.smtp_port:
            try:
                closers.append(listeners.start_smtp(settings.host, settings.smtp_port))
            except OSError as error:
                logger.error("SMTP door could not open port %s: %s", settings.smtp_port, error)
        if settings.syslog_port:
            try:
                closers.extend(await listeners.start_syslog(settings.host, settings.syslog_port))
            except OSError as error:
                logger.error("Syslog door could not open port %s: %s", settings.syslog_port, error)
    logger.info("nexsift %s started", __version__)
    try:
        yield
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await icon_service.close()
        for closer in closers:
            # The SMTP controller stops, the syslog transport and server close.
            try:
                if hasattr(closer, "close"):
                    closer.close()
                else:
                    closer.stop()
            except Exception:  # shutting down, the process ends anyway
                logger.debug("Closing a door failed", exc_info=True)


app = FastAPI(
    title="nexsift",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs" if get_settings().api_docs else None,
    openapi_url="/api/openapi.json" if get_settings().api_docs else None,
    redoc_url=None,
)
app.add_middleware(RequestContextMiddleware)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or "-"


def _refused(request: Request, status: int, code: str) -> None:
    """A refused request leaves a line, so the request id in the error message finds something in the log. An
    expired session is everyday business and stays at debug."""
    level = logging.DEBUG if code == "not_signed_in" else logging.INFO
    path = log_service.mask_path(request.url.path)
    logging.getLogger("nexsift.api").log(level, "Refused %s %s -> %s code=%s", request.method, path, status, code)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [".".join(str(part) for part in error.get("loc", ()) if part != "body") for error in exc.errors()]
    detail = meldung("invalid_input", "The input is not valid.", fields=fields, request_id=_request_id(request))
    _refused(request, 422, "invalid_input")
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Every error answer names its request: the interface shows the id, the log has it in every line."""
    detail = exc.detail
    if isinstance(detail, dict):
        detail = {**detail, "request_id": _request_id(request)}
        _refused(request, exc.status_code, str(detail.get("code", "-")))
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=exc.headers)


app.add_exception_handler(Exception, unhandled_error)

for module in (
    system,
    about,
    auth,
    oidc,
    sources,
    icons,
    threads,
    rules,
    targets,
    ingress,
    backups,
    logs,
    api_keys,
    api_v1,
):
    app.include_router(module.router)


def _mount_frontend(target: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    if not index.exists():
        return
    if (dist / "assets").is_dir():
        target.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    root = dist.resolve()
    start_page = index.resolve()

    @target.get("/{path:path}", include_in_schema=False, response_model=None)
    def spa(path: str) -> FileResponse | JSONResponse:
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": meldung("not_found", "Not found.")})
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and root in candidate.parents and candidate != start_page:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


_mount_frontend(app, get_settings().frontend_dist)
