from handwave.config.gesture_config import GESTURES
from handwave.ui.gesture_icons import gesture_icon


def test_every_gesture_and_unknown_names_get_an_icon(qtbot):
    for gesture in (*GESTURES, "My custom gesture"):
        assert not gesture_icon(gesture, "dark").isNull()
        assert not gesture_icon(gesture, "light").isNull()
