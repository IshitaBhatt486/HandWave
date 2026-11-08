"""MediaPipe-backed hand landmark processing."""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import cv2

from handwave.vision.lazy_imports import install_matplotlib_placeholder

install_matplotlib_placeholder()  # must run before mediapipe is imported (saves ~41 MB, ~0.8 s)
import mediapipe as mp  # noqa: E402

from handwave.vision.overlay_text import put_text

from handwave.gestures.custom_gesture import (
    CustomGestureMatcher,
    GestureDetection,
    combine_detections,
    extension_vector,
)
from handwave.gestures.hand_landmark_data import HandLandmarkData
from handwave.gestures.hand_state import HandState
from handwave.gestures.two_hand_recognizer import TwoHandDetection, TwoHandRecognizer

logger = logging.getLogger(__name__)

MAX_HANDS = 2  # two-hand gestures; tracked adaptively (see GestureEngine)


@dataclass(frozen=True)
class GestureResult:
    hands_detected: int = 0
    name: str | None = None
    fps: float = 0.0
    landmarks: HandLandmarkData | None = None
    confidence: float = 0.0
    hands: tuple[HandState, ...] = ()
    two_hand: TwoHandDetection = field(default_factory=TwoHandDetection)


class GestureEngine:
    """Detects and draws hand landmarks; gesture classification can be extended here."""

    # BGR. Champagne joints on ivory hairline bones, matching the app theme.
    LANDMARK_STYLE = mp.solutions.drawing_utils.DrawingSpec(
        color=(110, 169, 201), thickness=-1, circle_radius=3
    )
    CONNECTION_STYLE = mp.solutions.drawing_utils.DrawingSpec(
        color=(214, 224, 231), thickness=1, circle_radius=2
    )
    GESTURE_PATTERNS = {
        "Open Palm": {finger: "extended" for finger in ("thumb", "index", "middle", "ring", "pinky")},
        "Fist": {finger: "folded" for finger in ("thumb", "index", "middle", "ring", "pinky")},
        "Thumbs Up": {
            "thumb": "extended", "index": "folded", "middle": "folded", "ring": "folded", "pinky": "folded"
        },
        "Thumbs Down": {
            "thumb": "extended", "index": "folded", "middle": "folded", "ring": "folded", "pinky": "folded"
        },
        "Peace Sign": {
            "thumb": "folded", "index": "extended", "middle": "extended", "ring": "folded", "pinky": "folded"
        },
        "Pointing": {
            "thumb": "folded", "index": "extended", "middle": "folded", "ring": "folded", "pinky": "folded"
        },
    }

    # Adaptive two-hand tracking. MediaPipe re-runs palm detection on *every*
    # frame while fewer than max_num_hands are tracked, so asking for two
    # hands roughly doubled the cost of every one-hand frame (measured 40.8 ms
    # vs 20.0 ms). The engine therefore tracks one hand, and a background
    # probe looks for a second hand a few times per second on the latest
    # frame (MediaPipe releases the GIL, so it runs on another core). While
    # two hands are visible, frames go through the two-hand tracker.
    PROBE_INTERVAL_SECONDS = 0.3
    DUAL_RELEASE_SECONDS = 0.8

    def __init__(
        self,
        clock: Callable[[], float] = time.perf_counter,
        sensitivity: float = 0.6,
        overlay_enabled: bool = True,
        custom_matcher: CustomGestureMatcher | None = None,
        model_complexity: int = 1,
        debug_text: bool = False,
        two_hand_probe: bool = True,
    ) -> None:
        self.custom_matcher = custom_matcher
        self._hands_options = {
            "static_image_mode": False,
            "model_complexity": model_complexity,
            "min_detection_confidence": sensitivity,
            "min_tracking_confidence": sensitivity,
        }
        self._hands = mp.solutions.hands.Hands(max_num_hands=1, **self._hands_options)
        self._dual = None  # two-hand tracker, created on the probe thread when first needed
        self._dual_lock = threading.Lock()
        self._dual_active = False
        self._dual_lost_since: float | None = None
        self._probe_frame = None
        self._probe_stop = threading.Event()
        self._probe_thread: threading.Thread | None = None
        self.two_hand_probe = two_hand_probe
        self.debug_text = debug_text
        self._drawing = mp.solutions.drawing_utils
        self._connections = mp.solutions.hands.HAND_CONNECTIONS
        self._clock = clock
        self._last_frame_time: float | None = None
        self._fps = 0.0
        self.overlay_enabled = overlay_enabled
        self.two_hand_recognizer = TwoHandRecognizer()

    def process(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False  # also makes the frame safe to share with the probe
        result = self._track(rgb)

        detected_hands = result.multi_hand_landmarks or []
        handedness_list = getattr(result, "multi_handedness", None) or []
        count = len(detected_hands)
        now = self._clock()

        hand_states: list[HandState] = []
        for index, landmarks in enumerate(detected_hands):
            classification = handedness_list[index] if index < len(handedness_list) else None
            hand_states.append(HandState.from_mediapipe(landmarks, now, classification))
            if self.overlay_enabled:
                self._drawing.draw_landmarks(
                    frame,
                    landmarks,
                    self._connections,
                    self.LANDMARK_STYLE,
                    self.CONNECTION_STYLE,
                )

        if self._last_frame_time is not None:
            elapsed = now - self._last_frame_time
            if elapsed > 0:
                current_fps = 1.0 / elapsed
                # Smooth the display while keeping it responsive to performance drops.
                self._fps = current_fps if self._fps == 0 else (0.8 * self._fps + 0.2 * current_fps)
        self._last_frame_time = now

        result_gesture = self.recognize_hands(hand_states)
        status = "Hand detected" if count else "No hand detected"
        if self.overlay_enabled and self.debug_text:
            detection = GestureDetection(result_gesture.name or "Unknown", result_gesture.confidence)
            self._draw_overlay(frame, status, detection, result_gesture.landmarks)
        return frame, result_gesture

    @property
    def tracking_two_hands(self) -> bool:
        return self._dual_active

    def _track(self, rgb):
        """Run the right tracker for this frame (see PROBE_INTERVAL_SECONDS)."""
        if self._dual_active and self._dual is not None:
            with self._dual_lock:
                result = self._dual.process(rgb)
            if len(result.multi_hand_landmarks or []) >= 2:
                self._dual_lost_since = None
            else:
                now = time.monotonic()
                if self._dual_lost_since is None:
                    self._dual_lost_since = now
                elif now - self._dual_lost_since >= self.DUAL_RELEASE_SECONDS:
                    self._dual_active = False
                    logger.debug("Second hand gone; back to one-hand tracking")
            return result
        result = self._hands.process(rgb)
        if self.two_hand_probe:
            # Only look for a *second* hand while one is tracked. With no hand
            # in view the one-hand tracker already runs full detection itself,
            # so probing then would only burn CPU while the app sits idle.
            self._probe_frame = rgb if result.multi_hand_landmarks else None
            if self._probe_thread is None:
                self._probe_thread = threading.Thread(target=self._probe_loop, name="HandWave two-hand probe", daemon=True)
                self._probe_thread.start()
        return result

    def _probe_loop(self) -> None:
        while not self._probe_stop.wait(self.PROBE_INTERVAL_SECONDS):
            frame = self._probe_frame
            if self._dual_active or frame is None:
                continue
            try:
                with self._dual_lock:
                    if self._dual is None:
                        self._dual = mp.solutions.hands.Hands(max_num_hands=MAX_HANDS, **self._hands_options)
                    found = len(self._dual.process(frame).multi_hand_landmarks or [])
            except Exception:  # never let the probe take recognition down
                logger.exception("Two-hand probe failed")
                continue
            if found >= 2 and not self._probe_stop.is_set():
                self._dual_lost_since = None
                self._dual_active = True
                logger.debug("Second hand found; switching to two-hand tracking")

    def recognize_hands(self, hand_states: list[HandState]) -> GestureResult:
        """Run recognition over already-extracted hand states.

        This is the exact code path ``process()`` uses after MediaPipe
        extraction, factored out so replayed landmark sequences (which have no
        camera frame to feed MediaPipe) exercise the identical built-in,
        custom, and two-hand recognition logic instead of a second,
        parallel implementation.
        """
        # The first detected hand is treated as "primary" for single-hand fields,
        # preserving prior behavior exactly when only one hand is ever present.
        landmark_data = hand_states[0].landmarks if hand_states else None
        two_hand = self.two_hand_recognizer.update(hand_states)
        gesture = self.detect_gesture(landmark_data)
        return GestureResult(
            hands_detected=len(hand_states),
            name=gesture.name,
            fps=self._fps,
            landmarks=landmark_data,
            confidence=gesture.confidence,
            hands=tuple(hand_states),
            two_hand=two_hand,
        )

    def _draw_overlay(self, frame, status, gesture, landmark_data) -> None:
        put_text(frame, status, (16, 32), 0.75, 1)
        put_text(frame, f"FPS: {self._fps:.1f}", (16, 64), 0.75, 1)
        put_text(frame, f"Raw: {gesture.name} ({gesture.confidence:.0%})", (16, 96), 0.7, 1)
        if landmark_data is not None:
            for row, (finger, state) in enumerate(landmark_data.get_finger_states().items(), start=5):
                put_text(frame, f"{finger.title()}: {state}", (16, 32 * row), 0.6, 1)
            pinch_distance = landmark_data.get_pinch_distance()
            pinch_detected = pinch_distance <= 0.08
            put_text(frame, "Pinch detected" if pinch_detected else "Pinch not detected", (16, 320), 0.6, 1)
            put_text(frame, f"Pinch distance: {pinch_distance:.3f}", (16, 352), 0.6, 1)

    def detect_gesture(self, landmarks: HandLandmarkData | None) -> GestureDetection:
        """Recognize a gesture from a single normalized landmark snapshot.

        Built-in gestures are matched first and always win when they recognize
        anything; an optional custom-gesture matcher only fills in poses the
        built-in patterns leave as "Unknown" (see ``combine_detections``).
        """
        builtin = self._detect_builtin_gesture(landmarks)
        if self.custom_matcher is None or landmarks is None:
            return builtin
        custom = self.custom_matcher.match(extension_vector(landmarks))
        return combine_detections(builtin, custom)

    def _detect_builtin_gesture(self, landmarks: HandLandmarkData | None) -> GestureDetection:
        if landmarks is None:
            return GestureDetection()

        states = landmarks.get_finger_states()
        scores = landmarks.get_finger_extension_scores()
        four_fingers_up = all(states[finger] == "extended" for finger in ("index", "middle", "ring", "pinky"))
        if four_fingers_up and states["thumb"] == "folded" and landmarks.thumb_reach_to_pinky() >= self.PALM_THUMB_MIN_PINKY_REACH:
            # A flat "stop" palm rests the thumb alongside the index finger: short
            # reach to the middle knuckle, but not tucked across toward the
            # pinky like the "four" pose. Treat that thumb as part of the palm.
            states = {**states, "thumb": "extended"}
            scores = {**scores, "thumb": max(scores["thumb"], self.EXTENDED_SCORE)}
        for name, pattern in self.GESTURE_PATTERNS.items():
            if states != pattern:
                continue
            if name == "Pointing" and max(scores["middle"], scores["ring"], scores["pinky"]) > self.POINTING_MAX_OTHER_SCORE:
                continue  # another finger is only borderline folded (e.g. a "rock" pinky)
            if name == "Thumbs Up" and not self._thumb_points_up(landmarks):
                continue
            if name == "Thumbs Down" and not self._thumb_points_down(landmarks):
                continue
            if name == "Peace Sign" and self._finger_spread_degrees(landmarks) < self.PEACE_MIN_SPREAD_DEGREES:
                continue  # index and middle held together (HaGRID "two_up") is not a V
            matches = [score if pattern[finger] == "extended" else 1.0 - score for finger, score in scores.items()]
            if name == "Pointing":
                name = f"Pointing {self._pointing_direction(landmarks)}"
            return GestureDetection(name, sum(matches) / len(matches))
        return GestureDetection()

    @staticmethod
    def _pointing_direction(landmarks: HandLandmarkData) -> str:
        """Classify the index ray against its MCP joint in camera coordinates."""
        points = landmarks.get_landmarks()
        base, tip = points[5], points[8]
        dx, dy = tip.x - base.x, tip.y - base.y
        if abs(dx) > abs(dy) * 1.2:
            return "Right" if dx > 0 else "Left"
        return "Down" if dy > 0 else "Up"

    # Tuned on HaGRID landmarks (see docs/benchmarks/HAGRID_BENCHMARK_REPORT.md):
    # a V spreads >= 17 deg for 90% of "peace" images vs ~3 deg for two fingers held
    # together, and real thumbs-up/down poses lean up to ~55 deg from vertical.
    PEACE_MIN_SPREAD_DEGREES = 10.0
    PALM_THUMB_MIN_PINKY_REACH = 0.6
    POINTING_MAX_OTHER_SCORE = 0.75  # folded fingers must be clearly folded
    EXTENDED_SCORE = HandLandmarkData.EXTENDED_ANGLE_DEGREES / 180.0
    THUMB_MAX_TILT = math.tan(math.radians(60.0))  # horizontal/vertical ratio

    @staticmethod
    def _finger_spread_degrees(landmarks: HandLandmarkData) -> float:
        points = landmarks.get_landmarks()
        ax, ay = points[8].x - points[5].x, points[8].y - points[5].y
        bx, by = points[12].x - points[9].x, points[12].y - points[9].y
        norm = math.hypot(ax, ay) * math.hypot(bx, by)
        if norm == 0:
            return 0.0
        return math.degrees(math.acos(max(-1.0, min(1.0, (ax * bx + ay * by) / norm))))

    @classmethod
    def _thumb_points_up(cls, landmarks: HandLandmarkData) -> bool:
        points = landmarks.get_landmarks()
        wrist, thumb_mcp, thumb_tip = points[0], points[2], points[4]
        vertical = thumb_mcp.y - thumb_tip.y
        horizontal = abs(thumb_tip.x - thumb_mcp.x)
        return thumb_tip.y < wrist.y and vertical > 0 and horizontal < vertical * cls.THUMB_MAX_TILT

    @classmethod
    def _thumb_points_down(cls, landmarks: HandLandmarkData) -> bool:
        points = landmarks.get_landmarks()
        thumb_mcp, thumb_tip = points[2], points[4]
        vertical = thumb_tip.y - thumb_mcp.y
        horizontal = abs(thumb_tip.x - thumb_mcp.x)
        return vertical > 0 and horizontal < vertical * cls.THUMB_MAX_TILT

    def close(self) -> None:
        self._probe_stop.set()
        if self._probe_thread is not None:
            self._probe_thread.join(timeout=2.0)
            self._probe_thread = None
        self._hands.close()
        with self._dual_lock:
            if self._dual is not None:
                self._dual.close()
                self._dual = None
