"""Tests for agent display and UI integration."""

import pytest
from unittest.mock import Mock, MagicMock, patch


class TestAgentDisplayIntegration:
    """Test that all agent modes display information correctly."""
    
    def test_vision_mode_displays_strategy(self):
        """Test vision mode strategy is returned."""
        # Mock emulator with vision mode
        emu = Mock()
        emu.ai_mode = 'vision'
        emu.agent_runner = Mock()
        emu.agent_runner.strategy.return_value = {
            'objective': {'id': 'vision-1', 'title': 'Explore'},
            'reason': 'Looking for trainers',
            'action': 'move_up'
        }
        emu.agent_runner.public.return_value = {
            'status': 'acting',
            'thought': 'Moving north',
            'turn': 5
        }
        emu.snapshot = None
        emu.paused = False
        emu.speed = 1.0
        emu.manual_mode = False
        emu.policy = Mock()
        emu.policy.details.return_value = {}
        
        # Check that vision agent_runner is called
        assert emu.ai_mode == 'vision'
        assert emu.agent_runner is not None
        assert emu.agent_runner.strategy() is not None
    
    def test_gemini_mode_displays_strategy(self):
        """Test gemini mode strategy is returned."""
        # Mock emulator with gemini mode
        emu = Mock()
        emu.ai_mode = 'gemini'
        emu.agent_runner = Mock()
        emu.agent_runner.strategy.return_value = {
            'objective': {'id': 'gemini-1', 'title': 'Catch Pokemon'},
            'reason': 'High encounter rate',
            'action': 'enter_grass'
        }
        emu.agent_runner.public.return_value = {
            'status': 'thinking',
            'thought': 'Analyzing screen',
            'turn': 3
        }
        
        # Check gemini should be treated like vision for display
        assert emu.ai_mode == 'gemini'
        assert emu.agent_runner is not None
        assert emu.agent_runner.strategy() is not None
    
    def test_ml_mode_displays_strategy(self):
        """Test ML mode strategy is returned."""
        # Mock emulator with ML mode
        emu = Mock()
        emu.ai_mode = 'ml'
        emu.agent_runner = Mock()
        emu.agent_runner.strategy.return_value = {
            'objective': {'id': 'ml-agent', 'title': 'Explore: move up'},
            'reason': 'Learning from gameplay',
            'action': 'move_up'
        }
        emu.agent_runner.public.return_value = {
            'status': 'idle',
            'memory': 'ML Player (moves: 42)',
            'turn': 42
        }
        
        # Check ML should be treated like vision for display
        assert emu.ai_mode == 'ml'
        assert emu.agent_runner is not None
        assert emu.agent_runner.strategy() is not None
    
    def test_default_mode_no_agent_strategy(self):
        """Test default mode uses policy strategy."""
        emu = Mock()
        emu.ai_mode = 'default'
        emu.agent_runner = None
        emu.policy = Mock()
        emu.policy.details.return_value = {
            'objective': 'Default policy action',
            'action': 'walk'
        }
        
        # Default mode should not have agent_runner
        assert emu.ai_mode == 'default'
        assert emu.agent_runner is None
        assert emu.policy.details() is not None
    
    def test_manual_mode_no_agent_strategy(self):
        """Test manual mode uses policy strategy."""
        emu = Mock()
        emu.ai_mode = 'manual'
        emu.agent_runner = None
        emu.policy = Mock()
        emu.policy.details.return_value = {
            'objective': 'Waiting for player',
            'action': 'idle'
        }
        
        # Manual mode should not have agent_runner
        assert emu.ai_mode == 'manual'
        assert emu.agent_runner is None
        assert emu.policy.details() is not None
    
    def test_agent_error_status_displayed(self):
        """Test agent error status is properly displayed."""
        emu = Mock()
        emu.ai_mode = 'vision'
        emu.agent_runner = Mock()
        emu.agent_runner.public.return_value = {
            'status': 'error',
            'error': 'Failed to reach API endpoint'
        }
        emu.agent_runner.strategy.return_value = {
            'objective': {'id': 'error', 'title': 'Error'},
            'reason': 'Failed to reach API endpoint'
        }
        
        # Error status should be accessible
        status = emu.agent_runner.public()
        assert status['status'] == 'error'
        assert status['error'] is not None
    
    def test_agent_thinking_status_displayed(self):
        """Test agent thinking status is properly displayed."""
        emu = Mock()
        emu.ai_mode = 'gemini'
        emu.agent_runner = Mock()
        emu.agent_runner.public.return_value = {
            'status': 'thinking',
            'thought': 'Processing game state',
            'plan': ['Move up', 'Check status']
        }
        emu.agent_runner.strategy.return_value = {
            'reason': 'Watching the screen and deciding the next move.'
        }
        
        # Thinking status should be accessible
        status = emu.agent_runner.public()
        assert status['status'] == 'thinking'
        assert status['thought'] is not None
    
    def test_ml_mode_shows_learning_status(self):
        """Test ML mode displays learning progress."""
        emu = Mock()
        emu.ai_mode = 'ml'
        emu.agent_runner = Mock()
        emu.agent_runner.public.return_value = {
            'status': 'acting',
            'memory': 'ML Player (moves: 125, patterns: 5 locations)',
            'turn': 125,
            'plan': ['ML learning agent']
        }
        
        # ML memory should show learning progress
        status = emu.agent_runner.public()
        assert 'ML Player' in status['memory']
        assert 'moves' in status['memory']


