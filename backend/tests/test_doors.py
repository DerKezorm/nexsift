"""Every door, called the way the real senders call it."""

from fastapi.testclient import TestClient

from tests.conftest import UI, add_source, inbox


def test_own_webhook_takes_json(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook", "Backup script")
    url = source["connection"]["url"]
    assert url.startswith("http://testserver:8490/api/v1/hook/")
    path = url.split("testserver:8490", 1)[1]
    response = client.post(
        path, json={"title": "Backup done", "message": "12 of 12 OK https://pbs.example.com/", "priority": "info"}
    )
    assert response.status_code == 202
    [thread] = inbox(client)
    assert thread["title"] == "Backup done"
    assert thread["priority"] == "info"
    assert thread["links"] == [{"label": "pbs.example.com", "url": "https://pbs.example.com/"}]


def test_own_webhook_takes_plain_text_and_known_field_names(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook")
    path = "/api/v1/hook/" + source["connection"]["token"]
    client.post(path, content=b"disk nearly full\nsecond line")
    client.post(path, json={"subject": "Job", "text": "went wrong", "severity": "error"})
    titles = {thread["title"]: thread["priority"] for thread in inbox(client)}
    assert titles["disk nearly full"] == "info"
    assert titles["Job"] == "crit"


def test_unknown_token_is_refused_without_a_hint(client: TestClient, operator: dict) -> None:
    response = client.post("/api/v1/hook/nope", json={"title": "x"})
    assert response.status_code == 401
    assert inbox(client) == []


def test_javascript_links_never_become_buttons(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook")
    client.post(
        "/api/v1/hook/" + source["connection"]["token"],
        json={"title": "x", "links": [{"label": "evil", "url": "javascript:alert(1)"}]},
    )
    assert inbox(client)[0]["links"] == []


def test_too_large_bodies_are_refused(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook")
    response = client.post("/api/v1/hook/" + source["connection"]["token"], content=b"x" * (300 * 1024))
    assert response.status_code == 413


def test_gotify_door_answers_like_gotify(client: TestClient, gotify_client: TestClient, operator: dict) -> None:
    source = add_source(client, "gotify", "Some app")
    token = source["connection"]["token"]
    assert source["connection"]["server"] == "http://testserver:8491"
    response = gotify_client.post(f"/message?token={token}", json={"title": "Hello", "message": "World", "priority": 8})
    assert response.status_code == 200
    assert response.json()["title"] == "Hello"
    # The header way and the form way, as the official clients do it.
    gotify_client.post(
        "/message", headers={"X-Gotify-Key": token}, data={"title": "Form", "message": "x", "priority": "5"}
    )
    titles = {thread["title"]: thread["priority"] for thread in inbox(client)}
    assert titles == {"Hello": "crit", "Form": "warn"}
    assert gotify_client.get("/version").status_code == 200
    assert gotify_client.post("/message?token=wrong", json={"message": "x"}).status_code == 401


def test_ntfy_door_answers_like_ntfy(client: TestClient, ntfy_client: TestClient, operator: dict) -> None:
    source = add_source(client, "ntfy", "Home Assistant")
    topic = source["connection"]["topic"]
    response = ntfy_client.post(f"/{topic}", content=b"Washer done", headers={"Title": "Laundry", "Priority": "high"})
    assert response.status_code == 200
    assert response.json()["topic"] == topic
    ntfy_client.post("/", json={"topic": topic, "message": "Door open", "title": "Garage", "priority": 5})
    ntfy_client.get(f"/{topic}/publish?message=Via+GET")
    titles = {thread["title"]: thread["priority"] for thread in inbox(client)}
    assert titles == {"Laundry": "warn", "Garage": "crit", "Via GET": "info"}


def test_unknown_ntfy_topic_is_refused_and_offered(client: TestClient, ntfy_client: TestClient, operator: dict) -> None:
    response = ntfy_client.post("/typo-topic", content=b"hello")
    assert response.status_code == 403
    [stranger] = client.get("/api/sources/strangers").json()
    assert stranger["protocol"] == "ntfy" and stranger["key"] == "typo-topic"


def test_discord_door_takes_embeds(client: TestClient, operator: dict) -> None:
    source = add_source(client, "discord", "Radarr")
    path = source["connection"]["url"].split("testserver:8490", 1)[1]
    body = {
        "username": "Radarr",
        "embeds": [
            {
                "title": "Download Failed",
                "description": "The Quiet Hour (2023)",
                "color": 15548997,
                "url": "https://radarr.example.com/movie/1",
            }
        ],
    }
    assert client.post(path, json=body).status_code == 204
    assert client.post(path + "?wait=true", json={"content": "second"}).status_code == 200
    threads = {thread["title"]: thread for thread in inbox(client)}
    assert threads["Download Failed"]["priority"] == "crit"
    assert threads["Download Failed"]["links"][0]["url"] == "https://radarr.example.com/movie/1"
    wrong_id = path.replace("/api/webhooks/", "/api/webhooks/1")
    assert client.post(wrong_id, json={"content": "x"}).status_code == 404


def test_new_token_locks_out_the_old_one(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook")
    old = source["connection"]["token"]
    renewed = client.post(f"/api/sources/{source['id']}/token", headers=UI).json()
    assert renewed["connection"]["token"] != old
    assert client.post("/api/v1/hook/" + old, json={"title": "x"}).status_code == 401
    assert client.post("/api/v1/hook/" + renewed["connection"]["token"], json={"title": "x"}).status_code == 202


def test_test_button_puts_a_message_in_without_counting_as_heard(client: TestClient, operator: dict) -> None:
    source = add_source(client, "uptimekuma")
    assert client.post(f"/api/sources/{source['id']}/test", headers=UI).status_code == 200
    assert inbox(client)[0]["title"].startswith("Test message for")
    assert client.get(f"/api/sources/{source['id']}").json()["last_seen_at"] is None


def test_syslog_needs_a_host_name(client: TestClient, operator: dict) -> None:
    response = client.post("/api/sources", json={"preset": "syslog", "name": "Router"}, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "hostname_required"
    add_source(client, "syslog", "Router", "gw")
    again = client.post("/api/sources", json={"preset": "syslog", "hostname": "GW"}, headers=UI)
    assert again.status_code == 409


def test_deleting_a_source_takes_its_messages(client: TestClient, operator: dict) -> None:
    source = add_source(client, "webhook")
    client.post("/api/v1/hook/" + source["connection"]["token"], json={"title": "x"})
    assert client.delete(f"/api/sources/{source['id']}", headers=UI).status_code == 204
    assert inbox(client) == []


def test_a_token_only_opens_its_own_door(client: TestClient, gotify_client: TestClient, operator: dict) -> None:
    gotify_source = add_source(client, "gotify")
    webhook_source = add_source(client, "webhook")
    assert client.post("/api/v1/hook/" + gotify_source["connection"]["token"], json={"title": "x"}).status_code == 401
    wrong = gotify_client.post("/message?token=" + webhook_source["connection"]["token"], json={"message": "x"})
    assert wrong.status_code == 401


def test_a_stranger_gets_its_source_with_its_own_topic(
    client: TestClient, ntfy_client: TestClient, operator: dict
) -> None:
    ntfy_client.post("/homeassistant", content=b"hello")
    created = client.post("/api/sources", json={"preset": "ntfy", "name": "HA", "key": "homeassistant"}, headers=UI)
    assert created.status_code == 201
    assert created.json()["connection"]["topic"] == "homeassistant"
    assert client.get("/api/sources/strangers").json() == []
    assert ntfy_client.post("/homeassistant", content=b"hello").status_code == 200
    bad = client.post("/api/sources", json={"preset": "email", "key": "Not Valid!"}, headers=UI)
    assert bad.json()["detail"]["code"] == "key_invalid"


def test_gotify_tokens_look_like_gotify_tokens(client: TestClient, operator: dict) -> None:
    """shoutrrr (Watchtower and others) checks the shape before sending: 15 characters, starting with A."""
    source = add_source(client, "gotify")
    token = source["connection"]["token"]
    assert len(token) == 15 and token.startswith("A")
    renewed = client.post(f"/api/sources/{source['id']}/token", headers=UI).json()["connection"]["token"]
    assert len(renewed) == 15 and renewed.startswith("A") and renewed != token
    assert len(add_source(client, "webhook")["connection"]["token"]) == 24
