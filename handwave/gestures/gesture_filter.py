"""Temporal smoothing for frame-by-frame gesture recognition."""

from __future__ import annotations

import time
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class FilteredGesture:
    raw_gesture: str
    stable_gesture: str


class GestureFilter:
    """Change the stable gesture only on consistent, recent evidence.

    A gesture becomes stable when, within a short sliding window, it fills at
    least ``min_share`` of the frames *and* has been present for at least
    ``persistence_seconds``. The same rule applies to leaving a gesture (to
    "Unknown"), so brief tracking dropouts are ignored.

    Why not a long majority vote: with a 1 s majority window plus a 0.5 s
    hold, a new gesture first had to outvote a full second of old frames,
    which measured ~1.03 s from pose to action. This window reacts in about a
    third of that while rejecting misreads and flicker at least as well
    (see tests/test_gesture_filter.py and docs/performance.md).
    """

    def __init__(
        self,
        persistence_seconds: float = 0.25,
        history_seconds: float = 0.4,
        min_share: float = 0.7,
        max_frames: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if persistence_seconds < 0 or history_seconds <= 0 or max_frames <= 0 or not 0.5 < min_share <= 1.0:
            raise ValueError("Gesture filter timing, share and history limits must be valid")
        self.persistence_seconds = persistence_seconds
        self.history_seconds = max(history_seconds, persistence_seconds)
        self.min_share = min_share
        self._clock = clock
        self._history: deque[tuple[float, str]] = deque(maxlen=max_frames)
        self._stable = "Unknown"

    def update(self, raw_gesture: str | None) -> FilteredGesture:
        """Add one frame and return its raw and filtered gesture names."""
        now = self._clock()
        raw = raw_gesture or "Unknown"
        self._history.append((now, raw))
        cutoff = now - self.history_seconds
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

        dominant, count = Counter(gesture for _, gesture in self._history).most_common(1)[0]
        if dominant != self._stable and count >= self.min_share * len(self._history):
            first_seen = next(t for t, gesture in self._history if gesture == dominant)
            if now - first_seen >= self.persistence_seconds:
                self._stable = dominant

        return FilteredGesture(raw_gesture=raw, stable_gesture=self._stable)

    def reset(self) -> None:
        """Clear all temporal state, for example when the camera restarts."""
        self._history.clear()
        self._stable = "Unknown"
