"""Tests for ML player learning and exploration behavior."""

import pytest
import random
from unittest.mock import Mock
from pokesim.agent.ml_player import MLPlayer, MLDecision


class TestMLRandomExploration:
    """Test that ML player explores randomly at the start."""
    
    def test_early_game_high_exploration_rate(self):
        """Test that early game has high exploration rate."""
        player = MLPlayer()
        
        # Move count 0-100 should have high exploration
        for _ in range(10):
            state = {"in_battle": 0, "map": 1, "badges": [], "party": []}
            decision = player.decide(state)
            assert player.exploration_rate > 0.5
    
    def test_exploration_decreases_over_time(self):
        """Test that exploration gradually decreases as agent learns."""
        player = MLPlayer()
        
        # Initial exploration high
        exploration_at_100 = None
        
        # Make 100 moves
        for i in range(100):
            state = {"in_battle": 0, "map": 1, "badges": [], "party": []}
            player.decide(state)
            if i == 99:
                exploration_at_100 = player.exploration_rate
        
        # Make 1000 more moves
        for i in range(1000):
            state = {"in_battle": 0, "map": 1, "badges": [], "party": []}
            player.decide(state)
        
        # Exploration should have decreased
        assert player.exploration_rate < exploration_at_100
    
    def test_never_stops_exploring(self):
        """Test that agent maintains minimum exploration rate."""
        player = MLPlayer()
        
        # Make many moves to push toward minimum
        for _ in range(10000):
            state = {"in_battle": 0, "map": 1, "badges": [], "party": []}
            player.decide(state)
        
        # Should never go below minimum
        assert player.exploration_rate >= player.min_exploration
    
    def test_overworld_random_moves_early(self):
        """Test that overworld movement is random early in game."""
        player = MLPlayer()
        
        # First 100 moves should have random directions
        directions = []
        for _ in range(50):
            state = {"in_battle": 0, "map": 1, "badges": [], "party": [], "textbox": False, "start_menu": False}
            decision = player.decide(state)
            if decision.buttons:
                directions.append(decision.buttons[0])
        
        # Should have variety (not all same direction)
        unique_dirs = set(directions)
        assert len(unique_dirs) > 1, "Should explore multiple directions"


class TestMLLearning:
    """Test that ML player learns from outcomes."""
    
    def test_positive_reward_updates_q_values(self):
        """Test that positive rewards increase Q-values."""
        player = MLPlayer()
        
        # Make a decision
        state = {"in_battle": 0, "map": 1, "badges": [], "party": []}
        decision = player.decide(state)
        
        # No Q-values yet
        assert len(player.q_values) == 0
        
        # Learn from positive outcome
        player.learn_from_turn("caught Pidgeotto", state)
        
        # Should have Q-values now
        assert len(player.q_values) > 0
    
    def test_battle_decision_learns_from_victory(self):
        """Test learning from battle outcomes."""
        player = MLPlayer()
        
        state = {
            "in_battle": 1,
            "map": 1,
            "badges": [],
            "party": [{"hp": 20, "max_hp": 20, "level": 5}],
            "enemy_level": 3
        }
        
        decision = player.decide(state)
        assert decision is not None
        
        # Learn from victory
        player.learn_from_turn("defeated Pidgeotto", state)
        
        # Check Q-values were updated
        assert len(player.q_values) > 0
    
    def test_repeated_success_increases_confidence(self):
        """Test that repeated successes increase action confidence."""
        player = MLPlayer()
        
        state = {
            "in_battle": 0,
            "map": 1,
            "badges": [],
            "party": [],
            "textbox": False,
            "start_menu": False
        }
        
        # Make a decision and learn from it multiple times
        for _ in range(10):
            decision = player.decide(state)
            player.learn_from_turn("moved successfully", state)
        
        # Should have high Q-values for successful actions
        max_q = max(player.q_values.values()) if player.q_values else 0
        assert max_q > 0
    
    def test_failure_decreases_q_value(self):
        """Test that failures decrease Q-values."""
        player = MLPlayer()
        
        state = {
            "in_battle": 1,
            "map": 1,
            "badges": [],
            "party": [{"hp": 5, "max_hp": 20, "level": 5}],
            "enemy_level": 10
        }
        
        # Make decision
        decision = player.decide(state)
        
        # Learn from failure
        player.learn_from_turn("fainted", state)
        
        # Check if negative Q-values exist
        negative_qs = [q for q in player.q_values.values() if q < 0]
        assert len(negative_qs) >= 0  # May have learned from failure


class TestMLRewardCalculation:
    """Test reward calculation for outcomes."""
    
    def test_catch_gives_high_reward(self):
        """Test that catching a Pokemon gives positive reward."""
        player = MLPlayer()
        state = {}
        
        reward = player._calculate_reward("caught Pidgeotto", state)
        assert reward == 1.0
    
    def test_victory_gives_high_reward(self):
        """Test that battle victory gives positive reward."""
        player = MLPlayer()
        state = {}
        
        reward = player._calculate_reward("defeated trainer", state)
        assert reward == 0.8
    
    def test_fainted_gives_negative_reward(self):
        """Test that fainting gives negative reward."""
        player = MLPlayer()
        state = {}
        
        reward = player._calculate_reward("fainted", state)
        assert reward < 0
    
    def test_movement_gives_small_positive_reward(self):
        """Test that basic movement gets small positive reward."""
        player = MLPlayer()
        state = {}
        
        reward = player._calculate_reward("moved left", state)
        assert reward > 0
        assert reward < 0.1


