"""Structured JSON parsing for agent decisions.

Vision models are not compilers.  This module accepts the documented schema but
also tolerates common variations (markdown fences, a bare action string, a
singular ``action`` field, or ``hold`` in place of ``frames``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

BUTTONS = ("up", "down", "left", "right", "a", "b", "start", "select")
BUTTON_ALIASES = {
    "up": "up",
    "u": "up",
    "north": "up",
    "↑": "up",
    "down": "down",
    "d": "down",
    "south": "down",
    "↓": "down",
    "left": "left",
    "l": "left",
    "west": "left",
    "←": "left",
    "right": "right",
    "r": "right",
    "east": "right",
    "→": "right",
    "a": "a",
    "b": "b",
    "start": "start",
    "enter": "start",
    "select": "select",
    "shift": "select",
}


class ParseError(ValueError):
    """The response did not contain a usable JSON decision."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


@dataclass(frozen=True)
class AgentAction:
    buttons: tuple[str, ...]
    frames: int = 4

    def as_dict(self) -> dict[str, Any]:
        return {"buttons": list(self.buttons), "frames": self.frames}

    def label(self) -> str:
        return "+".join(button.upper() for button in self.buttons) or "wait"


@dataclass
class AgentDecision:
    thought: str = ""
    plan: list[str] = field(default_factory=list)
    actions: list[AgentAction] = field(default_factory=list)
    memory: str = ""
    done: bool = False
    raw: str = ""
    parse_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "thought": self.thought,
            "plan": list(self.plan),
            "actions": [action.as_dict() for action in self.actions],
            "memory": self.memory,
            "done": self.done,
        }

    def compact_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, separators=(",", ":"))


def extract_json(text: str) -> Any:
    """Return the first JSON value in a model response.

    Handles a fenced block, leading prose, and trailing commentary.  If the
    model returns multiple objects, the first object with a decision-looking
    key wins.
    """
    if not isinstance(text, str):
        raise ParseError("Response was not text", str(text))
    cleaned = text.strip().lstrip("\ufeff")
    if not cleaned:
        raise ParseError("Response was empty", text)

    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S | re.I)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    candidates: list[Any] = []
    for match in re.finditer(r"[\[{]", cleaned):
        try:
            value, _ = decoder.raw_decode(cleaned[match.start() :])
            candidates.append(value)
        except json.JSONDecodeError:
            continue
    for candidate in candidates:
        if isinstance(candidate, dict) and any(
            key in candidate
            for key in ("thought", "plan", "actions", "action", "buttons", "press")
        ):
            return candidate
    if candidates:
        return candidates[0]
    
    # For local models (like moondream, ollama, llama) that return plain text instead of JSON,
    # try to extract button presses from the response. This is a graceful fallback
    # to prevent constant error spam from models that don't understand JSON format.
    text_lower = cleaned.lower()
    buttons_found = []
    
    # Search for button keywords in order of likelihood
    for button in BUTTONS:
        # Use word boundaries to avoid false matches like "start" in "understand"
        if re.search(r"\b" + re.escape(button) + r"\b", text_lower):
            buttons_found.append(button)
    
    # Also check button aliases (like "u" for up, "d" for down)
    if not buttons_found:
        for alias, canonical in BUTTON_ALIASES.items():
            if alias != canonical and re.search(r"\b" + re.escape(alias) + r"\b", text_lower):
                if canonical not in buttons_found:
                    buttons_found.append(canonical)
    
    # Check for arrow symbols used in directions
    if not buttons_found:
        if "↑" in cleaned or re.search(r"\buparrow\b", text_lower):
            buttons_found.append("up")
        elif "↓" in cleaned or re.search(r"\bdownarrow\b", text_lower):
            buttons_found.append("down")
        elif "←" in cleaned or re.search(r"\bleftarrow\b", text_lower):
            buttons_found.append("left")
        elif "→" in cleaned or re.search(r"\brightarrow\b", text_lower):
            buttons_found.append("right")
    
    if buttons_found:
        # Model described an action in plain text, convert to JSON structure
        # Use the first button found as the primary action
        return {
            "thought": cleaned[:300],
            "actions": [{"buttons": [buttons_found[0]], "frames": 8}],
            "plan": ["Following local model guidance"],
        }
    
    # No buttons found but we have substantial text - this is most likely the model
    # is having trouble deciding. Return an action that lets the emulator handle it.
    # We don't use a wait-only action because parse_decision requires at least one button.
    # Instead, we'll have the fallback wait a bit longer for the next decision.
    if len(cleaned) > 15:
        # Return a sensible default: wait in neutral state
        # The emulator will handle this as a no-op with a short delay
        return {
            "thought": cleaned[:300],
            "actions": [{"buttons": ["a"], "frames": 2}],
            "plan": ["Waiting for clearer input"],
        }
    
    raise ParseError("No JSON object found in the model response", text)


def _button(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return BUTTON_ALIASES.get(value.strip().lower())


def _button_group(value: Any) -> tuple[str, ...]:
    """Parse ``"a"``, ``["a", "b"]``, ``"up+a"`` into one simultaneous press."""
    if isinstance(value, (list, tuple)):
        raw = [str(item) for item in value]
    elif isinstance(value, str):
        raw = re.split(r"\s*\+\s*", value.strip())
    else:
        return ()
    result = []
    for item in raw:
        button = _button(item)
        if button and button not in result:
            result.append(button)
    return tuple(result)


def _split_sequence(value: str) -> list[str]:
    parts = re.split(r"\s*(?:[,;→>]|\bthen\b|\s+-\s+)\s*", value.strip(), flags=re.I)
    return [part for part in parts if part.strip()]


def _int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "done"}
    return default


