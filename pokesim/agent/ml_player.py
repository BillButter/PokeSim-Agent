"""Machine learning-based player using learned decision patterns.

This player learns from gameplay patterns and makes decisions based on game state
without relying on a remote vision model. Uses a simple but effective decision tree
approach that can be extended with more sophisticated ML models.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class MLDecision:
    """Decision made by ML player."""
    buttons: tuple[str, ...] = ()
    frames: int = 8
    confidence: float = 1.0
    reasoning: str = ""


class MLPlayer:
    """Machine learning-based decision maker for Pokémon gameplay.
    
    Uses learned patterns from game state to make strategic decisions.
    Can be trained/improved over time with more gameplay data.
    """
    
    def __init__(self):
        self.move_count = 0
        self.battle_moves_learned: dict[str, float] = {}  # move name -> success rate
        self.location_exits: dict[int, list[str]] = {}  # map_id -> exit directions
        
    def decide(self, game_state: dict[str, Any]) -> MLDecision:
        """Decide next action based on game state.
        
        Args:
            game_state: Compact game state dict with location, party, battle info, etc.
        
        Returns:
            MLDecision with buttons to press and duration.
        """
        self.move_count += 1
        
        # Battle decisions (in_battle: 0=none, 1=wild, 2=trainer)
        in_battle = game_state.get("in_battle", 0)
        if in_battle == 1:
            return self._decide_wild_battle(game_state)
        elif in_battle == 2:
            return self._decide_trainer_battle(game_state)
        
        # Overworld movement
        elif game_state.get("textbox"):
            return MLDecision(("a",), 6, 0.9, "Advance dialogue")
        elif game_state.get("start_menu"):
            return MLDecision(("b",), 6, 0.95, "Close menu")
        else:
            return self._decide_overworld_movement(game_state)
    
    def _decide_wild_battle(self, state: dict[str, Any]) -> MLDecision:
        """Decide action in wild battle."""
        party = state.get("party", [])
        enemy_level = state.get("enemy_level", 0)
        
        if not party:
            return MLDecision(("a",), 8, 0.8, "Wait - no party")
        
        active = party[0]
        active_level = active.get("level", 1)
        active_hp = active.get("hp", 0)
        active_max_hp = active.get("max_hp", 1)
        hp_ratio = active_hp / active_max_hp if active_max_hp > 0 else 0
        
        # Low health: heal or switch
        if hp_ratio < 0.3:
            if len(party) > 1:
                return MLDecision(("a", "down"), 20, 0.85, "Switch weak Pokémon")
            return MLDecision(("a",), 8, 0.7, "Use move despite low HP")
        
        # Attack weak enemy
        if enemy_level < active_level:
            return MLDecision(("a",), 12, 0.9, "Attack weaker opponent")
        
        # Default: use move
        return MLDecision(("a",), 8, 0.8, "Use move")
    
    def _decide_trainer_battle(self, state: dict[str, Any]) -> MLDecision:
        """Decide action in trainer battle."""
        party = state.get("party", [])
        opponent = state.get("opponent", "")
        
        if not party:
            return MLDecision(("a",), 8, 0.7, "Wait - no party")
        
        active = party[0]
        hp_ratio = active.get("hp", 0) / active.get("max_hp", 1)
        
        # Low health: switch if available
        if hp_ratio < 0.25 and len(party) > 1:
            return MLDecision(("a", "down"), 20, 0.9, "Switch to fresh Pokémon")
        
        # Default: attack
        return MLDecision(("a",), 8, 0.85, "Use move in trainer battle")
    
    def _decide_overworld_movement(self, state: dict[str, Any]) -> MLDecision:
        """Decide movement in overworld."""
        # Use "map" not "map_id", and badges is a list not int
        map_id = state.get("map", 0)
        badges = state.get("badges", [])
        pokedex_owned = state.get("pokedex_owned", 0)
        
        # Convert badges list to int (count)
        badge_count = len(badges) if badges else 0
        
        # Learning: prefer directions we've explored before
        known_exits = self.location_exits.get(map_id, [])
        if known_exits:
            # Prefer non-backtracking
            directions = ["up", "down", "left", "right"]
            preferred = [d for d in directions if d in known_exits]
            if preferred:
                return MLDecision((preferred[0],), 24, 0.75, f"Move {preferred[0]}")
        
        # Default: wander
        import random
        # Use badge count instead of raw badges, ensure all are ints
        seed_value = max(0, int(map_id or 0)) + int(badge_count) + int(self.move_count or 0)
        random.seed(seed_value)
        direction = random.choice(["up", "down", "left", "right"])
        
        # Record that we tried this direction
        if map_id not in self.location_exits:
            self.location_exits[map_id] = []
        if direction not in self.location_exits[map_id]:
            self.location_exits[map_id].append(direction)
        
        return MLDecision((direction,), 16, 0.6, f"Explore: move {direction}")
    
    def learn_from_turn(self, result: str, new_state: dict[str, Any]) -> None:
        """Update learned patterns from gameplay outcome.
        
        Args:
            result: Description of what happened (e.g. "caught Pidgeotto")
            new_state: The resulting game state
        """
        # Simple learning: track successful patterns
        if "caught" in result.lower():
            self.battle_moves_learned["catch"] = \
                self.battle_moves_learned.get("catch", 0) * 0.9 + 1.0 * 0.1
        
        if "defeated" in result.lower():
            self.battle_moves_learned["defeat"] = \
                self.battle_moves_learned.get("defeat", 0) * 0.9 + 1.0 * 0.1
    
    def get_summary(self) -> str:
        """Get readable summary of learned patterns."""
        moves = ", ".join(
            f"{name}({score:.1f})" 
            for name, score in sorted(self.battle_moves_learned.items(), key=lambda x: -x[1])[:5]
        )
        return f"ML Player (moves: {self.move_count}, patterns: {len(self.location_exits)} locations, learned: {moves or 'none yet'})"
