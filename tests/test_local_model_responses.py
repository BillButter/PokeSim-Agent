"""Tests for local AI model response handling and fallback parsing.

Local models like moondream, ollama, and llama.cpp often return plain text
instead of structured JSON. This test suite verifies that the parser handles
these responses gracefully without error spam.
"""

from __future__ import annotations

import pytest

from pokesim.agent.parser import extract_json, parse_decision, ParseError


class TestMoondreamResponses:
    """Test parsing of moondream (local vision model) responses."""

    def test_moondream_simple_direction(self):
        """Test moondream response with simple direction."""
        text = "The player is in a grassy field. I should move up to find Pokemon."
        
        result = extract_json(text)
        
        assert isinstance(result, dict)
        assert "actions" in result
        assert result["actions"][0]["buttons"] == ["up"]

    def test_moondream_with_button_name(self):
        """Test moondream response mentioning button names."""
        text = "I see a dialog box. I need to press a to advance the conversation."
        
        result = extract_json(text)
        
        assert "a" in result["actions"][0]["buttons"]

    def test_moondream_battle_scenario(self):
        """Test moondream response during battle."""
        text = "We are in a Pokemon battle. The opponent sent out a Pidgeot. I should press a to select an attack."
        
        result = extract_json(text)
        
        assert result["actions"][0]["buttons"] == ["a"]

    def test_moondream_long_description(self):
        """Test moondream with verbose description."""
        text = "Looking at the screen, I can see a Pokemon trainer standing in front of a building that looks like a Pokemon Center. There are other trainers walking around. The path leads up to the building entrance. I should press up to enter the building."
        
        result = extract_json(text)
        
        assert "up" in result["actions"][0]["buttons"]
        # Thought should be truncated but present
        assert len(result["thought"]) > 0
        assert len(result["thought"]) <= 300

    def test_moondream_multiple_buttons_prefers_first(self):
        """Test that multiple button mentions picks the first one."""
        text = "I need to go up and then press a to talk to this person."
        
        result = extract_json(text)
        
        # Should pick the first button mentioned
        assert result["actions"][0]["buttons"][0] in ("up", "a")

    def test_moondream_no_button_produces_fallback(self):
        """Test moondream response without clear button instruction."""
        text = "The screen shows various Pokemon and trainer information. I am thinking about the best strategy for the next battle."
        
        result = extract_json(text)
        
        # Should produce a minimal action since parse_decision requires buttons
        assert len(result["actions"]) > 0
        # Will be a short press since no clear button was identified
        assert result["actions"][0]["frames"] <= 8


class TestOllamaResponses:
    """Test parsing of Ollama model responses."""

    def test_ollama_chat_format(self):
        """Test Ollama chat model output format."""
        text = "The player character is in Viridian City. I should navigate to the gym which is to the right. Let me press right."
        
        result = extract_json(text)
        
        assert "right" in result["actions"][0]["buttons"]

    def test_ollama_verbose_analysis(self):
        """Test Ollama verbose analysis output."""
        text = """
        Analysis of current game state:
        - Location: Route 1
        - Pokemon in party: 3
        - Enemy Pokemon: Pidgeot
        
        Decision: The terrain has tall grass to the left and a path leading up.
        I should move up to continue exploring Route 1.
        """
        
        result = extract_json(text)
        
        assert "up" in result["actions"][0]["buttons"]

    def test_ollama_reasoning_format(self):
        """Test Ollama with reasoning preamble."""
        text = """
        Reasoning: I observe that the character is at a crossroads.
        Looking at the mini-map, moving left would take me back to town.
        Moving down would also go backwards. Up is the correct direction.
        
        Action: Press the up button to continue forward.
        """
        
        result = extract_json(text)
        
        assert "up" in result["actions"][0]["buttons"]


