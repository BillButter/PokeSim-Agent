from __future__ import annotations

import base64

from app.agent.memory import RollingMemory, state_summary
from app.agent.parser import AgentAction, AgentDecision


def _add(memory: RollingMemory, index: int, *, image: str | None = None) -> None:
    memory.add(
        state={
            "map_name": "Pallet Town",
            "x": index,
            "y": 0,
            "badge_count": index,
            "party": [{"species": "Bulbasaur", "hp": 19, "max_hp": 19}],
        },
        delta={"money": {"from": 0, "to": index}},
        decision=AgentDecision(
            thought=f"thought {index}",
            plan=[f"step {index}"],
            actions=[AgentAction(("a",), 4)],
            memory=f"note {index}",
        ),
        result=f"result {index}",
        image_b64=image,
    )


def test_memory_is_bounded_and_keeps_revisions():
    memory = RollingMemory(max_turns=3)
    for index in range(5):
        _add(memory, index)
    snapshot = memory.snapshot()
    assert [turn["turn"] for turn in snapshot] == [3, 4, 5]
    assert memory.turn_count == 5
    assert memory.revision == 5
    assert memory.recent_plan() == ["step 4"]
    assert memory.last_result() == "result 4"
    assert snapshot[-1]["summary"].startswith("Pallet Town")


def test_build_messages_includes_images_only_for_recent_turns():
    image = base64.b64encode(b"fake-png").decode()
    memory = RollingMemory(max_turns=4, image_history=1)
    for index in range(3):
        _add(memory, index, image=image)

    messages = memory.build_messages(
        state={"map_name": "Route 1", "party": []},
        delta={},
        image_b64=image,
        game_title="POKEMON RED",
        max_actions=4,
        max_frames=120,
        active_plan=["Cross the grass"],
    )

    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert len(messages) == 1 + 3 * 2 + 1
    image_parts = [
        part
        for message in messages
        if isinstance(message["content"], list)
        for part in message["content"]
        if part.get("type") == "image_url"
    ]
    # One retained historical screenshot + the current one.
    assert len(image_parts) == 2
    current = messages[-1]["content"]
    assert any(part.get("type") == "image_url" for part in current)
    assert "CURRENT PLAN" in current[0]["text"]


def test_configure_shrinks_and_clear_resets():
    memory = RollingMemory(max_turns=10)
    for index in range(6):
        _add(memory, index)
    memory.configure(max_turns=2, image_history=0)
    assert len(memory.snapshot()) == 2
    memory.clear()
    assert memory.snapshot() == []
    assert memory.turn_count == 0
