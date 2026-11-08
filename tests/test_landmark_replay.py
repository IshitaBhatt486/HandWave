from unittest.mock import patch

import pytest

from handwave.gestures.custom_gesture import CustomGestureDefinition, CustomGestureMatcher, extension_vector
from handwave.gestures.gesture_engine import GestureEngine
from handwave.gestures.hand_landmark_data import HandLandmarkData
from handwave.gestures.hand_state import HandState
from handwave.gestures.landmark_replay import LandmarkReplayer
from handwave.gestures.landmark_sequence import LandmarkFrame, LandmarkSequence


class _Point:
    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = x, y, z


def _open_palm_state(timestamp=0.0, handedness=None):
    points = [_Point(0.5, 0.9) for _ in range(21)]
    points[2:5] = [_Point(0.42, 0.72), _Point(0.30, 0.60), _Point(0.18, 0.48)]
    for offset, x in zip((5, 9, 13, 17), (0.35, 0.45, 0.55, 0.65)):
        points[offset : offset + 4] = [
            _Point(x, 0.72), _Point(x, 0.57), _Point(x, 0.42), _Point(x, 0.27)
        ]
    return HandState(landmarks=HandLandmarkData(points), timestamp=timestamp, handedness=handedness)


def _no_hand_state():
    return None


def _engine(custom_matcher=None):
    with patch("handwave.gestures.gesture_engine.mp.solutions.hands.Hands"):
        return GestureEngine(custom_matcher=custom_matcher)


def test_replay_recognizes_a_builtin_gesture_deterministically():
    sequence = LandmarkSequence(frames=(LandmarkFrame(timestamp=0.0, hands=(_open_palm_state(),)),))
    replayer = LandmarkReplayer(sequence, _engine())

    steps = list(replayer.steps())
    assert len(steps) == 1
    assert steps[0].result.name == "Open Palm"
    assert steps[0].result.hands_detected == 1


def test_replay_is_deterministic_across_runs():
    sequence = LandmarkSequence(
        frames=(
            LandmarkFrame(timestamp=0.0, hands=(_open_palm_state(),)),
            LandmarkFrame(timestamp=0.1, hands=()),
        )
    )
    names_first = [step.result.name for step in LandmarkReplayer(sequence, _engine()).steps()]
    names_second = [step.result.name for step in LandmarkReplayer(sequence, _engine()).steps()]
    assert names_first == names_second == ["Open Palm", "Unknown"]


def test_replay_one_hand_sequence():
    sequence = LandmarkSequence(frames=(LandmarkFrame(timestamp=0.0, hands=(_open_palm_state(),)),))
    step = next(LandmarkReplayer(sequence, _engine()).steps())
    assert step.result.hands_detected == 1


def test_replay_two_hand_sequence_recognizes_both_palms_open():
    sequence = LandmarkSequence(
        frames=(
            LandmarkFrame(
                timestamp=0.0,
                hands=(
                    _open_palm_state(handedness="Left"),
                    _open_palm_state(handedness="Right"),
                ),
            ),
        )
    )
    step = next(LandmarkReplayer(sequence, _engine()).steps())
    assert step.result.hands_detected == 2
    assert step.result.two_hand.name == "Both Palms Open"


def test_replay_honors_speed_when_computing_delays():
    sequence = LandmarkSequence(
        frames=(
            LandmarkFrame(timestamp=0.0, hands=(_open_palm_state(),)),
            LandmarkFrame(timestamp=1.0, hands=(_open_palm_state(),)),
        )
    )
    normal = list(LandmarkReplayer(sequence, _engine(), speed=1.0).steps())
    fast = list(LandmarkReplayer(sequence, _engine(), speed=2.0).steps())
    assert normal[1].delay_seconds == pytest.approx(1.0)
    assert fast[1].delay_seconds == pytest.approx(0.5)


def test_replay_rejects_non_positive_speed():
    sequence = LandmarkSequence(frames=())
    with pytest.raises(ValueError):
        LandmarkReplayer(sequence, _engine(), speed=0)


def _middle_only_state(timestamp=0.0):
    """A pose the built-in patterns leave as "Unknown" (only middle extended)."""
    points = [_Point(0.5, 0.9) for _ in range(21)]
    points[2:5] = [_Point(0.42, 0.72), _Point(0.30, 0.72), _Point(0.30, 0.82)]  # thumb folded
    for offset, x, extended in zip((5, 9, 13, 17), (0.35, 0.45, 0.55, 0.65), (False, True, False, False)):
        if extended:
            points[offset : offset + 4] = [
                _Point(x, 0.72), _Point(x, 0.57), _Point(x, 0.42), _Point(x, 0.27)
            ]
        else:
            points[offset : offset + 4] = [
                _Point(x, 0.72), _Point(x, 0.58), _Point(x + 0.10, 0.58), _Point(x + 0.14, 0.68)
            ]
    return HandState(landmarks=HandLandmarkData(points), timestamp=timestamp)


def test_replay_coexists_with_custom_gestures():
    unknown_pose = _middle_only_state()
    salute = CustomGestureDefinition(
        name="Salute", representative_scores=extension_vector(unknown_pose.landmarks), tolerance=0.3
    )
    engine = _engine(custom_matcher=CustomGestureMatcher([salute]))
    sequence = LandmarkSequence(frames=(LandmarkFrame(timestamp=0.0, hands=(unknown_pose,)),))

    step = next(LandmarkReplayer(sequence, engine).steps())
    assert step.result.name == "Salute"  # the custom gesture fills in an otherwise-"Unknown" pose

    # And a genuine built-in pose still takes priority over any custom match.
    builtin_sequence = LandmarkSequence(frames=(LandmarkFrame(timestamp=0.0, hands=(_open_palm_state(),)),))
    builtin_step = next(LandmarkReplayer(builtin_sequence, engine).steps())
    assert builtin_step.result.name == "Open Palm"


def test_replay_empty_sequence_yields_no_steps():
    sequence = LandmarkSequence(frames=())
    assert list(LandmarkReplayer(sequence, _engine()).steps()) == []
