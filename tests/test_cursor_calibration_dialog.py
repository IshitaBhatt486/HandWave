from handwave.config.settings_manager import SettingsManager
from handwave.services.monitor_layout import MonitorGeometry, MonitorLayout
from handwave.ui.cursor_calibration_dialog import CalibrationStep, CursorCalibrationDialog
import numpy as np


def _profile():
    return {"center_x": 0.5, "center_y": 0.5, "left": 0.2, "right": 0.8, "top": 0.2, "bottom": 0.8}


def test_welcome_screen_exposes_start_and_cancel_controls(qtbot, tmp_path):
    dialog = CursorCalibrationDialog(SettingsManager(tmp_path / "settings.json"))
    qtbot.addWidget(dialog)
    assert dialog.start.text() == "Start Calibration"
    assert dialog.cancel.text() == "Cancel"
    assert "comfortable hand movement" in dialog.instruction.text()


def test_accept_persists_complete_reach_profile(qtbot, tmp_path):
    manager = SettingsManager(tmp_path / "settings.json")
    dialog = CursorCalibrationDialog(manager)
    qtbot.addWidget(dialog)
    dialog._step, dialog._values = CalibrationStep.RESULTS, _profile()
    dialog._validation_results = [(90, 90)] * 5
    dialog._validation_score = 90
    dialog.dead_zone.setCurrentText("15%")
    dialog.smoothing.setCurrentText("High")
    dialog.accept_calibration()
    assert manager.settings.cursor_reach_calibration == _profile()
    assert manager.settings.cursor_dead_zone_percent == 15
    assert manager.settings.cursor_smoothing == "high"


def test_invalid_reversed_profile_is_not_saved(qtbot, tmp_path):
    manager = SettingsManager(tmp_path / "settings.json")
    dialog = CursorCalibrationDialog(manager)
    qtbot.addWidget(dialog)
    invalid = _profile(); invalid["left"] = 0.7
    dialog._step, dialog._values = CalibrationStep.RESULTS, invalid
    dialog._validation_results = [(90, 90)] * 5
    dialog._validation_score = 90
    dialog.accept_calibration()
    assert manager.settings.cursor_reach_calibration is None
    assert "needs redo" in dialog.instruction.text()


def test_failed_validation_cannot_save_calibration(qtbot, tmp_path):
    manager = SettingsManager(tmp_path / "settings.json")
    dialog = CursorCalibrationDialog(manager)
    qtbot.addWidget(dialog)
    dialog._step, dialog._values, dialog._validation_score = CalibrationStep.RESULTS, _profile(), 40
    dialog._validation_results = [(40, 40)] * 5
    dialog.accept_calibration()
    assert manager.settings.cursor_reach_calibration is None
    assert "recommended" in dialog.instruction.text()


def test_live_preview_receives_camera_frame_and_virtual_hand_position(qtbot, tmp_path):
    dialog = CursorCalibrationDialog(SettingsManager(tmp_path / "settings.json"))
    qtbot.addWidget(dialog)
    dialog.feed_frame(np.zeros((24, 32, 3), dtype=np.uint8))
    dialog.feed_fingertips([(0.25, 0.75)])
    assert dialog.preview.frame is not None
    assert dialog.preview.hand == (0.25, 0.75)
    # The dialog renders feedback only; it owns no OS cursor controller.
    assert not hasattr(dialog, "pyautogui")


def test_calibration_emits_provisional_overlay_position_and_snaps_validation_target(qtbot, tmp_path):
    dialog = CursorCalibrationDialog(SettingsManager(tmp_path / "settings.json"))
    qtbot.addWidget(dialog)
    dialog._layout = MonitorLayout((MonitorGeometry("PRIMARY", 100, 200, 1000, 800, True),))
    dialog._values = _profile()
    positions = []
    dialog.virtual_cursor_position.connect(lambda x, y, snapped: positions.append((x, y, snapped)))

    dialog.feed_fingertips([(.5, .5)])
    assert positions[-1] == (600, 600, False)

    dialog._step = CalibrationStep.VALIDATION
    dialog._validation_index = 0
    dialog.feed_fingertips([(.5, .5)])
    assert positions[-1] == (600, 600, True)


def test_validation_preview_does_not_attempt_a_missing_capture_target(qtbot, tmp_path):
    dialog = CursorCalibrationDialog(SettingsManager(tmp_path / "settings.json"))
    qtbot.addWidget(dialog)
    dialog._step = CalibrationStep.VALIDATION
    dialog._render()
    dialog.preview.show()
    qtbot.wait(10)


def test_missed_capture_offers_retry_step_instead_of_dead_end(qtbot, tmp_path):
    dialog = CursorCalibrationDialog(SettingsManager(tmp_path / "settings.json"))
    qtbot.addWidget(dialog)
    dialog.start_calibration()
    dialog._remaining_ms = dialog._timer.interval()

    dialog._advance()  # no fingertips were captured

    assert dialog._step == CalibrationStep.CENTER
    assert not dialog.retry_step.isHidden()
    assert "Retry Step" in dialog.instruction.text()

    dialog._retry_step()
    assert dialog._timer.isActive()
    assert dialog.retry_step.isHidden()
    dialog._timer.stop()


def _capture(dialog, x, y):
    dialog._samples = [(x, y)] * 5
    dialog._remaining_ms = dialog._timer.interval()
    dialog._advance()


def test_full_reach_capture_reaches_validation(qtbot, tmp_path):
    dialog = CursorCalibrationDialog(SettingsManager(tmp_path / "settings.json"))
    qtbot.addWidget(dialog)
    dialog.start_calibration()
    for point in ((.5, .5), (.2, .5), (.8, .5), (.5, .2), (.5, .8)):
        _capture(dialog, *point)

    assert dialog._step == CalibrationStep.VALIDATION
    assert dialog._values == _profile()
    assert not dialog.redo.isHidden()


def test_reversed_reach_returns_to_start_with_explanation(qtbot, tmp_path):
    dialog = CursorCalibrationDialog(SettingsManager(tmp_path / "settings.json"))
    qtbot.addWidget(dialog)
    dialog.start_calibration()
    # "Left" captured to the right of center, as with an unmirrored camera.
    for point in ((.5, .5), (.8, .5), (.2, .5), (.5, .2), (.5, .8)):
        _capture(dialog, *point)

    assert dialog._step == CalibrationStep.WELCOME
    assert "either side of the center" in dialog.instruction.text()
    assert not dialog.start.isHidden()


def test_preview_renders_every_step_without_painter_type_errors(qtbot, tmp_path):
    dialog = CursorCalibrationDialog(SettingsManager(tmp_path / "settings.json"))
    qtbot.addWidget(dialog)
    dialog.feed_frame(np.zeros((48, 64, 3), dtype=np.uint8))
    dialog.feed_fingertips([(0.37, 0.61)])
    dialog._values = {"center_x": .47, "center_y": .53, "left": .13, "right": .91, "top": .17, "bottom": .89}
    for step in CalibrationStep:
        dialog._step = step
        dialog._render()
        assert not dialog.preview.grab().isNull()  # forces paintEvent


def test_preview_survives_a_reach_step_captured_at_the_center(qtbot, tmp_path):
    dialog = CursorCalibrationDialog(SettingsManager(tmp_path / "settings.json"))
    qtbot.addWidget(dialog)
    dialog.start_calibration()
    _capture(dialog, .5, .5)   # center
    _capture(dialog, .5, .5)   # "left" without moving: zero-width left reach
    dialog.feed_fingertips([(.3, .5)])
    assert not dialog.preview.grab().isNull()
    dialog._timer.stop()
