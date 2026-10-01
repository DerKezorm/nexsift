"""Backups: made through SQLite's backup API, listed, pruned, archived with a password, checked and restored at
the next start."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shutil
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pyzipper
from fastapi.testclient import TestClient

from app import __version__
from app.config import get_settings
from app.services import backups
from tests.conftest import UI, add_source

ARCHIVE_PASSWORD = "archive-pass-1234"
COUNTS = {"sources": 2, "rules": 3, "targets": 1, "threads": 4, "events": 5}


# --- Places ---------------------------------------------------------------------------------------------------- #


@pytest.fixture
def place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A data folder of its own with a key file, so restoring never touches the database of the test run."""
    settings = get_settings().model_copy(update={"data_dir": tmp_path, "secret_key": ""})
    settings._remembered_key = "key-of-then"
    (tmp_path / "secret.key").write_text("key-of-then", encoding="utf-8")
    monkeypatch.setattr(backups, "get_settings", lambda: settings)
    monkeypatch.setattr(backups, "restored_at_start", False)
    return settings


@pytest.fixture
def clean_folder():
    """The backup folder of the test run, empty before and after."""
    shutil.rmtree(backups.folder(), ignore_errors=True)
    yield backups.folder()
    shutil.rmtree(backups.folder(), ignore_errors=True)


def database(path: Path, marker: str, **counts: int) -> None:
    wanted = {**COUNTS, **counts}
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    for table, number in wanted.items():
        connection.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed names from COUNTS
        rows = [(f"{table}{i}",) for i in range(number)]
        connection.executemany(f"INSERT INTO {table} (name) VALUES (?)", rows)  # noqa: S608
    connection.execute("INSERT OR REPLACE INTO settings VALUES ('marker', ?)", (marker,))
    connection.commit()
    connection.close()


