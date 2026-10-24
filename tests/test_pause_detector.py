"""Tests for game pause detection system."""

from __future__ import annotations

import time

import pytest

from pokesim.agent.pause_detector import PauseDetector


class TestPauseDetectorBasic:
    """Test basic pause detection functionality."""

    def test_pause_detector_initialization(self):
        """Test pause detector initializes correctly."""
        detector = PauseDetector()

        assert detector.threshold == 0.85
        assert detector.duration == 0.5
        assert detector.check_interval == 0.1
        assert not detector.is_actively_detecting()

    def test_identical_frames_detected_as_pause(self):
        """Test that identical frames are recognized as pause."""
        detector = PauseDetector(duration=0.1)  # Quick for testing
        test_frame = b"fake_frame_data_12345"

        # First frame starts detection
        assert not detector.check_frame(test_frame)
        assert detector.is_actively_detecting()

        # Wait for pause duration
        time.sleep(0.15)

        # Same frame should be detected as pause
        assert detector.check_frame(test_frame)

    def test_frame_change_resets_detection(self):
        """Test that frame changes reset pause detection."""
        detector = PauseDetector(duration=0.1)
        frame1 = b"frame_1_data"
        frame2 = b"frame_2_data"

        # First frame
        detector.check_frame(frame1)
        assert detector.is_actively_detecting()

        # Different frame resets detection timer
        detector.check_frame(frame2)
        # Still detecting but timer restarted
        assert not detector.check_frame(frame2)

        # Wait for pause on frame2
        time.sleep(0.15)
        assert detector.check_frame(frame2)

    def test_reset_clears_state(self):
        """Test that reset clears pause detector state."""
        detector = PauseDetector()
        test_frame = b"test_frame"

        detector.check_frame(test_frame)
        assert detector.is_actively_detecting()

        detector.reset()
        assert not detector.is_actively_detecting()
        assert detector.time_until_pause() == detector.duration

    def test_time_until_pause_calculation(self):
        """Test time until pause calculation."""
        detector = PauseDetector(duration=0.2)
        test_frame = b"test_frame"

        # No detection yet
        assert detector.time_until_pause() == 0.2

        # Start detection
        detector.check_frame(test_frame)
        remaining = detector.time_until_pause()
        assert 0 < remaining <= 0.2

        # Wait half duration
        time.sleep(0.1)
        remaining = detector.time_until_pause()
        assert 0 < remaining <= 0.1

    def test_static_screen_sequence(self):
        """Test detection of static screen sequence."""
        detector = PauseDetector(duration=0.1)
        static_frame = b"static_screen_data_xyz"

        # First check starts detection
        assert not detector.check_frame(static_frame)
        
        # Wait for pause duration
        time.sleep(0.15)
        
        # Should now be detected as pause
        assert detector.check_frame(static_frame)

    def test_animated_screen_no_pause(self):
        """Test that animated/changing screen doesn't trigger pause."""
        detector = PauseDetector(duration=0.2)

        # Simulate changing frames
        for i in range(5):
            frame = f"animated_frame_{i}".encode()
            result = detector.check_frame(frame)
            assert result is False  # No pause while animating
            time.sleep(0.05)


