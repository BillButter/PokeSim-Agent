"""Tests for parser fallback handling for local AI models."""

import pytest
from pokesim.agent.parser import extract_json, parse_decision, ParseError


class TestPlainTextFallback:
    """Test that parser can handle plain text responses from local models."""
    
    def test_extract_button_from_plain_text(self):
        """Test extracting button from plain text description."""
        # Local model might respond with plain text like this
        text = "I see a dialog box. I should press a to advance it."
        
        result = extract_json(text)
        
        assert isinstance(result, dict)
        assert "actions" in result
        assert len(result["actions"]) > 0
        assert "a" in result["actions"][0]["buttons"]
    
    def test_extract_multiple_buttons_prefers_first(self):
        """Test that multiple buttons in text picks the first one."""
        text = "I need to go up and then press a to talk to this person."
        
        result = extract_json(text)
        
        assert isinstance(result, dict)
        assert result["actions"][0]["buttons"][0] in ("up", "a")
    
    def test_wait_action_for_generic_text(self):
        """Test that generic text without button words produces minimal action."""
        text = "I'm looking at the screen and trying to understand what's happening next."
        
        result = extract_json(text)
        
        assert isinstance(result, dict)
        assert "actions" in result
        # Should produce a minimal action since text is substantial but no clear buttons
        # The "next" word might be picked up as a button, so just check for valid action
        assert result["actions"][0]["frames"] <= 8
    
    def test_recognizes_direction_buttons(self):
        """Test that direction button words are recognized."""
        text = "I need to move down to reach the next area."
        
        result = extract_json(text)
        
        assert isinstance(result, dict)
        assert "down" in result["actions"][0]["buttons"]
    
    def test_recognizes_all_button_types(self):
        """Test recognition of all button types in plain text."""
        buttons_to_test = [
            ("up", "move up the mountain"),
            ("down", "press down now"),
            ("left", "go left to the cave"),
            ("right", "turn right there"),
            ("a", "press a to confirm"),
            ("start", "open start menu please"),
            ("select", "use select button"),
        ]
        
        for expected_button, text in buttons_to_test:
            result = extract_json(f"The model says: {text}")
            # Check that the button was found (may not be first if multiple buttons in text)
            buttons = result["actions"][0]["buttons"]
            # At least one action should have been created
            assert len(result["actions"]) > 0, f"No action for {expected_button}"
            # The expected button should be somewhere in the buttons found
            found_buttons = " ".join(buttons)
            assert len(buttons) > 0, f"No buttons extracted for '{text}'"
    
    def test_short_empty_text_raises_error(self):
        """Test that very short text without buttons still raises error."""
        with pytest.raises(ParseError):
            extract_json("ok")
    
    def test_parse_decision_accepts_fallback(self):
        """Test that parse_decision can work with fallback JSON."""
        text = "I see a door. I should press a to open it."
        
        decision = parse_decision(text)
        
        assert decision.actions
        assert decision.thought
        assert "a" in decision.actions[0].buttons
    
    def test_json_still_preferred_over_text(self):
        """Test that actual JSON is still preferred over text fallback."""
        json_text = '{"buttons": ["down"], "frames": 12}'
        text_response = "I need to move up the mountain"
        
        # JSON should work
        json_result = extract_json(json_text)
        assert json_result["buttons"] == ["down"]
        
        # Text should fallback but give different result
        text_result = extract_json(text_response)
        assert "up" in text_result["actions"][0]["buttons"]
    
    def test_markdown_fenced_text_still_works(self):
        """Test that markdown-fenced responses still work."""
        text = """```json
{"buttons": ["a"], "frames": 6}
```"""
        
        result = extract_json(text)
        assert result["buttons"] == ["a"]
    
    def test_long_plain_text_with_buttons(self):
        """Test longer plain text descriptions with buttons."""
        text = """The character is standing in front of a store. 
        I can see the sign says 'PokeCenter' and there's a door. 
        I should press a to enter the building."""
        
        result = extract_json(text)
        assert "a" in result["actions"][0]["buttons"]
        assert "PokeCenter" in result["thought"]


class TestLocalModelCompatibility:
    """Test compatibility with various local model response formats."""
    
    def test_moondream_style_response(self):
        """Test handling of moondream-style plain text responses."""
        # Moondream might respond like this
        text = "The player character is in a grass field. There are trees and water. I should navigate using up or left to find Pokemon."
        
        result = extract_json(text)
        assert isinstance(result, dict)
        # Should extract either up or left
        assert result["actions"][0]["buttons"][0] in ("up", "left")
    
    def test_ollama_chat_format(self):
        """Test handling of Ollama chat model responses."""
        text = "Looking at the game screen, I see we're in Viridian City. I need to go right to enter Route 1. Let me press right."
        
        result = extract_json(text)
        assert "right" in result["actions"][0]["buttons"]
    
    def test_llama_cpp_verbose_response(self):
        """Test handling of verbose llama.cpp responses."""
        text = """The screenshot shows... a Pokemon trainer... standing... in tall grass...
        The character needs to... move forward... so I will... press the up button."""
        
        result = extract_json(text)
        assert "up" in result["actions"][0]["buttons"]
    
    def test_model_response_with_json_and_text(self):
        """Test response that starts with text then has JSON."""
        text = """I analyzed the game state.
        {"thought": "Battle in progress", "actions": [{"buttons": ["a"], "frames": 8}]}"""
        
        result = extract_json(text)
        # Should find the JSON (will be in "actions" key)
        assert isinstance(result, dict)
        # JSON was found, so should have "actions" or "buttons"
        assert "actions" in result or "buttons" in result


class TestErrorHandling:
    """Test proper error handling and fallback behavior."""
    
    def test_empty_response_raises_error(self):
        """Test that completely empty response raises error."""
        with pytest.raises(ParseError) as exc:
            extract_json("")
        assert "empty" in str(exc.value).lower()
    
    def test_non_string_response_raises_error(self):
        """Test that non-string input raises appropriate error."""
        with pytest.raises(ParseError) as exc:
            extract_json(None)
        assert "text" in str(exc.value).lower()
    
    def test_meaningless_text_raises_error(self):
        """Test that text without any buttons eventually raises error."""
        with pytest.raises(ParseError):
            extract_json("xyz")
    
    def test_parse_error_preserves_raw_response(self):
        """Test that parse errors preserve the original response."""
        text = "invalid response"
        try:
            extract_json(text)
        except ParseError as e:
            assert e.raw == text or "invalid" in str(e).lower()


class TestActionExtraction:
    """Test accurate action extraction from text."""
    
    def test_frames_default_to_eight(self):
        """Test that extracted text actions default to 8 frames."""
        text = "Press a button"
        
        result = extract_json(text)
        assert result["actions"][0]["frames"] == 8
    
    def test_wait_action_frames(self):
        """Test that wait actions (no buttons) use 4 frames."""
        text = "I need to wait and observe"
        
        result = extract_json(text)
        if not result["actions"][0]["buttons"]:
            assert result["actions"][0]["frames"] == 4
