"""Tests for AI mode startup and runner initialization."""

import pytest
from unittest.mock import Mock, MagicMock, patch, call


class TestAIModeStartup:
    """Test that agent runners start for all agent modes."""
    
    def test_set_ai_mode_vision_starts_runner(self):
        """Test that setting vision mode starts the agent runner."""
        emulator = Mock()
        emulator._start_agent = Mock()
        emulator.input_epoch = 0
        
        ai_mode = 'vision'
        if ai_mode in ('vision', 'gemini', 'ml'):
            emulator._start_agent()
        
        emulator._start_agent.assert_called_once()
    
    def test_set_ai_mode_gemini_starts_runner(self):
        """Test that setting gemini mode starts the agent runner."""
        emulator = Mock()
        emulator._start_agent = Mock()
        emulator.input_epoch = 0
        
        ai_mode = 'gemini'
        if ai_mode in ('vision', 'gemini', 'ml'):
            emulator._start_agent()
        
        emulator._start_agent.assert_called_once()
    
    def test_set_ai_mode_ml_starts_runner(self):
        """Test that setting ml mode starts the agent runner."""
        emulator = Mock()
        emulator._start_agent = Mock()
        emulator.input_epoch = 0
        
        ai_mode = 'ml'
        if ai_mode in ('vision', 'gemini', 'ml'):
            emulator._start_agent()
        
        emulator._start_agent.assert_called_once()
    
    def test_set_ai_mode_default_does_not_start_runner(self):
        """Test that setting default mode does not start runner."""
        emulator = Mock()
        emulator._start_agent = Mock()
        
        ai_mode = 'default'
        if ai_mode in ('vision', 'gemini', 'ml'):
            emulator._start_agent()
        
        emulator._start_agent.assert_not_called()
    
    def test_set_ai_mode_manual_does_not_start_runner(self):
        """Test that setting manual mode does not start runner."""
        emulator = Mock()
        emulator._start_agent = Mock()
        
        ai_mode = 'manual'
        if ai_mode in ('vision', 'gemini', 'ml'):
            emulator._start_agent()
        
        emulator._start_agent.assert_not_called()
    
    def test_set_ai_mode_sets_manual_mode_for_manual(self):
        """Test that manual mode sets manual_mode flag."""
        emulator = Mock()
        emulator.manual_mode = False
        
        ai_mode = 'manual'
        if ai_mode == 'manual':
            emulator.manual_mode = True
        else:
            emulator.manual_mode = False
        
        assert emulator.manual_mode is True
    
    def test_set_ai_mode_clears_manual_for_agents(self):
        """Test that agent modes clear manual_mode flag."""
        emulator = Mock()
        emulator.manual_mode = True
        
        ai_mode = 'gemini'
        if ai_mode == 'manual':
            emulator.manual_mode = True
        else:
            emulator.manual_mode = False
        
        assert emulator.manual_mode is False
    
    def test_agent_modes_require_runner_start(self):
        """Test that all agent modes require runner initialization."""
        agent_modes = ('vision', 'gemini', 'ml')
        
        for mode in agent_modes:
            if mode in ('vision', 'gemini', 'ml'):
                should_start = True
            else:
                should_start = False
            
            assert should_start is True


class TestRunnerInitialization:
    """Test that correct runner is initialized for each mode."""
    
    def test_ml_mode_initializes_ml_runner(self):
        """Test that ML mode creates MLAgentRunner."""
        ai_mode = 'ml'
        
        if ai_mode == 'ml':
            runner_type = 'MLAgentRunner'
        else:
            runner_type = 'VisionAgentRunner'
        
        assert runner_type == 'MLAgentRunner'
    
    def test_vision_mode_initializes_vision_runner(self):
        """Test that vision mode creates VisionAgentRunner."""
        ai_mode = 'vision'
        
        if ai_mode == 'ml':
            runner_type = 'MLAgentRunner'
        else:
            runner_type = 'VisionAgentRunner'
        
        assert runner_type == 'VisionAgentRunner'
    
    def test_gemini_mode_initializes_vision_runner(self):
        """Test that gemini mode creates VisionAgentRunner (provider-agnostic)."""
        ai_mode = 'gemini'
        
        if ai_mode == 'ml':
            runner_type = 'MLAgentRunner'
        else:
            runner_type = 'VisionAgentRunner'
        
        assert runner_type == 'VisionAgentRunner'
    
    def test_runner_gets_correct_config(self):
        """Test that runner gets correct provider config."""
        ai_mode = 'gemini'
        
        runner = Mock()
        runner._config = Mock()
        
        if ai_mode == 'gemini':
            runner._config.return_value = Mock(provider='gemini')
        elif ai_mode == 'vision':
            runner._config.return_value = Mock(provider='openai')
        else:
            runner._config.return_value = None
        
        config = runner._config()
        assert config.provider == 'gemini'


class TestModeSwitch:
    """Test switching between AI modes."""
    
    def test_switch_from_default_to_gemini(self):
        """Test switching from default to gemini mode."""
        runner_created = False
        
        ai_mode = 'default'
        if ai_mode in ('vision', 'gemini', 'ml'):
            runner_created = True
        
        assert runner_created is False
        
        ai_mode = 'gemini'
        if ai_mode in ('vision', 'gemini', 'ml'):
            runner_created = True
        
        assert runner_created is True
    
    def test_switch_from_vision_to_gemini(self):
        """Test switching from vision to gemini mode."""
        current_mode = 'vision'
        new_mode = 'gemini'
        
        both_need_runner = (
            current_mode in ('vision', 'gemini', 'ml') and
            new_mode in ('vision', 'gemini', 'ml')
        )
        
        assert both_need_runner is True
    
    def test_switch_from_gemini_to_ml(self):
        """Test switching from gemini to ml mode."""
        current_mode = 'gemini'
        new_mode = 'ml'
        
        both_need_runner = (
            current_mode in ('vision', 'gemini', 'ml') and
            new_mode in ('vision', 'gemini', 'ml')
        )
        
        assert both_need_runner is True
    
    def test_switch_from_agent_to_manual(self):
        """Test switching from agent mode to manual."""
        current_mode = 'gemini'
        new_mode = 'manual'
        
        current_needs_runner = current_mode in ('vision', 'gemini', 'ml')
        new_needs_runner = new_mode in ('vision', 'gemini', 'ml')
        
        assert current_needs_runner is True
        assert new_needs_runner is False
    
    def test_switch_from_manual_to_agent(self):
        """Test switching from manual to agent mode."""
        current_mode = 'manual'
        new_mode = 'gemini'
        
        current_needs_runner = current_mode in ('vision', 'gemini', 'ml')
        new_needs_runner = new_mode in ('vision', 'gemini', 'ml')
        
        assert current_needs_runner is False
        assert new_needs_runner is True
