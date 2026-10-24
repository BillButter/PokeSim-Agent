"""The AI players selectable for an adventure.

Kept separate from the runner because importing the runner loads game data.
"""

from __future__ import annotations

from typing import Any

AI_MODES = ("default", "vision", "gemini", "ml", "manual")
AGENT_MODES = frozenset({"vision", "gemini", "ml"})


def validate_ai_mode(value: Any) -> str:
    if not isinstance(value, str) or value not in AI_MODES:
        raise ValueError("AI player must be default, vision, gemini, ml, or manual")
    return value
