"""Tests for the ML player decision engine."""

import pytest
from pokesim.agent.ml_player import MLPlayer, MLDecision


class TestMLDecision:
    """Test MLDecision dataclass."""
    
    def test_ml_decision_creation(self):
        decision = MLDecision(
            buttons=("up", "a"),
            frames=12,
            confidence=0.85,
            reasoning="Test move"
        )
        assert decision.buttons == ("up", "a")
        assert decision.frames == 12
        assert decision.confidence == 0.85
        assert decision.reasoning == "Test move"
    
    def test_ml_decision_defaults(self):
        decision = MLDecision()
        assert decision.buttons == ()
        assert decision.frames == 8
        assert decision.confidence == 1.0
        assert decision.reasoning == ""


class TestMLPlayer:
    """Test ML player decision making."""
    
    def setup_method(self):
        """Create fresh ML player for each test."""
        self.player = MLPlayer()
    
    def test_initialization(self):
        """Test player initializes correctly."""
        player = MLPlayer()
        assert player.move_count == 0
        assert player.battle_moves_learned == {}
        assert player.location_exits == {}
    
    def test_basic_overworld_state(self):
        """Test decision with basic overworld state."""
        state = {
            "in_battle": 0,
            "textbox": False,
            "start_menu": False,
            "map": 1,
            "badges": [],
            "party": [{"species": "bulbasaur", "level": 5, "hp": 20, "max_hp": 20}],
            "pokedex_owned": 1
        }
        decision = self.player.decide(state)
        assert isinstance(decision, MLDecision)
        assert len(decision.buttons) > 0
        assert decision.buttons[0] in ("up", "down", "left", "right")
    
    def test_textbox_advance(self):
        """Test player advances text in textbox."""
        state = {
            "in_battle": 0,
            "textbox": True,
            "start_menu": False,
            "map": 1,
            "badges": [],
        }
        decision = self.player.decide(state)
        assert decision.buttons == ("a",)
        assert "dialogue" in decision.reasoning.lower()
    
    def test_menu_close(self):
        """Test player closes start menu."""
        state = {
            "in_battle": 0,
            "textbox": False,
            "start_menu": True,
            "map": 1,
            "badges": [],
        }
        decision = self.player.decide(state)
        assert decision.buttons == ("b",)
        assert "menu" in decision.reasoning.lower()
    
    def test_wild_battle_decision(self):
        """Test player makes decision in wild battle."""
        state = {
            "in_battle": 1,  # Wild battle
            "textbox": False,
            "start_menu": False,
            "map": 1,
            "badges": [],
            "party": [{"species": "bulbasaur", "level": 5, "hp": 20, "max_hp": 20}],
            "enemy_level": 3
        }
        decision = self.player.decide(state)
        assert isinstance(decision, MLDecision)
        assert len(decision.buttons) > 0
    
    def test_trainer_battle_decision(self):
        """Test player makes decision in trainer battle."""
        state = {
            "in_battle": 2,  # Trainer battle
            "textbox": False,
            "start_menu": False,
            "map": 1,
            "badges": [],
            "party": [{"species": "bulbasaur", "level": 5, "hp": 20, "max_hp": 20}],
            "enemy_level": 5,
            "opponent": "Trainer"
        }
        decision = self.player.decide(state)
        assert isinstance(decision, MLDecision)
        assert len(decision.buttons) > 0
    
    def test_low_hp_wild_battle(self):
        """Test player switches or flees when HP is low."""
        state = {
            "in_battle": 1,
            "textbox": False,
            "start_menu": False,
            "map": 1,
            "badges": [],
            "party": [
                {"species": "bulbasaur", "level": 5, "hp": 3, "max_hp": 20},
                {"species": "squirtle", "level": 5, "hp": 20, "max_hp": 20}
            ],
            "enemy_level": 5
        }
        decision = self.player.decide(state)
        assert isinstance(decision, MLDecision)
        # Should attempt to switch or defend
        assert len(decision.buttons) > 0
    
    def test_move_count_increments(self):
        """Test move counter increments."""
        state = {
            "in_battle": 0,
            "textbox": False,
            "start_menu": False,
            "map": 1,
            "badges": [],
        }
        initial_count = self.player.move_count
        self.player.decide(state)
        assert self.player.move_count == initial_count + 1
    
    def test_location_memory(self):
        """Test player remembers explored locations."""
        state1 = {
            "in_battle": 0,
            "textbox": False,
            "start_menu": False,
            "map": 1,
            "badges": [],
        }
        # Make several moves in same location
        self.player.decide(state1)
        self.player.decide(state1)
        self.player.decide(state1)
        
        # Should have learned about this location
        assert 1 in self.player.location_exits
        assert len(self.player.location_exits[1]) > 0
    
    def test_badges_handling(self):
        """Test player handles badges list correctly."""
        state = {
            "in_battle": 0,
            "textbox": False,
            "start_menu": False,
            "map": 1,
            "badges": ["boulder", "cascade", "thunder"],  # List of badges
            "party": [{"species": "bulbasaur", "level": 20, "hp": 20, "max_hp": 20}],
            "pokedex_owned": 10
        }
        # Should not crash with badges as list
        decision = self.player.decide(state)
        assert isinstance(decision, MLDecision)
    
    def test_missing_state_fields(self):
        """Test player handles missing state fields gracefully."""
        minimal_state = {}
        # Should not crash with minimal state
        decision = self.player.decide(minimal_state)
        assert isinstance(decision, MLDecision)
    
    def test_learn_from_catch(self):
        """Test player learns from successful catches."""
        state = {"map": 1, "badges": []}
        initial_value = self.player.battle_moves_learned.get("catch", 0)
        self.player.learn_from_turn("caught Pidgeotto", state)
        new_value = self.player.battle_moves_learned.get("catch", 0)
        assert new_value > initial_value
    
    def test_learn_from_defeat(self):
        """Test player learns from victories."""
        state = {"map": 1, "badges": []}
        initial_value = self.player.battle_moves_learned.get("defeat", 0)
        self.player.learn_from_turn("defeated Trainer's Pikachu", state)
        new_value = self.player.battle_moves_learned.get("defeat", 0)
        assert new_value > initial_value
    
    def test_summary_output(self):
        """Test summary generation."""
        summary = self.player.get_summary()
        assert isinstance(summary, str)
        assert "ML Player" in summary or "moves" in summary.lower()
    
    def test_consistent_movement_with_seed(self):
        """Test movement is consistent with same seed."""
        state = {
            "in_battle": 0,
            "textbox": False,
            "start_menu": False,
            "map": 1,
            "badges": [],
        }
        
        player1 = MLPlayer()
        decision1 = player1.decide(state)
        
        player2 = MLPlayer()
        decision2 = player2.decide(state)
        
        # Same initial state should produce same first move (same seed)
        assert decision1.buttons == decision2.buttons
    
    def test_party_safety(self):
        """Test player handles empty or missing party."""
        state1 = {
            "in_battle": 1,
            "textbox": False,
            "start_menu": False,
            "map": 1,
            "badges": [],
            "party": [],
            "enemy_level": 5
        }
        # Should not crash with empty party
        decision1 = self.player.decide(state1)
        assert isinstance(decision1, MLDecision)
        
        state2 = {
            "in_battle": 1,
            "textbox": False,
            "start_menu": False,
            "map": 1,
            "badges": [],
            # Missing "party" key entirely
            "enemy_level": 5
        }
        # Should not crash with missing party
        decision2 = self.player.decide(state2)
        assert isinstance(decision2, MLDecision)
    
    def test_no_crash_with_none_values(self):
        """Test player doesn't crash with None values."""
        state = {
            "in_battle": 0,
            "textbox": False,
            "start_menu": False,
            "map": None,
            "badges": None,
            "party": None,
            "pokedex_owned": None
        }
        # Should handle None values gracefully
        decision = self.player.decide(state)
        assert isinstance(decision, MLDecision)
