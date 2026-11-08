from unittest.mock import MagicMock

from PyQt6.QtCore import QSettings

from handwave.config.settings_manager import AppSettings, SettingsManager
from handwave.ui.onboarding import MEDIA_GESTURES, NAVIGATION_GESTURES, OnboardingDialog
from tests.test_auto_pause import FakeCamera, FakeClap
from handwave.ui.main_window import MainWindow


def test_flow_walks_every_step_and_finishes(qtbot):
    dialog = OnboardingDialog(AppSettings())
    qtbot.addWidget(dialog)
    finished = []
    dialog.completed.connect(lambda: finished.append(True))
    assert dialog.next_button.text() == "Get started"
    assert not dialog.back_button.isVisibleTo(dialog)
    for _ in range(dialog.pages.count() - 1):
        dialog.next_button.click()
    assert dialog.next_button.text() == "Finish"
    assert "Gestures control" in dialog.summary.text()
    dialog.next_button.click()
    assert finished == [True] and not dialog.skipped


def test_choices_map_to_settings(qtbot):
    dialog = OnboardingDialog(AppSettings())
    qtbot.addWidget(dialog)
    dialog.media_card.setChecked(False)
    dialog.camera_group.button(1).setChecked(True)
    dialog.autostart_card.setChecked(False)
    dialog.clap_card.setChecked(False)
    dialog.calls_card.setChecked(False)
    dialog.light_card.setChecked(True)
    values = dialog.values()
    assert not any(values["enabled_gestures"][g] for g in MEDIA_GESTURES)
    assert any(values["enabled_gestures"][g] for g in NAVIGATION_GESTURES)
    assert values["camera_index"] == 1
    assert values["start_camera_on_launch"] is False
    assert values["double_clap_enabled"] is False
    assert values["pause_during_calls"] is False and values["pause_when_camera_in_use"] is True
    assert values["theme"] == "light"
    AppSettings(**{**AppSettings().__dict__, **values})  # all values validate


def test_gestures_without_an_action_stay_disabled(qtbot):
    dialog = OnboardingDialog(AppSettings())
    qtbot.addWidget(dialog)
    dialog.media_card.setChecked(True)
    assert dialog.values()["enabled_gestures"]["Fist"] is AppSettings().enabled_gestures["Fist"]


def _first_run_window(qtbot, tmp_path):
    manager = SettingsManager(tmp_path / "settings.json")
    onboarding = QSettings(str(tmp_path / "o.ini"), QSettings.Format.IniFormat)
    camera, clap = FakeCamera(), FakeClap()
    window = MainWindow(camera_manager=camera, clap_detector=clap, settings_manager=manager, onboarding_settings=onboarding)
    qtbot.addWidget(window)
    window.auto_pause.start = MagicMock()
    window.auto_pause._evaluate = lambda rules: None
    return window, camera, manager, onboarding


def test_first_launch_waits_for_setup_then_applies_choices(qtbot, tmp_path):
    window, camera, manager, onboarding = _first_run_window(qtbot, tmp_path)
    window.launch()
    assert window.onboarding_dialog is not None
    camera.start_camera.assert_not_called()  # camera waits for setup

    window.onboarding_dialog.camera_group.button(2).setChecked(True)
    window.onboarding_dialog.finish()
    qtbot.waitUntil(lambda: camera.start_camera.called, timeout=1000)
    assert manager.settings.camera_index == 2
    assert onboarding.value("onboarding/completed", False, type=bool)
    window.launch()
    assert camera.start_camera.call_count == 1  # second launch: no repeat
    window.exit_application()


def test_skipping_setup_keeps_settings(qtbot, tmp_path):
    window, camera, manager, _ = _first_run_window(qtbot, tmp_path)
    window.launch()
    window.onboarding_dialog.light_card.setChecked(True)
    window.onboarding_dialog.skip()
    assert manager.settings.theme == "dark"
    qtbot.waitUntil(lambda: camera.start_camera.called, timeout=1000)
    window.exit_application()


def test_setup_can_be_run_again_from_the_tray(qtbot, tmp_path):
    window, camera, manager, onboarding = _first_run_window(qtbot, tmp_path)
    onboarding.setValue("onboarding/completed", True)
    window.launch()
    assert window.onboarding_dialog is None
    window.setup_action.trigger()
    assert window.onboarding_dialog is not None and window.onboarding_dialog.isVisible()
    window.onboarding_dialog.dark_card.setChecked(False)
    window.onboarding_dialog.light_card.setChecked(True)
    window.onboarding_dialog.finish()
    assert manager.settings.theme == "light"
    assert camera.start_camera.call_count == 1  # rerunning setup does not restart services
    window.exit_application()
