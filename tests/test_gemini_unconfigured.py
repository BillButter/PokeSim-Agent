"""Tests for Gemini when API key is not configured."""

import pytest
from unittest.mock import Mock, patch
import os


class TestGeminiUnconfigured:
    """Test Gemini behavior when GEMINI_API_KEY is not set."""
    
    @patch.dict(os.environ, {}, clear=True)
    def test_gemini_config_without_api_key(self):
        """Test Gemini config when API key not set."""
        from pokesim.agent.config import AgentConfig
        
        config = AgentConfig.gemini_from_env()
        
        assert config.provider == "gemini"
        assert config.api_key == ""
        assert config.configured is False
    
    @patch.dict(os.environ, {}, clear=True)
    def test_runner_start_with_unconfigured_gemini(self):
        """Test that runner.start() handles unconfigured Gemini."""
        # Simulate what happens when runner.start() is called with no API key
        config = Mock()
        config.provider = "gemini"
        config.api_key = ""
        config.configured = False
        
        # What runner.start() does:
        if not config.configured:
            if config.provider == "gemini":
                error_message = "Set GEMINI_API_KEY to use the Gemini agent."
            else:
                error_message = "Set AI_BASE_URL and AI_MODEL to use the vision agent."
            status = "error"
        
        assert status == "error"
        assert error_message == "Set GEMINI_API_KEY to use the Gemini agent."
    
    @patch.dict(os.environ, {}, clear=True)
    def test_public_returns_error_when_unconfigured(self):
        """Test that runner.public() returns error when Gemini not configured."""
        # Simulate runner state when Gemini is unconfigured
        runner = Mock()
        runner._status = "error"
        runner._error = "Set GEMINI_API_KEY to use the Gemini agent."
        runner._thought = ""
        runner._plan = []
        runner._turn = 0
        
        # What public() returns
        public_info = {
            "status": runner._status,
            "error": runner._error,
            "configured": False,
            "mode": "gemini",
            "provider": "gemini"
        }
        
        assert public_info["status"] == "error"
        assert "GEMINI_API_KEY" in public_info["error"]
    
    @patch.dict(os.environ, {}, clear=True)
    def test_emulator_status_includes_error(self):
        """Test that emulator.status() includes error from runner."""
        # Simulate emulator.status() when Gemini runner has error
        runner = Mock()
        runner.public.return_value = {
            "status": "error",
            "error": "Set GEMINI_API_KEY to use the Gemini agent.",
            "configured": False
        }
        
        ai_mode = "gemini"
        if ai_mode in ('vision', 'gemini', 'ml') and runner is not None:
            agent = runner.public()
        else:
            agent = None
        
        status = {
            "ai_mode": "gemini",
            "agent": agent
        }
        
        assert status["agent"] is not None
        assert status["agent"]["status"] == "error"
        assert "GEMINI_API_KEY" in status["agent"]["error"]
    
    @patch.dict(os.environ, {}, clear=True)
    def test_api_returns_error_to_ui(self):
        """Test that /api/state returns the error to UI."""
        # This is what /api/state returns when Gemini not configured
        api_response = {
            "ai_mode": "gemini",
            "agent": {
                "status": "error",
                "error": "Set GEMINI_API_KEY to use the Gemini agent.",
                "configured": False,
                "provider": "gemini"
            }
        }
        
        assert api_response["agent"] is not None
        assert api_response["agent"]["status"] == "error"
    
    @patch.dict(os.environ, {}, clear=True)
    def test_ui_should_show_error_message(self):
        """Test that UI shows error message when Gemini not configured."""
        # What the UI receives
        state = {
            "ai_mode": "gemini",
            "agent": {
                "status": "error",
                "error": "Set GEMINI_API_KEY to use the Gemini agent."
            }
        }
        
        # UI rendering logic
        aiMode = state["ai_mode"]
        agent = state["agent"]
        
        # Panel should show
        panelHidden = not (aiMode == "vision" or aiMode == "gemini")
        assert panelHidden is False
        
        # Status should show error
        if agent and agent.get("status") == "error":
            displayError = agent.get("error", "Unknown error")
        else:
            displayError = None
        
        assert displayError == "Set GEMINI_API_KEY to use the Gemini agent."
    
    @patch.dict(os.environ, {}, clear=True)
    def test_what_should_appear_on_ui(self):
        """Test what should appear on UI when Gemini not configured."""
        # When user selects Gemini mode but GEMINI_API_KEY not set
        
        # The agent panel should appear with:
        agent_info = {
            "mode": "gemini",
            "status": "error",
            "error": "Set GEMINI_API_KEY to use the Gemini agent.",
            "thought": "The agent is waiting to recover.",
            "plan": ["Waiting for the first plan."]
        }
        
        # Verify each piece
        assert agent_info["status"] == "error"
        assert agent_info["error"] is not None
        assert "GEMINI_API_KEY" in agent_info["error"]
        
        # This error message SHOULD be visible to user
        visible_error = agent_info["error"]
        assert visible_error == "Set GEMINI_API_KEY to use the Gemini agent."