class TestPauseDetectorEdgeCases:
    """Test edge cases and special scenarios."""

    def test_none_last_frame_hash(self):
        """Test handling of first frame when no previous hash."""
        detector = PauseDetector()
        frame = b"first_frame"

        # First check should not be pause
        assert not detector.check_frame(frame)

    def test_empty_frame_data(self):
        """Test handling of empty frame data."""
        detector = PauseDetector()

        # Empty frames
        assert not detector.check_frame(b"")
        assert not detector.check_frame(b"")

    def test_very_similar_frames_different_data(self):
        """Test that frames with different data are not confused."""
        detector = PauseDetector(duration=0.1)

        # Frames that might look similar but have different hashes
        frame1 = b"frame_with_pixel_data_" + bytes([0x01] * 100)
        frame2 = b"frame_with_pixel_data_" + bytes([0x02] * 100)

        detector.check_frame(frame1)
        time.sleep(0.15)

        # Different frame should reset detection
        result = detector.check_frame(frame2)
        assert not result  # Not a pause, new frame detected

    def test_long_duration_setting(self):
        """Test with longer pause duration."""
        detector = PauseDetector(duration=0.3)
        frame = b"static_frame"

        detector.check_frame(frame)

        # At 0.1s - should not be pause
        time.sleep(0.1)
        assert not detector.check_frame(frame)

        # At 0.2s - should not be pause
        time.sleep(0.1)
        assert not detector.check_frame(frame)

        # At 0.35s - should be pause
        time.sleep(0.15)
        assert detector.check_frame(frame)

    def test_short_duration_setting(self):
        """Test with very short pause duration."""
        detector = PauseDetector(duration=0.05)
        frame = b"quick_frame"

        detector.check_frame(frame)
        time.sleep(0.08)

        assert detector.check_frame(frame)


class TestPauseDetectorIntegration:
    """Integration-style tests for pause detection."""

    def test_realistic_pause_sequence(self):
        """Test realistic sequence of pause detection."""
        detector = PauseDetector(duration=0.08)

        # Simulate game animation: frames 0-3 animating
        for i in range(4):
            frame = f"animation_frame_{i}".encode()
            result = detector.check_frame(frame)
            assert not result
            time.sleep(0.02)

        # Game pauses: static frame
        static_frame = b"pause_screen_stable"
        assert not detector.check_frame(static_frame)  # First static frame
        
        # Wait for pause duration
        time.sleep(0.10)
        
        # Should now be detected as pause
        assert detector.check_frame(static_frame)

    def test_multiple_pause_detections(self):
        """Test detecting multiple pauses in sequence."""
        detector = PauseDetector(duration=0.08)

        for pause_num in range(3):
            # Reset for new pause detection
            detector.reset()

            # Animate for a bit
            for i in range(2):
                frame = f"pause_{pause_num}_frame_{i}".encode()
                detector.check_frame(frame)
                time.sleep(0.01)

            # Static screen
            static = f"pause_{pause_num}_static".encode()
            assert not detector.check_frame(static)  # First check of static frame
            time.sleep(0.10)
            result = detector.check_frame(static)

            assert result, f"Pause {pause_num} not detected"

    def test_pause_detector_state_machine(self):
        """Test pause detector behaves like a state machine."""
        detector = PauseDetector(duration=0.08)

        # State 1: Fresh detector - not detecting
        assert not detector.is_actively_detecting()

        # State 2: First frame - start detecting
        detector.check_frame(b"frame1")
        assert detector.is_actively_detecting()

        # State 3: Same frame, not enough time - still detecting
        time.sleep(0.04)
        detector.check_frame(b"frame1")
        assert detector.is_actively_detecting()

        # State 4: Different frame - restart detection
        detector.check_frame(b"frame2")
        assert detector.is_actively_detecting()

        # State 5: Wait for duration then check - pause detected
        time.sleep(0.10)
        result = detector.check_frame(b"frame2")
        assert result


class TestPauseDetectorUtility:
    """Test utility methods."""

    def test_custom_threshold(self):
        """Test custom threshold setting."""
        detector = PauseDetector(threshold=0.95)
        assert detector.threshold == 0.95

    def test_custom_interval(self):
        """Test custom check interval."""
        detector = PauseDetector(check_interval=0.05)
        assert detector.check_interval == 0.05

    def test_detector_independence(self):
        """Test multiple detectors are independent."""
        detector1 = PauseDetector()
        detector2 = PauseDetector()

        detector1.check_frame(b"frame1")
        detector2.check_frame(b"frame2")

        assert detector1._last_frame_hash != detector2._last_frame_hash
