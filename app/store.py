"""Small, crash-safe JSON persistence for settings and per-game profiles."""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .config import AIConfig, Settings

log = logging.getLogger(__name__)

DEFAULT_GAME = {
    "ai_mode": "default",
    "overrides": {},
    "created_at": None,
}


class Repository:
    """Owns ``settings.json`` and ``games.json`` under the data directory."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.data_dir = settings.data_dir
        self.settings_path = self.data_dir / "settings.json"
        self.games_path = self.data_dir / "games.json"
        self._lock = threading.RLock()

    # ---------------- low level ----------------
    def _read(self, path: Path, default: Any) -> Any:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value
        except FileNotFoundError:
            return copy.deepcopy(default)
        except (OSError, ValueError) as exc:
            log.warning("Could not read %s (%s); using defaults", path, exc)
            return copy.deepcopy(default)

    def _write(self, path: Path, value: Any, *, private: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=path.name, dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if private:
                os.chmod(temp_path, 0o600)
            os.replace(temp_path, path)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    # ---------------- AI settings ----------------
    def get_ai(self) -> AIConfig:
        with self._lock:
            stored = self._read(self.settings_path, {}).get("ai", {})
        values = self.settings.ai.with_overrides(stored or {})
        # Keep values usable even when a hand-edited file contains silly values.
        values.poll_interval = min(120.0, max(0.5, float(values.poll_interval)))
        values.max_context_turns = min(40, max(1, int(values.max_context_turns)))
        values.image_history = min(8, max(0, int(values.image_history)))
        values.max_actions = min(24, max(1, int(values.max_actions)))
        values.max_frames = min(1200, max(1, int(values.max_frames)))
        values.temperature = min(2.0, max(0.0, float(values.temperature)))
        values.timeout = min(600.0, max(1.0, float(values.timeout)))
        return values

    def update_ai(self, updates: dict[str, Any]) -> AIConfig:
        with self._lock:
            current = self.get_ai()
            merged = current.with_overrides(
                {key: value for key, value in updates.items() if value is not None}
            )
            payload = self._read(self.settings_path, {})
            payload["ai"] = merged.as_dict()
            self._write(self.settings_path, payload, private=True)
            return merged

    # ---------------- games ----------------
    def list_games(self) -> list[dict]:
        with self._lock:
            games = self._read(self.games_path, {})
        if not isinstance(games, dict):
            return []
        result = []
        for game_id, profile in games.items():
            if not isinstance(profile, dict):
                continue
            merged = copy.deepcopy(DEFAULT_GAME)
            merged.update(profile)
            merged["id"] = game_id
            merged.setdefault("overrides", {})
            result.append(merged)
        result.sort(key=lambda item: (item.get("name") or "").lower())
        return result

    def get_game(self, game_id: str) -> dict | None:
        for profile in self.list_games():
            if profile["id"] == game_id:
                return profile
        return None

    def upsert_game(self, profile: dict) -> dict:
        game_id = str(profile["id"])
        with self._lock:
            games = self._read(self.games_path, {})
            if not isinstance(games, dict):
                games = {}
            merged = copy.deepcopy(DEFAULT_GAME)
            merged.update(games.get(game_id, {}))
            merged.update(profile)
            games[game_id] = merged
            self._write(self.games_path, games)
        return self.get_game(game_id) or {}

    def update_game(self, game_id: str, updates: dict[str, Any]) -> dict | None:
        with self._lock:
            games = self._read(self.games_path, {})
            if not isinstance(games, dict) or game_id not in games:
                return None
            profile = games[game_id]
            if updates.get("clear_overrides"):
                profile["overrides"] = {}
            for key, value in updates.items():
                if key == "overrides":
                    current = profile.setdefault("overrides", {})
                    for field, field_value in (value or {}).items():
                        # Blank values mean "inherit the global setting".
                        if field_value is None or field_value == "":
                            current.pop(field, None)
                        else:
                            current[field] = field_value
                elif key == "clear_overrides":
                    continue
                elif value is not None:
                    profile[key] = value
            self._write(self.games_path, games)
        return self.get_game(game_id)

    def remove_game(self, game_id: str) -> bool:
        with self._lock:
            games = self._read(self.games_path, {})
            if not isinstance(games, dict) or game_id not in games:
                return False
            del games[game_id]
            self._write(self.games_path, games)
            return True

    def effective_ai(self, game_id: str | None = None) -> AIConfig:
        """Global endpoint settings plus the selected game's optional overrides."""
        config = self.get_ai()
        if not game_id:
            return config
        profile = self.get_game(game_id)
        if not profile:
            return config
        overrides = profile.get("overrides") or {}
        # Empty strings mean "clear this override", not "use an empty endpoint".
        clean = {
            key: value
            for key, value in overrides.items()
            if value is not None and value != ""
        }
        return config.with_overrides(clean)
