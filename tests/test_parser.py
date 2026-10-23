from __future__ import annotations

import json

import pytest

from app.agent.parser import (
    AgentAction,
    ParseError,
    extract_json,
    parse_decision,
)


def test_parses_fenced_json_with_plan_and_actions():
    raw = """Here is my move:
```json
{
  "thought": "The path north is open.",
  "plan": ["Go north", "Enter the grass"],
  "actions": [
    {"buttons": ["up"], "frames": 20},
    {"buttons": ["a"], "frames": 4}
  ],
  "memory": "Route 1 is north.",
  "done": false
}
```
"""
    decision = parse_decision(raw, max_actions=8, max_frames=240)
    assert decision.thought == "The path north is open."
    assert decision.plan == ["Go north", "Enter the grass"]
    assert decision.actions == [AgentAction(("up",), 20), AgentAction(("a",), 4)]
    assert decision.memory == "Route 1 is north."
    assert decision.done is False


def test_parses_bare_action_strings_and_aliases():
    decision = parse_decision(
        '{"action": "press a for 6 then move north 12, enter", "plan": "1. Open menu\\n2. Choose"}'
    )
    assert decision.actions == [
        AgentAction(("a",), 6),
        AgentAction(("up",), 12),
        AgentAction(("start",), 4),
    ]
    assert decision.plan == ["Open menu", "Choose"]


def test_plan_list_markers_do_not_eat_real_digits():
    decision = parse_decision(
        '{"plan": "1. Reach Route 1\\n- Cross Route 1\\n• Beat gym 1", "actions": [{"buttons": "a"}]}'
    )
    assert decision.plan == ["Reach Route 1", "Cross Route 1", "Beat gym 1"]


def test_parses_singular_and_bare_button_maps():
    assert parse_decision('{"button": "b", "hold": 9}').actions == [AgentAction(("b",), 9)]
    assert parse_decision('{"up": 11}').actions == [AgentAction(("up",), 11)]
    # An alias key that does not map to a button must not create a None action.
    assert parse_decision('{"enter": 4, "down": 8}').actions == [AgentAction(("start",), 4), AgentAction(("down",), 8)]


def test_repeat_and_sequence_forms():
    decision = parse_decision(
        json.dumps(
            {
                "actions": [
                    {"buttons": "left", "frames": 8, "repeat": 2},
                    {"sequence": ["down 4", "right 4"]},
                ]
            }
        )
    )
    assert decision.actions == [
        AgentAction(("left",), 8),
        AgentAction(("left",), 8),
        AgentAction(("down",), 4),
        AgentAction(("right",), 4),
    ]


def test_limits_are_enforced():
    decision = parse_decision(
        '{"actions": [{"buttons": "a", "frames": 9999}, {"buttons": "b"}, {"buttons": "up"}]}',
        max_actions=2,
        max_frames=30,
    )
    assert decision.actions == [AgentAction(("a",), 30), AgentAction(("b",), 4)]


def test_multiple_objects_first_decision_wins():
    payload = extract_json('noise {"foo": 1} then {"thought": "second", "actions": [{"buttons": "a"}]}')
    assert payload["thought"] == "second"


def test_invalid_responses_raise_parse_error():
    with pytest.raises(ParseError):
        parse_decision("")
    with pytest.raises(ParseError):
        parse_decision("I cannot help with that.")
    with pytest.raises(ParseError):
        parse_decision('{"thought": "nothing to do", "actions": []}')
    with pytest.raises(ParseError):
        parse_decision("[1, 2, 3]")
