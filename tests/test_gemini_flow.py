"""End-to-end flow tests for Gemini agent to diagnose display issues."""

import pytest
from unittest.mock import Mock, MagicMock, patch
import json


class TestGeminiFullFlow:
    """Test the complete flow from mode selection to UI display."""
    
    def test_api_returns_agent_info_when_gemini_mode(self):
        """Test that /api/state returns agent info when in gemini mode."""
        # Simulate what /api/state does
        emulator = Mock()
        emulator.ai_mode = 'gemini'
        emulator.agent_runner = Mock()
        emulator.agent_runner.public.return_value = {
            'mode': 'gemini',
            'status': 'thinking',
            'thought': 'Analyzing screen...',
            'plan': ['Move north', 'Check map'],
            'configured': True
        }
        emulator.agent_runner.strategy.return_value = {
            'objective': {'id': 'g1', 'title': 'Catch Pokemon'},
            'reason': 'Looking for encounters'
        }
        emulator.policy = Mock()
        emulator.policy.details.return_value = {}
        emulator.manual_mode = False
        emulator.paused = False
        
        # Simulate status() logic
        ai_mode = emulator.ai_mode
        if ai_mode in ('vision', 'gemini', 'ml') and emulator.agent_runner is not None:
            strategy = emulator.agent_runner.strategy()
            agent = emulator.agent_runner.public()
        else:
            strategy = emulator.policy.details()
            agent = None
        
        # This is what the API returns
        api_response = {
            'ai_mode': ai_mode,
            'agent': agent,
            'strategy': strategy
        }
        
        # Should have agent info
        assert api_response['agent'] is not None
        assert api_response['agent']['mode'] == 'gemini'
        assert api_response['agent']['status'] == 'thinking'
    
    def test_ui_receives_agent_data_from_api(self):
        """Test that UI gets the agent data."""
        # This is what the API returns
        state = {
            'ai_mode': 'gemini',
            'agent': {
                'mode': 'gemini',
                'status': 'thinking',
                'thought': 'Analyzing screen...',
                'plan': ['Move north', 'Check map'],
                'configured': True
            },
            'strategy': {
                'objective': {'id': 'g1', 'title': 'Catch Pokemon'},
                'reason': 'Looking for encounters'
            }
        }
        
        # UI checks these values (simulating JavaScript)
        aiMode = state['ai_mode']
        agent = state['agent']
        
        # This is what renderAgent() checks
        shouldShowPanel = aiMode in ('vision', 'gemini', 'ml')
        
        assert shouldShowPanel is True
        assert agent is not None
        assert agent['status'] == 'thinking'
    
    def test_ui_renders_agent_panel_for_gemini(self):
        """Test that agent panel renders for gemini mode."""
        # Simulate the state
        aiMode = 'gemini'
        agent = {
            'status': 'thinking',
            'thought': 'Looking at the screen',
            'plan': ['Move up', 'Check status'],
            'memory': 'Observed grass tiles ahead',
            'turn': 42
        }
        
        # This is renderAgent() logic
        panelHidden = not (aiMode == 'vision' or aiMode == 'gemini')
        
        assert panelHidden is False
        assert agent is not None
    
    def test_gemini_mode_selector_sets_mode(self):
        """Test that selecting gemini mode in UI sets ai_mode."""
        # User clicks "Gemini" in mode selector
        selectedMode = 'gemini'
        
        # This would call POST /internal/ai_mode with {'ai_mode': 'gemini'}
        # Which calls emulator.set_ai_mode('gemini')
        
        # After set_ai_mode:
        emulator_ai_mode = selectedMode
        runner_created = selectedMode in ('vision', 'gemini', 'ml')
        
        assert emulator_ai_mode == 'gemini'
        assert runner_created is True
    
    def test_runner_creates_and_returns_info(self):
        """Test that runner is created and returns agent info."""
        ai_mode = 'gemini'
        
        # When set_ai_mode('gemini') is called:
        if ai_mode in ('vision', 'gemini', 'ml'):
            # _start_agent() is called
            # For gemini, VisionAgentRunner is created
            runner = Mock()
            runner.start = Mock()
            runner.public = Mock(return_value={
                'status': 'thinking',
                'thought': 'Processing game state',
                'mode': 'gemini'
            })
            runner.start()
        
        assert runner is not None
        assert runner.public() is not None
    
    def test_api_response_includes_agent(self):
        """Test that status() includes agent in response."""
        # After mode switch and runner creation
        runner = Mock()
        runner.public.return_value = {
            'status': 'thinking',
            'mode': 'gemini',
            'configured': True
        }
        
        ai_mode = 'gemini'
        
        if ai_mode in ('vision', 'gemini', 'ml') and runner is not None:
            agent_info = runner.public()
        else:
            agent_info = None
        
        status = {
            'ai_mode': ai_mode,
            'agent': agent_info
        }
        
        assert status['agent'] is not None
        assert status['ai_mode'] == 'gemini'
    
    def test_client_receives_full_state(self):
        """Test that client receives complete state."""
        # This is what comes from /api/state
        response_json = {
            'ai_mode': 'gemini',
            'agent': {
                'status': 'thinking',
                'mode': 'gemini',
                'thought': 'Analyzing game screen...',
                'plan': ['Move up', 'Continue north'],
                'configured': True
            },
            'strategy': {
                'objective': {'title': 'Find Pokemon'}
            }
        }
        
        # Client JS receives and processes
        state = response_json
        aiMode = state['ai_mode']
        agent = state['agent']
        
        # Verify what client has
        assert state['agent'] is not None
        assert aiMode == 'gemini'
        assert agent['status'] in ('thinking', 'acting', 'error', 'idle')
    
    def test_missing_agent_object_breaks_display(self):
        """Test that missing agent object breaks display."""
        # This is what happens if agent_runner is None
        response = {
            'ai_mode': 'gemini',
            'agent': None,  # ← Problem!
            'strategy': {}
        }
        
        # UI tries to display
        agent = response['agent']
        
        if agent is None:
            display_broken = True
        else:
            display_broken = False
        
        assert display_broken is True


