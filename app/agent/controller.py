"""The control loop that turns model decisions into emulator button presses."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from ..gen1 import state_delta
from .client import AIClientError, VisionClient
from .memory import RollingMemory
from .parser import AgentAction, AgentDecision, ParseError, parse_decision

log = logging.getLogger(__name__)

DEFAULT_INTERVAL = 0.45
DEFAULT_ACTIONS = [
    ("up", 14),
    ("a", 6),
    ("left", 14),
    ("a", 6),
    ("down", 14),
    ("a", 6),
    ("right", 14),
    ("a", 6),
]


class DefaultPolicy:
    """A small, local autopilot used by the per-game ``Default`` option.

    This is intentionally modest: it keeps the game moving and demonstrates the
    full control loop without a model endpoint.  It is not intended to replace
    PokeSim's mature strategic policy.
    """

    def __init__(self, seed: int = 1):
        self._step = 0
        self._random = random.Random(seed)
        self._last_map: str | None = None
        self._last_badges = -1
        self._battle_turns = 0

    def decide(self, state: dict[str, Any]) -> AgentDecision:
        map_name = state.get("map_name", "the overworld")
        badges = int(state.get("badge_count") or 0)
        if state.get("battle") in ("wild", "trainer"):
            self._battle_turns += 1
            actions = [
                AgentAction(("a",), 10),
                AgentAction(("a",), 10),
                AgentAction(("down",), 8),
                AgentAction(("a",), 10),
            ]
            thought = f"Default autopilot is in a {state.get('battle')} battle; advancing menus and choosing a move."
            plan = ["Finish the current battle", "Heal when back in the overworld", "Continue exploring"]
        else:
            self._battle_turns = 0
            direction, frames = DEFAULT_ACTIONS[self._step % len(DEFAULT_ACTIONS)]
            self._step += 1
            actions = [
                AgentAction((direction,), frames),
                AgentAction(("a",), 6),
            ]
            thought = f"Default autopilot: exploring {map_name}, moving {direction} and checking for dialogue."
            plan = [
                f"Explore {map_name}",
                "Advance dialogue and collect items",
                "Work toward the next badge",
            ]
        if self._last_map and self._last_map != map_name:
            thought = f"Default autopilot: arrived at {map_name}. Looking around before moving on."
        if self._last_badges >= 0 and badges > self._last_badges:
            thought = f"Default autopilot: earned a badge! {badges}/8 now. Continuing the adventure."
        self._last_map = map_name
        self._last_badges = badges
        return AgentDecision(
            thought=thought,
            plan=plan,
            actions=actions,
            memory=f"map={map_name}; badges={badges}; party={len(state.get('party', []))}",
        )


class AgentController:
    def __init__(self, session):
        self.session = session
        self.default = DefaultPolicy(seed=abs(hash(session.game_id)) % 10000)
        self._errors = 0

    async def run(self) -> None:
        session = self.session
        try:
            while session.running:
                if session.manual:
                    session.set_agent(status="manual", error=None)
                    await asyncio.sleep(0.25)
                    continue
                if session.paused:
                    session.set_agent(status="paused", error=None)
                    await asyncio.sleep(0.25)
                    continue
                mode = session.ai_mode
                if mode == "manual":
                    session.set_agent(status="manual", error=None)
                    await asyncio.sleep(0.5)
                    continue
                if mode == "default":
                    await self._default_turn()
                else:
                    await self._vision_turn()
        except asyncio.CancelledError:
            session.set_agent(status="idle")
            raise
        except Exception as exc:  # pragma: no cover - last-resort loop guard
            log.exception("Agent loop stopped")
            session.set_agent(status="error", error=f"Agent loop stopped: {exc}")

    async def _default_turn(self) -> None:
        session = self.session
        state = session.current_state()
        decision = self.default.decide(state)
        previous = session.previous_state()
        delta = state_delta(previous, state)
        session.set_agent(
            status="acting",
            thought=decision.thought,
            plan=decision.plan,
            error=None,
            last_action=summarise_actions(decision.actions),
        )
        result = await session.execute_actions(decision.actions)
        session.memory.add(
            state=state,
            delta=delta,
            decision=decision,
            result=result,
        )
        session.set_agent(
            status="waiting",
            thought=decision.thought,
            plan=decision.plan,
            turn=session.memory.turn_count,
            last_action=summarise_actions(decision.actions),
        )
        await asyncio.sleep(DEFAULT_INTERVAL)

    async def _vision_turn(self) -> None:
        session = self.session
        config = session.get_ai()
        session.memory.configure(
            max_turns=config.max_context_turns, image_history=config.image_history
        )
        if not config.base_url or not config.model:
            session.set_agent(
                status="error",
                error="No vision model is configured. Open Settings and set a base URL and model ID.",
            )
            await asyncio.sleep(4)
            return

        observation = await session.observe()
        state = observation.get("state") or {}
        delta = observation.get("delta") or {}
        image = observation.get("frame_b64")
        if not image:
            session.set_agent(status="thinking", error=None, thought="Waiting for the first frame…")
            await asyncio.sleep(0.5)
            return

        if session.manual or session.paused:
            return

        session.set_agent(
            status="thinking",
            error=None,
            thought="Looking at the screen and planning the next move…",
            turn=session.memory.turn_count,
            model=config.model,
            endpoint=config.base_url,
            last_action="",
        )
        messages = session.memory.build_messages(
            state=state,
            delta=delta,
            image_b64=image,
            game_title=session.title,
            max_actions=config.max_actions,
            max_frames=config.max_frames,
            active_plan=session.memory.recent_plan() or None,
        )
        client = VisionClient(config)
        try:
            raw = await client.complete(messages)
            self._errors = 0
            decision = parse_decision(
                raw, max_actions=config.max_actions, max_frames=config.max_frames
            )
        except (AIClientError, ParseError) as exc:
            self._errors += 1
            message = str(exc)
            session.log_event("agent_error", message)
            session.set_agent(status="error", error=message, thought="The vision model did not answer with a usable decision.")
            if self._errors <= 2 and not session.manual and not session.paused:
                # Keep the game alive while the user fixes an endpoint or prompt.
                fallback = AgentDecision(
                    thought="Fallback: advancing dialogue while the vision agent recovers.",
                    plan=session.memory.recent_plan() or ["Recover the vision connection"],
                    actions=[AgentAction(("a",), 4)],
                    raw="",
                    parse_error=message,
                )
                await session.execute_actions(fallback.actions)
                session.memory.add(
                    state=state,
                    delta=delta,
                    decision=fallback,
                    result="Fallback action after an agent error.",
                    image_b64=None,
                    error=message[:500],
                )
            await asyncio.sleep(min(15.0, max(2.0, config.poll_interval)))
            return
        except asyncio.CancelledError:
            raise

        if session.manual or session.paused:
            session.log_event("agent", "Decision discarded because manual control was taken.")
            return

        if not decision.plan:
            decision.plan = session.memory.recent_plan()
        session.set_agent(
            status="acting",
            thought=decision.thought,
            plan=decision.plan,
            last_action=summarise_actions(decision.actions),
            raw=decision.raw[:4000],
        )
        session.log_event(
            "agent_thought",
            decision.thought,
            {"actions": [action.as_dict() for action in decision.actions]},
        )
        result = await session.execute_actions(decision.actions)
        session.memory.add(
            state=state,
            delta=delta,
            decision=decision,
            result=result,
            image_b64=image,
        )
        session.set_agent(
            status="idle" if decision.done else "waiting",
            thought=decision.thought,
            plan=decision.plan,
            turn=session.memory.turn_count,
            last_action=summarise_actions(decision.actions),
            error=None,
        )
        await asyncio.sleep(10 if decision.done else config.poll_interval)


def summarise_actions(actions: list[AgentAction]) -> str:
    if not actions:
        return "wait"
    return " · ".join(f"{action.label()} ×{action.frames}f" for action in actions)
