from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from handwave.gestures.gesture_engine import GestureEngine


def _landmarks():
    point = SimpleNamespace(x=0.5, y=0.5, z=0.0)
    return SimpleNamespace(landmark=[point] * 21)


def _engine_with_results(results, times=(1.0, 1.04)):
    hands = MagicMock()
    hands.process.side_effect = results
    with patch("handwave.gestures.gesture_engine.mp.solutions.hands.Hands", return_value=hands) as factory:
        engine = GestureEngine(clock=iter(times).__next__, debug_text=True, two_hand_probe=False)
    return engine, hands, factory


def test_configures_up_to_two_hands_and_draws_themed_landmarks_and_connections():
    landmarks = _landmarks()
    engine, _, factory = _engine_with_results(
        [SimpleNamespace(multi_hand_landmarks=[landmarks])], times=(1.0,)
    )
    engine._drawing = MagicMock()
    frame = np.zeros((100, 160, 3), dtype=np.uint8)

    with patch("handwave.gestures.gesture_engine.put_text") as put_text:
        _, result = engine.process(frame)

    # One-hand tracking by default; a second hand is picked up adaptively.
    assert factory.call_args.kwargs["max_num_hands"] == 1
    assert len(landmarks.landmark) == 21
    engine._drawing.draw_landmarks.assert_called_once_with(
        frame,
        landmarks,
        engine._connections,
        engine.LANDMARK_STYLE,
        engine.CONNECTION_STYLE,
    )
    assert engine.LANDMARK_STYLE.color == (110, 169, 201)  # champagne joints (BGR)
    assert engine.CONNECTION_STYLE.color == (214, 224, 231)  # ivory hairline bones (BGR)
    assert result.hands_detected == 1
    assert put_text.call_args_list[0].args[1] == "Hand detected"


def test_reports_hand_loss_and_recovers_while_updating_fps():
    landmarks = _landmarks()
    engine, _, _ = _engine_with_results(
        [
            SimpleNamespace(multi_hand_landmarks=[landmarks]),
            SimpleNamespace(multi_hand_landmarks=None),
            SimpleNamespace(multi_hand_landmarks=[landmarks]),
        ],
        times=(1.0, 1.04, 1.08),
    )
    engine._drawing = MagicMock()
    frame = np.zeros((100, 160, 3), dtype=np.uint8)

    with patch("handwave.gestures.gesture_engine.put_text") as put_text:
        first = engine.process(frame.copy())[1]
        lost = engine.process(frame.copy())[1]
        recovered = engine.process(frame.copy())[1]

    statuses = [
        call.args[1]
        for call in put_text.call_args_list
        if call.args[1] in {"Hand detected", "No hand detected"}
    ]
    assert statuses == ["Hand detected", "No hand detected", "Hand detected"]
    assert first.fps == 0.0
    assert lost.fps > 20
    assert recovered.hands_detected == 1
    assert recovered.fps > 20
    assert recovered.landmarks is not None
    overlay_text = [call.args[1] for call in put_text.call_args_list]
    assert "Thumb: folded" in overlay_text
    assert "Pinky: folded" in overlay_text


def test_close_releases_mediapipe_resources():
    engine, hands, _ = _engine_with_results([], times=())
    engine.close()
    hands.close.assert_called_once_with()


def test_overlay_text_has_a_dark_outline_for_legibility():
    from handwave.vision.overlay_text import OUTLINE_COLOR, TEXT_COLOR, put_text

    frame = np.full((40, 200, 3), 255, dtype=np.uint8)  # white scene
    put_text(frame, "Hand detected", (4, 28))
    assert (frame == OUTLINE_COLOR).all(axis=2).any()  # outline survives on a bright scene
    assert (np.abs(frame.astype(int) - TEXT_COLOR).sum(axis=2) < 30).any()


def test_two_hands_are_tracked_adaptively_and_released():
    import threading
    from handwave.gestures import gesture_engine as module

    one, two = SimpleNamespace(multi_hand_landmarks=[_landmarks()]), SimpleNamespace(multi_hand_landmarks=[_landmarks(), _landmarks()])
    single, dual = MagicMock(), MagicMock()
    single.process.return_value = one
    dual.process.return_value = two
    trackers = iter([single, dual])
    with patch.object(module.mp.solutions.hands, "Hands", side_effect=lambda **kw: next(trackers)) as factory:
        engine = GestureEngine(overlay_enabled=False)
        engine.PROBE_INTERVAL_SECONDS = 0.01
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        engine.process(frame.copy())  # one hand; starts the probe
        deadline = threading.Event()
        for _ in range(200):
            if engine.tracking_two_hands:
                break
            deadline.wait(0.01)
        assert engine.tracking_two_hands
        assert [call.kwargs["max_num_hands"] for call in factory.call_args_list] == [1, 2]
        _, result = engine.process(frame.copy())
        assert result.hands_detected == 2  # frames now go through the two-hand tracker

        dual.process.return_value = one  # second hand leaves
        engine.DUAL_RELEASE_SECONDS = 0.0
        engine.process(frame.copy())
        engine.process(frame.copy())
        assert not engine.tracking_two_hands
        engine.close()
    dual.close.assert_called_once()


def test_debug_text_is_off_by_default():
    engine, _, _ = _engine_with_results([SimpleNamespace(multi_hand_landmarks=[_landmarks()])], times=(1.0,))
    engine.debug_text = False
    engine._drawing = MagicMock()
    with patch("handwave.gestures.gesture_engine.put_text") as put_text:
        engine.process(np.zeros((100, 160, 3), dtype=np.uint8))
    put_text.assert_not_called()
    engine._drawing.draw_landmarks.assert_called_once()  # landmarks are still drawn


def test_probe_stays_idle_while_no_hand_is_visible():
    engine, hands, _ = _engine_with_results([SimpleNamespace(multi_hand_landmarks=None)], times=(1.0,))
    engine.two_hand_probe = True
    engine.process(np.zeros((48, 64, 3), dtype=np.uint8))
    assert engine._probe_frame is None
    engine.close()


def test_matplotlib_is_not_loaded_by_the_engine():
    import subprocess, sys
    code = ("import sys; from handwave.gestures.gesture_engine import GestureEngine; "
            "from handwave.vision.lazy_imports import is_placeholder; "
            "print(is_placeholder(sys.modules.get('matplotlib.pyplot')))")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert result.stdout.strip().endswith("True"), result.stderr[-500:]
