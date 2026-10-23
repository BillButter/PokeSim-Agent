"""Rolling short-term memory for the vision agent."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .client import image_part
from .parser import AgentDecision
from .prompts import compact_state, observation_text, system_prompt


@dataclass
class MemoryTurn:
    turn: int
    timestamp: float
    state: dict[str, Any]
    delta: dict[str, Any]
    thought: str
    plan: list[str]
    actions: list[dict[str, Any]]
    result: str
    memory: str = ""
    image_b64: str | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def decision_json(self) -> str:
        return json.dumps(
            {
                "thought": self.thought,
                "plan": self.plan,
                "actions": self.actions,
                "memory": self.memory,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def public(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "timestamp": self.timestamp,
            "summary": state_summary(self.state),
            "state": compact_state(self.state),
            "delta": self.delta,
            "thought": self.thought,
            "plan": self.plan,
            "actions": self.actions,
            "result": self.result,
            "memory": self.memory,
            "error": self.error,
        }


def state_summary(state: dict[str, Any] | None) -> str:
    if not state:
        return "No state"
    party = ", ".join(
        f"{mon.get('species')} {mon.get('hp')}/{mon.get('max_hp')}"
        for mon in state.get("party", [])
    ) or "no party"
    return (
        f"{state.get('map_name')} ({state.get('x')},{state.get('y')}) · "
        f"{state.get('badge_count')} badges · {party}"
    )


class RollingMemory:
    def __init__(self, max_turns: int = 8, image_history: int = 2):
        self.max_turns = max(1, max_turns)
        self.image_history = max(0, image_history)
        self._turns: deque[MemoryTurn] = deque(maxlen=self.max_turns)
        self._lock = threading.RLock()
        self._next_turn = 1
        self.revision = 0

    def configure(self, *, max_turns: int | None = None, image_history: int | None = None) -> None:
        if max_turns:
            self.max_turns = max(1, int(max_turns))
            self._turns = deque(self._turns, maxlen=self.max_turns)
        if image_history is not None:
            self.image_history = max(0, int(image_history))

    def add(
        self,
        *,
        state: dict[str, Any],
        delta: dict[str, Any],
        decision: AgentDecision,
        result: str,
        image_b64: str | None = None,
        error: str | None = None,
    ) -> MemoryTurn:
        with self._lock:
            turn = MemoryTurn(
                turn=self._next_turn,
                timestamp=time.time(),
                state=dict(state or {}),
                delta=delta or {},
                thought=decision.thought,
                plan=list(decision.plan),
                actions=[action.as_dict() for action in decision.actions],
                result=result,
                memory=decision.memory,
                image_b64=image_b64,
                error=error,
            )
            self._next_turn += 1
            self._turns.append(turn)
            self.revision += 1
            return turn

    def clear(self) -> None:
        with self._lock:
            self._turns.clear()
            self._next_turn = 1
            self.revision += 1

    def recent_plan(self) -> list[str]:
        with self._lock:
            if not self._turns:
                return []
            return list(self._turns[-1].plan)

    def last_result(self) -> str:
        with self._lock:
            return self._turns[-1].result if self._turns else ""

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [turn.public() for turn in self._turns]

    @property
    def turn_count(self) -> int:
        with self._lock:
            return self._next_turn - 1

    def build_messages(
        self,
        *,
        state: dict[str, Any],
        delta: dict[str, Any],
        image_b64: str | None,
        game_title: str,
        max_actions: int,
        max_frames: int,
        active_plan: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            turns = list(self._turns)
            turn_number = self._next_turn
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": system_prompt(
                    game_title, max_actions=max_actions, max_frames=max_frames
                ),
            }
        ]
        first_image_index = max(0, len(turns) - self.image_history)
        for index, turn in enumerate(turns):
            has_image = bool(turn.image_b64) and index >= first_image_index
            text = observation_text(
                turn.state,
                turn.delta,
                turn=turn.turn,
                previous_result=turn.result,
                active_plan=turn.plan,
            )
            text += "\nSCREENSHOT: " + (
                "attached." if has_image else "not retained; rely on the state."
            )
            content: list[dict[str, Any]] = [{"type": "text", "text": text}]
            if has_image:
                content.append(image_part(turn.image_b64 or ""))
            messages.append({"role": "user", "content": content})
            messages.append(
                {
                    "role": "assistant",
                    "content": turn.decision_json(),
                }
            )
        current_text = observation_text(
            state,
            delta,
            turn=turn_number,
            previous_result=self.last_result(),
            active_plan=active_plan or self.recent_plan(),
        )
        current: list[dict[str, Any]] = [{"type": "text", "text": current_text}]
        if image_b64:
            current.append(image_part(image_b64))
        messages.append({"role": "user", "content": current})
        return messages
