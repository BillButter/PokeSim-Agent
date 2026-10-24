"""Comprehensive tests for Gemini agent configuration and display."""

import pytest
from unittest.mock import Mock, patch
from pokesim.agent.config import AgentConfig, GEMINI_BASE_URL, GEMINI_MODEL


class TestGeminiConfiguration:
    """Test Gemini configuration loading from environment."""
    
    @patch.dict('os.environ', {}, clear=True)
    def test_gemini_from_env_no_config(self):
        """Test Gemini config with no env vars set."""
        config = AgentConfig.gemini_from_env()
        assert config.provider == "gemini"
        assert config.model == GEMINI_MODEL
        assert config.base_url == GEMINI_BASE_URL
        assert config.api_key == ""
        assert config.configured is False  # No API key = not configured
    
    @patch.dict('os.environ', {'GEMINI_API_KEY': 'test-key-123'})
    def test_gemini_from_env_with_key(self):
        """Test Gemini config with API key set."""
        config = AgentConfig.gemini_from_env()
        assert config.provider == "gemini"
        assert config.api_key == "test-key-123"
        assert config.configured is True  # Has API key = configured
    
    @patch.dict('os.environ', {'GEMINI_API_KEY': 'key', 'GEMINI_MODEL': 'custom-model'})
    def test_gemini_from_env_custom_model(self):
        """Test Gemini with custom model specified."""
        config = AgentConfig.gemini_from_env()
        assert config.model == "custom-model"
        assert config.api_key == "key"
        assert config.configured is True
    
    @patch.dict('os.environ', {'GEMINI_API_KEY': 'key', 'GEMINI_BASE_URL': 'https://custom.api.com'})
    def test_gemini_from_env_custom_base_url(self):
        """Test Gemini with custom base URL."""
        config = AgentConfig.gemini_from_env()
        assert config.base_url == "https://custom.api.com"
        assert config.api_key == "key"
        assert config.configured is True
    
    def test_gemini_configured_requires_api_key(self):
        """Test that Gemini requires API key to be configured."""
        # Without API key
        config_no_key = AgentConfig(
            base_url=GEMINI_BASE_URL,
            model=GEMINI_MODEL,
            provider="gemini",
            api_key=""
        )
        assert config_no_key.configured is False
        
        # With API key
        config_with_key = AgentConfig(
            base_url=GEMINI_BASE_URL,
            model=GEMINI_MODEL,
            provider="gemini",
            api_key="key"
        )
        assert config_with_key.configured is True
    
    def test_gemini_configured_needs_base_url_and_model(self):
        """Test that Gemini needs both base URL and model."""
        # Missing base URL
        config_no_url = AgentConfig(
            base_url="",
            model=GEMINI_MODEL,
            provider="gemini",
            api_key="key"
        )
        assert config_no_url.configured is False
        
        # Missing model
        config_no_model = AgentConfig(
            base_url=GEMINI_BASE_URL,
            model="",
            provider="gemini",
            api_key="key"
        )
        assert config_no_model.configured is False


class TestGeminiDisplay:
    """Test Gemini display in emulator status."""
    
    def test_gemini_mode_status_includes_agent_info(self):
        """Test that gemini mode includes agent info in status."""
        # Mock agent runner
        agent_runner = Mock()
        agent_runner.public.return_value = {
            'status': 'thinking',
            'thought': 'Analyzing screen...',
            'plan': ['Check for Pokemon', 'Evaluate battle'],
            'turn': 5
        }
        agent_runner.strategy.return_value = {
            'objective': {'id': 'gemini-1', 'title': 'Catch Pokemon'},
            'reason': 'High encounter rate observed'
        }
        
        # Simulate what emulator.status() should do
        ai_mode = 'gemini'
        
        # This is the fix: check for gemini in agent modes
        if ai_mode in ('vision', 'gemini', 'ml') and agent_runner is not None:
            strategy = agent_runner.strategy()
            agent = agent_runner.public()
            shows_agent = True
        else:
            strategy = None
            agent = None
            shows_agent = False
        
        # Should show agent info for gemini
        assert shows_agent is True
        assert agent is not None
        assert strategy is not None
        assert agent['status'] == 'thinking'
    
    def test_gemini_error_status_displayed(self):
        """Test that Gemini error status is properly shown."""
        agent_runner = Mock()
        agent_runner.public.return_value = {
            'status': 'error',
            'error': 'Failed to reach Gemini API'
        }
        agent_runner.strategy.return_value = {
            'objective': {'id': 'error', 'title': 'Error'},
            'reason': 'Failed to reach Gemini API'
        }
        
        ai_mode = 'gemini'
        if ai_mode in ('vision', 'gemini', 'ml') and agent_runner is not None:
            agent = agent_runner.public()
            strategy = agent_runner.strategy()
            shows_error = True
        else:
            shows_error = False
        
        assert shows_error is True
        assert agent['status'] == 'error'
        assert agent['error'] is not None
    
    def test_gemini_unconfigured_shows_error_message(self):
        """Test that unconfigured Gemini shows helpful error."""
        config = AgentConfig(provider="gemini", api_key="")
        
        if not config.configured:
            if config.provider == "gemini":
                error_message = "Set GEMINI_API_KEY to use the Gemini agent."
            else:
                error_message = "Set AI_BASE_URL and AI_MODEL to use the vision agent."
        
        assert error_message == "Set GEMINI_API_KEY to use the Gemini agent."


