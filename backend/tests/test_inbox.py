"""Bundling, rules, throttling, and the actions on threads."""

from datetime import timedelta

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Thread
from tests.conftest import UI, add_source, inbox


def _hook(client: TestClient, source: dict):
    path = "/api/v1/hook/" + source["connection"]["token"]
    return lambda **body: client.post(path, json=body)


def test_same_warning_bundles_into_one_thread(client: TestClient, operator: dict) -> None:
    send = _hook(client, add_source(client, "webhook"))
    send(title="Disk sda at 91 %", priority="warning")
    send(title="Disk sda at 92 %", priority="warning")
    send(title="Something else", priority="warning")
    threads = inbox(client)
    assert len(threads) == 2
    bundled = next(thread for thread in threads if thread["event_count"] == 2)
    assert bundled["title"] == "Disk sda at 92 %"


def test_a_sources_routine_bundles_into_one_line_whatever_the_titles(client: TestClient, operator: dict) -> None:
    """No knowledge of the sender needed: its info messages share one line, problems keep their own."""
    send = _hook(client, add_source(client, "webhook"))
    send(title="Download started", body="Film A")
    send(title="Upgraded", body="Film B")
    send(title="Title added", body="Film C")
    send(title="Download failed", priority="critical")
    threads = inbox(client)
    assert len(threads) == 2
    routine = next(thread for thread in threads if thread["event_count"] == 3)
    assert routine["routine"] is True
    assert routine["preview"] == "Title added: Film C"
    problem = next(thread for thread in threads if thread["priority"] == "crit")
    assert problem["routine"] is False
    assert problem["title"] == "Download failed"


def test_a_single_routine_message_is_shown_as_itself(client: TestClient, operator: dict) -> None:
    send = _hook(client, add_source(client, "webhook"))
    send(title="Download started", body="Film A")
    (thread,) = inbox(client)
    assert thread["routine"] is False
    assert thread["preview"] == "Film A"


def test_bundle_window_ends(client: TestClient, operator: dict) -> None:
    send = _hook(client, add_source(client, "webhook"))
    send(title="Nightly job ran")
    with SessionLocal() as db:
        thread = db.query(Thread).one()
        thread.last_at = thread.last_at - timedelta(minutes=16)
        db.commit()
    send(title="Nightly job ran")
    assert len(inbox(client)) == 2


def test_an_unresolved_critical_problem_stays_one_line(client: TestClient, operator: dict) -> None:
    send = _hook(client, add_source(client, "webhook"))
    send(title="VM 104 stopped", priority="critical")
    with SessionLocal() as db:
        thread = db.query(Thread).one()
        thread.last_at = thread.last_at - timedelta(hours=5)
        db.commit()
    send(title="VM 104 stopped", priority="critical")
    [thread] = inbox(client)
    assert thread["event_count"] == 2


def test_archived_thread_is_not_reopened(client: TestClient, operator: dict) -> None:
    send = _hook(client, add_source(client, "webhook"))
    send(title="Update available")
    [thread] = inbox(client)
    client.post("/api/threads/state", json={"ids": [thread["id"]], "state": "archived"}, headers=UI)
    send(title="Update available")
    assert len(inbox(client)) == 1
    assert len(inbox(client, "archived")) == 1


def test_new_event_makes_a_read_thread_unread(client: TestClient, operator: dict) -> None:
    send = _hook(client, add_source(client, "webhook"))
    send(title="Temperature high")
    [thread] = inbox(client)
    client.post("/api/threads/state", json={"ids": [thread["id"]], "state": "read"}, headers=UI)
    send(title="Temperature high")
    assert inbox(client)[0]["state"] == "unread"


def test_keyword_rules_respect_word_boundaries(client: TestClient, operator: dict) -> None:
    send = _hook(client, add_source(client, "webhook"))
    send(title="Backup finished with 0 errors")
    send(title="Backup ERROR on disk 2")
    priorities = {thread["title"]: thread["priority"] for thread in inbox(client)}
    assert priorities == {"Backup finished with 0 errors": "info", "Backup ERROR on disk 2": "crit"}


