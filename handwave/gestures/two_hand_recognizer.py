"""Two-hand gestures as an explicit relationship between two ``HandState`` snapshots.

Deliberately does not just run the single-hand classifier twice and guess: a
two-hand gesture is only recognized from *relational* features (centroid
distance and its change over time) combined with pose agreement between the
two hands, not from either hand's pose alone.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from handwave.gestures.hand_state import HandState

# Minimum change in hand separation per frame that counts as moving apart/together.
# Motion only counts while both hands hold an open palm (see update()).
MOTION_DISTANCE_THRESHOLD = 0.03


@dataclass(frozen=True)
class TwoHandDetection:
    name: str = "Unknown"
    confidence: float = 0.0
    hands_detected: int = 0
    left_pose: str | None = None
    right_pose: str | None = None


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


class TwoHandRecognizer:
    """Stateful: tracks centroid distance across frames to detect apart/together motion."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._previous_distance: float | None = None

    def reset(self) -> None:
        self._previous_distance = None

    def update(self, hands: list[HandState]) -> TwoHandDetection:
        if len(hands) != 2:
            self.reset()
            return TwoHandDetection(hands_detected=len(hands))

        first, second = hands
        distance = _distance(first.centroid, second.centroid)
        left_pose, right_pose = self._label_poses(first, second)

        motion: str | None = None
        if self._previous_distance is not None:
            delta = distance - self._previous_distance
            if abs(delta) >= MOTION_DISTANCE_THRESHOLD:
                motion = "apart" if delta > 0 else "together"
        self._previous_distance = distance

        both_open = first.pose == "Open Palm" and second.pose == "Open Palm"
        both_fists = first.pose == "Fist" and second.pose == "Fist"

        if both_open and motion == "apart":
            name, confidence = "Hands Moving Apart", 0.9
        elif both_open and motion == "together":
            name, confidence = "Hands Moving Together", 0.9
        elif both_open:
            name, confidence = "Both Palms Open", 0.85
        elif both_fists:
            name, confidence = "Both Fists", 0.85
        else:
            name, confidence = "Unknown", 0.0

        return TwoHandDetection(
            name=name,
            confidence=confidence,
            hands_detected=2,
            left_pose=left_pose,
            right_pose=right_pose,
        )

    @staticmethod
    def _label_poses(first: HandState, second: HandState) -> tuple[str | None, str | None]:
        by_hand = {first.handedness: first.pose, second.handedness: second.pose}
        return by_hand.get("Left"), by_hand.get("Right")
