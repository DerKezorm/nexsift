"""The main app: interface, API, the own webhook and the Discord path, and everything that runs in the
background (push worker, housekeeping, SMTP and syslog doors). The Gotify and ntfy doors are separate apps on
their own ports, see ``gateways.py``; ``serve.py`` starts all of them together."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, housekeeping, listeners
from .config import get_settings
from .db import SessionLocal, init_db
from .meldungen import meldung
from .middleware import RequestContextMiddleware, unhandled_error
from .routers import auth, ingress, oidc, rules, sources, system, targets, threads
from .services import bus, presets, push

logger = logging.getLogger("nexsift")


def _setup_logging() -> None:
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # The mail library talks a lot at INFO; only its warnings matter.
    logging.getLogger("mail.log").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _setup_logging()
    init_db()
    get_settings().resolved_secret_key()
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


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [".".join(str(part) for part in error.get("loc", ()) if part != "body") for error in exc.errors()]
    return JSONResponse(
        status_code=422, content={"detail": meldung("invalid_input", "The input is not valid.", fields=fields)}
    )


app.add_exception_handler(Exception, unhandled_error)

for module in (system, auth, oidc, sources, threads, rules, targets, ingress):
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