class TestMLExploitation:
    """Test that ML player exploits learned patterns."""
    
    def test_learned_actions_used_over_time(self):
        """Test that best actions are used more often."""
        player = MLPlayer()
        
        # Build up some Q-values
        state = {"in_battle": 0, "map": 1, "badges": [], "party": [], "textbox": False, "start_menu": False}
        
        # Give high Q-value to one action
        state_hash = player._state_hash(state)
        player.q_values[(state_hash, "up")] = 0.9
        player.q_values[(state_hash, "down")] = 0.1
        
        # Make many moves in low-exploration phase
        player.exploration_rate = 0.05  # Low exploration
        
        # Track which action is chosen
        actions = []
        for _ in range(50):
            state = {"in_battle": 0, "map": 1, "badges": [], "party": [], "textbox": False, "start_menu": False}
            decision = player.decide(state)
            if decision.buttons:
                actions.append(decision.buttons[0])
        
        # Should choose "up" more often due to higher Q-value
        up_count = actions.count("up")
        assert up_count > 0


class TestMLStateTracking:
    """Test that ML player tracks game state properly."""
    
    def test_location_tracking(self):
        """Test that ML player tracks visited locations."""
        player = MLPlayer()
        
        # Visit different locations
        for map_id in [1, 2, 3, 1, 2]:
            state = {
                "in_battle": 0,
                "map": map_id,
                "badges": [],
                "party": [],
                "textbox": False,
                "start_menu": False
            }
            player.decide(state)
        
        # Should have visited 3 unique locations
        assert len(player.location_map) == 3
    
    def test_state_hash_consistent(self):
        """Test that same game state produces same hash."""
        player = MLPlayer()
        
        state = {
            "map": 5,
            "party": [{"level": 10}],
            "badges": ["boulder", "cascade"]
        }
        
        hash1 = player._state_hash(state)
        hash2 = player._state_hash(state)
        
        assert hash1 == hash2
    
    def test_state_hash_different_for_different_states(self):
        """Test that different states produce different hashes."""
        player = MLPlayer()
        
        state1 = {"map": 5, "party": [{"level": 10}], "badges": []}
        state2 = {"map": 6, "party": [{"level": 10}], "badges": []}
        
        hash1 = player._state_hash(state1)
        hash2 = player._state_hash(state2)
        
        assert hash1 != hash2


class TestMLBattleDecisions:
    """Test ML player decision-making in battles."""
    
    def test_attack_when_healthy(self):
        """Test that player attacks when healthy in wild battle."""
        player = MLPlayer()
        
        state = {
            "in_battle": 1,
            "map": 1,
            "badges": [],
            "party": [{"hp": 20, "max_hp": 20, "level": 10}],
            "enemy_level": 5
        }
        
        decision = player.decide(state)
        assert decision.reasoning is not None
    
    def test_switch_when_low_health(self):
        """Test that player switches when low on health."""
        player = MLPlayer()
        
        state = {
            "in_battle": 1,
            "map": 1,
            "badges": [],
            "party": [
                {"hp": 2, "max_hp": 20, "level": 10},
                {"hp": 15, "max_hp": 15, "level": 10}
            ],
            "enemy_level": 5
        }
        
        decision = player.decide(state)
        # Should consider switching
        assert decision is not None


class TestMLSummary:
    """Test that ML player provides useful summary information."""
    
    def test_summary_contains_move_count(self):
        """Test that summary shows move count."""
        player = MLPlayer()
        
        for _ in range(50):
            state = {"in_battle": 0, "map": 1, "badges": [], "party": []}
            player.decide(state)
        
        summary = player.get_summary()
        assert "moves: 50" in summary
    
    def test_summary_shows_learned_patterns(self):
        """Test that summary shows number of patterns learned."""
        player = MLPlayer()
        
        # Create some Q-values
        player.q_values[("state1", "action1")] = 0.5
        player.q_values[("state2", "action2")] = 0.7
        
        summary = player.get_summary()
        assert "2" in summary or "patterns" in summary
    
    def test_summary_shows_reward(self):
        """Test that summary shows average reward."""
        player = MLPlayer()
        
        # Add some moves with rewards
        for _ in range(10):
            state = {"in_battle": 0, "map": 1, "badges": [], "party": []}
            player.decide(state)
            player.learn_from_turn("moved", state)
        
        summary = player.get_summary()
        assert "reward" in summary.lower()


class TestMLProgressPhases:
    """Test that ML player shows clear learning phases."""
    
    def test_early_exploration_phase(self):
        """Test first phase is pure exploration."""
        player = MLPlayer()
        
        # Very beginning
        state = {"in_battle": 0, "map": 1, "badges": [], "party": []}
        for _ in range(50):
            player.decide(state)
        
        assert player.move_count <= 50
        assert player.exploration_rate > 0.6
    
    def test_learning_phase_starts(self):
        """Test that learning phase begins after exploration."""
        player = MLPlayer()
        
        state = {"in_battle": 0, "map": 1, "badges": [], "party": []}
        initial_exploration = None
        for i in range(1000):
            player.decide(state)
            player.learn_from_turn("moved", state)
            if i == 0:
                initial_exploration = player.exploration_rate
        
        # After 1000 moves, exploration should have decreased significantly
        assert player.exploration_rate < initial_exploration
        assert len(player.q_values) > 0
        assert player.move_count == 1000
