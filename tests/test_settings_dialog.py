from PyQt6.QtWidgets import QTabWidget

from handwave.actions.action_definition import ActionDefinition
from handwave.config.settings_manager import AppSettings
from handwave.ui.settings_dialog import SettingsDialog


def test_dialog_edits_sensitivity_binding_and_enabled_state(qtbot):
    dialog = SettingsDialog(AppSettings())
    qtbot.addWidget(dialog)

    dialog.sensitivity.setValue(0.8)
    row = dialog._gesture_rows["Fist"]
    row.type_combo.setCurrentIndex(row.type_combo.findData("media"))
    row.media_combo.setCurrentIndex(row.media_combo.findData("play_pause"))
    row.enabled_checkbox.setChecked(True)
    dialog._gesture_rows["Peace Sign"].enabled_checkbox.setChecked(False)

    values = dialog.values()

    assert values["gesture_sensitivity"] == 0.8
    assert values["gesture_bindings"]["Fist"]["type"] == "media"
    assert values["gesture_bindings"]["Fist"]["value"] == "play_pause"
    assert values["enabled_gestures"]["Fist"] is True
    assert values["enabled_gestures"]["Peace Sign"] is False
    assert values["auto_switch_profiles"] is True


def test_dialog_toggles_auto_switch_profiles(qtbot):
    dialog = SettingsDialog(AppSettings())
    qtbot.addWidget(dialog)

    dialog.auto_switch_profiles.setChecked(False)

    assert dialog.values()["auto_switch_profiles"] is False


def test_dialog_can_exit_the_background_process_when_window_closes(qtbot):
    dialog = SettingsDialog(AppSettings())
    qtbot.addWidget(dialog)

    dialog.exit_on_close.setChecked(True)

    assert dialog.values()["exit_on_close"] is True


def test_dialog_is_organized_into_sections(qtbot):
    dialog = SettingsDialog(AppSettings())
    qtbot.addWidget(dialog)

    tabs = dialog.findChild(QTabWidget)
    labels = [tabs.tabText(index) for index in range(tabs.count())]
    assert labels == ["General", "Camera", "Microphone", "Auto-pause", "Cursor Control", "Gestures && Actions", "Appearance"]


def test_dialog_persists_show_cursor_overlay_toggle(qtbot):
    dialog = SettingsDialog(AppSettings())
    qtbot.addWidget(dialog)

    assert dialog.show_cursor_overlay.isChecked()
    dialog.show_cursor_overlay.setChecked(False)

    assert dialog.values()["cursor_assist_overlay_enabled"] is False


def test_dialog_edits_camera_index_and_theme(qtbot):
    dialog = SettingsDialog(AppSettings())
    qtbot.addWidget(dialog)

    dialog.camera_index.setValue(2)
    dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData("light"))

    values = dialog.values()
    assert values["camera_index"] == 2
    assert values["theme"] == "light"


def test_dialog_edits_fingerprint_indicator_options(qtbot):
    dialog = SettingsDialog(AppSettings())
    qtbot.addWidget(dialog)

    dialog.show_fingerprint_indicator.setChecked(False)
    dialog.fingerprint_indicator_size.setValue(24)
    dialog.fingerprint_indicator_opacity.setValue(0.7)
    dialog.fingerprint_indicator_fade_duration_ms.setValue(400)

    values = dialog.values()
    assert values["show_fingerprint_indicator"] is False
    assert values["fingerprint_indicator_size"] == 24
    assert values["fingerprint_indicator_opacity"] == 0.7
    assert values["fingerprint_indicator_fade_duration_ms"] == 400


def test_dialog_edits_global_cooldown(qtbot):
    dialog = SettingsDialog(AppSettings())
    qtbot.addWidget(dialog)

    dialog.cooldown.setValue(2.5)

    assert dialog.values()["gesture_cooldown"] == 2.5


def test_dialog_supports_keyboard_hotkey_action(qtbot):
    dialog = SettingsDialog(AppSettings())
    qtbot.addWidget(dialog)

    row = dialog._gesture_rows["Swipe Right"]
    row.enabled_checkbox.setChecked(True)
    row.type_combo.setCurrentIndex(row.type_combo.findData("hotkey"))
    row.text_value.setText("ctrl+pagedown")

    binding = dialog.values()["gesture_bindings"]["Swipe Right"]
    assert binding["type"] == "hotkey"
    assert binding["value"] == "ctrl+pagedown"


def test_dialog_lists_all_configurable_navigation_gestures(qtbot):
    dialog = SettingsDialog(AppSettings())
    qtbot.addWidget(dialog)

    assert {
        "Finger Swipe Up",
        "Hand Swipe Up",
        "Finger Swipe Down",
        "Hand Swipe Down",
        "Pointing Up",
        "Pointing Down",
        "Pointing Left",
        "Pointing Right",
        "Swipe Left",
        "Swipe Right",
    } <= set(dialog._gesture_rows)
    row = dialog._gesture_rows["Open Palm"].enabled_checkbox
    assert "Open Palm" in row.text()
    assert row.accessibleName() == "Open Palm"
    assert not row.icon().isNull()


def test_dialog_requires_a_safe_hold_for_command_actions_without_confirmation_control(qtbot):
    dialog = SettingsDialog(AppSettings())
    qtbot.addWidget(dialog)

    row = dialog._gesture_rows["Pointing"]
    row.enabled_checkbox.setChecked(True)
    row.type_combo.setCurrentIndex(row.type_combo.findData("command"))

    assert not hasattr(row, "confirmation_checkbox")
    assert row.action_dict()["requires_confirmation"] is False
    assert row.action_dict()["hold_duration"] >= ActionDefinition.CONFIRMATION_HOLD
