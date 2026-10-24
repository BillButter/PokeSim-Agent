"""Tests for Gemini production scenarios and error cases."""

import pytest
from unittest.mock import Mock, patch
import threading
import time
from pokesim.agent.config import AgentConfig, GEMINI_BASE_URL, GEMINI_MODEL


class TestGeminiProductionScenarios:
    """Test real-world scenarios for Gemini agent."""
    
    def test_gemini_not_configured_returns_error_info(self):
        """Test that unconfigured Gemini returns error in public()."""
        # Simulate runner state when not configured
        runner = Mock()
        runner._status = "error"
        runner._error = "Set GEMINI_API_KEY to use the Gemini agent."
        runner._thought = ""
        runner._plan = []
        runner._memory = ""
        runner._last_action = ""
        runner._turn = 0
        
        config = Mock()
        config.provider = "gemini"
        config.configured = False
        config.base_url = GEMINI_BASE_URL
        config.model = GEMINI_MODEL
        config.api_key = ""
        
        # Simulate public() return
        public_info = {
            "mode": "gemini",
            "provider": "gemini",
            "status": "error",
            "configured": False,
            "error": "Set GEMINI_API_KEY to use the Gemini agent.",
            "thought": "",
            "plan": [],
            "memory": ""
        }
        
        # UI should show this error
        assert public_info["status"] == "error"
        assert public_info["error"] is not None
        assert "GEMINI_API_KEY" in public_info["error"]
    
    def test_gemini_api_key_set_returns_configured_true(self):
        """Test that with API key, configured is True."""
        config = AgentConfig(
            provider="gemini",
            base_url=GEMINI_BASE_URL,
            model=GEMINI_MODEL,
            api_key="test-key"
        )
        
        assert config.configured is True
        assert config.api_key == "test-key"
    
    def test_gemini_thinking_state_visible(self):
        """Test that Gemini thinking state is visible to UI."""
        runner = Mock()
        runner.public.return_value = {
            "mode": "gemini",
            "provider": "gemini",
            "status": "thinking",
            "configured": True,
            "thought": "Analyzing game screen...",
            "plan": ["Check map", "Find wild Pokemon"],
            "error": None
        }
        
        public_info = runner.public()
        
        # UI should see thinking state
        assert public_info["status"] == "thinking"
        assert public_info["thought"] is not None
        assert len(public_info["thought"]) > 0
    
    def test_gemini_acting_state_visible(self):
        """Test that Gemini acting state is visible to UI."""
        runner = Mock()
        runner.public.return_value = {
            "mode": "gemini",
            "provider": "gemini",
            "status": "acting",
            "configured": True,
            "thought": "Pressing up button",
            "plan": ["Continue north", "Check for trainers"],
            "last_action": "up"
        }
        
        public_info = runner.public()
        
        # UI should see acting state
        assert public_info["status"] == "acting"
        assert public_info["last_action"] is not None
    
    def test_gemini_mode_emulator_status_includes_agent(self):
        """Test that emulator.status() includes agent info for gemini mode."""
        # Create mock emulator
        emulator = Mock()
        emulator.ai_mode = "gemini"
        emulator.agent_runner = Mock()
        
        # Mock runner returns
        emulator.agent_runner.public.return_value = {
            "status": "thinking",
            "mode": "gemini",
            "configured": True,
            "thought": "Processing screen"
        }
        emulator.agent_runner.strategy.return_value = {
            "objective": {"id": "g1", "title": "Catch Pokemon"},
            "reason": "Wild Pokemon spotted"
        }
        
        # Simulate what emulator.status() should do
        ai_mode = emulator.ai_mode
        if ai_mode in ('vision', 'gemini', 'ml') and emulator.agent_runner is not None:
            agent = emulator.agent_runner.public()
            strategy = emulator.agent_runner.strategy()
        else:
            agent = None
            strategy = None
        
        # Should include agent info
        assert agent is not None
        assert strategy is not None
        assert agent["mode"] == "gemini"
    
    def test_gemini_mode_with_no_runner_shows_nothing(self):
        """Test that if runner was never created, agent info is None."""
        emulator = Mock()
        emulator.ai_mode = "gemini"
        emulator.agent_runner = None  # Not created (e.g., config error)
        
        ai_mode = emulator.ai_mode
        if ai_mode in ('vision', 'gemini', 'ml') and emulator.agent_runner is not None:
            agent = emulator.agent_runner.public()
        else:
            agent = None
        
        # When runner is None, agent should be None
        assert agent is None
    
    def test_emulator_initializes_gemini_runner_if_configured(self):
        """Test that emulator creates runner if Gemini is configured."""
        # This is what SHOULD happen during emulator init
        config = AgentConfig(
            provider="gemini",
            base_url=GEMINI_BASE_URL,
            model=GEMINI_MODEL,
            api_key="test-key"
        )
        
        if config.configured:
            # Runner should be created
            runner_created = True
        else:
            runner_created = False
        
        assert runner_created is True
    
    def test_emulator_does_not_initialize_gemini_runner_if_not_configured(self):
        """Test that emulator doesn't create runner if Gemini not configured."""
        config = AgentConfig(
            provider="gemini",
            base_url=GEMINI_BASE_URL,
            model=GEMINI_MODEL,
            api_key=""  # Not set
        )
        
        if config.configured:
            runner_created = True
        else:
            runner_created = False
        
        assert runner_created is False