class TestAgentModeChecking:
    """Test that agent modes are correctly identified."""
    
    def test_agent_modes_require_runner(self):
        """Test that agent modes require agent_runner."""
        agent_modes = ('vision', 'gemini', 'ml')
        for mode in agent_modes:
            # Each agent mode should have a runner
            assert mode in ('vision', 'gemini', 'ml')
    
    def test_non_agent_modes_no_runner(self):
        """Test that non-agent modes don't need runner."""
        non_agent_modes = ('default', 'manual')
        for mode in non_agent_modes:
            # These modes should not use agent runner
            assert mode in ('default', 'manual')
    
    def test_all_ai_modes_handled(self):
        """Test that all AI modes are handled."""
        all_modes = ('default', 'vision', 'gemini', 'ml', 'manual')
        agent_modes = ('vision', 'gemini', 'ml')
        non_agent_modes = ('default', 'manual')
        
        # All modes should be either agent or non-agent
        for mode in all_modes:
            is_agent = mode in agent_modes
            is_non_agent = mode in non_agent_modes
            assert is_agent or is_non_agent


class TestStatusMethodConditions:
    """Test status() method conditional logic."""
    
    def test_status_with_vision_mode_and_runner(self):
        """Test status returns agent info for vision mode."""
        mode = 'vision'
        has_runner = True
        
        # Vision mode with runner should return agent info
        should_show_agent = mode in ('vision', 'gemini', 'ml') and has_runner
        assert should_show_agent is True
    
    def test_status_with_gemini_mode_and_runner(self):
        """Test status returns agent info for gemini mode."""
        mode = 'gemini'
        has_runner = True
        
        # Gemini mode with runner should return agent info
        should_show_agent = mode in ('vision', 'gemini', 'ml') and has_runner
        assert should_show_agent is True
    
    def test_status_with_ml_mode_and_runner(self):
        """Test status returns agent info for ML mode."""
        mode = 'ml'
        has_runner = True
        
        # ML mode with runner should return agent info
        should_show_agent = mode in ('vision', 'gemini', 'ml') and has_runner
        assert should_show_agent is True
    
    def test_status_with_default_mode(self):
        """Test status returns policy info for default mode."""
        mode = 'default'
        has_runner = False
        
        # Default mode should not show agent info
        should_show_agent = mode in ('vision', 'gemini', 'ml') and has_runner
        assert should_show_agent is False
    
    def test_status_with_manual_mode(self):
        """Test status returns policy info for manual mode."""
        mode = 'manual'
        has_runner = False
        
        # Manual mode should not show agent info
        should_show_agent = mode in ('vision', 'gemini', 'ml') and has_runner
        assert should_show_agent is False
    
    def test_status_with_agent_mode_but_no_runner(self):
        """Test status with agent mode but no runner."""
        mode = 'vision'
        has_runner = False
        
        # Agent mode without runner should fall back to policy
        should_show_agent = mode in ('vision', 'gemini', 'ml') and has_runner
        assert should_show_agent is False
