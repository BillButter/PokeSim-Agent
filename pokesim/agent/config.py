"""Configuration for the optional model-backed agents.

The autopilot mode does not use any of this.  The ``vision`` player reads an
OpenAI-compatible endpoint configured on the server.  The ``gemini`` player
uses Google's OpenAI-compatible Gemini endpoint, so it needs no extra SDK.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value.strip()


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _tuning() -> dict:
    return {
        "poll_interval": max(0.5, _float("AI_POLL_INTERVAL", 4.0)),
        "max_context_turns": max(1, _int("AI_MAX_CONTEXT_TURNS", 8)),
        "image_history": max(0, _int("AI_IMAGE_HISTORY", 2)),
        "max_actions": max(1, min(12, _int("AI_MAX_ACTIONS", 8))),
        "max_frames": max(1, min(240, _int("AI_MAX_FRAMES", 120))),
        "temperature": max(0.0, min(2.0, _float("AI_TEMPERATURE", 0.2))),
        "timeout": max(5.0, _float("AI_TIMEOUT", 120.0)),
    }


GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_MODEL = "gemini-2.5-flash"


@dataclass(slots=True)
class AgentConfig:
    """An OpenAI-compatible model endpoint used by a vision-led AI player."""

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    provider: str = "openai"
    poll_interval: float = 4.0
    max_context_turns: int = 8
    image_history: int = 2
    max_actions: int = 8
    max_frames: int = 120
    temperature: float = 0.2
    timeout: float = 120.0

    @classmethod
    def from_env(cls) -> AgentConfig:
        """The generic ``vision`` player: any OpenAI-compatible endpoint."""
        return cls(
            base_url=_env("AI_BASE_URL") or _env("OPENAI_BASE_URL"),
            api_key=_env("AI_API_KEY") or _env("OPENAI_API_KEY"),
            model=_env("AI_MODEL") or _env("OPENAI_MODEL"),
            **_tuning(),
        )

    @classmethod
    def gemini_from_env(cls) -> AgentConfig:
        """The ``gemini`` player, using Google's OpenAI-compatible endpoint."""
        return cls(
            base_url=_env("GEMINI_BASE_URL") or GEMINI_BASE_URL,
            api_key=_env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY"),
            model=_env("GEMINI_MODEL") or GEMINI_MODEL,
            provider="gemini",
            **_tuning(),
        )

    @property
    def configured(self) -> bool:
        if self.provider == "gemini" and not self.api_key:
            return False
        return bool(self.base_url and self.model)

    def public(self) -> dict:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "configured": self.configured,
            "poll_interval": self.poll_interval,
            "max_context_turns": self.max_context_turns,
            "image_history": self.image_history,
            "max_actions": self.max_actions,
            "max_frames": self.max_frames,
            "temperature": self.temperature,
            "has_api_key": bool(self.api_key),
        }

    def as_dict(self) -> dict:
        return asdict(self)
