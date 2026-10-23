"""Game sessions, the emulator worker thread, and manual/AI handover."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from .agent.controller import AgentController
from .agent.memory import RollingMemory
from .config import Settings
from .emulator import BaseEmulator, MockEmulator, PyBoyEmulator
from .gen1 import state_delta
from .store import Repository

log = logging.getLogger(__name__)

AI_MODES = ("default", "vision", "manual")
SCREEN_SIZE = (160, 144)


class SessionError(RuntimeError):
    pass


def empty_state(title: str) -> dict[str, Any]:
    return {
        "game": title,
        "trainer": "Trainer",
        "rival": "",
        "map_id": 0,
        "map_name": "Starting up",
        "x": 0,
        "y": 0,
        "badges": [False] * 8,
        "badge_count": 0,
        "badge_names": [],
        "money": 0,
        "playtime": "00:00:00",
        "in_battle": 0,
        "battle": "overworld",
        "pokedex_owned": 0,
        "pokedex_seen": 0,
        "party": [],
        "party_count": 0,
        "timestamp": time.time(),
    }


@dataclass
class Command:
    kind: str
    buttons: tuple[str, ...] = ()
    frames: int = 4
    settle: int = 2
    future: asyncio.Future | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


class EmulatorWorker(threading.Thread):
    """The only thread that touches the emulator.

    PyBoy is not thread-safe and a frame tick can be expensive.  Every manual
    press and agent sequence is queued here, which also gives the session one
    reliable place to cancel a long action on takeover.
    """

    def __init__(
        self,
        session: "GameSession",
        emulator: BaseEmulator,
        *,
        frame_fps: int,
        loop: asyncio.AbstractEventLoop,
    ):
        super().__init__(name=f"emulator-{session.game_id}", daemon=True)
        self.session = session
        self.emulator = emulator
        self.frame_interval = 1.0 / max(1, frame_fps)
        self.loop = loop
        self.commands: queue.Queue[Command] = queue.Queue()
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.held: set[str] = set()
        self._active_cancel: threading.Event | None = None
        self._active_lock = threading.Lock()
        self._last_capture = 0.0
        self._last_state = 0.0

    # ---------------- public, called from the event loop ----------------
    def submit(self, command: Command) -> None:
        self.commands.put(command)

    def cancel_active(self) -> None:
        with self._active_lock:
            if self._active_cancel:
                self._active_cancel.set()

    def stop(self) -> None:
        self.stop_event.set()
        self.pause_event.clear()
        self.cancel_active()

    def pause(self) -> None:
        self.pause_event.set()

    def resume(self) -> None:
        self.pause_event.clear()

    # ---------------- worker ----------------
    def run(self) -> None:  # noqa: C901 - a small state machine
        try:
            self._capture()
            self._update_state()
            while not self.stop_event.is_set():
                if self.pause_event.is_set():
                    if time.monotonic() - self._last_capture > 0.5:
                        self._capture()
                    time.sleep(0.03)
                    continue
                try:
                    command = self.commands.get_nowait()
                except queue.Empty:
                    command = None
                started = time.monotonic()
                frames = 0
                if command is not None:
                    if command.kind == "stop":
                        self._resolve(command, {"frames": 0})
                        break
                    frames = self._run_command(command)
                else:
                    self._tick(1)
                    frames = 1
                target = frames / 60.0
                elapsed = time.monotonic() - started
                if elapsed < target:
                    time.sleep(target - elapsed)
        except Exception as exc:  # pragma: no cover - fatal backend failure
            log.exception("Emulator worker failed")
            self._finish_pending(exc)
            self.session.fail(exc)
        finally:
            for button in list(self.held):
                try:
                    self.emulator.button_up(button)
                except Exception:
                    pass
            self.held.clear()
            self._capture()

    def _run_command(self, command: Command) -> int:
        with self._active_lock:
            self._active_cancel = command.cancel
        frames = 0
        try:
            if command.kind in ("press", "sequence"):
                for button in command.buttons:
                    self.emulator.button_down(button)
                    self.held.add(button)
                try:
                    for _ in range(max(1, command.frames)):
                        if command.cancel.is_set() or self.stop_event.is_set():
                            break
                        self._tick(1)
                        frames += 1
                finally:
                    for button in command.buttons:
                        self.emulator.button_up(button)
                        self.held.discard(button)
                for _ in range(max(0, command.settle)):
                    if command.cancel.is_set() or self.stop_event.is_set():
                        break
                    self._tick(1)
                    frames += 1
                self._resolve(
                    command,
                    {
                        "frames": frames,
                        "interrupted": command.cancel.is_set(),
                        "buttons": list(command.buttons),
                    },
                )
            elif command.kind == "down":
                for button in command.buttons:
                    self.emulator.button_down(button)
                    self.held.add(button)
                self._resolve(command, {"frames": 0, "buttons": list(command.buttons)})
            elif command.kind == "up":
                for button in command.buttons:
                    self.emulator.button_up(button)
                    self.held.discard(button)
                self._resolve(command, {"frames": 0, "buttons": list(command.buttons)})
            elif command.kind == "tick":
                for _ in range(max(1, command.frames)):
                    if command.cancel.is_set() or self.stop_event.is_set():
                        break
                    self._tick(1)
                    frames += 1
                self._resolve(command, {"frames": frames})
            else:
                self._resolve(command, {"frames": 0, "error": f"unknown command {command.kind}"})
        except Exception as exc:
            self._resolve(command, error=exc)
            raise
        finally:
            with self._active_lock:
                self._active_cancel = None
        return frames

    def _tick(self, frames: int = 1) -> None:
        for _ in range(max(1, frames)):
            if self.stop_event.is_set():
                return
            self.emulator.tick(1)
            now = time.monotonic()
            if now - self._last_capture >= self.frame_interval:
                self._capture()
            if now - self._last_state >= 0.35:
                self._update_state()

    def _capture(self) -> None:
        try:
            image = self.emulator.screen()
            if image.size != SCREEN_SIZE:
                image = image.resize(SCREEN_SIZE, Image.Resampling.NEAREST)
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG", compress_level=1)
            png = buffer.getvalue()
            self.session._set_frame(png, base64.b64encode(png).decode("ascii"))
            self._last_capture = time.monotonic()
        except Exception:
            log.exception("Could not capture frame")

    def _update_state(self) -> None:
        try:
            state = self.emulator.snapshot()
            self.session._set_state(state)
            self._last_state = time.monotonic()
        except Exception:
            log.exception("Could not read game state")

    def _resolve(self, command: Command, result: Any = None, *, error: Exception | None = None) -> None:
        future = command.future
        if future is None:
            return

        def settle() -> None:
            if future.done():
                return
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(result)

        try:
            self.loop.call_soon_threadsafe(settle)
        except RuntimeError:
            pass

    def _finish_pending(self, exc: Exception) -> None:
        while True:
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                break
            self._resolve(command, error=exc)


class GameSession:
    def __init__(self, profile: dict, settings: Settings, repository: Repository):
        self.profile = dict(profile)
        self.game_id = str(profile["id"])
        self.settings = settings
        self.repository = repository
        self.rom_path = Path(profile["rom"]) if profile.get("rom") else None
        self.demo = bool(profile.get("demo")) or self.rom_path is None
        self.title = str(profile.get("title") or profile.get("name") or "Pokémon")
        self.name = str(profile.get("name") or self.title)
        self.created_at = profile.get("created_at")

        self._lock = threading.RLock()
        self._lifecycle = asyncio.Lock()
        self._input_lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._worker: EmulatorWorker | None = None
        self._emulator: BaseEmulator | None = None
        self._task: asyncio.Task | None = None

        self.running = False
        self.paused = False
        self.manual = False
        self.game_status = "stopped"
        self.error: str | None = None
        self.emulator_kind: str | None = None
        self._state = empty_state(self.title)
        self._previous_state: dict[str, Any] | None = None
        self._delta: dict[str, Any] = {}
        self._frame_bytes: bytes | None = None
        self._frame_b64: str | None = None
        self._frame_seq = 0
        self._state_rev = 0
        self._agent_rev = 0
        self._events_rev = 0
        self._events: deque[dict[str, Any]] = deque(maxlen=120)
        self._event_id = 0
        self.memory = RollingMemory(
            max_turns=settings.ai.max_context_turns,
            image_history=settings.ai.image_history,
        )
        self._agent: dict[str, Any] = {
            "mode": self.ai_mode,
            "status": "idle",
            "thought": "",
            "plan": [],
            "last_action": "",
            "error": None,
            "turn": 0,
            "model": "",
            "endpoint": "",
            "updated_at": time.time(),
        }

    # ---------------- basic properties ----------------
    @property
    def ai_mode(self) -> str:
        mode = str(self.profile.get("ai_mode") or "default")
        return mode if mode in AI_MODES else "default"

    def get_ai(self):
        return self.repository.effective_ai(self.game_id)

    def current_state(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def previous_state(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._previous_state) if self._previous_state else None

    # Read-only stream accessors used by the WebSocket endpoint.  Keeping these
    # here avoids reaching into private attributes from ``main.py``.
    @property
    def frame_seq(self) -> int:
        return self._frame_seq

    @property
    def frame_b64(self) -> str | None:
        return self._frame_b64

    @property
    def state_rev(self) -> int:
        return self._state_rev

    @property
    def agent_rev(self) -> int:
        return self._agent_rev

    @property
    def events_rev(self) -> int:
        return self._events_rev

    # ---------------- emulator callbacks ----------------
    def _set_frame(self, png: bytes, b64: str) -> None:
        with self._lock:
            self._frame_bytes = png
            self._frame_b64 = b64
            self._frame_seq += 1

    def _set_state(self, state: dict[str, Any]) -> None:
        with self._lock:
            previous = self._state
            self._previous_state = previous
            self._delta = state_delta(previous, state)
            self._state = state
            self._state_rev += 1
            if previous.get("map_id") != state.get("map_id"):
                self._append_event_locked(
                    "map",
                    f"Arrived at {state.get('map_name')}",
                    {"map": state.get("map_name"), "x": state.get("x"), "y": state.get("y")},
                )
            if (state.get("badge_count") or 0) > (previous.get("badge_count") or 0):
                self._append_event_locked(
                    "badge",
                    f"Badge earned ({state.get('badge_count')}/8)",
                    {"badges": state.get("badge_names")},
                )
            previous_party = {mon.get("slot"): mon for mon in previous.get("party", [])}
            for mon in state.get("party", []):
                old = previous_party.get(mon.get("slot"))
                if old and old.get("hp", 0) > 0 and mon.get("hp") == 0:
                    self._append_event_locked(
                        "faint", f"{mon.get('species')} fainted", {"slot": mon.get("slot")}
                    )

    def fail(self, exc: Exception) -> None:
        self.running = False
        self.game_status = "error"
        self.error = str(exc)
        self.set_agent(status="error", error=str(exc))

    def log_event(self, kind: str, message: str, data: dict | None = None) -> None:
        with self._lock:
            self._append_event_locked(kind, message, data)

    def _append_event_locked(self, kind: str, message: str, data: dict | None) -> None:
        self._event_id += 1
        self._events.append(
            {
                "id": self._event_id,
                "time": time.time(),
                "kind": kind,
                "message": message,
                "data": data or {},
            }
        )
        self._events_rev += 1

    # ---------------- agent status ----------------
    def set_agent(self, **values: Any) -> None:
        with self._lock:
            changed = False
            for key, value in values.items():
                if key not in self._agent or self._agent.get(key) != value:
                    self._agent[key] = value
                    changed = True
            if changed:
                self._agent["updated_at"] = time.time()
                self._agent_rev += 1

    def _sync_agent_mode(self) -> None:
        self.set_agent(mode=self.ai_mode)

    # ---------------- lifecycle ----------------
    async def start(self) -> dict[str, Any]:
        async with self._lifecycle:
            if self.running:
                return self.summary()
            self._loop = asyncio.get_running_loop()
            self._input_lock = asyncio.Lock()
            self.error = None
            self.game_status = "starting"
            self.set_agent(status="starting", error=None)
            try:
                self._emulator = await asyncio.to_thread(self._build_emulator)
            except Exception as exc:
                self.running = False
                self.game_status = "error"
                self.error = str(exc)
                self.set_agent(status="error", error=str(exc))
                raise SessionError(str(exc)) from exc
            self.emulator_kind = getattr(self._emulator, "kind", "unknown")
            self.paused = False
            self.manual = self.ai_mode == "manual"
            self.memory.clear()
            self._worker = EmulatorWorker(
                self,
                self._emulator,
                frame_fps=self.settings.frame_fps,
                loop=self._loop,
            )
            self.running = True
            self.game_status = "running"
            self._worker.start()
            # Give the worker a moment to capture the first frame and state so
            # the UI does not briefly render the "Starting up" placeholder.
            for _ in range(250):
                if not self.running:
                    break
                if self._frame_seq > 0 and self._state_rev > 0:
                    break
                await asyncio.sleep(0.02)
            self.log_event("session", f"Started {self.name} ({self.emulator_kind})")
            self._sync_agent_mode()
            if self.manual:
                self.set_agent(status="manual")
            else:
                self._start_agent()
            return self.summary()

    def _build_emulator(self) -> BaseEmulator:
        if self.demo:
            return MockEmulator(self.title)
        if not self.rom_path or not self.rom_path.exists():
            raise SessionError(f"ROM file is missing: {self.rom_path}")
        save_dir = self.settings.data_dir / "games" / self.game_id
        return PyBoyEmulator(
            self.rom_path,
            save_dir,
            title=self.title,
            speed=self.settings.emulation_speed,
        )

    async def stop(self) -> dict[str, Any]:
        async with self._lifecycle:
            self.running = False
            await self._stop_agent()
            worker = self._worker
            self._worker = None
            if worker is not None:
                worker.stop()
                await asyncio.to_thread(worker.join, 6)
                if worker.is_alive():
                    log.warning("Emulator worker for %s did not stop", self.game_id)
            emulator = self._emulator
            self._emulator = None
            if emulator is not None:
                await asyncio.to_thread(emulator.close)
            self.paused = False
            self.manual = False
            self.game_status = "stopped"
            self.emulator_kind = None
            self.set_agent(status="idle", last_action="")
            self.log_event("session", f"Stopped {self.name}")
            return self.summary()

    def _start_agent(self) -> None:
        if not self.running or self.paused or self.manual:
            return
        if self.ai_mode == "manual":
            self.manual = True
            return
        if self._task is not None and not self._task.done():
            return
        controller = AgentController(self)
        self._task = asyncio.create_task(controller.run(), name=f"agent-{self.game_id}")
        self.set_agent(status="starting", mode=self.ai_mode, error=None)

    async def _stop_agent(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            if self._worker is not None:
                self._worker.cancel_active()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("Agent task ended with an error")
        self.set_agent(status="idle")

    async def restart_agent(self) -> None:
        await self._stop_agent()
        self._sync_agent_mode()
        if self.manual:
            self.set_agent(status="manual")
        elif self.running and not self.paused:
            self._start_agent()

    # ---------------- controls ----------------
    async def set_ai_mode(self, mode: str) -> dict[str, Any]:
        if mode not in AI_MODES:
            raise SessionError(f"Unknown AI mode: {mode}")
        updated = self.repository.update_game(self.game_id, {"ai_mode": mode})
        if updated:
            self.profile = updated
        self.manual = mode == "manual"
        self.set_agent(mode=mode, error=None)
        await self.restart_agent()
        if mode == "manual":
            self.set_agent(status="manual")
        return self.summary()

    async def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        overrides = updates.pop("overrides", None) or {}
        if overrides:
            cleaned = {key: value for key, value in overrides.items() if value is not None}
            updated = self.repository.update_game(
                self.game_id, {"overrides": cleaned, **updates}
            )
        else:
            updated = self.repository.update_game(self.game_id, updates)
        if updated:
            self.profile = updated
            if updated.get("name"):
                self.name = str(updated["name"])
                self.profile["name"] = self.name
        mode = updates.get("ai_mode")
        if mode:
            await self.set_ai_mode(str(mode))
        else:
            await self.restart_agent()
        return self.snapshot()

    async def take_control(self) -> dict[str, Any]:
        self.manual = True
        if self._worker is not None:
            self._worker.cancel_active()
        await self._stop_agent()
        self.set_agent(status="manual", error=None)
        self.log_event("control", "Manual control taken")
        return self.summary()

    async def handover(self) -> dict[str, Any]:
        if self.ai_mode == "manual":
            updated = self.repository.update_game(self.game_id, {"ai_mode": "default"})
            if updated:
                self.profile = updated
        self.manual = False
        self.set_agent(status="idle", error=None, mode=self.ai_mode)
        self.log_event("control", "Handed back to the AI")
        if self.running and not self.paused:
            self._start_agent()
        return self.summary()

    async def pause(self) -> dict[str, Any]:
        self.paused = True
        if self._worker is not None:
            self._worker.pause()
        await self._stop_agent()
        self.set_agent(status="paused")
        self.log_event("control", "Game paused")
        return self.summary()

    async def resume(self) -> dict[str, Any]:
        self.paused = False
        if self._worker is not None:
            self._worker.resume()
        self.log_event("control", "Game resumed")
        if self.running and not self.manual:
            self._start_agent()
        elif self.manual:
            self.set_agent(status="manual")
        return self.summary()

    async def press(self, button: str, action: str = "press", frames: int = 4) -> dict[str, Any]:
        if not self.running:
            raise SessionError("The game is not running")
        if self.paused:
            raise SessionError("The game is paused")
        if not self.manual:
            await self.take_control()
        assert self._input_lock is not None
        command = Command(
            kind=action if action in ("press", "down", "up") else "press",
            buttons=(button,),
            frames=max(1, min(120, frames)),
        )
        async with self._input_lock:
            future = self._submit(command)
            timeout = max(4.0, command.frames / 60.0 + 3.0)
            try:
                result = await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                command.cancel.set()
                raise SessionError("The emulator did not process that input in time")
        return {"ok": True, "result": result}

    async def execute_actions(self, actions) -> str:
        if not self.running or self.paused or self.manual:
            return "Interrupted before the first action."
        executed = 0
        total_frames = 0
        for action in actions:
            if not self.running or self.paused or self.manual:
                return f"Interrupted after {executed} action(s)."
            if self.ai_mode == "manual":
                return f"Interrupted after {executed} action(s): manual mode."
            if not action.buttons:
                continue
            command = Command(
                kind="sequence",
                buttons=tuple(action.buttons),
                frames=action.frames,
                settle=2,
            )
            assert self._input_lock is not None
            async with self._input_lock:
                future = self._submit(command)
                timeout = max(5.0, action.frames / 60.0 + 5.0)
                try:
                    result = await asyncio.wait_for(future, timeout=timeout)
                except asyncio.TimeoutError:
                    command.cancel.set()
                    return f"Timed out after {executed} action(s)."
                if result.get("interrupted"):
                    return f"Interrupted after {executed} action(s)."
                executed += 1
                total_frames += int(result.get("frames") or 0)
        return f"Executed {executed} action(s), {total_frames} frames."

    def _submit(self, command: Command) -> asyncio.Future:
        if self._worker is None or self._loop is None:
            raise SessionError("The game is not running")
        future: asyncio.Future = self._loop.create_future()
        command.future = future
        self._worker.submit(command)
        return future

    # ---------------- observation and API shapes ----------------
    async def observe(self) -> dict[str, Any]:
        with self._lock:
            return {
                "frame_b64": self._frame_b64,
                "frame_seq": self._frame_seq,
                "state": dict(self._state),
                "delta": dict(self._delta),
                "title": self.title,
                "demo": self.demo,
            }

    def agent_snapshot(self) -> dict[str, Any]:
        with self._lock:
            agent = dict(self._agent)
            agent["mode"] = self.ai_mode
            agent["manual"] = self.manual
            agent["paused"] = self.paused
            agent["available_modes"] = list(AI_MODES)
            return agent

    def memory_snapshot(self) -> list[dict[str, Any]]:
        return self.memory.snapshot()

    def events_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            state = self._state
            agent = dict(self._agent)
            return {
                "id": self.game_id,
                "name": self.name,
                "title": self.title,
                "rom": str(self.rom_path) if self.rom_path else None,
                "demo": self.demo,
                "ai_mode": self.ai_mode,
                "running": self.running,
                "paused": self.paused,
                "manual": self.manual,
                "status": self.game_status,
                "error": self.error,
                "emulator": self.emulator_kind,
                "frame_seq": self._frame_seq,
                "state_rev": self._state_rev,
                "agent_rev": self._agent_rev,
                "events_rev": self._events_rev,
                "trainer": state.get("trainer"),
                "map_name": state.get("map_name"),
                "badge_count": state.get("badge_count"),
                "party_count": state.get("party_count"),
                "agent": {
                    "mode": self.ai_mode,
                    "status": agent.get("status"),
                    "thought": agent.get("thought"),
                    "plan": agent.get("plan"),
                    "last_action": agent.get("last_action"),
                    "error": agent.get("error"),
                    "turn": agent.get("turn"),
                    "model": agent.get("model"),
                    "endpoint": agent.get("endpoint"),
                    "updated_at": agent.get("updated_at"),
                },
                "overrides": self.profile.get("overrides") or {},
                "created_at": self.created_at,
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            frame_seq = self._frame_seq
            state = dict(self._state)
            agent = dict(self._agent)
            frame_b64 = self._frame_b64
        ai = self.get_ai()
        payload = self.summary()
        payload.update(
            {
                "state": state,
                "agent": {
                    **agent,
                    "mode": self.ai_mode,
                    "manual": self.manual,
                    "paused": self.paused,
                    "available_modes": list(AI_MODES),
                },
                "memory": self.memory_snapshot(),
                "events": self.events_snapshot(),
                "ai": ai.public(),
                "frame_seq": frame_seq,
            }
        )
        # Frames are sent over the WebSocket; include one for the initial REST load.
        payload["frame"] = frame_b64
        return payload