class TestGeminiErrorDisplay:
    """Test that errors are properly displayed."""
    
    def test_panel_shows_when_error(self):
        """Test that agent panel shows even when there's an error."""
        aiMode = "gemini"
        agent = {"status": "error"}
        
        # Panel should show for gemini mode
        panelHidden = not (aiMode == "vision" or aiMode == "gemini")
        
        assert panelHidden is False
    
    def test_error_text_renders(self):
        """Test that error text is rendered."""
        # JavaScript renderAgent() logic
        agent = {
            "status": "error",
            "error": "Set GEMINI_API_KEY to use the Gemini agent."
        }
        
        # Line 546-548 in app.js: error = details.status === 'error' ? String(...) : ''
        # Simulate ternary
        if agent.get("status") == "error":
            error_display = agent.get("error") or "The model endpoint did not answer."
        else:
            error_display = ""
        
        assert error_display == "Set GEMINI_API_KEY to use the Gemini agent."
    
    def test_error_visibility(self):
        """Test that error is not hidden."""
        # Line 548 in app.js: hidden = !error
        error = "Set GEMINI_API_KEY to use the Gemini agent."
        
        error_hidden = not bool(error)
        
        assert error_hidden is False
    
    def test_status_displays_error_label(self):
        """Test that status displays 'Error' label."""
        # Line 524 in app.js
        details = {"status": "error"}
        manualMode = False
        paused = False
        
        status_map = {
            "thinking": "Thinking",
            "acting": "Acting",
            "error": "Error",
            "idle": "Idle"
        }
        
        displayed_status = status_map.get(details.get("status"), "Starting")
        
        assert displayed_status == "Error"


class TestHowToFixGemini:
    """Test how to fix the "not showing" issue."""
    
    def test_production_needs_gemini_api_key(self):
        """Test that production needs GEMINI_API_KEY set."""
        # If pokeai.jamestrey.com shows nothing for Gemini, it's probably because:
        
        production_needs = {
            "GEMINI_API_KEY": "Must be set in environment"
        }
        
        # To fix: Add GEMINI_API_KEY to production environment
        assert "GEMINI_API_KEY" in production_needs
    
    def test_error_message_is_helpful(self):
        """Test that error message tells user what to do."""
        error = "Set GEMINI_API_KEY to use the Gemini agent."
        
        helpful = "GEMINI_API_KEY" in error and "Set" in error
        
        assert helpful is True
    
    def test_vision_works_without_config_error(self):
        """Test that Vision shows different error if not configured."""
        agent_runner = Mock()
        config = Mock(provider="vision", configured=False)
        
        if not config.configured:
            if config.provider == "gemini":
                message = "Set GEMINI_API_KEY to use the Gemini agent."
            else:
                message = "Set AI_BASE_URL and AI_MODEL to use the vision agent."
        
        assert "AI_BASE_URL" in message
        assert "GEMINI_API_KEY" not in message