def test_rule_can_drop_group_and_rename(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook")
    send = _hook(client, source)
    drop = {
        "name": "Ignore DHCP",
        "source_id": source["id"],
        "conditions": [{"field": "any", "op": "contains", "value": "DHCPACK"}],
        "actions": {"drop": True},
    }
    group = {
        "name": "Logins together",
        "conditions": [{"field": "title", "op": "regex", "value": r"login from \S+"}],
        "actions": {"group_key": "logins", "title_template": "{count} logins"},
    }
    assert client.post("/api/rules", json=drop, headers=UI).status_code == 201
    assert client.post("/api/rules", json=group, headers=UI).status_code == 201
    send(title="DHCPACK on eth0")
    send(title="login from alice")
    send(title="login from bob")
    [thread] = inbox(client)
    assert thread["title"] == "2 logins"


def test_rule_validation_explains_itself(client: TestClient, operator: dict) -> None:
    bad = {
        "name": "x",
        "conditions": [{"field": "title", "op": "regex", "value": "(unclosed"}],
        "actions": {"priority": "crit"},
    }
    response = client.post("/api/rules", json=bad, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "rule_regex"
    none = {"name": "x", "conditions": [{"field": "title", "op": "word", "value": "a"}], "actions": {}}
    assert client.post("/api/rules", json=none, headers=UI).json()["detail"]["code"] == "rule_no_action"


def test_try_shows_what_would_happen(client: TestClient, operator: dict) -> None:
    result = client.post("/api/rules/try", json={"title": "Pool DEGRADED", "body": ""}, headers=UI).json()
    assert result["matched"] == ["Words for trouble make it a warning"]
    assert result["actions"] == {"priority": "warn"}


def test_rule_order_decides(client: TestClient, operator: dict) -> None:
    rules = client.get("/api/rules").json()
    ids = [rule["id"] for rule in rules]
    response = client.put("/api/rules/order", json={"ids": list(reversed(ids))}, headers=UI)
    assert [rule["id"] for rule in response.json()] == list(reversed(ids))
    assert client.put("/api/rules/order", json={"ids": ids[:1]}, headers=UI).status_code == 422


def test_throttle_counts_instead_of_storing(client: TestClient, operator: dict) -> None:
    client.put("/api/settings", json={"values": {"throttle_per_minute": 3}}, headers=UI)
    send = _hook(client, add_source(client, "webhook"))
    for number in range(10):
        send(title=f"loop {number}")
    [thread] = inbox(client)
    assert thread["event_count"] == 3
    assert thread["throttled_count"] == 7


def test_delete_can_be_undone(client: TestClient, operator: dict) -> None:
    send = _hook(client, add_source(client, "webhook"))
    send(title="oops")
    [thread] = inbox(client)
    assert client.delete(f"/api/threads/{thread['id']}", headers=UI).status_code == 204
    assert inbox(client) == []
    assert client.post(f"/api/threads/{thread['id']}/restore", headers=UI).status_code == 200
    assert len(inbox(client)) == 1


def _changed(client: TestClient, action: str, **payload) -> list[int]:
    response = client.post(f"/api/threads/{action}", json=payload, headers=UI)
    assert response.status_code == 200, response.text
    return sorted(response.json()["changed"])


def test_a_problem_can_be_closed_by_hand_and_opened_again(client: TestClient, operator: dict) -> None:
    send = _hook(client, add_source(client, "webhook"))
    send(title="Container gotify stopped", priority="critical")
    [thread] = inbox(client, "crit")
    assert _changed(client, "resolve", ids=[thread["id"]]) == [thread["id"]]
    assert inbox(client, "crit") == []
    [closed] = inbox(client)
    assert closed["resolved_at"] and closed["resolved_by"] == "Marked as done by hand"
    # The same problem again is a new problem, not a note on the closed one.
    send(title="Container gotify stopped", priority="critical")
    assert len(inbox(client, "crit")) == 1
    assert _changed(client, "reopen", ids=[thread["id"]]) == [thread["id"]]
    assert len(inbox(client, "crit")) == 2


def test_reopening_leaves_an_all_clear_from_the_sender_alone(client: TestClient, operator: dict) -> None:
    send = _hook(client, add_source(client, "webhook"))
    send(title="Pool FAILED", priority="critical")
    [thread] = inbox(client, "crit")
    with SessionLocal() as db:
        row = db.get(Thread, thread["id"])
        row.resolved_at = row.last_at
        row.resolved_by = "Pool ONLINE"
        db.commit()
    assert _changed(client, "resolve", ids=[thread["id"]]) == []
    assert _changed(client, "reopen", ids=[thread["id"]]) == []
    assert inbox(client)[0]["resolved_by"] == "Pool ONLINE"


def test_close_everything_critical_of_one_source(client: TestClient, operator: dict) -> None:
    nas = _hook(client, add_source(client, "webhook", name="NAS"))
    pve = _hook(client, add_source(client, "webhook", name="PVE"))
    nas(title="Container a stopped", priority="critical")
    nas(title="Container b stopped", priority="critical")
    nas(title="Disk warm", priority="warning")
    pve(title="VM 104 stopped", priority="critical")
    nas_id = next(thread["source_id"] for thread in inbox(client) if thread["title"] == "Disk warm")
    assert len(_changed(client, "resolve-all", source_id=nas_id)) == 2
    assert [thread["title"] for thread in inbox(client, "crit")] == ["VM 104 stopped"]
    assert next(thread for thread in inbox(client) if thread["title"] == "Disk warm")["resolved_at"] is None
    assert len(_changed(client, "resolve-all")) == 1
    assert inbox(client, "crit") == []


def test_several_can_be_deleted_and_restored_at_once(client: TestClient, operator: dict) -> None:
    send = _hook(client, add_source(client, "webhook"))
    for title in ("one", "two", "three"):
        send(title=title, priority="warning")
    ids = [thread["id"] for thread in inbox(client)]
    assert _changed(client, "delete", ids=ids[:2]) == sorted(ids[:2])
    assert [thread["id"] for thread in inbox(client)] == ids[2:]
    assert _changed(client, "restore", ids=ids) == sorted(ids[:2])
    assert len(inbox(client)) == 3


def test_views_counts_search_and_read_all(client: TestClient, operator: dict) -> None:
    send = _hook(client, add_source(client, "webhook"))
    send(title="Pool FAILED", message="zpool tank")
    send(title="Weekly report", message="all fine")
    counts = client.get("/api/threads/counts").json()["views"]
    assert counts == {"inbox": 2, "unread": 2, "crit": 1, "archived": 0}
    found = client.get("/api/threads?q=tank").json()["items"]
    assert [thread["title"] for thread in found] == ["Pool FAILED"]
    assert client.post("/api/threads/read-all", json={"view": "inbox"}, headers=UI).json()["changed"] == 2
    assert client.get("/api/threads/counts").json()["views"]["unread"] == 0


def test_settings_bounds(client: TestClient, operator: dict) -> None:
    response = client.put("/api/settings", json={"values": {"bundle_minutes": 0}}, headers=UI)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "out_of_range"
    assert client.put("/api/settings", json={"values": {"nope": 1}}, headers=UI).status_code == 422
    ok = client.put(
        "/api/settings",
        json={"values": {"bundle_minutes": 30, "public_url": "https://nexsift.example.com/"}},
        headers=UI,
    )
    assert ok.json()["public_url"] == "https://nexsift.example.com"


def test_same_kind_at_the_same_instant_still_bundles(client: TestClient, operator: dict) -> None:
    import threading

    from app.adapters.base import Incoming
    from app.db import SessionLocal
    from app.models import Source
    from app.services import ingest

    source_id = add_source(client, "webhook")["id"]

    def send() -> None:
        with SessionLocal() as db:
            ingest.accept(db, db.get(Source, source_id), Incoming(title="Same thing"), {})

    workers = [threading.Thread(target=send) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    [thread] = inbox(client)
    assert thread["event_count"] == 8


def test_a_single_event_keeps_its_own_title(client: TestClient, operator: dict) -> None:
    from tests.conftest import add_source as add

    source = add(client, "paperless")
    path = "/api/v1/hook/" + source["connection"]["token"]
    client.post(path, json={"title": "New document: Invoice"})
    assert inbox(client)[0]["title"] == "New document: Invoice"
    client.post(path, json={"title": "New document: Letter"})
    assert inbox(client)[0]["title"] == "Paperless: 2 new documents"


def test_the_source_counter_survives_messages_at_the_same_instant(client: TestClient, operator: dict) -> None:
    import threading

    from app.adapters.base import Incoming
    from app.db import SessionLocal
    from app.models import Source
    from app.services import ingest

    source_id = add_source(client, "webhook")["id"]
    ready = threading.Barrier(6)

    def send(number: int) -> None:
        with SessionLocal() as db:
            source = db.get(Source, source_id)  # loaded before the lock, like the doors do
            ready.wait()
            ingest.accept(db, source, Incoming(title=f"message {chr(97 + number)}"), {})

    workers = [threading.Thread(target=send, args=(number,)) for number in range(6)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert client.get(f"/api/sources/{source_id}").json()["count_total"] == 6


def test_a_deleted_built_in_rule_stays_deleted_after_a_restart(client: TestClient, operator: dict) -> None:
    """The built-in rules are handed out at every start; one the operator deleted must not come back."""
    from app.services import presets

    rules = client.get("/api/rules").json()
    keyword = next(rule for rule in rules if rule["built_in"] == "keywords-critical")
    assert client.delete(f"/api/rules/{keyword['id']}", headers=UI).status_code == 204
    with SessionLocal() as db:
        presets.install_defaults(db)
    assert all(rule["built_in"] != "keywords-critical" for rule in client.get("/api/rules").json())
    assert any(rule["built_in"] == "keywords-warning" for rule in client.get("/api/rules").json())


def test_german_failure_words_make_it_critical_but_not_fehler(client: TestClient, operator: dict) -> None:
    send = _hook(client, add_source(client, "webhook"))
    send(title="Sicherung fehlgeschlagen")
    send(title="Datensicherung abgeschlossen", message="0 Fehler")
    priorities = {thread["title"]: thread["priority"] for thread in inbox(client)}
    assert priorities["Sicherung fehlgeschlagen"] == "crit"
    assert priorities["Datensicherung abgeschlossen"] == "info"


def test_untouched_built_in_rules_get_the_new_words_edited_ones_keep_theirs(client: TestClient, operator: dict) -> None:
    from app.models import Rule
    from app.services import presets

    with SessionLocal() as db:
        critical = db.query(Rule).filter(Rule.built_in == "keywords-critical").one()
        critical.conditions = presets.PREVIOUS_CONDITIONS["keywords-critical"][0]
        warning = db.query(Rule).filter(Rule.built_in == "keywords-warning").one()
        warning.conditions = [{"field": "any", "op": "word", "value": "WARN|MINE"}]
        db.commit()
        presets.install_defaults(db)
    with SessionLocal() as db:
        critical = db.query(Rule).filter(Rule.built_in == "keywords-critical").one()
        warning = db.query(Rule).filter(Rule.built_in == "keywords-warning").one()
        assert "FEHLGESCHLAGEN" in critical.conditions[0]["value"]
        assert warning.conditions[0]["value"] == "WARN|MINE"


def test_archive_all_of_a_view_and_back(client: TestClient, operator: dict) -> None:
    nas = _hook(client, add_source(client, "webhook", name="NAS"))
    pve = _hook(client, add_source(client, "webhook", name="PVE"))
    nas(title="Container a stopped", priority="critical")
    nas(title="Disk warm", priority="warning")
    pve(title="VM 104 stopped", priority="critical")
    [read] = [thread for thread in inbox(client) if thread["title"] == "Disk warm"]
    client.post("/api/threads/state", json={"ids": [read["id"]], "state": "read"}, headers=UI)
    result = client.post("/api/threads/archive-all", json={"view": "crit"}, headers=UI).json()
    assert len(result["changed"]) == 2 and set(result["before"]) == {"unread"}
    assert [thread["title"] for thread in inbox(client)] == ["Disk warm"]
    # Everything else; the states before come back so the undo restores them.
    result = client.post("/api/threads/archive-all", json={"view": "inbox"}, headers=UI).json()
    assert result["before"] == {"read": [read["id"]]}
    assert inbox(client) == [] and len(inbox(client, "archived")) == 3
    # What is archived already does not count again, so the undo would not bring it out of the archive.
    assert client.post("/api/threads/archive-all", json={"view": "all"}, headers=UI).json()["changed"] == []
    nas_id = read["source_id"]
    assert len(_changed(client, "unarchive-all", source_id=nas_id)) == 2
    assert sorted(thread["title"] for thread in inbox(client)) == ["Container a stopped", "Disk warm"]


def test_delete_everything_in_the_archive_or_of_a_source(client: TestClient, operator: dict) -> None:
    nas = _hook(client, add_source(client, "webhook", name="NAS"))
    pve = _hook(client, add_source(client, "webhook", name="PVE"))
    for title in ("one", "two", "three"):
        nas(title=title, priority="warning")
    pve(title="VM 104 stopped", priority="critical")
    threads = inbox(client)
    nas_id = next(thread["source_id"] for thread in threads if thread["title"] == "one")
    one = next(thread["id"] for thread in threads if thread["title"] == "one")
    client.post("/api/threads/state", json={"ids": [one], "state": "archived"}, headers=UI)
    assert client.get(f"/api/threads/counts?source_id={nas_id}").json()["views"] == {
        "inbox": 2,
        "unread": 2,
        "crit": 0,
        "archived": 1,
    }
    assert _changed(client, "delete-all", view="archived") == [one]
    assert inbox(client, "archived") == [] and len(inbox(client)) == 3
    # "all" of a source: its inbox and its archive, never another source.
    client.post("/api/threads/archive-all", json={"view": "inbox", "source_id": nas_id}, headers=UI)
    nas(title="four", priority="warning")
    deleted = _changed(client, "delete-all", view="all", source_id=nas_id)
    assert len(deleted) == 3
    assert [thread["title"] for thread in inbox(client)] == ["VM 104 stopped"]
    assert len(_changed(client, "restore", ids=deleted + [one])) == 4
    assert len(inbox(client)) + len(inbox(client, "archived")) == 5
