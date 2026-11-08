from types import SimpleNamespace

from handwave.gestures.hand_landmark_data import HandLandmarkData


def _point(x, y, z=0.0):
    return SimpleNamespace(x=x, y=y, z=z)


def _hand(folded=False):
    points = [_point(0.5, 0.9) for _ in range(21)]
    if folded:
        # tucked across the palm, as a real fist holds the thumb
        points[2:5] = [_point(0.4, 0.8), _point(0.45, 0.75), _point(0.48, 0.72)]
    else:
        points[2:5] = [_point(0.4, 0.75), _point(0.3, 0.65), _point(0.2, 0.55)]

    for offset, x in zip((5, 9, 13, 17), (0.35, 0.45, 0.55, 0.65)):
        if folded:
            points[offset : offset + 4] = [
                _point(x, 0.7), _point(x, 0.58), _point(x + 0.08, 0.58), _point(x + 0.12, 0.66)
            ]
        else:
            points[offset : offset + 4] = [
                _point(x, 0.7), _point(x, 0.55), _point(x, 0.4), _point(x, 0.25)
            ]
    return SimpleNamespace(landmark=points)


def test_open_hand_has_21_normalized_points_and_all_fingers_extended():
    data = HandLandmarkData.from_mediapipe(_hand())
    assert len(data.get_landmarks()) == 21
    assert set(data.get_finger_states().values()) == {"extended"}


def test_fist_has_all_fingers_folded():
    data = HandLandmarkData.from_mediapipe(_hand(folded=True))
    assert set(data.get_finger_states().values()) == {"folded"}





def test_rejects_incomplete_hand():
    try:
        HandLandmarkData([_point(0, 0)] * 20)
    except ValueError as error:
        assert "Expected 21" in str(error)
    else:
        raise AssertionError("Incomplete hand landmarks should be rejected")
