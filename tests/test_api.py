from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def _demo(client: TestClient) -> dict:
    games = client.get("/api/games").json()["games"]
    demo = next(game for game in games if game["demo"])
    assert demo["ai_mode"] == "default"
    return demo


def _start_manual(client: TestClient) -> str:
    demo = _demo(client)
    game_id = demo["id"]
    response = client.patch(f"/api/games/{game_id}", json={"ai_mode": "manual"})
    assert response.status_code == 200
    response = client.post(f"/api/games/{game_id}/start")
    assert response.status_code == 200, response.text
    return game_id


def test_health_and_defaults(client: TestClient):
    health = client.get("/api/health").json()
    assert health["ok"] is True
    assert health["version"] == "0.1.0"
    assert health["pyboy"] in (True, False)

    payload = client.get("/api/games").json()
    assert payload["modes"] == ["default", "vision", "manual"]
    assert payload["ai"]["base_url"] == "http://localhost:11434/v1"
    demo = _demo(client)
    assert demo["id"] == "demo"
    assert demo["running"] is False


def test_start_snapshot_input_pause_resume_and_stop(client: TestClient):
    game_id = _start_manual(client)
    snapshot = client.get(f"/api/games/{game_id}").json()
    assert snapshot["running"] is True
    assert snapshot["agent"]["mode"] == "manual"
    assert snapshot["agent"]["status"] == "manual"
    assert snapshot["state"]["map_name"] == "Pallet Town"
    assert snapshot["state"]["party_count"] == 1
    assert snapshot["frame"].startswith("iVBOR")  # PNG base64

    response = client.post(
        f"/api/games/{game_id}/input",
        json={"button": "a", "action": "press", "frames": 2},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True

    assert client.post(f"/api/games/{game_id}/control", json={"action": "pause"}).status_code == 200
    paused = client.post(
        f"/api/games/{game_id}/input",
        json={"button": "a", "action": "press", "frames": 2},
    )
    assert paused.status_code == 409
    assert client.post(f"/api/games/{game_id}/control", json={"action": "resume"}).status_code == 200

    stopped = client.post(f"/api/games/{game_id}/stop").json()
    assert stopped["running"] is False
    assert stopped["status"] == "stopped"


def test_per_game_mode_and_endpoint_overrides(client: TestClient):
    game_id = _demo(client)["id"]

    response = client.patch(
        f"/api/games/{game_id}",
        json={"base_url": "http://localhost:9999/v1", "model": "small-vision", "poll_interval": 2},
    )
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["overrides"]["base_url"] == "http://localhost:9999/v1"
    assert summary["overrides"]["model"] == "small-vision"

    response = client.patch(f"/api/games/{game_id}", json={"clear_overrides": True})
    assert response.status_code == 200
    assert response.json()["overrides"] == {}

    response = client.patch(f"/api/games/{game_id}", json={"ai_mode": "vision"})
    assert response.status_code == 200
    assert response.json()["ai_mode"] == "vision"
    assert response.json()["agent"]["mode"] == "vision"

    invalid = client.patch(f"/api/games/{game_id}", json={"ai_mode": "nope"})
    assert invalid.status_code == 422


def test_global_settings_hides_and_persists_api_key(client: TestClient, settings: Settings):
    response = client.put(
        "/api/settings",
        json={"base_url": "https://example.test/v1", "model": "vision-1", "api_key": "top-secret"},
    )
    assert response.status_code == 200, response.text
    public = response.json()
    assert public["has_api_key"] is True
    assert "api_key" not in public

    stored = client.get("/api/settings").json()
    assert stored["base_url"] == "https://example.test/v1"
    assert stored["model"] == "vision-1"
    assert "api_key" not in stored

    text = (settings.data_dir / "settings.json").read_text()
    assert "top-secret" in text

    cleared = client.put("/api/settings", json={"clear_api_key": True}).json()
    assert cleared["has_api_key"] is False


def test_websocket_streams_hello_and_frames(client: TestClient):
    game_id = _start_manual(client)
    with client.websocket_connect(f"/ws/games/{game_id}") as websocket:
        hello = websocket.receive_json()
        assert hello["type"] == "hello"
        assert hello["game"]["id"] == game_id
        assert hello["state"]["map_name"] == "Pallet Town"

        kinds = []
        frame = None
        for _ in range(12):
            message = websocket.receive_json()
            kinds.append(message["type"])
            if message["type"] == "frame":
                frame = message
                break
        assert frame is not None, kinds
        assert frame["seq"] >= 1
        assert frame["data"].startswith("iVBOR")


def test_default_autopilot_takes_turns(client: TestClient):
    game_id = _demo(client)["id"]
    assert client.patch(f"/api/games/{game_id}", json={"ai_mode": "default"}).status_code == 200
    assert client.post(f"/api/games/{game_id}/start").status_code == 200

    deadline = time.time() + 10
    snapshot = {}
    while time.time() < deadline:
        snapshot = client.get(f"/api/games/{game_id}").json()
        if snapshot.get("memory"):
            break
        time.sleep(0.1)

    assert snapshot.get("running") is True
    assert snapshot.get("memory"), "the default autopilot did not record a turn"
    assert snapshot["agent"]["mode"] == "default"
    assert snapshot["agent"]["last_action"]
    client.post(f"/api/games/{game_id}/stop")


def test_take_control_and_handover(client: TestClient):
    game_id = _demo(client)["id"]
    assert client.patch(f"/api/games/{game_id}", json={"ai_mode": "default"}).status_code == 200
    assert client.post(f"/api/games/{game_id}/start").status_code == 200

    taken = client.post(f"/api/games/{game_id}/control", json={"action": "take_control"}).json()
    assert taken["manual"] is True
    assert taken["agent"]["status"] == "manual"

    handed = client.post(f"/api/games/{game_id}/control", json={"action": "handover"}).json()
    assert handed["manual"] is False
    assert handed["agent"]["mode"] == "default"
    client.post(f"/api/games/{game_id}/stop")


def test_unknown_game_and_missing_rom_errors(settings: Settings):
    settings.demo_game = False
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/games").json()["games"] == []
        assert client.get("/api/games/nope").status_code == 404
        assert client.post("/api/games/nope/start").status_code == 400
        assert client.post("/api/games/nope/stop").status_code == 404
