from handwave.gestures.hand_landmark_data import HandLandmarkData, NormalizedLandmark
from handwave.gestures.hand_state import HandState
from handwave.gestures.two_hand_recognizer import TwoHandRecognizer


def _landmarks_at(cx, cy, open_palm=True):
    """21 landmarks centered at (cx, cy); open_palm controls the pose classification."""
    # Built from the same relative joint geometry used by other gesture tests.
    base = [NormalizedLandmark(cx, cy + 0.4, 0.0) for _ in range(21)]
    if open_palm:
        base[2:5] = [
            NormalizedLandmark(cx - 0.08, cy + 0.22, 0.0),
            NormalizedLandmark(cx - 0.20, cy + 0.10, 0.0),
            NormalizedLandmark(cx - 0.32, cy - 0.02, 0.0),
        ]
        for offset, x in zip((5, 9, 13, 17), (-0.15, -0.05, 0.05, 0.15)):
            base[offset : offset + 4] = [
                NormalizedLandmark(cx + x, cy + 0.22, 0.0),
                NormalizedLandmark(cx + x, cy + 0.07, 0.0),
                NormalizedLandmark(cx + x, cy - 0.08, 0.0),
                NormalizedLandmark(cx + x, cy - 0.23, 0.0),
            ]
    else:
        base[2:5] = [  # thumb tucked across the palm, as in a real fist
            NormalizedLandmark(cx - 0.10, cy + 0.30, 0.0),
            NormalizedLandmark(cx - 0.06, cy + 0.25, 0.0),
            NormalizedLandmark(cx - 0.02, cy + 0.21, 0.0),
        ]
        for offset, x in zip((5, 9, 13, 17), (-0.15, -0.05, 0.05, 0.15)):
            base[offset : offset + 4] = [
                NormalizedLandmark(cx + x, cy + 0.22, 0.0),
                NormalizedLandmark(cx + x, cy + 0.08, 0.0),
                NormalizedLandmark(cx + x + 0.10, cy + 0.08, 0.0),
                NormalizedLandmark(cx + x + 0.14, cy + 0.18, 0.0),
            ]

    return HandLandmarkData(base)


def _hand(cx, cy, handedness=None, open_palm=True, timestamp=0.0):
    return HandState(landmarks=_landmarks_at(cx, cy, open_palm), timestamp=timestamp, handedness=handedness)


def test_no_gesture_with_one_hand():
    recognizer = TwoHandRecognizer(clock=lambda: 0.0)
    result = recognizer.update([_hand(0.5, 0.5)])
    assert result.name == "Unknown"
    assert result.hands_detected == 1


def test_no_gesture_with_zero_hands():
    recognizer = TwoHandRecognizer(clock=lambda: 0.0)
    result = recognizer.update([])
    assert result.name == "Unknown"
    assert result.hands_detected == 0


def test_both_palms_open_recognized_when_stationary():
    recognizer = TwoHandRecognizer(clock=lambda: 0.0)
    recognizer.update([_hand(0.3, 0.5), _hand(0.7, 0.5)])
    result = recognizer.update([_hand(0.3, 0.5), _hand(0.7, 0.5)])
    assert result.name == "Both Palms Open"
    assert result.hands_detected == 2


def test_both_fists_recognized():
    recognizer = TwoHandRecognizer(clock=lambda: 0.0)
    recognizer.update([_hand(0.3, 0.5, open_palm=False), _hand(0.7, 0.5, open_palm=False)])
    result = recognizer.update([_hand(0.3, 0.5, open_palm=False), _hand(0.7, 0.5, open_palm=False)])
    assert result.name == "Both Fists"


def test_mismatched_poses_are_unknown_not_a_false_two_hand_activation():
    recognizer = TwoHandRecognizer(clock=lambda: 0.0)
    recognizer.update([_hand(0.3, 0.5, open_palm=True), _hand(0.7, 0.5, open_palm=False)])
    result = recognizer.update([_hand(0.3, 0.5, open_palm=True), _hand(0.7, 0.5, open_palm=False)])
    assert result.name == "Unknown"


def test_hands_moving_apart_requires_open_palms_and_increasing_distance():
    recognizer = TwoHandRecognizer(clock=lambda: 0.0)
    recognizer.update([_hand(0.45, 0.5), _hand(0.55, 0.5)])
    result = recognizer.update([_hand(0.2, 0.5), _hand(0.8, 0.5)])
    assert result.name == "Hands Moving Apart"


def test_hands_moving_together_requires_open_palms_and_decreasing_distance():
    recognizer = TwoHandRecognizer(clock=lambda: 0.0)
    recognizer.update([_hand(0.1, 0.5), _hand(0.9, 0.5)])
    result = recognizer.update([_hand(0.45, 0.5), _hand(0.55, 0.5)])
    assert result.name == "Hands Moving Together"


def test_small_motion_below_threshold_does_not_trigger_false_activation():
    recognizer = TwoHandRecognizer(clock=lambda: 0.0)
    recognizer.update([_hand(0.3, 0.5), _hand(0.7, 0.5)])
    result = recognizer.update([_hand(0.301, 0.5), _hand(0.699, 0.5)])
    assert result.name == "Both Palms Open"  # stable pose, not misread as motion


def test_hand_disappearing_resets_motion_tracking():
    recognizer = TwoHandRecognizer(clock=lambda: 0.0)
    recognizer.update([_hand(0.2, 0.5), _hand(0.8, 0.5)])
    recognizer.update([_hand(0.2, 0.5)])  # one hand disappears
    result = recognizer.update([_hand(0.45, 0.5), _hand(0.55, 0.5)])
    # No stale "previous distance" carried across the gap: first re-detection of
    # two hands reports the stable pose, not a stale motion gesture.
    assert result.name == "Both Palms Open"


def test_rapid_appearance_and_disappearance_never_crashes():
    recognizer = TwoHandRecognizer(clock=lambda: 0.0)
    sequences = [
        [],
        [_hand(0.3, 0.5)],
        [_hand(0.3, 0.5), _hand(0.7, 0.5)],
        [],
        [_hand(0.3, 0.5), _hand(0.7, 0.5)],
    ]
    for hands in sequences:
        result = recognizer.update(hands)
        assert result.hands_detected == len(hands)


def test_left_and_right_pose_labels_use_handedness_when_available():
    recognizer = TwoHandRecognizer(clock=lambda: 0.0)
    result = recognizer.update([_hand(0.3, 0.5, handedness="Left"), _hand(0.7, 0.5, handedness="Right")])
    assert result.left_pose == "Open Palm"
    assert result.right_pose == "Open Palm"


def test_ambiguous_handedness_yields_no_left_right_labels():
    recognizer = TwoHandRecognizer(clock=lambda: 0.0)
    result = recognizer.update([_hand(0.3, 0.5, handedness=None), _hand(0.7, 0.5, handedness=None)])
    assert result.left_pose is None
    assert result.right_pose is None
