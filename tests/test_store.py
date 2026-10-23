from __future__ import annotations

import json
import stat

from app.store import Repository


def test_game_profiles_default_to_default_mode(repository: Repository):
    profile = repository.upsert_game({"id": "red", "name": "Red"})
    assert profile["ai_mode"] == "default"
    assert profile["overrides"] == {}
    assert repository.get_game("red")["ai_mode"] == "default"
    assert repository.get_game("missing") is None


def test_overrides_merge_and_can_be_cleared(repository: Repository):
    repository.upsert_game({"id": "red", "name": "Red"})
    repository.update_game(
        "red",
        {
            "overrides": {
                "base_url": "http://localhost:9999/v1",
                "model": "vision-small",
                "poll_interval": 2,
            }
        },
    )
    effective = repository.effective_ai("red")
    assert effective.base_url == "http://localhost:9999/v1"
    assert effective.model == "vision-small"
    assert effective.poll_interval == 2

    # Blank means inherit.
    repository.update_game("red", {"overrides": {"model": "", "base_url": None}})
    profile = repository.get_game("red")
    assert profile["overrides"] == {"poll_interval": 2}
    assert repository.effective_ai("red").model == "llava"

    repository.update_game("red", {"clear_overrides": True})
    assert repository.get_game("red")["overrides"] == {}
    assert repository.effective_ai("red").poll_interval == 0.5


def test_ai_settings_round_trip_is_private(repository: Repository):
    updated = repository.update_ai(
        {"base_url": "https://example.test/v1", "api_key": "secret", "model": "m"}
    )
    assert updated.api_key == "secret"
    assert "api_key" not in updated.public()
    assert updated.public()["has_api_key"] is True

    reloaded = repository.get_ai()
    assert reloaded.api_key == "secret"
    assert reloaded.base_url == "https://example.test/v1"

    mode = stat.S_IMODE(repository.settings_path.stat().st_mode)
    assert mode == 0o600
    payload = json.loads(repository.settings_path.read_text())
    assert payload["ai"]["api_key"] == "secret"


def test_corrupt_files_fall_back_to_defaults(repository: Repository):
    repository.settings_path.write_text("{not json", encoding="utf-8")
    repository.games_path.write_text("[]", encoding="utf-8")
    assert repository.get_ai().model == "llava"
    assert repository.list_games() == []


def test_remove_game(repository: Repository):
    repository.upsert_game({"id": "red", "name": "Red"})
    assert repository.remove_game("red") is True
    assert repository.remove_game("red") is False