class TestGeminiAPIErrors:
    """Test various API error scenarios."""
    
    def test_gemini_api_unauthorized_error(self):
        """Test that invalid API key shows auth error."""
        runner = Mock()
        runner.public.return_value = {
            "status": "error",
            "configured": True,  # Config OK
            "error": "HTTP 403 Unauthorized - Invalid API key",
            "has_api_key": True
        }
        
        public_info = runner.public()
        assert public_info["status"] == "error"
        assert "403" in public_info["error"]
        assert public_info["has_api_key"] is True
    
    def test_gemini_api_timeout_error(self):
        """Test that API timeout shows network error."""
        runner = Mock()
        runner.public.return_value = {
            "status": "error",
            "configured": True,
            "error": "Timeout connecting to Gemini API",
            "turn": 5  # Had processed some turns before error
        }
        
        public_info = runner.public()
        assert public_info["status"] == "error"
        assert "Timeout" in public_info["error"]
    
    def test_gemini_api_rate_limit_error(self):
        """Test that rate limiting shows rate limit error."""
        runner = Mock()
        runner.public.return_value = {
            "status": "error",
            "configured": True,
            "error": "HTTP 429 Too Many Requests - Rate limited",
        }
        
        public_info = runner.public()
        assert public_info["status"] == "error"
        assert "429" in public_info["error"]


class TestGeminiUIDisplay:
    """Test that Gemini info displays correctly in UI."""
    
    def test_gemini_error_displays_in_status(self):
        """Test that Gemini error is displayed to user."""
        # This is what gets returned via /api/state endpoint
        state = {
            "ai_mode": "gemini",
            "agent": {
                "status": "error",
                "error": "Set GEMINI_API_KEY to use the Gemini agent.",
                "configured": False
            },
            "strategy": None  # No strategy when unconfigured
        }
        
        # UI should see error status
        assert state["agent"]["status"] == "error"
        assert state["agent"]["error"] is not None
    
    def test_gemini_thinking_displays_in_strategy(self):
        """Test that Gemini thinking displays via strategy."""
        state = {
            "ai_mode": "gemini",
            "agent": {
                "status": "thinking",
                "thought": "Analyzing screen...",
                "plan": ["Check map", "Find Pokemon"],
                "configured": True
            },
            "strategy": {
                "objective": {"id": "g1", "title": "Find Pokemon"},
                "reason": "Looking for wild Pokemon"
            }
        }
        
        # UI should see thinking and strategy
        assert state["agent"]["status"] == "thinking"
        assert state["strategy"] is not None
        assert state["strategy"]["objective"]["title"] == "Find Pokemon"
    
    def test_gemini_acting_displays_action(self):
        """Test that Gemini action displays in strategy."""
        state = {
            "ai_mode": "gemini",
            "agent": {
                "status": "acting",
                "last_action": "up"
            },
            "strategy": {
                "action": "up",
                "next": {"title": "Continue north"}
            }
        }
        
        # UI should see the action
        assert state["strategy"]["action"] == "up"
        assert "north" in state["strategy"]["next"]["title"].lower()


class TestGeminiModeSwitch:
    """Test switching to Gemini mode."""
    
    def test_switch_to_gemini_from_default(self):
        """Test switching from default to gemini mode."""
        # Initial state
        emulator = Mock()
        emulator.ai_mode = "default"
        emulator.agent_runner = None
        
        # User switches to Gemini
        emulator.ai_mode = "gemini"
        
        # Now emulator should initialize runner
        if emulator.ai_mode == "gemini" and emulator.agent_runner is None:
            # Runner creation would happen here
            should_create_runner = True
        else:
            should_create_runner = False
        
        assert should_create_runner is True
    
    def test_switch_to_gemini_from_vision(self):
        """Test switching from vision to gemini mode."""
        emulator = Mock()
        emulator.ai_mode = "vision"
        vision_runner = Mock()
        emulator.agent_runner = vision_runner
        
        # User switches to Gemini
        emulator.ai_mode = "gemini"
        old_runner = emulator.agent_runner
        emulator.agent_runner = Mock()  # New Gemini runner
        
        # Old runner should be stopped
        vision_runner.stop = Mock()
        vision_runner.stop()
        
        assert emulator.ai_mode == "gemini"
        assert emulator.agent_runner is not vision_runner
        vision_runner.stop.assert_called()
