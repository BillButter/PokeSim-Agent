"""Machine learning-based player using learned decision patterns.

This player learns through exploration: starts with random moves, collects
feedback on outcomes, and gradually learns which actions work best in which
situations. Uses an experience buffer to build decision trees over time.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class MLDecision:
    """Decision made by ML player."""
    buttons: tuple[str, ...] = ()
    frames: int = 8
    confidence: float = 1.0
    reasoning: str = ""


@dataclass
class Experience:
    """Single experience: state -> action -> outcome."""
    state_hash: str
    action: str
    reward: float
    next_state_hash: str
    battle: bool = False


class MLPlayer:
    """Machine learning-based decision maker that learns through exploration.
    
    Strategy:
    1. Early game: Make RANDOM moves to explore state space
    2. Collect feedback: Track rewards (successful battles, catches, exploration)
    3. Learn patterns: Build decision trees of state -> best action
    4. Exploit: Use learned patterns when confidence is high
    5. Explore: Occasionally try new moves to continue learning
    
    This creates a simple but effective reinforcement learning agent.
    """
    
    def __init__(self):
        self.move_count = 0
        self.total_reward = 0.0
        
        # Experience buffer: list of (state, action, reward) tuples
        self.experiences: list[Experience] = []
        self.max_experiences = 10000  # Memory limit
        
        # State-action Q-values: (state_hash, action) -> cumulative reward
        self.q_values: dict[tuple[str, str], float] = {}
        self.action_counts: dict[tuple[str, str], int] = {}
        
        # Exploration parameters
        self.exploration_rate = 0.8  # Start high, decrease over time
        self.min_exploration = 0.1  # Never stop exploring completely
        
        # Game knowledge
        self.location_map: dict[int, str] = {}  # map_id -> explored state
        self.pokemon_types: dict[str, str] = {}  # pokemon -> type
        self.battle_outcomes: dict[str, list[float]] = {}  # opponent -> win rates
        
        # Track last state for learning
        self._last_state_hash: str | None = None
        
    def decide(self, game_state: dict[str, Any]) -> MLDecision:
        """Decide next action based on game state and learned patterns.
        
        Strategy: Epsilon-greedy with gradual shift from exploration to exploitation.
        
        Args:
            game_state: Current game state with location, party, battle info, etc.
        
        Returns:
            MLDecision with buttons to press and reasoning.
        """
        self.move_count += 1
        
        # Decrease exploration as we gather more data
        self.exploration_rate = max(
            self.min_exploration,
            0.8 * (1.0 - min(self.move_count / 5000.0, 0.95))
        )
        
        # Store current state for learning
        state_hash = self._state_hash(game_state)
        self._last_state_hash = state_hash
        
        # Battle decisions (in_battle: 0=none, 1=wild, 2=trainer)
        in_battle = game_state.get("in_battle", 0)
        if in_battle == 1:
            decision = self._decide_wild_battle(game_state)
        elif in_battle == 2:
            decision = self._decide_trainer_battle(game_state)
        else:
            # Non-battle decisions
            if game_state.get("textbox"):
                decision = MLDecision(("a",), 6, 0.95, "Advance dialogue")
            elif game_state.get("start_menu"):
                decision = MLDecision(("b",), 6, 0.95, "Close menu")
            else:
                decision = self._decide_overworld_movement(game_state)
        
        # Record this decision as an experience
        action = " + ".join(decision.buttons) if decision.buttons else "wait"
        exp = Experience(
            state_hash=state_hash,
            action=action,
            reward=0.0,  # Will be updated in learn_from_turn
            next_state_hash=state_hash,
            battle=in_battle > 0
        )
        self.experiences.append(exp)
        
        return decision
    
    def _state_hash(self, state: dict[str, Any]) -> str:
        """Create a hash of relevant state features for Q-learning."""
        # Include: map, party level, badges, pokedex, items count
        map_id = state.get("map", 0)
        party = state.get("party", [])
        
        avg_level = 0
        if party:
            avg_level = sum(p.get("level", 1) for p in party) / len(party)
        
        badges = state.get("badges", [])
        badge_count = len(badges) if isinstance(badges, list) else badges
        
        return f"map{map_id}_lv{int(avg_level)}_badges{badge_count}"
    
    def _decide_wild_battle(self, state: dict[str, Any]) -> MLDecision:
        """Decide action in wild battle with learning."""
        party = state.get("party", [])
        enemy_name = state.get("enemy", "Unknown")
        enemy_level = state.get("enemy_level", 0)
        
        if not party:
            return MLDecision(("a",), 8, 0.5, "Waiting for party info")
        
        active = party[0]
        active_hp = active.get("hp", 0)
        active_max_hp = active.get("max_hp", 1)
        active_level = active.get("level", 1)
        hp_ratio = active_hp / active_max_hp if active_max_hp > 0 else 0
        
        state_hash = self._state_hash(state)
        
        # Decide between attack/switch/catch based on learned patterns + random
        possible_actions = []
        
        # Always can attack
        possible_actions.append(("attack", "Use move", 0.8))
        
        # Can try to catch (basic strategy)
        if enemy_level <= active_level:
            possible_actions.append(("throw", "Throw Pokéball", 0.6))
        
        # Can switch if we have alternatives
        if len(party) > 1:
            possible_actions.append(("switch", "Switch Pokémon", 0.7))
        
        # If low health, prioritize switching or escape
        if hp_ratio < 0.25 and len(party) > 1:
            return MLDecision(("a", "down"), 20, 0.85, "Switch - low health")
        
        # Use learned Q-values if available
        best_action = None
        best_q = -float('inf')
        
        for action, reasoning, default_conf in possible_actions:
            q_value = self.q_values.get((state_hash, action), 0)
            if q_value > best_q:
                best_q = q_value
                best_action = (action, reasoning, default_conf)
        
        # Epsilon-greedy: sometimes explore random action
        if random.random() < self.exploration_rate:
            best_action = random.choice(possible_actions)
        
        action, reasoning, confidence = best_action
        
        if action == "throw":
            return MLDecision(("a",), 8, confidence, reasoning)
        elif action == "switch":
            return MLDecision(("a", "down"), 20, confidence, reasoning)
        else:  # attack
            return MLDecision(("a",), 8, confidence, reasoning)
    
    def _decide_trainer_battle(self, state: dict[str, Any]) -> MLDecision:
        """Decide action in trainer battle with learning."""
        party = state.get("party", [])
        opponent = state.get("opponent", "Trainer")
        
        if not party:
            return MLDecision(("a",), 8, 0.5, "Waiting for party")
        
        active = party[0]
        hp_ratio = active.get("hp", 0) / max(1, active.get("max_hp", 1))
        
        state_hash = self._state_hash(state)
        
        # Track battle outcomes for this opponent
        if opponent not in self.battle_outcomes:
            self.battle_outcomes[opponent] = []
        
        # Strategy: switch if low health, else attack
        if hp_ratio < 0.25 and len(party) > 1:
            return MLDecision(("a", "down"), 20, 0.9, "Switch - low health")
        
        # Check learned Q-value
        q_attack = self.q_values.get((state_hash, "attack"), 0.5)
        q_switch = self.q_values.get((state_hash, "switch"), 0.4)
        
        # Explore occasionally even in trainer battles
        if random.random() < self.exploration_rate * 0.5:
            if random.random() < 0.5 and len(party) > 1:
                return MLDecision(("a", "down"), 20, 0.7, "Explore: try switching")
        
        # Attack by default
        return MLDecision(("a",), 8, max(0.7, q_attack), "Use best move")
    
    def _decide_overworld_movement(self, state: dict[str, Any]) -> MLDecision:
        """Decide movement in overworld with exploration and learning."""
        map_id = state.get("map", 0)
        
        # Track location
        if map_id not in self.location_map:
            self.location_map[map_id] = f"location_{len(self.location_map)}"
        
        state_hash = self._state_hash(state)
        
        # List of possible directions
        directions = ["up", "down", "left", "right"]
        
        # Early game: explore more randomly
        if self.move_count < 100:
            direction = random.choice(directions)
            return MLDecision(
                (direction,),
                16,
                0.5,
                f"Random exploration: move {direction} (learning phase)"
            )
        
        # Mid game: balance exploration and exploitation
        if random.random() < self.exploration_rate:
            # Explore: pick random direction
            direction = random.choice(directions)
            confidence = 0.4 + self.exploration_rate * 0.3
            return MLDecision(
                (direction,),
                16,
                confidence,
                f"Explore: move {direction}"
            )
        else:
            # Exploit: use learned Q-values
            best_dir = None
            best_q = -float('inf')
            
            for direction in directions:
                q = self.q_values.get((state_hash, direction), 0)
                if q > best_q:
                    best_q = q
                    best_dir = direction
            
            if best_dir is None:
                best_dir = random.choice(directions)
            
            confidence = 0.6 + min(0.3, self.move_count / 1000.0)
            return MLDecision(
                (best_dir,),
                16,
                confidence,
                f"Learned: move {best_dir} (Q={best_q:.2f})"
            )
    
    def learn_from_turn(self, result: str, new_state: dict[str, Any], last_state: dict[str, Any] | None = None) -> None:
        """Update learned patterns from gameplay outcome.
        
        This is called after each action to provide feedback on what worked.
        
        Args:
            result: String describing what happened (for logging)
            new_state: New game state after the action
            last_state: Previous state for context (optional)
        """
        # Calculate reward based on what happened
        reward = self._calculate_reward(result, new_state)
        self.total_reward += reward
        
        # Always update Q-values based on recent actions
        # Apply credit to recent decisions
        for i, exp in enumerate(self.experiences[-5:]):  # Look at recent experiences
            # Weight recent actions more heavily
            decay = 0.7 ** (4 - i)  # More recent = higher weight
            q_key = (exp.state_hash, exp.action)
            current_q = self.q_values.get(q_key, 0)
            count = self.action_counts.get(q_key, 0)
            
            # Q-learning update: blend old and new values
            new_q = (current_q * count + reward * decay) / (count + 1)
            self.q_values[q_key] = new_q
            self.action_counts[q_key] = count + 1
        
        # Keep memory limited
        if len(self.experiences) > self.max_experiences:
            self.experiences = self.experiences[-self.max_experiences:]
    
    def _calculate_reward(self, result: str, state: dict[str, Any]) -> float:
        """Calculate reward for an outcome.
        
        Returns float between -1.0 (bad) and +1.0 (excellent).
        """
        result_lower = result.lower()
        
        # Major rewards
        if "caught" in result_lower:
            return 1.0
        if "defeated" in result_lower or "victory" in result_lower:
            return 0.8
        
        # Minor rewards
        if "damaged" in result_lower or "landed" in result_lower:
            return 0.2
        if "dodged" in result_lower or "avoided" in result_lower:
            return 0.15
        
        # Neutral
        if "moved" in result_lower or "advance" in result_lower:
            return 0.05
        
        # Small penalties
        if "miss" in result_lower:
            return -0.1
        if "damage taken" in result_lower:
            return -0.15
        if "fainted" in result_lower:
            return -0.5
        
        # Default: tiny positive for just existing
        return 0.01
    
    def get_summary(self) -> str:
        """Get readable summary of learned patterns and progress."""
        avg_reward = self.total_reward / max(1, self.move_count)
        
        # Show top learned actions
        top_actions = sorted(
            self.q_values.items(),
            key=lambda x: x[1],
            reverse=True
        )[:3]
        
        top_moves = ", ".join(
            f"{action}({q:.2f})"
            for (state, action), q in top_actions
        )
        
        explored_locations = len(self.location_map)
        exploration = f"{self.exploration_rate:.0%} exploration"
        
        return (
            f"ML Agent (moves: {self.move_count}, "
            f"reward: {avg_reward:+.3f}, "
            f"learned: {len(self.q_values)} patterns, "
            f"explored: {explored_locations} locations, "
            f"{exploration})"
        )
