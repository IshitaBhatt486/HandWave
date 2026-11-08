from types import SimpleNamespace
from unittest.mock import patch

from handwave.gestures.custom_gesture import CustomGestureDefinition, CustomGestureMatcher, extension_vector
from handwave.gestures.gesture_engine import GestureEngine
from handwave.gestures.hand_landmark_data import HandLandmarkData


def _point(x, y):
    return SimpleNamespace(x=x, y=y, z=0.0)


def _pose(extended, thumb_up=False, thumb_down=False, bend=0.04, spread=0.0, thumb_alongside=False):
    points = [_point(0.5, 0.9) for _ in range(21)]
    if "thumb" in extended:
        if thumb_up:
            points[2:5] = [_point(0.35, 0.72), _point(0.35, 0.52), _point(0.35, 0.30)]
        elif thumb_down:
            points[2:5] = [_point(0.35, 0.60), _point(0.35, 0.72), _point(0.35, 0.84)]
        else:  # sideways, nearly horizontal
            points[2:5] = [_point(0.40, 0.74), _point(0.28, 0.72), _point(0.14, 0.70)]
    elif thumb_alongside:  # flat 'stop' palm: thumb rests beside the index finger
        points[2:5] = [_point(0.38, 0.80), _point(0.36, 0.75), _point(0.37, 0.70)]
    else:  # tucked across the palm toward the middle knuckle
        points[2:5] = [_point(0.40, 0.80), _point(0.45, 0.76), _point(0.50, 0.74)]

    tilt = {"index": -spread, "middle": spread}
    for name, offset, x in zip(
        ("index", "middle", "ring", "pinky"), (5, 9, 13, 17), (0.40, 0.45, 0.50, 0.55)
    ):
        if name in extended:
            lean = tilt.get(name, 0.0)
            points[offset : offset + 4] = [
                _point(x, 0.72), _point(x + lean / 3, 0.57), _point(x + 2 * lean / 3, 0.42), _point(x + lean + bend, 0.27)
            ]
        else:
            points[offset : offset + 4] = [
                _point(x, 0.72), _point(x, 0.58), _point(x + 0.10, 0.58), _point(x + 0.14, 0.68)
            ]
    return HandLandmarkData(points)


def _engine():
    with patch("handwave.gestures.gesture_engine.mp.solutions.hands.Hands"):
        return GestureEngine()


def test_recognizes_all_supported_gestures():
    engine = _engine()
    cases = {
        "Open Palm": _pose({"thumb", "index", "middle", "ring", "pinky"}),
        "Fist": _pose(set()),
        "Thumbs Up": _pose({"thumb"}, thumb_up=True),
        "Thumbs Down": _pose({"thumb"}, thumb_down=True),
        "Peace Sign": _pose({"index", "middle"}, spread=0.08),
        "Pointing Up": _pose({"index"}),
    }
    for expected, landmarks in cases.items():
        detection = engine.detect_gesture(landmarks)
        assert detection.name == expected
        assert 0.0 < detection.confidence <= 1.0


def test_unlisted_pattern_and_sideways_thumb_are_unknown():
    engine = _engine()
    assert engine.detect_gesture(_pose({"middle"})).name == "Unknown"
    assert engine.detect_gesture(_pose({"thumb"})).name == "Unknown"
    assert engine.detect_gesture(None).confidence == 0.0


def test_confidence_updates_with_live_joint_geometry():
    engine = _engine()
    straight = engine.detect_gesture(_pose({"index"}, bend=0.0))
    less_straight = engine.detect_gesture(_pose({"index"}, bend=0.04))
    assert straight.name == less_straight.name == "Pointing Up"
    assert straight.confidence != less_straight.confidence


def test_builtin_gesture_wins_over_a_similar_custom_gesture():
    """Built-in gestures must never regress when a custom gesture is registered."""
    open_palm = _pose({"thumb", "index", "middle", "ring", "pinky"})
    conflicting = CustomGestureDefinition(
        name="Copycat", representative_scores=extension_vector(open_palm), tolerance=0.3
    )
    engine = _engine()
    engine.custom_matcher = CustomGestureMatcher([conflicting])

    assert engine.detect_gesture(open_palm).name == "Open Palm"


def test_custom_gesture_fills_in_when_builtin_is_unknown():
    unknown_pose = _pose({"middle"})
    salute = CustomGestureDefinition(
        name="Salute", representative_scores=extension_vector(unknown_pose), tolerance=0.05
    )
    engine = _engine()
    engine.custom_matcher = CustomGestureMatcher([salute])

    detection = engine.detect_gesture(unknown_pose)
    assert detection.name == "Salute"
    assert detection.confidence > 0.0


def test_without_a_custom_matcher_unknown_poses_stay_unknown():
    engine = _engine()
    assert engine.custom_matcher is None
    assert engine.detect_gesture(_pose({"middle"})).name == "Unknown"


def test_tucked_thumb_rules_from_real_world_data():
    """HaGRID-derived rules: tucked thumbs, V-spread, flat palms and loose fingers."""
    engine = _engine()
    # Two fingers held together is not a peace sign.
    assert engine.detect_gesture(_pose({"index", "middle"}, spread=0.0, bend=0.0)).name == "Unknown"
    # Four fingers up with the thumb tucked across the palm is not an open palm.
    assert engine.detect_gesture(_pose({"index", "middle", "ring", "pinky"})).name == "Unknown"
    # A flat palm with the thumb resting alongside the index finger is.
    assert engine.detect_gesture(_pose({"index", "middle", "ring", "pinky"}, thumb_alongside=True)).name == "Open Palm"


def test_thumb_reach_separates_tucked_from_extended():
    assert _pose(set()).thumb_reach() < HandLandmarkData.THUMB_EXTENDED_REACH
    assert _pose({"thumb"}).thumb_reach() > HandLandmarkData.THUMB_EXTENDED_REACH