def marker(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT value FROM settings WHERE key = 'marker'").fetchone()[0]
    finally:
        connection.close()


def made(place, marker_value: str = "then", **changes) -> Path:
    source = place.data_dir / "source.db"
    database(source, marker_value)
    return backups.create(source=source, **changes)


def rewrite_manifest(copy: Path, **changes) -> None:
    manifest = json.loads(copy.with_suffix(".json").read_text(encoding="utf-8"))
    manifest.update(changes)
    copy.with_suffix(".json").write_text(json.dumps(manifest), encoding="utf-8")


# --- Making and listing ---------------------------------------------------------------------------------------- #


def test_a_copy_takes_what_still_sits_in_the_wal_and_says_what_it_is(place) -> None:
    """A file copy of a WAL database misses the rows not yet checkpointed; the backup API does not."""
    source = place.data_dir / "source.db"
    database(source, "checkpointed")
    writer = sqlite3.connect(source)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("UPDATE settings SET value='in the wal' WHERE key='marker'")
    writer.commit()
    try:
        assert source.with_name("source.db-wal").stat().st_size > 0
        copy = backups.create(source=source, note="Before the new rules")
    finally:
        writer.close()
    assert copy.parent == place.data_dir / "backups"
    assert re.fullmatch(r"nexsift-\d{4}-\d{2}-\d{2}-\d{6}(-\d+)?\.db", copy.name)
    assert marker(copy) == "in the wal"
    checked = sqlite3.connect(copy)
    try:
        assert checked.execute("PRAGMA journal_mode").fetchone()[0] == "delete", "one self-contained file"
    finally:
        checked.close()
    manifest = json.loads(copy.with_suffix(".json").read_text(encoding="utf-8"))
    assert manifest["version"] == __version__
    assert (manifest["kind"], manifest["note"]) == ("manual", "Before the new rules")
    assert {name: manifest[name] for name in COUNTS} == COUNTS
    assert manifest["schema"].startswith("sha256:")
    assert datetime.fromisoformat(manifest["created"]) > datetime.now(UTC) - timedelta(minutes=1)


def test_the_list_is_newest_first_and_says_whether_a_copy_is_compatible(place) -> None:
    older = made(place, kind=backups.SCHEDULED)
    newer = made(place, note="by hand")
    rewrite_manifest(older, created="2026-09-01T03:00:00+00:00")
    rewrite_manifest(newer, created="2026-09-02T03:00:00+00:00")
    stranger = place.data_dir / "backups" / "nexsift-2026-09-03-030000.db"
    shutil.copyfile(newer, stranger)
    entries = backups.entries()
    assert [entry.name for entry in entries][1:] == [newer.name, older.name]
    assert [entry.kind for entry in entries] == ["manual", "manual", "scheduled"]
    without_manifest = entries[0]
    assert (without_manifest.version, without_manifest.compatible, without_manifest.reason) == (
        "",
        False,
        "unknown_version",
    )
    assert (entries[1].compatible, entries[1].reason, entries[1].note) == (True, "ok", "by hand")
    assert entries[1].size == newer.stat().st_size


def test_a_copy_of_a_newer_version_is_listed_but_not_compatible(place) -> None:
    copy = made(place)
    rewrite_manifest(copy, version="9.0.0")
    (entry,) = backups.entries()
    assert (entry.compatible, entry.reason) == (False, "backup_newer")
    assert backups.compatible("") == (False, "unknown_version")
    assert backups.compatible(__version__) == (True, "ok")
    assert backups.compatible("0.0.1") == (True, "ok")


def test_only_automatic_copies_are_pruned(place) -> None:
    by_hand = made(place, note="keep me")
    kinds = (backups.SCHEDULED, backups.UPDATE, backups.SCHEDULED, backups.UPDATE)
    automatic = [made(place, kind=kind) for kind in kinds]
    for index, copy in enumerate([by_hand, *automatic]):
        rewrite_manifest(copy, created=f"2026-09-0{index + 1}T03:00:00+00:00")
    assert backups.prune(2) == 2
    left = {entry.name for entry in backups.entries()}
    assert left == {by_hand.name, automatic[2].name, automatic[3].name}
    assert not automatic[0].exists() and not automatic[0].with_suffix(".json").exists()


def test_a_name_that_could_lead_out_of_the_folder_is_refused(place) -> None:
    copy = made(place)
    assert backups.path_of(copy.name) == copy
    for name in ("../nexsift.db", "nexsift-..\\x.db", "secret.key", "nexsift-2026-01-01-000000.db", "x/" + copy.name):
        with pytest.raises(backups.BackupError) as caught:
            backups.path_of(name)
        assert caught.value.code == "backup_not_found"


# --- The schedule ---------------------------------------------------------------------------------------------- #


def at(hour: int, day: int = 24) -> datetime:
    return datetime(2026, 9, day, hour, 30, tzinfo=UTC)


def test_the_first_scheduled_copy_comes_at_night_or_a_day_after_waiting_began(place) -> None:
    assert backups.due("daily", now=at(3))
    assert not backups.due("daily", now=at(14))
    assert not backups.due("daily", now=at(14), waiting_since=at(20, day=23))
    assert backups.due("daily", now=at(14), waiting_since=at(13, day=23))
    assert not backups.due("off", now=at(3))


def test_a_daily_copy_waits_its_day_and_catches_up_a_day_late(place) -> None:
    copy = made(place, kind=backups.SCHEDULED)
    rewrite_manifest(copy, created=at(3, day=17).isoformat())
    assert not backups.due("daily", now=at(1, day=18))
    assert backups.due("daily", now=at(3, day=18))
    assert not backups.due("daily", now=at(14, day=18))
    assert backups.due("daily", now=at(14, day=19))
    assert backups.due("weekly", now=at(3, day=24))
    assert not backups.due("weekly", now=at(3, day=23))
    assert not backups.due("monthly", now=at(3, day=30))


def test_the_schedule_is_daily_and_keeps_seven_unless_the_operator_says_otherwise() -> None:
    from app.db import SessionLocal
    from app.services import settings_service

    with SessionLocal() as db:
        assert (backups.schedule(db), backups.keep(db)) == ("daily", 7)
        settings_service.save(db, {"backup_schedule": "weekly", "backup_keep": 3})
        assert (backups.schedule(db), backups.keep(db)) == ("weekly", 3)
        settings_service.save(db, {"backup_schedule": "hourly", "backup_keep": "many"})
        assert (backups.schedule(db), backups.keep(db)) == ("daily", 7)


def test_the_job_notes_since_when_it_waits_and_makes_the_copy(
    clean_folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db import SessionLocal
    from app.services import settings_service

    made_copies: list[str] = []
    monkeypatch.setattr(backups, "create", lambda **kwargs: made_copies.append(kwargs["kind"]))
    monkeypatch.setattr(backups, "due", lambda every, **kwargs: kwargs["waiting_since"] is not None)
    backups.run_job()
    assert made_copies == ["scheduled"]
    with SessionLocal() as db:
        stored = settings_service.get(db, backups.SETTING_WAITING)
    assert datetime.fromisoformat(stored) > datetime.now(UTC) - timedelta(minutes=5)


async def test_the_hourly_loop_runs_after_its_interval_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[float] = []
    monkeypatch.setattr(backups, "INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(backups, "run_job", lambda: runs.append(1))
    stop = asyncio.Event()
    task = asyncio.create_task(backups.run_forever(stop))
    await asyncio.sleep(0.01)
    assert runs == [], "the first look comes after the interval, not at the start"
    await asyncio.sleep(0.2)
    stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert len(runs) >= 1


# --- The archive ----------------------------------------------------------------------------------------------- #


def test_the_archive_needs_its_password_and_carries_key_and_manifest(place) -> None:
    copy = made(place, note="note")
    archive = backups.archive(copy.name, ARCHIVE_PASSWORD)
    try:
        assert archive.parent == place.data_dir / "backups" and archive.name.startswith(".archive-")
        assert [entry.name for entry in backups.entries()] == [copy.name], "temporary files are not listed"
        with pyzipper.AESZipFile(archive) as zipped:
            assert set(zipped.namelist()) == {"nexsift.db", "secret.key", "nexsift-backup.json"}
            assert zipped.getinfo("nexsift.db").wz_aes_strength == 3, "AES-256"
            with pytest.raises(RuntimeError):
                zipped.read("secret.key")
            zipped.setpassword(ARCHIVE_PASSWORD.encode())
            assert zipped.read("secret.key") == b"key-of-then"
            assert zipped.read("nexsift.db").startswith(b"SQLite format 3\x00")
            manifest = json.loads(zipped.read("nexsift-backup.json"))
        assert manifest["note"] == "note" and manifest["sources"] == 2
        with zipfile.ZipFile(archive) as plain, pytest.raises(RuntimeError, match="encrypted"):
            plain.read("secret.key")
        brief = backups.check(archive, ARCHIVE_PASSWORD)
        assert (brief.compatible, brief.reason, brief.key_in_archive, brief.key_from_env) == (True, "ok", True, False)
        assert (brief.counts, brief.note, brief.version) == (COUNTS, "note", __version__)
        with pytest.raises(backups.BackupError) as caught:
            backups.check(archive, "wrong-password")
        assert (caught.value.code, caught.value.status) == ("archive_wrong_password", 401)
    finally:
        archive.unlink()


def test_a_key_from_the_environment_is_named_not_packed(place) -> None:
    copy = made(place)
    place.secret_key = "from-the-environment"
    archive = backups.archive(copy.name, ARCHIVE_PASSWORD)
    try:
        with pyzipper.AESZipFile(archive) as zipped:
            assert "secret.key" not in zipped.namelist()
            zipped.setpassword(ARCHIVE_PASSWORD.encode())
            assert b"NEXSIFT_SECRET_KEY" in zipped.read(backups.NO_KEY_FILE)
        brief = backups.check(archive, ARCHIVE_PASSWORD)
        assert (brief.key_in_archive, brief.key_from_env) == (False, True)
    finally:
        archive.unlink()


def test_a_short_password_is_refused(place) -> None:
    copy = made(place)
    with pytest.raises(backups.BackupError) as caught:
        backups.archive(copy.name, "elevenchars")
    assert (caught.value.code, caught.value.status) == ("password_too_short", 422)
    assert not [item for item in (place.data_dir / "backups").iterdir() if item.name.startswith(".archive-")]


def zipped_file(path: Path, members: dict[str, bytes], password: str = ARCHIVE_PASSWORD) -> Path:
    with pyzipper.AESZipFile(path, "w", encryption=pyzipper.WZ_AES) as zipped:
        zipped.setpassword(password.encode())
        for name, content in members.items():
            zipped.writestr(name, content)
    return path


def manifest_bytes(version: str = __version__, kind: str = "manual", **changes) -> bytes:
    document = {
        "version": version,
        "schema": "",
        "kind": kind,
        "note": "from elsewhere",
        "created": "2026-09-24T03:00:00+00:00",
        **COUNTS,
        **changes,
    }
    return json.dumps(document).encode()


def sqlite_bytes(tmp_path: Path, marker_value: str) -> bytes:
    path = tmp_path / f"{marker_value}.db"
    database(path, marker_value)
    return path.read_bytes()


@pytest.mark.parametrize(
    "members",
    [
        None,
        {"nexsift.db": b"x"},
        {"nexsift.db": b"not a database at all", "nexsift-backup.json": b"{}"},
        {"nexsift.db": b"SQLite format 3\x00rest", "nexsift-backup.json": b"not json"},
        {"nexsift.db": b"SQLite format 3\x00rest", "nexsift-backup.json": b'{"version": 3}'},
        {"nexsift.db": b"SQLite format 3\x00rest", "nexsift-backup.json": manifest_bytes(sources="many")},
        {"nexsift.db": b"SQLite format 3\x00rest", "nexsift-backup.json": manifest_bytes(note="line\nbreak")},
        {"nextrmnl.db": b"SQLite format 3\x00rest", "nextrmnl-backup.json": manifest_bytes()},
    ],
)
def test_what_is_no_backup_is_named_invalid(tmp_path: Path, members) -> None:
    path = tmp_path / "upload.zip"
    if members is None:
        path.write_bytes(b"this is no zip")
    else:
        zipped_file(path, members)
    with pytest.raises(backups.BackupError) as caught:
        backups.check(path, ARCHIVE_PASSWORD)
    assert (caught.value.code, caught.value.status) == ("archive_invalid", 422)


# --- Restoring ------------------------------------------------------------------------------------------------- #


def test_a_restore_is_laid_out_with_a_copy_of_now_and_swapped_in_at_the_start(place) -> None:
    copy = made(place, marker_value="then")
    archive = backups.archive(copy.name, ARCHIVE_PASSWORD)
    # Afterwards the installation moves on.
    database(place.database_path, "now", sources=5)
    (place.data_dir / "secret.key").write_text("key-of-now", encoding="utf-8")
    place._remembered_key = "key-of-now"
    try:
        brief = backups.stage_restore(archive, ARCHIVE_PASSWORD)
    finally:
        archive.unlink()
    assert brief.version == __version__ and brief.counts["sources"] == 2
    pending = place.data_dir / "backups" / backups.PENDING
    assert (pending / "nexsift-backup.json").is_file()
    assert (pending / "nexsift.db").is_file() and (pending / "secret.key").is_file()
    # Nothing is swapped before the start, and the copy of now is a listed update backup.
    assert marker(place.database_path) == "now"
    before = [entry for entry in backups.entries() if entry.note == "before restore"]
    assert len(before) == 1 and before[0].kind == "update"
    assert marker(place.data_dir / "backups" / before[0].name) == "now"
    # A side file of the old database would be read into the restored one.
    for suffix in ("-wal", "-shm", "-journal"):
        place.database_path.with_name("nexsift.db" + suffix).write_bytes(b"old frames")

    assert backups.apply_pending() is True
    # Before anything reads the database: SQLite itself would quietly drop side files it cannot use.
    for suffix in ("-wal", "-shm", "-journal"):
        assert not place.database_path.with_name("nexsift.db" + suffix).exists(), suffix
    assert backups.restored_at_start is True
    assert marker(place.database_path) == "then"
    assert (place.data_dir / "secret.key").read_text(encoding="utf-8") == "key-of-then"
    assert place.resolved_secret_key() == "key-of-then", "the process forgets the old key"
    assert not pending.exists()
    # A second start has nothing to do.
    assert backups.apply_pending() is False


def test_a_key_from_the_environment_wins_over_the_archive(place, tmp_path: Path) -> None:
    database(place.database_path, "now")
    pending = place.data_dir / "backups" / backups.PENDING
    pending.mkdir(parents=True)
    (pending / "nexsift.db").write_bytes(sqlite_bytes(tmp_path, "then"))
    (pending / "secret.key").write_text("key-of-then", encoding="utf-8")
    (pending / "nexsift-backup.json").write_bytes(manifest_bytes())
    (place.data_dir / "secret.key").write_text("key-of-now", encoding="utf-8")
    place.secret_key = "from-the-environment"
    assert backups.apply_pending() is True
    assert marker(place.database_path) == "then"
    assert (place.data_dir / "secret.key").read_text(encoding="utf-8") == "key-of-now"


@pytest.mark.parametrize("laid_out", [("nexsift.db",), ("nexsift-backup.json",), ()])
def test_a_half_written_restore_is_thrown_away(place, laid_out: tuple[str, ...]) -> None:
    database(place.database_path, "now")
    pending = place.data_dir / "backups" / backups.PENDING
    pending.mkdir(parents=True)
    for name in laid_out:
        (pending / name).write_bytes(b"half written")
    assert backups.apply_pending() is False
    assert not pending.exists()
    assert marker(place.database_path) == "now"


def test_a_newer_backup_is_refused_before_anything_is_laid_out(place, tmp_path: Path) -> None:
    database(place.database_path, "now")
    path = zipped_file(
        tmp_path / "newer.zip",
        {"nexsift.db": sqlite_bytes(tmp_path, "future"), "nexsift-backup.json": manifest_bytes("9.0.0")},
    )
    brief = backups.check(path, ARCHIVE_PASSWORD)
    assert (brief.compatible, brief.reason) == (False, "backup_newer")
    with pytest.raises(backups.BackupError) as caught:
        backups.stage_restore(path, ARCHIVE_PASSWORD)
    assert (caught.value.code, caught.value.status) == ("backup_newer", 409)
    assert not (place.data_dir / "backups" / backups.PENDING).exists()
    assert backups.entries() == [], "no copy of now either"


def test_a_backup_without_a_version_is_refused(place, tmp_path: Path) -> None:
    database(place.database_path, "now")
    path = zipped_file(
        tmp_path / "unknown.zip", {"nexsift.db": sqlite_bytes(tmp_path, "x"), "nexsift-backup.json": manifest_bytes("")}
    )
    with pytest.raises(backups.BackupError) as caught:
        backups.stage_restore(path, ARCHIVE_PASSWORD)
    assert caught.value.code == "unknown_version"


def test_stale_temporary_files_are_swept(place) -> None:
    base = place.data_dir / "backups"
    base.mkdir()
    old = base / ".upload-1-2.zip"
    fresh = base / ".archive-3-4.zip"
    old.write_bytes(b"x")
    fresh.write_bytes(b"x")
    now = old.stat().st_mtime + backups.TEMPORARY_MAX_AGE + 1
    os.utime(fresh, (now - 10, now - 10))
    assert backups.sweep_temporary(now) == 1
    assert not old.exists() and fresh.exists()


def test_the_process_ends_in_a_thread_after_the_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    class Ended(BaseException):
        """The real os._exit never returns; the fake must not either, or the thread runs on into the real one."""

    ended: list[object] = []
    done = threading.Event()

    def fake_exit(code: int) -> None:
        ended.append(("exit", code))
        done.set()
        raise Ended()

    def fake_kill(pid: int, sig: int) -> None:
        ended.append(("kill", pid, sig))
        done.set()
        raise Ended()

    monkeypatch.setattr(backups.os, "_exit", fake_exit)
    monkeypatch.setattr(backups.os, "kill", fake_kill)
    monkeypatch.setattr(backups, "restart_requested", False)
    monkeypatch.setattr(threading, "excepthook", lambda args: None)
    backups.restart_soon(delay=0.01)
    assert ended == [], "not before the answer went out"
    assert done.wait(2)
    assert backups.restart_requested is True, "serve ends with the restart code"
    if os.name == "nt":
        assert ended[0] == ("exit", backups.RESTART_CODE)
    else:
        assert ended[0] == ("kill", os.getpid(), backups.signal.SIGTERM)


# --- Through the API ------------------------------------------------------------------------------------------- #


def test_the_page_makes_lists_downloads_and_deletes(client: TestClient, operator: dict, clean_folder: Path) -> None:
    listed = client.get("/api/backups").json()
    assert listed["entries"] == [] and listed["schedule"] == "daily" and listed["keep"] == 7
    assert listed["folder"] == str(clean_folder)
    add_source(client, "webhook", "nexcrate")

    made_one = client.post("/api/backups", json={"note": "by hand"}, headers=UI)
    assert made_one.status_code == 201, made_one.text
    entry = made_one.json()
    assert (entry["kind"], entry["note"], entry["compatible"], entry["reason"]) == ("manual", "by hand", True, "ok")
    assert entry["version"] == __version__ and entry["size"] > 0
    assert set(entry) == {"name", "size", "created", "kind", "note", "version", "compatible", "reason"}

    # The manifest counts what the copy holds: one source, the rules its preset brought.
    manifest = json.loads((clean_folder / entry["name"]).with_suffix(".json").read_text(encoding="utf-8"))
    assert manifest["sources"] == 1 and manifest["targets"] == 0

    backups.create(kind=backups.SCHEDULED)
    kinds = sorted(item["kind"] for item in client.get("/api/backups").json()["entries"])
    assert kinds == ["auto", "manual"]

    download = client.post(f"/api/backups/{entry['name']}/archive", json={"password": ARCHIVE_PASSWORD}, headers=UI)
    assert download.status_code == 200, download.text
    assert download.headers["content-type"] == "application/zip"
    assert entry["name"].removesuffix(".db") + ".zip" in download.headers["content-disposition"]
    with pyzipper.AESZipFile(io.BytesIO(download.content)) as zipped:
        zipped.setpassword(ARCHIVE_PASSWORD.encode())
        assert zipped.read("nexsift.db").startswith(b"SQLite format 3\x00")
        assert zipped.read("secret.key").decode() == get_settings().resolved_secret_key()
    assert not [item for item in clean_folder.iterdir() if item.name.startswith(".archive-")], "gone once sent"

    short = client.post(f"/api/backups/{entry['name']}/archive", json={"password": "short"}, headers=UI)
    assert short.status_code == 422 and short.json()["detail"]["code"] == "password_too_short"
    assert short.json()["detail"]["minimum"] == 12
    unknown = client.post(
        "/api/backups/nexsift-2000-01-01-000000.db/archive", json={"password": ARCHIVE_PASSWORD}, headers=UI
    )
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "backup_not_found"

    assert client.delete(f"/api/backups/{entry['name']}", headers=UI).status_code == 204
    missing = client.delete(f"/api/backups/{entry['name']}", headers=UI)
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "backup_not_found"
    assert client.delete("/api/backups/..%2Fnexsift.db", headers=UI).status_code == 404


def test_the_schedule_is_set_through_the_settings(client: TestClient, operator: dict) -> None:
    saved = client.put("/api/settings", json={"values": {"backup_schedule": "weekly", "backup_keep": 12}}, headers=UI)
    assert saved.status_code == 200, saved.text
    assert (saved.json()["backup_schedule"], saved.json()["backup_keep"]) == ("weekly", 12)
    listed = client.get("/api/backups").json()
    assert (listed["schedule"], listed["keep"]) == ("weekly", 12)
    wrong = client.put("/api/settings", json={"values": {"backup_schedule": "hourly"}}, headers=UI)
    assert wrong.status_code == 422 and wrong.json()["detail"]["field"] == "backup_schedule"
    too_many = client.put("/api/settings", json={"values": {"backup_keep": 101}}, headers=UI)
    assert too_many.status_code == 422 and too_many.json()["detail"]["code"] == "out_of_range"


def test_an_uploaded_archive_is_checked_and_restored_with_a_restart(
    client: TestClient, operator: dict, clean_folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    restarts: list[int] = []
    # Never the real one: it would end the test run.
    monkeypatch.setattr(backups, "restart_soon", lambda: restarts.append(1))
    entry = client.post("/api/backups", json={"note": "to restore"}, headers=UI).json()
    archive = client.post(
        f"/api/backups/{entry['name']}/archive", json={"password": ARCHIVE_PASSWORD}, headers=UI
    ).content
    files = {"file": ("backup.zip", archive, "application/zip")}

    wrong = client.post("/api/backups/check", files=files, data={"password": "wrong-password"}, headers=UI)
    assert wrong.status_code == 401 and wrong.json()["detail"]["code"] == "archive_wrong_password"
    garbage = client.post("/api/backups/check", files={"file": ("x.zip", b"nope")}, data={"password": "x"}, headers=UI)
    assert garbage.status_code == 422 and garbage.json()["detail"]["code"] == "archive_invalid"

    checked = client.post("/api/backups/check", files=files, data={"password": ARCHIVE_PASSWORD}, headers=UI)
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert (body["note"], body["kind"], body["compatible"], body["reason"]) == ("to restore", "manual", True, "ok")
    assert body["version"] == __version__ and set(body["counts"]) == set(COUNTS)
    assert (body["key_in_archive"], body["key_from_env"]) == (True, False)
    assert restarts == []

    restored = client.post("/api/backups/restore", files=files, data={"password": ARCHIVE_PASSWORD}, headers=UI)
    assert restored.status_code == 202, restored.text
    assert restored.json()["restarting"] is True
    assert restarts == [1]
    pending = clean_folder / backups.PENDING
    assert (pending / "nexsift-backup.json").is_file() and (pending / "nexsift.db").is_file()
    assert not [item for item in clean_folder.iterdir() if item.name.startswith(".upload-")]
    before = [item for item in client.get("/api/backups").json()["entries"] if item["note"] == "before restore"]
    assert len(before) == 1 and before[0]["kind"] == "update"
    # Never applied inside the test run: the next start would swap the live database.
    shutil.rmtree(pending)


def test_a_newer_archive_is_refused_through_the_api(
    client: TestClient, operator: dict, clean_folder: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    restarts: list[int] = []
    monkeypatch.setattr(backups, "restart_soon", lambda: restarts.append(1))
    archive = zipped_file(
        tmp_path / "newer.zip",
        {"nexsift.db": sqlite_bytes(tmp_path, "future"), "nexsift-backup.json": manifest_bytes("9.0.0")},
    ).read_bytes()
    files = {"file": ("backup.zip", archive, "application/zip")}
    checked = client.post("/api/backups/check", files=files, data={"password": ARCHIVE_PASSWORD}, headers=UI)
    assert checked.status_code == 200
    assert (checked.json()["compatible"], checked.json()["reason"]) == (False, "backup_newer")
    refused = client.post("/api/backups/restore", files=files, data={"password": ARCHIVE_PASSWORD}, headers=UI)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "backup_newer"
    assert refused.json()["detail"]["request_id"] == refused.headers["x-request-id"]
    assert restarts == [] and not (clean_folder / backups.PENDING).exists()
    assert client.get("/api/backups").json()["entries"] == [], "no copy of now either"


def test_backups_need_a_signed_in_operator(client: TestClient, operator: dict, clean_folder: Path) -> None:
    assert client.post("/api/backups", json={"note": "x"}).status_code == 403, "no CSRF header"
    signed_out = TestClient(client.app, base_url="http://testserver")
    assert signed_out.get("/api/backups").status_code == 401
    assert signed_out.post("/api/backups", json={"note": "x"}, headers=UI).status_code == 401
    check = signed_out.post("/api/backups/check", files={"file": ("x.zip", b"x")}, data={"password": "x"}, headers=UI)
    assert check.status_code == 401
    assert (
        signed_out.post(
            "/api/backups/restore", files={"file": ("x.zip", b"x")}, data={"password": "x"}, headers=UI
        ).status_code
        == 401
    )


# --- The copy before a schema change --------------------------------------------------------------------------- #


def test_the_copy_before_a_schema_change_is_made_once_and_only_then(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import db as database_module

    made_copies: list[dict] = []
    monkeypatch.setattr(backups, "create", lambda **kwargs: made_copies.append(kwargs))
    database_module.init_db()
    assert made_copies == [], "nothing to add, nothing to back up"

    connection = sqlite3.connect(get_settings().database_path)
    try:
        connection.execute("ALTER TABLE targets DROP COLUMN last_error")
        connection.commit()
    finally:
        connection.close()
    database_module._add_missing_columns()
    assert len(made_copies) == 1 and made_copies[0]["kind"] == "update"
    connection = sqlite3.connect(get_settings().database_path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(targets)")}
    finally:
        connection.close()
    assert "last_error" in columns


def test_a_new_table_is_a_schema_change_too(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import db as database_module

    made_copies: list[dict] = []
    monkeypatch.setattr(backups, "create", lambda **kwargs: made_copies.append(kwargs))
    connection = sqlite3.connect(get_settings().database_path)
    try:
        connection.execute("DROP TABLE api_keys")
        connection.commit()
    finally:
        connection.close()
    database_module.init_db()
    assert len(made_copies) == 1 and made_copies[0]["note"] == "before schema change"
    database_module.init_db()
    assert len(made_copies) == 1, "once the table is there, nothing more"
