"""Detect game pauses (static screens) before AI decision-making.

The AI model should only make decisions when the game has stabilized
on a static screen. This module detects when the screen hasn't changed
significantly for a short duration, indicating it's safe to ask the AI
for the next move.

This prevents the game rendering from being interrupted mid-animation
or mid-action by the AI model thinking time.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

PAUSE_DETECTION_THRESHOLD = 0.85  # Screen must be 85% identical to previous frame
PAUSE_DURATION = 0.5  # Screen must be static for 500ms
FRAME_CHECK_INTERVAL = 0.1  # Check frame every 100ms


class PauseDetector:
    """Detects when the game screen is mostly static (paused)."""

    def __init__(self, threshold: float = PAUSE_DETECTION_THRESHOLD, 
                 duration: float = PAUSE_DURATION,
                 check_interval: float = FRAME_CHECK_INTERVAL):
        """Initialize pause detector.
        
        Args:
            threshold: Similarity threshold (0-1) to consider screens identical
            duration: How long screen must be static (seconds)
            check_interval: How often to check for changes (seconds)
        """
        self.threshold = threshold
        self.duration = duration
        self.check_interval = check_interval
        self._last_frame_hash: str | None = None
        self._last_change_time: float = time.monotonic()
        self._pause_start_time: float | None = None

    def check_frame(self, frame_data: bytes) -> bool:
        """Check if the screen is currently in a pause state.
        
        Args:
            frame_data: Raw frame bytes (PNG or similar)
            
        Returns:
            True if screen has been static long enough to be considered paused
        """
        current_time = time.monotonic()
        current_hash = hashlib.sha256(frame_data).hexdigest()
        
        # First frame - start tracking
        if self._last_frame_hash is None:
            self._last_frame_hash = current_hash
            self._pause_start_time = current_time
            return False
        
        # Check if frame is identical to last frame
        is_same_frame = self._is_frame_similar(current_hash)
        
        if is_same_frame:
            # Same frame - continue pause detection
            elapsed = current_time - self._pause_start_time
            if elapsed >= self.duration:
                log.debug(f"Screen pause detected after {elapsed:.2f}s of stability")
                return True
        else:
            # Frame changed - restart pause detection
            self._pause_start_time = current_time
            self._last_change_time = current_time
        
        self._last_frame_hash = current_hash
        return False

    def _is_frame_similar(self, new_hash: str) -> bool:
        """Check if frame hash is similar to last frame.
        
        For exact frame matching, hashes must be identical.
        In practice, we check exact hash equality since frames are 
        typically either identical or noticeably different.
        
        Args:
            new_hash: SHA256 hash of current frame
            
        Returns:
            True if frames are similar enough to be considered the same
        """
        if self._last_frame_hash is None:
            return False
        
        # Frames are identical if hashes match exactly
        return new_hash == self._last_frame_hash

    def reset(self) -> None:
        """Reset pause detection state."""
        self._last_frame_hash = None
        self._last_change_time = time.monotonic()
        self._pause_start_time = None

    def time_until_pause(self) -> float:
        """Get seconds until pause is detected.
        
        Returns:
            Seconds remaining for pause detection, or 0.0 if paused
        """
        if self._pause_start_time is None:
            return self.duration
        
        elapsed = time.monotonic() - self._pause_start_time
        remaining = max(0.0, self.duration - elapsed)
        return remaining

    def is_actively_detecting(self) -> bool:
        """Check if pause detection is currently in progress.
        
        Returns:
            True if watching for a pause, False if frame changed recently
        """
        return self._pause_start_time is not None