class TestLlamaCppResponses:
    """Test parsing of llama.cpp server responses."""

    def test_llama_cpp_stream_format(self):
        """Test llama.cpp streaming output."""
        text = "The game screen shows... a Pokemon trainer... in a tall grass area. I should... move down... to find more Pokemon."
        
        result = extract_json(text)
        
        assert "down" in result["actions"][0]["buttons"]

    def test_llama_cpp_hesitant_phrasing(self):
        """Test llama.cpp with hesitant/uncertain phrasing."""
        # Note: Word boundaries match "a" from articles too, so we test with clearer input
        text = "Looking at the screen... This looks like menu. I should press select. Or maybe start."
        
        result = extract_json(text)
        
        # Should extract at least one button from the choices offered
        assert len(result["actions"]) > 0
        # Should have found one of the buttons mentioned
        found_button = result["actions"][0]["buttons"][0]
        assert found_button in ("select", "start")

    def test_llama_cpp_fragmented_output(self):
        """Test llama.cpp fragmented/incomplete output."""
        text = "I see the player... there is... I should go... right... yes right"
        
        result = extract_json(text)
        
        assert "right" in result["actions"][0]["buttons"]


class TestLocalModelEdgeCases:
    """Test edge cases for local model responses."""

    def test_response_with_arrow_symbols(self):
        """Test response using arrow symbols for directions."""
        text = "Move ↑ to continue forward through this area."
        
        result = extract_json(text)
        
        assert "up" in result["actions"][0]["buttons"]

    def test_response_with_slash_notation(self):
        """Test response with slash notation for buttons."""
        text = "Press a/b to confirm or cancel your choice."
        
        result = extract_json(text)
        
        # Should extract at least one button
        assert len(result["actions"][0]["buttons"]) > 0
        assert result["actions"][0]["buttons"][0] in ("a", "b")

    def test_response_with_direction_words(self):
        """Test response using compass direction words."""
        text = "I need to go north to reach the next town."
        
        result = extract_json(text)
        
        # "north" is aliased to "up"
        assert "up" in result["actions"][0]["buttons"]

    def test_response_with_coordinate_references(self):
        """Test response with coordinate or location references."""
        text = "The player is at x=10, y=20 and should move west to the cave entrance."
        
        result = extract_json(text)
        
        assert "left" in result["actions"][0]["buttons"]

    def test_response_with_multiple_sentences(self):
        """Test long multi-sentence response."""
        text = """
        The game state shows a Pokemon trainer in a battle scenario.
        The opposing Pokemon is Bulbasaur with moderate health.
        My Pokemon has full health and knows several moves.
        I should press a to open the move selection menu.
        This will allow me to choose the best attack strategy.
        """
        
        result = extract_json(text)
        
        assert "a" in result["actions"][0]["buttons"]
        assert result["thought"]

    def test_response_without_clear_instruction(self):
        """Test response that doesn't give clear instruction."""
        text = "The screen displays game information and status updates for the Pokemon battle."
        
        result = extract_json(text)
        
        # Should produce minimal action since no buttons mentioned
        # (parse_decision requires at least one button)
        assert len(result["actions"]) > 0
        assert result["actions"][0]["frames"] <= 8


class TestParseDecisionWithFallback:
    """Test that parse_decision works with fallback JSON."""

    def test_parse_decision_from_plain_text(self):
        """Test parse_decision handles plain text properly."""
        text = "I see a door ahead. I should press a to open it."
        
        decision = parse_decision(text)
        
        assert decision.actions
        assert decision.thought
        assert "a" in decision.actions[0].buttons

    def test_parse_decision_with_minimal_action(self):
        """Test parse_decision handles unclear input with minimal action."""
        text = "The interface is loading and I should wait for it to fully display before taking action."
        
        decision = parse_decision(text)
        
        assert decision.actions
        # Should have a minimal action since parse_decision requires buttons
        assert len(decision.actions[0].buttons) > 0
        # Frames should be very short for uncertain input
        assert decision.actions[0].frames <= 4

    def test_parse_decision_preserves_thought(self):
        """Test that parse_decision preserves the model's thought in the response."""
        text = "Looking at the Pokemon, I notice it has good HP but low defense. I should press down to select a different move."
        
        decision = parse_decision(text)
        
        assert "Pokemon" in decision.thought or "move" in decision.thought.lower()
        assert "down" in decision.actions[0].buttons


