"""The log routes: reading with filters, the level with its expiry, download, clear, the request id."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import SessionLocal
from app.services import logs, settings_service
from tests.conftest import UI, add_source

probe = logging.getLogger("nexsift.probe")


@pytest.fixture(autouse=True)
def normal_mode_afterwards() -> Iterator[None]:
    """The level is process-wide; whatever a test sets, the next one starts at normal."""
    yield
    logs.apply_mode(logs.DEFAULT_MODE)


def test_the_log_needs_a_signed_in_operator(client: TestClient, operator: dict) -> None:
    signed_out = TestClient(client.app, base_url="http://testserver")
    assert signed_out.get("/api/logs").status_code == 401
    assert signed_out.get("/api/logs/level").status_code == 401
    assert signed_out.put("/api/logs/level", json={"mode": "quiet"}, headers=UI).status_code == 401
    assert signed_out.get("/api/logs/download").status_code == 401
    assert signed_out.delete("/api/logs", headers=UI).status_code == 401
    assert client.delete("/api/logs").status_code == 403, "no CSRF header"
    assert client.get("/api/logs").status_code == 200


def test_the_file_lies_in_the_data_folder() -> None:
    assert logs.log_file() == get_settings().data_dir / "logs" / "nexsift.log"


def test_the_level_filter_includes_higher_levels(client: TestClient, operator: dict) -> None:
    probe.info("probe-levels info line")
    probe.warning("probe-levels warning line")
    probe.error("probe-levels error line")
    lines = client.get("/api/logs", params={"level": "WARNING", "search": "probe-levels"}).json()
    assert [line["level"] for line in lines] == ["ERROR", "WARNING"], "newest first, INFO left out"
    assert all(line["logger"] == "nexsift.probe" for line in lines)
    everything = client.get("/api/logs", params={"search": "probe-levels"}).json()
    assert [line["level"] for line in everything] == ["ERROR", "WARNING", "INFO"]
    assert client.get("/api/logs", params={"level": "LOUD"}).status_code == 422


def test_the_search_by_request_id_finds_the_lines_of_one_request(client: TestClient, operator: dict) -> None:
    created = client.post("/api/sources", json={"preset": "webhook", "name": "switch"}, headers=UI)
    assert created.status_code == 201, created.text
    request_id = created.headers["x-request-id"]
    lines = client.get("/api/logs", params={"search": request_id}).json()
    assert lines, "the request logged something"
    assert all(line["request_id"] == request_id for line in lines)
    assert all(line["user"] == "admin" for line in lines)
    assert any(line["message"].startswith("Source created") for line in lines)
    other = client.post("/api/sources", json={"preset": "webhook", "name": "router"}, headers=UI)
    assert other.headers["x-request-id"] != request_id
    assert all(
        line["request_id"] == request_id for line in client.get("/api/logs", params={"search": request_id}).json()
    )


def test_every_error_answer_names_its_request(client: TestClient, operator: dict) -> None:
    missing = client.get("/api/sources/999999")
    assert missing.status_code == 404
    assert missing.json()["detail"]["request_id"] == missing.headers["x-request-id"]
    invalid = client.put("/api/settings", json={"values": {"bundle_minutes": 0}}, headers=UI)
    assert invalid.json()["detail"]["request_id"] == invalid.headers["x-request-id"]
    shapeless = client.post("/api/sources", json={"preset": 3}, headers=UI)
    assert shapeless.status_code == 422
    assert shapeless.json()["detail"]["request_id"] == shapeless.headers["x-request-id"]
    # The id in the message finds the refusal in the log, with its code.
    for answer, code in ((missing, "not_found"), (invalid, "out_of_range"), (shapeless, "invalid_input")):
        lines = client.get("/api/logs", params={"search": answer.headers["x-request-id"]}).json()
        assert any(f"code={code}" in line["message"] and line["message"].startswith("Refused") for line in lines), code


def test_a_deep_level_with_a_duration_expires(client: TestClient, operator: dict) -> None:
    level = client.get("/api/logs/level").json()
    assert (level["mode"], level["until"], level["fixed_by_env"]) == ("normal", None, False)
    assert level["modes"] == ["quiet", "normal", "detailed", "trace"] and 30 in level["durations"]

    changed = client.put("/api/logs/level", json={"mode": "detailed", "minutes": 30}, headers=UI)
    assert changed.status_code == 200, changed.text
    assert changed.json()["mode"] == "detailed"
    until = datetime.fromisoformat(changed.json()["until"])
    assert timedelta(minutes=29) < until - datetime.now(UTC) < timedelta(minutes=31)
    assert logs.current_mode() == "detailed"
    assert client.put("/api/logs/level", json={"mode": "trace", "minutes": 7}, headers=UI).status_code == 422

    # Time passes: the stored end lies in the past.
    with SessionLocal() as db:
        settings_service.save(db, {"log_mode_until": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()})
    state = logs.state()
    assert (state.mode, state.until) == ("normal", None)
    assert logs.current_mode() == "normal"
    assert client.get("/api/logs/level").json()["mode"] == "normal"
    with SessionLocal() as db:
        assert settings_service.get(db, "log_mode") == "normal"
        assert settings_service.get(db, "log_mode_until") is None


def test_a_level_without_a_duration_stays(client: TestClient, operator: dict) -> None:
    changed = client.put("/api/logs/level", json={"mode": "quiet"}, headers=UI)
    assert changed.status_code == 200 and changed.json()["until"] is None
    assert logs.enforce_expiry() is False
    assert logs.state().mode == "quiet"


def test_the_stored_level_survives_a_restart(client: TestClient, operator: dict) -> None:
    client.put("/api/logs/level", json={"mode": "detailed", "minutes": 120}, headers=UI)
    logs.apply_mode(logs.DEFAULT_MODE)
    logs.apply_stored_mode()
    assert logs.current_mode() == "detailed"


def test_the_environment_overrides_and_locks_the_level(
    client: TestClient, operator: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "log_level", "DEBUG")
    level = client.get("/api/logs/level").json()
    assert (level["mode"], level["fixed_by_env"]) == ("detailed", True)
    refused = client.put("/api/logs/level", json={"mode": "quiet"}, headers=UI)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "log_level_from_environment"
    monkeypatch.setattr(get_settings(), "log_level", "")
    assert logs.env_mode() is None, "empty means the interface decides"


def test_each_level_lets_through_what_it_promises(client: TestClient, operator: dict) -> None:
    content = logging.getLogger(logs.CONTENT_LOGGER)
    expected = {
        "quiet": (False, False, False),
        "normal": (True, False, False),
        "detailed": (True, True, False),
        "trace": (True, True, True),
    }
    for mode, (info, debug, said) in expected.items():
        logs.apply_mode(mode)
        assert probe.isEnabledFor(logging.INFO) is info, mode
        assert probe.isEnabledFor(logging.DEBUG) is debug, mode
        assert content.isEnabledFor(logging.DEBUG) is said, mode
        for sealed in logs.SEALED_LOGGERS:
            assert not logging.getLogger(sealed).isEnabledFor(logging.INFO), (mode, sealed)


def test_the_download_includes_rotated_files(client: TestClient, operator: dict) -> None:
    probe.warning("probe-download current line")
    rotated = logs.log_dir() / "nexsift.log.1"
    rotated.write_text("2026-09-01 03:00:00 INFO     nexsift.probe [-] | probe-download older line\n", encoding="utf-8")
    try:
        response = client.get("/api/logs/download")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert 'filename="nexsift-log-' in response.headers["content-disposition"]
        text = response.text
        assert "===== nexsift.log.1 =====" in text and "probe-download older line" in text
        assert "===== nexsift.log =====" in text and "probe-download current line" in text
        assert text.index("nexsift.log.1 =====") < text.index("===== nexsift.log ====="), "oldest first"
    finally:
        rotated.unlink(missing_ok=True)


def test_clear_empties_the_file_and_removes_rotated_ones(client: TestClient, operator: dict) -> None:
    probe.warning("probe-clear marker line")
    rotated = logs.log_dir() / "nexsift.log.2"
    rotated.write_text("older\n", encoding="utf-8")
    assert client.get("/api/logs", params={"search": "probe-clear"}).json()
    assert client.delete("/api/logs", headers=UI).status_code == 204
    assert not rotated.exists()
    text = logs.log_file().read_text(encoding="utf-8")
    assert "probe-clear marker line" not in text
    assert client.get("/api/logs", params={"search": "probe-clear"}).json() == []
    assert any(line["message"] == "Log cleared by operator" for line in client.get("/api/logs").json())
    probe.warning("probe-clear after line")
    assert "probe-clear after line" in logs.log_file().read_text(encoding="utf-8")


def test_old_rotated_files_are_purged(client: TestClient, operator: dict) -> None:
    import os
    import time

    old = logs.log_dir() / "nexsift.log.3"
    old.write_text("old\n", encoding="utf-8")
    then = time.time() - (logs.RETENTION_DAYS + 1) * 86400
    os.utime(old, (then, then))
    fresh = logs.log_dir() / "nexsift.log.2"
    fresh.write_text("fresh\n", encoding="utf-8")
    try:
        assert logs.purge_old() == 1
        assert not old.exists() and fresh.exists()
    finally:
        fresh.unlink(missing_ok=True)


def test_a_source_change_is_logged_with_name_and_door(client: TestClient, operator: dict) -> None:
    source = add_source(client, "gotify", "Watchtower")
    lines = client.get("/api/logs", params={"search": "Source created"}).json()
    assert any("name=Watchtower kind=generic door=gotify" in line["message"] for line in lines)
    assert client.delete(f"/api/sources/{source['id']}", headers=UI).status_code == 204
    assert any("Source deleted" in line["message"] for line in client.get("/api/logs").json())
