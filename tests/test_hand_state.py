from types import SimpleNamespace

from handwave.gestures.hand_landmark_data import HandLandmarkData
from handwave.gestures.hand_state import HandState


def _point(x, y):
    return SimpleNamespace(x=x, y=y, z=0.0)


def _open_palm_points():
    points = [_point(0.5, 0.9) for _ in range(21)]
    points[2:5] = [_point(0.42, 0.72), _point(0.30, 0.60), _point(0.18, 0.48)]
    for offset, x in zip((5, 9, 13, 17), (0.35, 0.45, 0.55, 0.65)):
        points[offset : offset + 4] = [
            _point(x, 0.72), _point(x, 0.57), _point(x, 0.42), _point(x, 0.27)
        ]
    return points


def _fist_points():
    points = [_point(0.5, 0.9) for _ in range(21)]
    points[2:5] = [_point(0.42, 0.80), _point(0.45, 0.76), _point(0.48, 0.73)]  # tucked across the palm
    for offset, x in zip((5, 9, 13, 17), (0.35, 0.45, 0.55, 0.65)):
        points[offset : offset + 4] = [
            _point(x, 0.72), _point(x, 0.58), _point(x + 0.10, 0.58), _point(x + 0.14, 0.68)
        ]
    return points


def _classification(label, score):
    return SimpleNamespace(classification=[SimpleNamespace(label=label, score=score)])


def test_pose_classifies_open_palm_and_fist():
    open_palm = HandState(landmarks=HandLandmarkData(_open_palm_points()), timestamp=0.0)
    fist = HandState(landmarks=HandLandmarkData(_fist_points()), timestamp=0.0)
    assert open_palm.pose == "Open Palm"
    assert fist.pose == "Fist"


def test_pose_is_other_for_mixed_gestures():
    mixed_points = _open_palm_points()
    mixed_points[5:9] = _fist_points()[5:9]  # fold only the index finger
    state = HandState(landmarks=HandLandmarkData(mixed_points), timestamp=0.0)
    assert state.pose == "Other"


def test_from_mediapipe_reads_confident_handedness():
    raw = SimpleNamespace(landmark=_open_palm_points())
    state = HandState.from_mediapipe(raw, timestamp=1.0, handedness_classification=_classification("Left", 0.95))
    assert state.handedness == "Left"
    assert state.handedness_confidence == 0.95


def test_from_mediapipe_treats_low_confidence_handedness_as_uncertain():
    raw = SimpleNamespace(landmark=_open_palm_points())
    state = HandState.from_mediapipe(raw, timestamp=1.0, handedness_classification=_classification("Right", 0.4))
    assert state.handedness is None  # explicit "uncertain", never a guessed label


def test_from_mediapipe_without_handedness_classification_is_none():
    raw = SimpleNamespace(landmark=_open_palm_points())
    state = HandState.from_mediapipe(raw, timestamp=1.0, handedness_classification=None)
    assert state.handedness is None
    assert state.handedness_confidence == 0.0


def test_centroid_is_computed_from_landmarks():
    state = HandState(landmarks=HandLandmarkData(_open_palm_points()), timestamp=0.0)
    assert state.centroid == state.landmarks.get_centroid()
