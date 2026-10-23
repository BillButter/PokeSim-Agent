"""Configuration for the optional vision agent.

The autopilot mode does not use any of this.  A vision adventure reads an
OpenAI-compatible ``/chat/completions`` endpoint configured on the server.
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


@dataclass(slots=True)
class AgentConfig:
    """The OpenAI-compatible vision endpoint used by ``ai_mode=vision``."""

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    poll_interval: float = 4.0
    max_context_turns: int = 8
    image_history: int = 2
    max_actions: int = 8
    max_frames: int = 120
    temperature: float = 0.2
    timeout: float = 120.0

    @classmethod
    def from_env(cls) -> AgentConfig:
        return cls(
            base_url=_env("AI_BASE_URL") or _env("OPENAI_BASE_URL"),
            api_key=_env("AI_API_KEY") or _env("OPENAI_API_KEY"),
            model=_env("AI_MODEL") or _env("OPENAI_MODEL"),
            poll_interval=max(0.5, _float("AI_POLL_INTERVAL", 4.0)),
            max_context_turns=max(1, _int("AI_MAX_CONTEXT_TURNS", 8)),
            image_history=max(0, _int("AI_IMAGE_HISTORY", 2)),
            max_actions=max(1, min(12, _int("AI_MAX_ACTIONS", 8))),
            max_frames=max(1, min(240, _int("AI_MAX_FRAMES", 120))),
            temperature=max(0.0, min(2.0, _float("AI_TEMPERATURE", 0.2))),
            timeout=max(5.0, _float("AI_TIMEOUT", 120.0)),
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    def public(self) -> dict:
        return {
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
