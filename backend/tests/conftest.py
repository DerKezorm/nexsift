"""Every test run gets its own empty data directory and cheap Argon2 parameters."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

_DATA = tempfile.mkdtemp(prefix="nexsift-tests-")
os.environ["NEXSIFT_DATA_DIR"] = _DATA
os.environ["NEXSIFT_DISABLE_BACKGROUND"] = "1"
os.environ["NEXSIFT_ARGON2_TIME"] = "1"
os.environ["NEXSIFT_ARGON2_MEMORY_KIB"] = "1024"
os.environ["NEXSIFT_ARGON2_PARALLELISM"] = "1"
os.environ["NEXSIFT_FRONTEND_DIST"] = os.path.join(_DATA, "no-frontend")
os.environ["NEXSIFT_COOKIE_SECURE"] = "off"
os.environ["NEXSIFT_PUBLIC_PORTS"] = "web=8490,gotify=8491,ntfy=8492,smtp=25,syslog=514"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.gateways import gotify, ntfy  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Account,
    ApiKey,
    AuthSession,
    Delivery,
    Event,
    Rule,
    Setting,
    Source,
    Target,
    Thread,
)
from app.security import brake  # noqa: E402
from app.services import ingest, push, strangers  # noqa: E402

UI = {"X-Requested-By": "nexsift"}
PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    init_db()
    with SessionLocal() as db:
        for model in (Delivery, Event, Thread, Rule, Target, Source, AuthSession, Account, Setting, ApiKey):
            db.execute(delete(model))
        db.commit()
    brake._fails.clear()
    ingest.counter.clear()
    push.reset_for_tests()
    push.transport_for_tests = None
    strangers.clear()
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client


@pytest.fixture
def gotify_client() -> Iterator[TestClient]:
    with TestClient(gotify, base_url="http://testserver:8001") as test_client:
        yield test_client


@pytest.fixture
def ntfy_client() -> Iterator[TestClient]:
    with TestClient(ntfy, base_url="http://testserver:8002") as test_client:
        yield test_client


@pytest.fixture
def operator(client: TestClient) -> dict:
    response = client.post(
        "/api/setup", json={"name": "admin", "password": PASSWORD, "email": "admin@example.com"}, headers=UI
    )
    assert response.status_code == 200, response.text
    return response.json()


def add_source(client: TestClient, preset: str, name: str = "", hostname: str = "") -> dict:
    response = client.post("/api/sources", json={"preset": preset, "name": name, "hostname": hostname}, headers=UI)
    assert response.status_code == 201, response.text
    return response.json()


def inbox(client: TestClient, view: str = "inbox") -> list[dict]:
    response = client.get(f"/api/threads?view={view}")
    assert response.status_code == 200, response.text
    return response.json()["items"]