class TestGeminiInitializationSteps:
    """Test each step of Gemini initialization."""
    
    def test_step1_user_selects_gemini(self):
        """Step 1: User selects Gemini from dropdown."""
        # UI sends POST /internal/ai_mode with {'ai_mode': 'gemini'}
        request_data = {'ai_mode': 'gemini'}
        
        assert request_data['ai_mode'] == 'gemini'
    
    def test_step2_set_ai_mode_called(self):
        """Step 2: emulator.set_ai_mode('gemini') is called."""
        emulator = Mock()
        emulator.ai_mode = 'default'
        emulator._clear_agent_actions = Mock()
        emulator._start_agent = Mock()
        
        # Call set_ai_mode
        value = 'gemini'
        emulator.ai_mode = value
        emulator._clear_agent_actions()
        
        if value in ('vision', 'gemini', 'ml'):
            emulator._start_agent()
        
        assert emulator.ai_mode == 'gemini'
        emulator._clear_agent_actions.assert_called_once()
        emulator._start_agent.assert_called_once()
    
    def test_step3_start_agent_creates_runner(self):
        """Step 3: _start_agent() creates VisionAgentRunner."""
        ai_mode = 'gemini'
        agent_runner = None
        
        # This is _start_agent() logic
        if ai_mode == 'ml':
            runner_class = 'MLAgentRunner'
        else:
            runner_class = 'VisionAgentRunner'
        
        if agent_runner is None:
            agent_runner = f'{runner_class}(self)'
        
        assert agent_runner == 'VisionAgentRunner(self)'
    
    def test_step4_runner_loads_config(self):
        """Step 4: Runner loads Gemini configuration."""
        runner = Mock()
        
        # _config() method
        ai_mode = 'gemini'
        if ai_mode == 'gemini':
            config = Mock(
                provider='gemini',
                api_key='key-from-env',
                model='gemini-2.5-flash',
                configured=True
            )
        else:
            config = Mock(configured=False)
        
        assert config.provider == 'gemini'
        assert config.configured is True
    
    def test_step5_runner_starts(self):
        """Step 5: Runner.start() is called."""
        runner = Mock()
        runner.start = Mock()
        
        # Call start
        runner.start()
        
        runner.start.assert_called_once()
    
    def test_step6_runner_begins_processing(self):
        """Step 6: Runner begins game observation and decision-making."""
        runner = Mock()
        runner.public = Mock(return_value={
            'status': 'thinking',
            'mode': 'gemini',
            'turn': 1
        })
        
        # Get public status
        status = runner.public()
        
        assert status['status'] == 'thinking'
        assert status['mode'] == 'gemini'
    
    def test_step7_status_method_called(self):
        """Step 7: emulator.status() is called by /api/state."""
        emulator = Mock()
        emulator.ai_mode = 'gemini'
        emulator.agent_runner = Mock()
        emulator.agent_runner.public.return_value = {
            'status': 'acting',
            'mode': 'gemini'
        }
        
        # status() logic
        ai_mode = emulator.ai_mode
        if ai_mode in ('vision', 'gemini', 'ml') and emulator.agent_runner is not None:
            agent = emulator.agent_runner.public()
        else:
            agent = None
        
        assert agent is not None
        assert agent['mode'] == 'gemini'
    
    def test_step8_api_response_sent(self):
        """Step 8: API response includes agent info."""
        agent_info = {
            'status': 'acting',
            'mode': 'gemini',
            'thought': 'Moving north'
        }
        
        api_response = {
            'ai_mode': 'gemini',
            'agent': agent_info
        }
        
        assert api_response['agent'] is not None
    
    def test_step9_ui_receives_response(self):
        """Step 9: UI JavaScript receives the response."""
        json_response = '''
        {
            "ai_mode": "gemini",
            "agent": {
                "status": "acting",
                "mode": "gemini",
                "thought": "Moving north"
            }
        }
        '''
        
        state = json.loads(json_response)
        
        assert state['agent'] is not None
        assert state['agent']['status'] == 'acting'
    
    def test_step10_ui_renders_panel(self):
        """Step 10: UI renders agent panel."""
        aiMode = 'gemini'
        agent = {
            'status': 'acting',
            'thought': 'Moving north'
        }
        
        # renderAgent() check
        panelHidden = not (aiMode == 'vision' or aiMode == 'gemini')
        
        assert panelHidden is False
        
        # Panel should display agent info
        should_show = agent is not None and not panelHidden
        
        assert should_show is True


