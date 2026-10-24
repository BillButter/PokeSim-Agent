"""The vision-led control loop used by ``ai_mode=vision``.

The runner never touches the emulator directly.  It reads a snapshot and a
screenshot through ``Emulator.call()``, asks an OpenAI-compatible model for a
short button plan, then queues those presses for the emulator loop.  The
strategic autopilot remains the only thing that runs in ``ai_mode=default``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from ..ram import read_snapshot
from .client import AIClientError, VisionClient, encode_png
from .config import AgentConfig
from .goals import inject_goals_into_prompt
from .memory import RollingMemory, state_summary
from .modes import AGENT_MODES, validate_ai_mode
from .parser import ParseError, parse_decision
from .pause_detector import PauseDetector
from .prompts import system_prompt

log = logging.getLogger(__name__)


def state_delta(previous: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any]:
    """A compact, human-readable difference used in the rolling memory."""
    if not previous or not current:
        return {}
    delta: dict[str, Any] = {}
    for key in ("map_name", "money", "badges", "owned", "seen", "in_battle", "enemy", "enemy_level",
                "playtime", "textbox", "start_menu"):
        if previous.get(key) != current.get(key):
            delta[key] = {"from": previous.get(key), "to": current.get(key)}
    before = {mon.get("slot", index): mon for index, mon in enumerate(previous.get("party", []))}
    after = {mon.get("slot", index): mon for index, mon in enumerate(current.get("party", []))}
    for slot in sorted(set(before) | set(after)):
        old, new = before.get(slot), after.get(slot)
        if not old or not new:
            continue
        label = new.get("name") or new.get("species") or old.get("name") or f"party {slot + 1}"
        if old.get("hp") != new.get("hp"):
            delta[f"{label} HP"] = {"from": old.get("hp"), "to": new.get("hp")}
        if old.get("level") != new.get("level"):
            delta[f"{label} level"] = {"from": old.get("level"), "to": new.get("level")}
    return delta


class VisionAgentRunner:
    """Own the model conversation and feed button sequences to the emulator."""

    def __init__(self, emulator, goals: str = ""):
        self.emulator = emulator
        self.goals = goals
        self.vision_config = AgentConfig.from_env()
        self.gemini_config = AgentConfig.gemini_from_env()
        tuning = self.vision_config
        self.memory = RollingMemory(
            max_turns=tuning.max_context_turns,
            image_history=tuning.image_history,
        )
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
        self._last_game: str = ""
        self._pause_detector = PauseDetector()

    def _config(self) -> AgentConfig:
        if getattr(self.emulator, "ai_mode", "vision") == "gemini":
            return self.gemini_config
        return self.vision_config

    # ---------------- lifecycle ----------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        config = self._config()
        if not config.configured:
            if config.provider == "gemini":
                message = "Set GEMINI_API_KEY to use the Gemini agent."
            else:
                message = "Set AI_BASE_URL and AI_MODEL to use the vision agent."
            self._set_status("error", message)
            log.warning(message)
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="vision-agent", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)

    def reset(self) -> None:
        """Discard in-flight observations after manual takeover or a mode switch."""
        with self._lock:
            self._previous_state = None
            self._last_action = ""
            self._error = None
            if self._status in {"acting", "thinking"}:
                self._status = "idle"
        self._pause_detector.reset()

    # ---------------- public status ----------------
    def public(self) -> dict[str, Any]:
        config = self._config()
        with self._lock:
            return {
                "mode": getattr(self.emulator, "ai_mode", "vision"),
                "provider": config.provider,
                "status": self._status,
                "configured": config.configured,
                "base_url": config.base_url,
                "model": config.model,
                "has_api_key": bool(config.api_key),
                "thought": self._thought,
                "plan": list(self._plan),
                "memory": self._memory,
                "last_action": self._last_action,
                "error": self._error,
                "turn": self._turn,
                "memory_turns": self.memory.turn_count,
            }

    def strategy(self) -> dict[str, Any]:
        status = self.public()
        plan = status["plan"]
        fallback = "Gemini agent" if status["mode"] == "gemini" else "Vision agent"
        objective = plan[0] if plan else fallback
        if status["status"] == "error" and status["error"]:
            reason = status["error"]
        elif status["status"] == "thinking":
            reason = "Watching the screen and deciding the next move."
        elif status["thought"]:
            reason = status["thought"]
        elif status["status"] == "acting":
            reason = "Following the current plan."
        else:
            reason = "Waiting for the next observation."
        return {
            "objective": {"id": "vision-agent", "title": objective},
            "reason": reason,
            "action": status["last_action"] or status["status"],
            "next": {"title": plan[1] if len(plan) > 1 else "Continue the journey"},
            "visited_tiles": 0,
            "agent": status,
        }

    # ---------------- loop ----------------
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
        while not self._stop.is_set():
            if not self._active():
                self._set_status("idle")
                self._stop.wait(0.5)
                continue
            try:
                self._turn_once()
            except (AIClientError, ParseError) as error:
                log.warning("vision agent turn failed: %s", error)
                self._set_status("error", str(error))
                self._stop.wait(3)
            except Exception as error:  # noqa: BLE001 - never kill the worker because of one model turn
                log.exception("vision agent turn failed")
                self._set_status("error", str(error) or error.__class__.__name__)
                self._stop.wait(3)

    def _turn_once(self) -> None:
        emu = self.emulator
        config = self._config()
        
        # Wait for game screen to stabilize before making a decision
        if not self._wait_for_pause(emu):
            return
        
        self._set_status("thinking", None)
        snapshot, image = self._observe(emu)
        if snapshot is None:
            self._stop.wait(1)
            return
        state = snapshot.to_dict(egg_view=True) if getattr(emu, "generation", 1) == 2 else snapshot.to_dict()
        state = {**state, "generation": getattr(emu, "generation", 1)}
        game_title = getattr(emu, "rom_note", "") or "Pokémon"
        self._last_game = game_title
        delta = state_delta(self._previous_state, state)
        image_b64 = encode_png(image) if image is not None else None
        messages = self.memory.build_messages(
            state=state,
            delta=delta,
            image_b64=image_b64,
            game_title=game_title,
            max_actions=config.max_actions,
            max_frames=config.max_frames,
            active_plan=self._plan,
            goals=self.goals,
        )
        decision = asyncio.run(VisionClient(config).complete(messages))
        if not self._active():
            self._set_status("idle")
            return
        parsed = parse_decision(
            decision,
            max_actions=config.max_actions,
            max_frames=config.max_frames,
        )
        actions = [(list(action.buttons), max(1, min(config.max_frames, action.frames)))
                   for action in parsed.actions]
        if not actions:
            raise ParseError("The model did not choose an action")
        self.memory.add(
            state=state,
            delta=delta,
            decision=parsed,
            result=", ".join("+".join(action.buttons) or "wait" for action in parsed.actions),
            image_b64=image_b64,
        )
        with self._lock:
            self._turn += 1
            self._thought = parsed.thought
            self._plan = list(parsed.plan)
            if parsed.memory:
                self._memory = parsed.memory
            self._last_action = ", ".join(action.label() for action in parsed.actions)
            self._error = None
            self._status = "acting"
        self._previous_state = state
        emu.enqueue_agent_actions(actions)

        # Let the emulator finish the queued actions before looking again.
        deadline = time.monotonic() + max(5.0, sum(frames for _, frames in actions) / 30.0 + 5.0)
        while self._active() and time.monotonic() < deadline:
            if emu.agent_actions.empty() and emu.agent_idle.is_set():
                break
            self._stop.wait(0.2)
        self._stop.wait(config.poll_interval)
        if self._active():
            self._set_status("idle")

    def _wait_for_pause(self, emu) -> bool:
        """Wait for game screen to stabilize (pause state) before requesting AI decision.
        
        This prevents the AI model from stalling the game rendering during animations
        or mid-action sequences. We wait for the screen to remain mostly static for a
        short duration, indicating the game is in a pause state (menu, dialogue, or
        end of animation).
        
        Args:
            emu: The emulator instance
            
        Returns:
            True if pause detected and ready for decision, False if stopped
        """
        config = self._config()
        poll_interval = config.poll_interval
        max_wait_time = 30.0  # Don't wait more than 30 seconds
        start_time = time.monotonic()
        
        log.debug("Waiting for game to pause before AI decision")
        
        while self._active() and time.monotonic() - start_time < max_wait_time:
            # Capture current frame
            _, image = self._observe(emu)
            if image is None:
                self._stop.wait(poll_interval)
                continue
            
            # Convert image to bytes for pause detection
            import io
            from PIL import Image
            
            image_bytes = io.BytesIO()
            image.save(image_bytes, format="PNG")
            frame_data = image_bytes.getvalue()
            
            # Check if screen is in a pause state
            if self._pause_detector.check_frame(frame_data):
                elapsed = time.monotonic() - start_time
                log.debug(f"Game pause detected after {elapsed:.2f}s - ready for AI decision")
                return True
            
            # Wait before checking again
            self._stop.wait(self._pause_detector.check_interval)
        
        if not self._active():
            return False
        
        # Timeout reached, log and proceed anyway
        log.warning("Timeout waiting for game pause (30s) - proceeding with AI decision anyway")
        return True

    def _observe(self, emu):
        def capture():
            if getattr(emu, "generation", 1) == 2:
                snapshot = emu._read()
                image = emu.pb.screen.image.convert("RGB")
            else:
                snapshot = read_snapshot(emu.pb.memory, emu.frame)
                image = emu._image()
            return snapshot, image

        try:
            return emu.call(capture, timeout=20)
        except Exception as error:
            log.warning("could not capture vision observation: %s", error)
            self._set_status("error", f"Could not read the game screen: {error}")
            return None, None
