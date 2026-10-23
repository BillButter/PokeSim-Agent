"""The per-game AI selector without needing a ROM or generated game data."""

import pytest

from pokesim.agent.config import AgentConfig
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
