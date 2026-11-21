"""The mark and the icons are asked for again before use, and their addresses carry a version.

⚠️ Without a cache header a browser guesses how long it may keep a file. After a sister app's new mark, Chrome installed
the web app with the old icon from its own storage, even after uninstalling it; and a tab kept the old favicon although
the new one came with ``no-cache``, because the old entry from before still counted. Hence both: ``no-cache`` and ``?v=2``.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import FRESH, _mount_frontend
from app.services import icons

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
PUBLIC = FRONTEND / "public"


def _built(tmp_path: Path) -> TestClient:
    """A built frontend with made-up files, served the way the real one is."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>nexsift</title>", encoding="utf-8")
    for name in ("icon-192.png", "logo.svg", "sw.js", "manifest.webmanifest", "robots.txt"):
        (dist / name).write_bytes(b"made up")
    app = FastAPI()
    _mount_frontend(app, dist)
    return TestClient(app)


def test_the_mark_and_the_icons_are_asked_for_again(tmp_path: Path) -> None:
    client = _built(tmp_path)
    for address in ("/icon-192.png?v=2", "/logo.svg?v=2", "/sw.js", "/manifest.webmanifest"):
        answer = client.get(address)
        assert answer.status_code == 200, address
        assert answer.content == b"made up", address
        assert answer.headers["cache-control"] == "no-cache", address


def test_other_files_keep_what_they_had(tmp_path: Path) -> None:
    """Only the listed files: the header is no blanket over everything the build writes."""
    answer = _built(tmp_path).get("/robots.txt")
    assert answer.status_code == 200
    assert "cache-control" not in answer.headers


def test_every_file_at_the_top_of_public_is_asked_for_again() -> None:
    files = {path.name for path in PUBLIC.iterdir() if path.is_file()}
    assert files, "public/ has no files"
    assert files <= FRESH, sorted(files - FRESH)


def test_the_addresses_of_the_icons_carry_the_version() -> None:
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert '<link rel="icon" type="image/svg+xml" href="/logo.svg?v=2" />' in index
    assert '<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=2" />' in index
    manifest = json.loads((PUBLIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert [icon["src"] for icon in manifest["icons"]] == [
        "/icon-192.png?v=2",
        "/icon-512.png?v=2",
        "/icon-maskable-512.png?v=2",
    ]
    worker = (PUBLIC / "sw.js").read_text(encoding="utf-8")
    assert "icon: '/icon-192.png?v=2'" in worker and "badge: '/badge-96.png?v=2'" in worker
    # ntfy fetches the logo of a push from GitHub and keeps it; a new address is a new picture there too.
    assert icons.NEXSIFT_LOGO.endswith("/frontend/public/icon-192.png?v=2")
    assert icons.public_url("nexapps/nexsift").endswith("/bundled_icons/nexsift.png?v=2")


def test_the_icons_have_the_sizes_their_names_say() -> None:
    def size(name: str) -> tuple[int, int]:
        head = (PUBLIC / name).read_bytes()[:24]
        assert head[:8] == b"\x89PNG\r\n\x1a\n", name
        return struct.unpack(">II", head[16:24])

    assert size("icon-192.png") == (192, 192)
    assert size("icon-512.png") == size("icon-maskable-512.png") == (512, 512)
    assert size("apple-touch-icon.png") == (180, 180)
    assert size("badge-96.png") == (96, 96)
