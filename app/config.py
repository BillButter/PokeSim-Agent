"""Configuration for the PokeSim Agentic fork.

Environment variables are read once at startup.  AI settings can later be
overridden from the web UI and are persisted in ``data/settings.json``.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

try:  # optional, only useful for local development
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(_env(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(_env(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_path(name: str, default: Path) -> Path:
    raw = _env(name)
    if not raw:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (PROJECT_DIR / path).resolve()


@dataclass(slots=True)
class AIConfig:
    """OpenAI-compatible vision endpoint configuration."""

    base_url: str = "http://localhost:11434/v1"
    api_key: str = ""
    model: str = "llava"
    poll_interval: float = 4.0
    max_context_turns: int = 8
    image_history: int = 2
    max_actions: int = 8
    max_frames: int = 240
    temperature: float = 0.2
    timeout: float = 120.0

    @classmethod
    def from_env(cls) -> "AIConfig":
        return cls(
            base_url=str(
                _env("AI_BASE_URL")
                or _env("OPENAI_BASE_URL")
                or "http://localhost:11434/v1"
            ),
            api_key=str(_env("AI_API_KEY") or _env("OPENAI_API_KEY") or ""),
            model=str(_env("AI_MODEL") or _env("OPENAI_MODEL") or "llava"),
            poll_interval=_env_float("AI_POLL_INTERVAL", 4.0),
            max_context_turns=_env_int("AI_MAX_CONTEXT_TURNS", 8),
            image_history=_env_int("AI_IMAGE_HISTORY", 2),
            max_actions=_env_int("AI_MAX_ACTIONS", 8),
            max_frames=_env_int("AI_MAX_FRAMES", 240),
            temperature=_env_float("AI_TEMPERATURE", 0.2),
            timeout=_env_float("AI_TIMEOUT", 120.0),
        )

    def with_overrides(self, values: dict[str, Any]) -> "AIConfig":
        clean: dict[str, Any] = {}
        for key, value in values.items():
            if value is not None and hasattr(self, key):
                clean[key] = value
        return replace(self, **clean)

    def public(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "poll_interval": self.poll_interval,
            "max_context_turns": self.max_context_turns,
            "image_history": self.image_history,
            "max_actions": self.max_actions,
            "max_frames": self.max_frames,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "has_api_key": bool(self.api_key),
        }

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Settings:
    # Local-only by default: the dashboard has no authentication.  The Docker
    # image sets POKESIM_HOST=0.0.0.0 because the container port is published.
    host: str = "127.0.0.1"
    port: int = 8000
    roms_dir: Path = field(default_factory=lambda: PROJECT_DIR / "roms")
    data_dir: Path = field(default_factory=lambda: PROJECT_DIR / "data")
    demo_game: bool = True
    frame_fps: int = 12
    emulation_speed: int = 0
    default_ai_mode: str = "default"
    log_level: str = "INFO"
    ai: AIConfig = field(default_factory=AIConfig.from_env)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=str(_env("POKESIM_HOST", "127.0.0.1")),
            port=_env_int("POKESIM_PORT", 8000),
            roms_dir=_env_path("POKESIM_ROMS_DIR", PROJECT_DIR / "roms"),
            data_dir=_env_path("POKESIM_DATA_DIR", PROJECT_DIR / "data"),
            demo_game=_env_bool("POKESIM_DEMO_GAME", True),
            frame_fps=max(1, min(60, _env_int("POKESIM_FRAME_FPS", 12))),
            emulation_speed=max(0, _env_int("POKESIM_EMULATION_SPEED", 0)),
            default_ai_mode=str(_env("POKESIM_DEFAULT_AI_MODE", "default")),
            log_level=str(_env("POKESIM_LOG_LEVEL", "INFO")),
            ai=AIConfig.from_env(),
        )

    def ensure_dirs(self) -> None:
        self.roms_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "games").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "roms").mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    settings = Settings.from_env()
    settings.ensure_dirs()
    return settings
