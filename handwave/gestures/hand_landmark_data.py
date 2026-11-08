"""Normalized hand landmark data and finger-state extraction."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Sequence

FingerState = Literal["extended", "folded"]


@dataclass(frozen=True)
class NormalizedLandmark:
    """One MediaPipe landmark in normalized image coordinates."""

    x: float
    y: float
    z: float


class HandLandmarkData:
    """Immutable snapshot of all 21 landmarks for one detected hand."""

    FINGER_JOINTS = {
        "thumb": (2, 3, 4),
        "index": (5, 6, 7, 8),
        "middle": (9, 10, 11, 12),
        "ring": (13, 14, 15, 16),
        "pinky": (17, 18, 19, 20),
    }
    EXTENDED_ANGLE_DEGREES = 150.0

    def __init__(self, landmarks: Sequence[object]) -> None:
        if len(landmarks) != 21:
            raise ValueError(f"Expected 21 hand landmarks, received {len(landmarks)}")
        self._landmarks = tuple(
            NormalizedLandmark(float(point.x), float(point.y), float(point.z))
            for point in landmarks
        )

    @classmethod
    def from_mediapipe(cls, hand_landmarks: object) -> "HandLandmarkData":
        """Build a snapshot from MediaPipe's NormalizedLandmarkList."""
        return cls(hand_landmarks.landmark)

    def get_landmarks(self) -> tuple[NormalizedLandmark, ...]:
        """Return all 21 normalized points in MediaPipe landmark-index order."""
        return self._landmarks

    def get_finger_states(self) -> dict[str, FingerState]:
        """Classify each finger using joint angles, independent of hand rotation."""
        threshold = self.EXTENDED_ANGLE_DEGREES / 180.0
        return {
            finger: "extended" if score >= threshold else "folded"
            for finger, score in self.get_finger_extension_scores().items()
        }

    # Thumb reach: distance from the thumb tip to the middle-finger knuckle,
    # relative to palm length (wrist -> middle knuckle). A thumb folded across
    # the palm stays *straight*, so joint angles cannot tell it apart from an
    # extended thumb (62% balanced accuracy on HaGRID); reach separates them
    # at 95%. A reach of THUMB_EXTENDED_REACH maps to the shared 150° threshold.
    THUMB_EXTENDED_REACH = 0.6

    def thumb_reach(self) -> float:
        points = self._landmarks
        palm = math.hypot(points[9].x - points[0].x, points[9].y - points[0].y)
        if palm == 0:
            return 0.0
        return math.hypot(points[4].x - points[9].x, points[4].y - points[9].y) / palm

    def thumb_reach_to_pinky(self) -> float:
        """Thumb-tip distance to the pinky knuckle, relative to palm length."""
        points = self._landmarks
        palm = math.hypot(points[9].x - points[0].x, points[9].y - points[0].y)
        if palm == 0:
            return 0.0
        return math.hypot(points[4].x - points[17].x, points[4].y - points[17].y) / palm

    def get_finger_extension_scores(self) -> dict[str, float]:
        """Return continuous 0..1 straightness scores for live confidence values."""
        scores: dict[str, float] = {}
        threshold = self.EXTENDED_ANGLE_DEGREES / 180.0
        for name, joints in self.FINGER_JOINTS.items():
            if name == "thumb":
                score = self.thumb_reach() / self.THUMB_EXTENDED_REACH * threshold
            else:
                mcp, pip, dip, tip = joints
                score = min(
                    self._angle(mcp, pip, dip),
                    self._angle(pip, dip, tip),
                ) / 180.0
            scores[name] = max(0.0, min(1.0, score))
        return scores

    def get_pinch_distance(self) -> float:
        """Return normalized 3D distance between thumb tip and index tip."""
        thumb, index = self._landmarks[4], self._landmarks[8]
        return math.sqrt(
            (thumb.x - index.x) ** 2
            + (thumb.y - index.y) ** 2
            + (thumb.z - index.z) ** 2
        )

    def get_pinch_midpoint_y(self) -> float:
        """Return the normalized vertical midpoint of thumb and index tips."""
        return (self._landmarks[4].y + self._landmarks[8].y) / 2.0

    def get_centroid(self) -> tuple[float, float]:
        """Return the normalized image-plane centroid of all 21 landmarks."""
        count = len(self._landmarks)
        return (
            sum(point.x for point in self._landmarks) / count,
            sum(point.y for point in self._landmarks) / count,
        )

    def _angle(self, first: int, vertex: int, last: int) -> float:
        a, b, c = (self._landmarks[index] for index in (first, vertex, last))
        vector_a = (a.x - b.x, a.y - b.y, a.z - b.z)
        vector_c = (c.x - b.x, c.y - b.y, c.z - b.z)
        magnitude = math.sqrt(sum(value * value for value in vector_a)) * math.sqrt(
            sum(value * value for value in vector_c)
        )
        if magnitude == 0:
            return 0.0
        cosine = sum(x * y for x, y in zip(vector_a, vector_c)) / magnitude
        return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
