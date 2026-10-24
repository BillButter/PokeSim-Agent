"""Machine learning agent runner - non-network based learning player."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .ml_player import MLPlayer
from .modes import AGENT_MODES

log = logging.getLogger(__name__)


class MLAgentRunner:
    """ML-based agent that learns from gameplay without external services.
    
    This agent:
    1. Starts with random exploration (high exploration_rate)
    2. Gradually learns patterns from successes and failures
    3. Shifts from exploration to exploitation as confidence grows
    4. Maintains Q-learning values for state-action pairs
    5. Never fully stops exploring to handle new situations
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
        self._recent_actions: list[str] = []

    def start(self) -> None:
        """Start the ML agent loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ml-agent", daemon=True)
        self._thread.start()
        log.info("ML agent started - entering random exploration phase")

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
            "visited_tiles": len(self.ml_player.location_map),
            "agent": status,
        }

    def _active(self) -> bool:
        emu = self.emulator
        if emu is None:
            return False
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
                from ..ram import read_snapshot
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

        # Track action for learning
        action_str = " + ".join(ml_decision.buttons) if ml_decision.buttons else "wait"
        self._recent_actions.append(action_str)
        if len(self._recent_actions) > 5:
            self._recent_actions.pop(0)

        # Enqueue actions
        actions = [(list(ml_decision.buttons), ml_decision.frames)]
        with self._lock:
            self._turn += 1
            self._thought = ml_decision.reasoning
            
            # Show learning phase progress
            exploration = self.ml_player.exploration_rate
            if self.ml_player.move_count < 100:
                phase = "🔍 Exploration Phase"
            elif exploration > 0.5:
                phase = "📊 Learning Phase"
            elif exploration > 0.2:
                phase = "🎯 Building Patterns"
            else:
                phase = "💡 Expert Phase"
            
            self._plan = [
                f"{phase} ({exploration:.0%} random)",
                f"Q-values learned: {len(self.ml_player.q_values)}",
            ]
            
            self._last_action = action_str
            self._memory = self.ml_player.get_summary()
            self._error = None
            self._status = "acting"

        emu.enqueue_agent_actions(actions)

        # Let emulator finish actions
        deadline = time.monotonic() + 5.0
        while self._active() and time.monotonic() < deadline:
            if (hasattr(emu, 'agent_actions') and hasattr(emu, 'agent_idle') and
                emu.agent_actions.empty() and emu.agent_idle.is_set()):
                break
            self._stop.wait(0.2)

        # Learn from result
        # Provide meaningful feedback based on game events
        result = self._describe_outcome(state)
        self.ml_player.learn_from_turn(result, state, self._previous_state)

        self._stop.wait(1)
        if self._active():
            self._set_status("idle")

    def _describe_outcome(self, state: dict[str, Any]) -> str:
        """Describe what happened on this turn for learning."""
        # Extract meaningful events from state
        events = []
        
        # Battle outcomes
        in_battle = state.get("in_battle", 0)
        if not in_battle and len(self._recent_actions) > 0:
            # Exited battle
            events.append("battle_ended")
        
        party = state.get("party", [])
        if party:
            active = party[0]
            hp = active.get("hp", 0)
            max_hp = active.get("max_hp", 1)
            
            if hp > 0:
                events.append("pokemon_healthy")
            else:
                events.append("pokemon_fainted")
        
        # Exploration
        if "moved" in (self._last_action or "").lower():
            events.append("moved")
        
        # Default description
        if events:
            return " + ".join(events)
        return "turn_executed"
