"""System prompt and compact observation text for the vision agent."""

from __future__ import annotations

import json
from typing import Any


def system_prompt(
    game_title: str,
    *,
    max_actions: int = 8,
    max_frames: int = 240,
) -> str:
    return f"""You are an autonomous Pokémon player. You see the live 160x144 Game Boy screen and a JSON snapshot of the game's memory. You control the emulator one short button sequence at a time.

GAME: {game_title}

CONTROLS
- up, down, left, right: move / navigate menus
- a: confirm, talk, advance text, use a move
- b: cancel / back
- start: open the menu
- select: secondary menu

STATE
The user message contains trainer, location, x/y, badges, money, playtime, battle state, Pokédex counts, and every party member's species, level, HP, status and moves. Treat it as ground truth. The screenshot is the primary source for menus, dialogue and spatial navigation.

HOW TO PLAY
- Advance dialogue and battle text with A. Do not mash A blindly in menus or when a cursor is on an important choice.
- In the overworld, move in short bursts and look at the new screenshot before choosing the next direction.
- In battle, choose useful moves; switch or heal when a party member is in danger.
- Follow your multi-step plan across turns. Keep the plan short and concrete.
- If the screen is a title screen, press START then A. If it is blank or fading, wait briefly.
- If an action had no visible effect, try a different direction or press A.
- Never claim to have done something the buttons cannot do. You only control the eight buttons.

OUTPUT
Return ONLY one JSON object, with no markdown fences and no prose outside it:

{{
  "thought": "one or two sentences about what you see and what you will do next",
  "plan": ["short step", "next step", "goal"],
  "actions": [
    {{"buttons": ["a"], "frames": 6}},
    {{"buttons": ["up"], "frames": 16}},
    {{"buttons": ["a"], "frames": 6}}
  ],
  "memory": "optional note to your future self",
  "done": false
}}

RULES FOR ACTIONS
- 1 to {max_actions} actions per turn.
- Each action holds its buttons for 1 to {max_frames} emulated frames, then releases them.
- Use 4-12 frames for a tap, 12-30 frames to walk one or two tiles, and 30-80 frames for a longer walk.
- Buttons in one action are pressed together. Use separate actions for a sequence.
- Prefer several small actions over one huge blind movement.
- If you need to wait, use a short action such as {{"buttons": ["a"], "frames": 4}} and explain why.
"""


def compact_state(state: dict[str, Any] | None) -> dict[str, Any]:
    if not state:
        return {}
    party = []
    for mon in state.get("party", []):
        moves = mon.get("move_details")
        party.append(
            {
                "species": mon.get("name") or mon.get("species"),
                "nickname": mon.get("nick"),
                "level": mon.get("level"),
                "hp": mon.get("hp"),
                "max_hp": mon.get("max_hp"),
                "status": mon.get("status_label") or mon.get("status"),
                "moves": [move.get("name") for move in moves] if moves else mon.get("moves"),
            }
        )
    badges = state.get("badges")
    if isinstance(badges, list):
        badge_names, badge_count = badges, len(badges)
    else:
        badge_count = int(badges or 0)
        badge_names = state.get("badge_names") or []
    battle = state.get("battle")
    if not battle:
        in_battle = state.get("in_battle")
        battle = "wild" if in_battle == 1 else "trainer" if in_battle == 2 else "overworld"
    return {
        "game": state.get("game") or state.get("version"),
        "generation": state.get("generation"),
        "trainer": state.get("trainer") or state.get("player_name"),
        "rival": state.get("rival") or state.get("rival_name"),
        "location": state.get("map_name"),
        "map_id": state.get("map") or state.get("map_id"),
        "x": state.get("x"),
        "y": state.get("y"),
        "badges": badge_count,
        "badge_names": badge_names,
        "money": state.get("money"),
        "playtime": state.get("playtime"),
        "battle": battle,
        "enemy": state.get("enemy"),
        "enemy_level": state.get("enemy_level"),
        "opponent": state.get("opponent"),
        "textbox": state.get("textbox"),
        "start_menu": state.get("start_menu"),
        "pokedex_owned": state.get("owned", state.get("pokedex_owned")),
        "pokedex_seen": state.get("seen", state.get("pokedex_seen")),
        "party": party,
        "demo": bool(state.get("demo")),
    }


def json_block(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def summarise_state(state: dict[str, Any] | None) -> str:
    if not state:
        return "No game state yet."
    party = ", ".join(
        f"{mon.get('species') or mon.get('name')} L{mon.get('level')} {mon.get('hp')}/{mon.get('max_hp')}"
        for mon in state.get("party", [])
    ) or "no party"
    return (
        f"{state.get('player_name') or state.get('trainer') or 'Trainer'} at "
        f"{state.get('map_name')} ({state.get('x')},{state.get('y')}); "
        f"badges {len(state.get('badges') or [])}/8; money ₽{state.get('money')}; party: {party}"
    )


def observation_text(
    state: dict[str, Any],
    delta: dict[str, Any] | None,
    *,
    turn: int,
    previous_result: str = "",
    active_plan: list[str] | None = None,
) -> str:
    lines = [
        f"TURN {turn}",
        "CURRENT STATE: " + json_block(compact_state(state)),
        "STATE SUMMARY: " + summarise_state(state),
    ]
    if delta:
        lines.append("CHANGES SINCE LAST TURN: " + json_block(delta))
    if previous_result:
        lines.append("PREVIOUS ACTIONS: " + previous_result)
    if active_plan:
        lines.append("CURRENT PLAN: " + json_block(active_plan))
    lines.append(
        "Look at the attached screenshot. Reply with the next JSON decision only."
    )
    return "\n".join(lines)
