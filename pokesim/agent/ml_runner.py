"""Machine learning agent runner - non-network based learning player."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from ..ram import read_snapshot
from .ml_player import MLPlayer
from .modes import AGENT_MODES

log = logging.getLogger(__name__)


class MLAgentRunner:
    """ML-based agent that learns from gameplay without external services.
    
    Runs locally using decision patterns learned during play.
    No network calls or external model required.
    """

    def __init__(self, emulator):
        self.emulator = emulator
        self.ml_player = MLPlayer()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._status = "idle"
        self._thought = ""
        self._plan: list[str] = []
        self._memory = ""
        self._last_action = ""
        self._error: str | None = None
        self._turn = 0
        self._previous_state: dict[str, Any] | None = None

    def start(self) -> None:
        """Start the ML agent loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ml-agent", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the ML agent loop."""
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)

    def reset(self) -> None:
        """Reset agent state after mode switch."""
        with self._lock:
            if self._status in {"acting", "thinking"}:
                self._status = "idle"

    def public(self) -> dict[str, Any]:
        """Public status for UI."""
        with self._lock:
            return {
                "mode": "ml",
                "provider": "ml",
                "status": self._status,
                "configured": True,
                "thought": self._thought,
                "plan": list(self._plan),
                "memory": self._memory or self.ml_player.get_summary(),
                "last_action": self._last_action,
                "error": self._error,
                "turn": self._turn,
            }

    def strategy(self) -> dict[str, Any]:
        """Strategy info for game display."""
        status = self.public()
        plan = status["plan"]
        objective = plan[0] if plan else "ML learning agent"
        return {
            "objective": {"id": "ml-agent", "title": objective},
            "reason": status["thought"] or status["memory"],
            "action": status["last_action"] or status["status"],
            "next": {"title": plan[1] if len(plan) > 1 else "Continue learning"},
            "visited_tiles": 0,
            "agent": status,
        }

    def _active(self) -> bool:
        emu = self.emulator
        return (not self._stop.is_set() and getattr(emu, "ai_mode", "default") in AGENT_MODES
                and not getattr(emu, "manual_mode", False) and not getattr(emu, "paused", False))

    def _set_status(self, status: str, error: str | None = None) -> None:
        with self._lock:
            self._status = status
            if error is not None:
                self._error = error

    def _run(self) -> None:
        """Main ML agent loop."""
        while not self._stop.is_set():
            if not self._active():
                self._set_status("idle")
                self._stop.wait(0.5)
                continue
            try:
                self._turn_once()
            except Exception as error:
                log.exception("ML agent turn failed")
                self._set_status("error", str(error) or error.__class__.__name__)
                self._stop.wait(2)

    def _turn_once(self) -> None:
        """Execute one turn of ML agent logic."""
        emu = self.emulator
        self._set_status("thinking", None)

        # Capture game state
        def capture():
            if getattr(emu, "generation", 1) == 2:
                snapshot = emu._read()
            else:
                snapshot = read_snapshot(emu.pb.memory, emu.frame)
            return snapshot

        try:
            snapshot = emu.call(capture, timeout=10)
        except Exception as error:
            log.warning("could not capture ML observation: %s", error)
            self._set_status("error", f"Could not read game: {error}")
            return

        if snapshot is None:
            self._stop.wait(1)
            return

        # Convert to compact state
        state = snapshot.to_dict(egg_view=True) if getattr(emu, "generation", 1) == 2 else snapshot.to_dict()

        # Get decision from ML player
        ml_decision = self.ml_player.decide(state)

        if not self._active():
            self._set_status("idle")
            return

        # Enqueue actions
        actions = [(list(ml_decision.buttons), ml_decision.frames)]
        with self._lock:
            self._turn += 1
            self._thought = ml_decision.reasoning
            self._plan = [self.ml_player.get_summary()]
            self._last_action = " + ".join(ml_decision.buttons) or "wait"
            self._memory = f"Confidence: {ml_decision.confidence:.1%}"
            self._error = None
            self._status = "acting"

        emu.enqueue_agent_actions(actions)

        # Let emulator finish actions
        deadline = time.monotonic() + 5.0
        while self._active() and time.monotonic() < deadline:
            if emu.agent_actions.empty() and emu.agent_idle.is_set():
                break
            self._stop.wait(0.2)

        # Learn from result
        self.ml_player.learn_from_turn(self._last_action, state)

        self._stop.wait(1)
        if self._active():
            self._set_status("idle")
