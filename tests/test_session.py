from __future__ import annotations

import pytest

from app.agent.parser import AgentAction
from app.config import Settings
from app.session import GameSession, SessionError
from app.store import Repository


@pytest.fixture
def session(settings: Settings, repository: Repository) -> GameSession:
    repository.upsert_game(
        {
            "id": "demo",
            "name": "Demo",
            "title": "Pokémon Demo",
            "rom": None,
            "demo": True,
            "ai_mode": "manual",
        }
    )
    profile = repository.get_game("demo")
    return GameSession(profile, settings, repository)


async def test_manual_lifecycle_and_actions(session: GameSession):
    await session.start()
    try:
        assert session.running is True
        assert session.emulator_kind == "demo"
        assert session.paused is False
        assert session.manual is True
        assert session.agent_snapshot()["status"] == "manual"

        # Manual input is accepted without asking for control again.
        result = await session.press("a", "press", 2)
        assert result["ok"] is True

        await session.pause()
        assert session.paused is True
        with pytest.raises(SessionError):
            await session.press("a")

        await session.resume()
        assert session.paused is False

        # A manual-mode handover promotes the game to the default autopilot.
        await session.handover()
        assert session.manual is False
        assert session.ai_mode == "default"
    finally:
        await session.stop()

    assert session.running is False
    assert session.game_status == "stopped"


async def test_pause_stops_agent_and_execute_actions_reports_interruption(session: GameSession):
    await session.start()
    try:
        # No controller is running in the manual fixture, so allow the command
        # path to execute while exercising the same checks the agent uses.
        session.profile["ai_mode"] = "default"
        session.manual = False
        assert await session.execute_actions([AgentAction(("a",), 2)]) == "Executed 1 action(s), 4 frames."
        await session.take_control()
        assert session.manual is True
        assert await session.execute_actions([AgentAction(("a",), 2)]) == "Interrupted before the first action."
    finally:
        await session.stop()


async def test_set_ai_mode_persists(session: GameSession, repository: Repository):
    await session.start()
    try:
        await session.set_ai_mode("manual")
        assert repository.get_game("demo")["ai_mode"] == "manual"
        with pytest.raises(SessionError):
            await session.set_ai_mode("unknown")
    finally:
        await session.stop()