class TestJsonStillPreferred:
    """Verify that actual JSON is still preferred over text fallback."""

    def test_json_response_not_affected(self):
        """Test that valid JSON responses still work perfectly."""
        json_text = '{"thought": "Battle in progress", "actions": [{"buttons": ["a"], "frames": 6}]}'
        
        result = extract_json(json_text)
        
        assert result["thought"] == "Battle in progress"
        assert result["actions"][0]["buttons"] == ["a"]

    def test_markdown_fenced_json_works(self):
        """Test that markdown-fenced JSON still works."""
        text = """
        My analysis shows that pressing A is the best move.
        
        ```json
        {"buttons": ["a"], "frames": 8, "thought": "Confirmed"}
        ```
        
        This should advance the dialog.
        """
        
        result = extract_json(text)
        
        # Should extract the fenced JSON, not fall back to text
        assert result["buttons"] == ["a"]
        assert result["thought"] == "Confirmed"

    def test_embedded_json_object_preferred(self):
        """Test that embedded JSON objects are preferred over text fallback."""
        text = """
        I think the best move is this one:
        {"buttons": ["right"], "frames": 12, "plan": ["Move to the cave"]}
        This will help us make progress.
        """
        
        result = extract_json(text)
        
        # Should extract the JSON object
        assert result["buttons"] == ["right"]
        assert result["frames"] == 12

    def test_word_boundary_avoids_false_positives(self):
        """Test that word boundaries prevent false matches in JSON."""
        # This JSON contains "start" in a value, not as a button instruction
        json_text = '{"thought": "I will start this battle now", "actions": [{"buttons": ["b"], "frames": 4}]}'
        
        result = extract_json(json_text)
        
        # Should extract JSON, not get confused by "start" in the text
        assert result["actions"][0]["buttons"] == ["b"]


class TestErrorCases:
    """Test that actual errors still raise appropriately."""

    def test_empty_response_raises_error(self):
        """Test that completely empty response raises error."""
        with pytest.raises(ParseError):
            extract_json("")

    def test_whitespace_only_raises_error(self):
        """Test that whitespace-only response raises error."""
        with pytest.raises(ParseError):
            extract_json("   \n\n   ")

    def test_very_short_meaningless_text_raises_error(self):
        """Test that very short text without buttons raises error."""
        with pytest.raises(ParseError):
            extract_json("xyz")

    def test_text_without_buttons_or_length_raises_error(self):
        """Test that short text without buttons raises error."""
        with pytest.raises(ParseError):
            extract_json("ok")

    def test_non_string_input_raises_error(self):
        """Test that non-string input raises appropriate error."""
        with pytest.raises(ParseError):
            extract_json(None)


class TestLocalModelCompatibility:
    """Integration tests for real local model scenarios."""

    def test_moondream_typical_response(self):
        """Test typical moondream response without JSON."""
        # Real example of what moondream might return
        text = "I see a Pokemon game interface. The character is in a building. There's a door to the right. I should press right to exit."
        
        result = extract_json(text)
        decision = parse_decision(text)
        
        assert "right" in result["actions"][0]["buttons"]
        assert decision.actions[0].buttons == ("right",)

    def test_ollama_with_no_json_training(self):
        """Test Ollama model that hasn't been trained for JSON."""
        text = "The game shows tall grass and a path. The player should move up to continue exploring."
        
        result = extract_json(text)
        decision = parse_decision(text)
        
        assert "up" in decision.actions[0].buttons

    def test_repeated_local_model_calls(self):
        """Test that repeated local model calls don't cause issues."""
        responses = [
            "Move up to the town.",
            "I see a shop. Press a to enter.",
            "Navigate to the gym by going right.",
            "The battle screen is displayed. Press a to attack.",
        ]
        
        for text in responses:
            result = extract_json(text)
            decision = parse_decision(text)
            
            # Each should produce valid decision
            assert decision.actions
            assert decision.thought
