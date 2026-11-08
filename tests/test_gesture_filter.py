from unittest.mock import MagicMock

from handwave.actions.action_mapper import ActionMapper
from handwave.gestures.gesture_filter import GestureFilter


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_rapid_hand_movement_never_becomes_stable_or_triggers_actions():
    clock = Clock()
    gesture_filter = GestureFilter(clock=clock)
    gui = MagicMock()
    keys = MagicMock()
    mapper = ActionMapper(clock=clock, pyautogui_module=gui, keyboard_module=keys)

    for index in range(20):
        clock.now = index * 0.05
        raw = "Open Palm" if index % 2 == 0 else "Peace Sign"
        filtered = gesture_filter.update(raw)
        mapper.execute(filtered.stable_gesture)

    assert filtered.stable_gesture == "Unknown"
    gui.press.assert_not_called()
    keys.send.assert_not_called()


def test_stable_gesture_requires_250ms_then_triggers_only_once():
    clock = Clock()
    gesture_filter = GestureFilter(clock=clock)
    gui = MagicMock()
    mapper = ActionMapper(clock=clock, pyautogui_module=gui, keyboard_module=MagicMock())
    outputs = []

    for index in range(16):
        clock.now = index * 0.05
        filtered = gesture_filter.update("Thumbs Up")
        outputs.append(filtered)
        mapper.execute(filtered.stable_gesture)

    assert all(output.raw_gesture == "Thumbs Up" for output in outputs)
    assert outputs[4].stable_gesture == "Unknown"
    assert outputs[5].stable_gesture == "Thumbs Up"
    gui.press.assert_called_once_with("volumeup")


def test_majority_vote_ignores_occasional_bad_frames():
    clock = Clock()
    gesture_filter = GestureFilter(clock=clock)
    sequence = ["Pointing", "Pointing", "Unknown", "Pointing"] * 4

    for index, raw in enumerate(sequence):
        clock.now = index * 0.05
        result = gesture_filter.update(raw)

    assert result.raw_gesture == "Pointing"
    assert result.stable_gesture == "Pointing"


def test_reset_clears_stable_gesture_and_history():
    clock = Clock()
    gesture_filter = GestureFilter(persistence_seconds=0, clock=clock)
    assert gesture_filter.update("Fist").stable_gesture == "Fist"
    gesture_filter.reset()
    assert gesture_filter.update(None).stable_gesture == "Unknown"


def test_new_gesture_registers_quickly_after_a_long_idle_period():
    """Regression: the old 1 s majority made a pose wait ~1 s after idle frames."""
    clock = Clock()
    gesture_filter = GestureFilter(clock=clock)
    for index in range(60):  # 3 s of no gesture
        clock.now = index * 0.05
        gesture_filter.update(None)
    start = clock.now
    stable_at = None
    for index in range(1, 40):
        clock.now = start + index * 0.05
        if gesture_filter.update("Peace Sign").stable_gesture == "Peace Sign":
            stable_at = clock.now - start
            break
    assert stable_at is not None and stable_at <= 0.36


def test_brief_tracking_dropouts_do_not_drop_a_stable_gesture():
    clock = Clock()
    gesture_filter = GestureFilter(clock=clock)
    for index in range(20):
        clock.now = index * 0.05
        gesture_filter.update("Open Palm")
    for index in range(20, 23):  # 150 ms of lost tracking
        clock.now = index * 0.05
        assert gesture_filter.update(None).stable_gesture == "Open Palm"


def test_misreads_below_the_share_never_switch_the_gesture():
    clock = Clock()
    gesture_filter = GestureFilter(clock=clock)
    pattern = ["Fist", "Fist", "Thumbs Up"]  # one in three frames misread
    for index in range(60):
        clock.now = index * 0.05
        result = gesture_filter.update(pattern[index % 3])
        assert result.stable_gesture in ("Unknown", "Fist")
    assert result.stable_gesture == "Fist"


def test_invalid_parameters_are_rejected():
    import pytest

    for kwargs in ({"min_share": 0.5}, {"history_seconds": 0}, {"persistence_seconds": -1}):
        with pytest.raises(ValueError):
            GestureFilter(**kwargs)