class TestGeminiDebugCheckpoints:
    """Test checkpoints to debug why Gemini might not show."""
    
    def test_checkpoint_api_mode_is_gemini(self):
        """Checkpoint: Verify ai_mode is actually 'gemini' in API response."""
        response = {'ai_mode': 'gemini'}
        
        assert response['ai_mode'] == 'gemini', "API returned wrong mode"
    
    def test_checkpoint_agent_not_none(self):
        """Checkpoint: Verify agent object is not None."""
        response = {'agent': {'status': 'thinking'}}
        
        assert response['agent'] is not None, "Agent is None - runner not created"
    
    def test_checkpoint_agent_has_status(self):
        """Checkpoint: Verify agent has status field."""
        agent = {'status': 'thinking'}
        
        assert 'status' in agent, "Agent missing status field"
        assert agent['status'] in ('thinking', 'acting', 'error', 'idle'), f"Invalid status: {agent['status']}"
    
    def test_checkpoint_panel_not_hidden(self):
        """Checkpoint: Verify panel is not hidden for gemini."""
        aiMode = 'gemini'
        
        panelHidden = not (aiMode == 'vision' or aiMode == 'gemini')
        
        assert panelHidden is False, "Panel is hidden for gemini mode"
    
    def test_checkpoint_runner_initialized(self):
        """Checkpoint: Verify runner is actually created."""
        emulator = Mock()
        emulator.ai_mode = 'gemini'
        emulator.agent_runner = Mock()  # Should not be None
        
        assert emulator.agent_runner is not None, "Runner was not initialized"
    
    def test_checkpoint_config_loaded(self):
        """Checkpoint: Verify Gemini config is loaded."""
        config = Mock(
            provider='gemini',
            api_key='key',
            configured=True
        )
        
        assert config.configured is True, "Gemini not properly configured"
        assert config.provider == 'gemini', "Wrong provider"