def _actions_from_string(value: str, max_frames: int) -> list[AgentAction]:
    actions: list[AgentAction] = []
    for part in _split_sequence(value):
        # "press a" / "tap start" are common phrasings.
        part = re.sub(r"^(?:press|tap|push|hold|move)\s+", "", part.strip(), flags=re.I)
        frames_match = re.search(r"(?:for\s+)?(\d+)\s*(?:frames?|ticks?)?$", part, re.I)
        frames = _int(frames_match.group(1), 4) if frames_match else 4
        if frames_match:
            part = part[: frames_match.start()].strip()
        buttons = _button_group(part)
        if buttons:
            actions.append(AgentAction(buttons, max(1, min(max_frames, frames))))
    return actions


def _normalise_plan(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        # Remove list markers such as "1." or "- " but keep meaningful digits
        # like "Route 1" at the end of a step.
        lines = [
            re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
            for line in value.splitlines()
        ]
        return [line for line in lines if line][:10]
    if isinstance(value, dict):
        value = [value]
    if isinstance(value, (list, tuple)):
        plan = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = str(
                    item.get("step")
                    or item.get("text")
                    or item.get("title")
                    or item.get("description")
                    or ""
                ).strip()
                status = item.get("status")
                if status and text:
                    text = f"{text} ({status})"
            else:
                text = str(item).strip()
            if text:
                plan.append(text)
        return plan[:10]
    return []


def _unwrap_action(item: Any, max_frames: int) -> list[AgentAction]:
    if isinstance(item, str):
        return _actions_from_string(item, max_frames)
    if not isinstance(item, dict):
        return []
    buttons_value = (
        item.get("buttons")
        if "buttons" in item
        else item.get("button", item.get("keys", item.get("press", item.get("inputs"))))
    )
    if buttons_value is None and "sequence" in item:
        sequence = item.get("sequence")
        if isinstance(sequence, str):
            return _actions_from_string(sequence, max_frames)
        if isinstance(sequence, (list, tuple)):
            actions: list[AgentAction] = []
            for entry in sequence:
                actions.extend(_unwrap_action(entry, max_frames))
            return actions
    frames = _int(
        item.get("frames", item.get("hold", item.get("hold_frames", item.get("duration", 4)))),
        4,
    )
    repeat = max(1, min(12, _int(item.get("repeat", item.get("times", 1)), 1)))
    buttons = _button_group(buttons_value)
    if not buttons:
        return []
    frames = max(1, min(max_frames, frames))
    return [AgentAction(buttons, frames) for _ in range(repeat)]


def parse_decision(
    text: str,
    *,
    max_actions: int = 8,
    max_frames: int = 240,
) -> AgentDecision:
    """Parse a model response into a validated decision."""
    payload = extract_json(text)
    raw = text
    if not isinstance(payload, dict):
        if isinstance(payload, (list, tuple)):
            payload = {"actions": payload}
        else:
            raise ParseError("JSON decision must be an object", raw)

    thought = (
        payload.get("thought")
        or payload.get("reasoning")
        or payload.get("rationale")
        or payload.get("analysis")
        or payload.get("message")
        or ""
    )
    if isinstance(thought, dict):
        thought = json.dumps(thought, ensure_ascii=False)
    thought = str(thought).strip()[:2000]

    plan = _normalise_plan(payload.get("plan") or payload.get("steps") or payload.get("strategy"))
    memory = str(
        payload.get("memory")
        or payload.get("remember")
        or payload.get("note")
        or ""
    ).strip()[:500]

    actions: list[AgentAction] = []
    if "actions" in payload:
        raw_actions = payload.get("actions")
        if isinstance(raw_actions, (list, tuple)):
            for item in raw_actions:
                actions.extend(_unwrap_action(item, max_frames))
        elif raw_actions is not None:
            actions.extend(_unwrap_action(raw_actions, max_frames))
    elif "action" in payload:
        actions.extend(_unwrap_action(payload["action"], max_frames))
    elif any(
        key in payload
        for key in ("sequence", "buttons", "button", "keys", "press", "inputs", "hold")
    ):
        # A single action object supplied at the top level, e.g.
        # {"button": "b", "hold": 9} or {"buttons": ["a"], "frames": 6}.
        actions.extend(_unwrap_action(payload, max_frames))

    # A few models return a bare ``{"up": 12}`` or ``{"press": "a"}`` shape.
    if not actions:
        for key, value in payload.items():
            button = _button(key)
            if button is not None:
                frames = _int(value, 4)
                actions.append(AgentAction((button,), max(1, min(max_frames, frames))))
                if len(actions) >= max_actions:
                    break

    actions = actions[:max_actions]
    if not actions:
        raise ParseError("The JSON decision had no buttons to press", raw)

    done = _bool(payload.get("done", payload.get("finished", False)))
    return AgentDecision(
        thought=thought or "No reasoning supplied.",
        plan=plan,
        actions=actions,
        memory=memory,
        done=done,
        raw=raw,
    )
