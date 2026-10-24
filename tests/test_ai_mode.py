"""The per-game AI selector without needing a ROM or generated game data."""

import json
import re
from pathlib import Path

import pytest

from pokesim.agent.config import AgentConfig
from pokesim.agent.memory import RollingMemory
from pokesim.agent.parser import ParseError, parse_decision
from pokesim.app.manager import Manager


def test_agent_config_is_server_wide(monkeypatch):
    monkeypatch.setenv('AI_BASE_URL', 'http://localhost:11434/v1')
    monkeypatch.setenv('AI_API_KEY', 'secret')
    monkeypatch.setenv('AI_MODEL', 'vision-model')
    monkeypatch.setenv('AI_MAX_FRAMES', '240')
    config = AgentConfig.from_env()
    assert config.configured
    assert config.model == 'vision-model'
    public = config.public()
    assert public['configured'] is True
    assert public['has_api_key'] is True
    assert 'secret' not in str(public)
    assert config.max_frames == 240


def test_agent_config_accepts_openai_names(monkeypatch):
    monkeypatch.delenv('AI_BASE_URL', raising=False)
    monkeypatch.delenv('AI_MODEL', raising=False)
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://api.example.com/v1')
    monkeypatch.setenv('OPENAI_MODEL', 'gpt-vision')
    assert AgentConfig.from_env().configured


def test_decision_parser_normalises_actions():
    decision = parse_decision(
        '```json\n{"thought":"walk","plan":["Route 1"],'
        '"actions":[{"buttons":"up","frames":999},{"press":"A","hold":2}]}\n```',
        max_actions=8,
        max_frames=120,
    )
    assert decision.thought == 'walk'
    assert decision.plan == ['Route 1']
    assert decision.actions[0].buttons == ('up',)
    assert decision.actions[0].frames == 120
    assert decision.actions[1].buttons == ('a',)
    assert decision.actions[1].frames == 2


def test_decision_parser_rejects_empty_output():
    with pytest.raises(ParseError):
        parse_decision('   ')


def test_adventure_settings_default_and_validation():
    assert Manager.validate_adventure_settings({})['ai_mode'] == 'default'
    assert Manager.validate_adventure_settings({'ai_mode': 'vision'})['ai_mode'] == 'vision'
    assert Manager.validate_adventure_settings({'ai_mode': 'manual'})['ai_mode'] == 'manual'
    with pytest.raises(ValueError, match='AI player'):
        Manager.validate_adventure_settings({'ai_mode': 'automatic'})


def test_rolling_memory_returns_recent_image_plan_and_note():
    memory = RollingMemory(max_turns=2, image_history=1)
    decision = parse_decision(
        '{"thought":"walk north","plan":["Reach Route 1","Find Viridian"],'
        '"actions":[{"buttons":["up"],"frames":24}],"memory":"Oak lab is south"}',
        max_actions=8,
        max_frames=120,
    )
    memory.add(
        state={"map_name": "Pallet Town", "party": [{"name": "Bulbasaur", "hp": 20, "max_hp": 20}],
               "badges": [], "money": 3000},
        delta={"money": {"from": 2500, "to": 3000}},
        decision=decision,
        result="UP",
        image_b64="cG5n",
    )
    messages = memory.build_messages(
        state={"map_name": "Pallet Town", "party": [{"name": "Bulbasaur", "hp": 20, "max_hp": 20}],
               "badges": [], "money": 3000},
        delta={}, image_b64=None, game_title="Pokémon Red",
        max_actions=8, max_frames=120,
    )
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert any(part.get("type") == "image_url" for part in messages[1]["content"])
    assert messages[2]["role"] == "assistant"
    assert json.loads(messages[2]["content"])["memory"] == "Oak lab is south"
    assert "CURRENT PLAN" in messages[-1]["content"][0]["text"]
    assert "Bulbasaur" in messages[-1]["content"][0]["text"]


def test_adventure_forms_order_the_ai_players():
    root = Path(__file__).resolve().parents[1]
    html = (root / 'pokesim/web/static/library.html').read_text()
    for element_id in ('new-ai-mode', 'settings-ai-mode'):
        match = re.search(rf'id="{element_id}"(.*?)</select>', html, re.S)
        assert match, element_id
        values = re.findall(r'<option value="([^"]+)"', match.group(1))
        assert values == ['default', 'vision', 'gemini', 'manual']


def test_quadlet_public_url_matches_its_published_address():
    root = Path(__file__).resolve().parents[1]
    unit = (root / 'deploy/pokesim-agent.container').read_text()
    assert 'PublishPort=127.0.0.1:8000:8000' in unit
    assert 'Environment=PUBLIC_URL=http://127.0.0.1:8000' in unit