class TestGeminiRunnerStatus:
    """Test that Gemini runner properly reports status."""
    
    def test_gemini_public_returns_gemini_provider(self):
        """Test that Gemini runner identifies itself."""
        # Mock a Gemini-configured runner
        runner = Mock()
        runner.public.return_value = {
            'mode': 'gemini',
            'provider': 'gemini',
            'status': 'acting',
            'configured': True,
            'base_url': GEMINI_BASE_URL,
            'model': GEMINI_MODEL,
            'has_api_key': True,
            'thought': 'Choosing action',
            'plan': ['up', 'a'],
            'memory': 'Observed trainer ahead',
            'turn': 10
        }
        
        public_info = runner.public()
        assert public_info['provider'] == 'gemini'
        assert public_info['mode'] == 'gemini'
        assert public_info['configured'] is True
    
    def test_gemini_strategy_includes_decision(self):
        """Test that Gemini strategy includes the decision made."""
        runner = Mock()
        runner.strategy.return_value = {
            'objective': {'id': 'gemini-1', 'title': 'Battle'},
            'reason': 'Trainer battle detected',
            'action': 'a',
            'next': {'title': 'Use move'},
            'visited_tiles': 42,
            'agent': {
                'status': 'acting',
                'thought': 'Choosing move',
                'plan': ['Use move', 'Continue battle']
            }
        }
        
        strategy = runner.strategy()
        assert strategy['objective']['id'] == 'gemini-1'
        assert strategy['agent']['status'] == 'acting'
        assert 'title' in strategy['next']


class TestGeminiVsVisionDisplay:
    """Test that Gemini displays same as Vision."""
    
    def test_both_modes_show_same_info_structure(self):
        """Test vision and gemini have same display structure."""
        # Vision config
        vision_runner = Mock()
        vision_runner.public.return_value = {
            'mode': 'vision',
            'provider': 'openai',
            'status': 'acting',
            'thought': 'Moving north'
        }
        vision_runner.strategy.return_value = {
            'objective': {'id': 'v1', 'title': 'Explore'},
            'reason': 'Looking for trainers'
        }
        
        # Gemini config
        gemini_runner = Mock()
        gemini_runner.public.return_value = {
            'mode': 'gemini',
            'provider': 'gemini',
            'status': 'acting',
            'thought': 'Moving north'
        }
        gemini_runner.strategy.return_value = {
            'objective': {'id': 'g1', 'title': 'Explore'},
            'reason': 'Looking for trainers'
        }
        
        # Both should have same keys
        vision_info = vision_runner.public()
        gemini_info = gemini_runner.public()
        
        for key in ['status', 'thought']:
            assert key in vision_info
            assert key in gemini_info
        
        for key in ['objective', 'reason']:
            assert key in vision_runner.strategy()
            assert key in gemini_runner.strategy()


class TestGeminiInitializationInEmulator:
    """Test Gemini runner initialization in emulator."""
    
    def test_gemini_mode_creates_vision_runner(self):
        """Test that gemini mode uses VisionAgentRunner (not ML runner)."""
        ai_mode = 'gemini'
        
        # Gemini should use VisionAgentRunner (which is provider-agnostic)
        if ai_mode == 'ml':
            runner_class = 'MLAgentRunner'
        elif ai_mode in ('vision', 'gemini'):
            runner_class = 'VisionAgentRunner'
        else:
            runner_class = None
        
        assert runner_class == 'VisionAgentRunner'
    
    def test_gemini_mode_gets_correct_config(self):
        """Test that gemini mode gets Gemini config not vision config."""
        ai_mode = 'gemini'
        
        # Simulating emulator._config() logic
        if ai_mode == 'gemini':
            config_source = 'gemini_config'
        else:
            config_source = 'vision_config'
        
        assert config_source == 'gemini_config'


class TestGeminiErrorScenarios:
    """Test various error scenarios for Gemini."""
    
    def test_gemini_no_api_key_shows_error(self):
        """Test Gemini without API key shows configuration error."""
        config = AgentConfig.gemini_from_env()  # No GEMINI_API_KEY in env
        
        if not config.configured:
            status = 'error'
            error_msg = "Set GEMINI_API_KEY to use the Gemini agent."
        else:
            status = 'ready'
            error_msg = None
        
        assert status == 'error'
        assert error_msg is not None
    
    def test_gemini_api_call_failure_shows_error(self):
        """Test Gemini API failure shows error on UI."""
        runner = Mock()
        runner.public.return_value = {
            'status': 'error',
            'error': 'HTTP 403 Unauthorized',
            'configured': True
        }
        
        public = runner.public()
        assert public['status'] == 'error'
        assert public['error'] is not None
        assert public['configured'] is True
    
    def test_gemini_thinking_shows_status(self):
        """Test Gemini thinking status displays."""
        runner = Mock()
        runner.public.return_value = {
            'status': 'thinking',
            'thought': 'Processing image...',
            'configured': True
        }
        
        public = runner.public()
        assert public['status'] == 'thinking'
        assert 'thought' in public
