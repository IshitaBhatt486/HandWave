from unittest.mock import MagicMock

import pytest

from handwave.actions.action_definition import ActionDefinition, MacroStep, parse_macro
from handwave.actions.action_executor import ActionExecutor
from handwave.config.settings_manager import SettingsManager

STEPS = [{"type": "hotkey", "value": "Ctrl+C"}, {"type": "wait", "value": "150"}, {"type": "key", "value": "Enter"},
         {"type": "text", "value": "hi"}, {"type": "media", "value": "play_pause"}]


def test_macro_normalizes_steps_and_round_trips():
    macro = ActionDefinition("macro", STEPS)
    assert [step.value for step in macro.value] == ["ctrl+c", "150", "enter", "hi", "play_pause"]
    assert macro.describe() == "Macro · 5 steps"
    assert ActionDefinition.from_data(macro.to_dict()) == macro


@pytest.mark.parametrize("steps", [
    [],
    [{"type": "wait", "value": "100"}],
    [{"type": "command", "value": "calc.exe"}],
    [{"type": "key", "value": "a"}] * 33,
    [{"type": "wait", "value": "6000"}, {"type": "wait", "value": "6000"}, {"type": "key", "value": "a"}],
    [{"type": "wait", "value": "soon"}, {"type": "key", "value": "a"}],
    [{"type": "hotkey", "value": "c+ctrl+c"}],
    "ctrl+c",
])
def test_invalid_macros_are_rejected(steps):
    with pytest.raises(ValueError):
        ActionDefinition("macro", steps)


def test_executor_runs_steps_in_order_with_waits():
    calls = []
    gui = MagicMock()
    gui.hotkey.side_effect = lambda *keys: calls.append(("hotkey", keys))
    gui.press.side_effect = lambda key: calls.append(("press", key))
    gui.write.side_effect = lambda text: calls.append(("write", text))
    executor = ActionExecutor(pyautogui_module=gui, keyboard_module=None, sleep=lambda s: calls.append(("sleep", s)))

    executor.execute(ActionDefinition("macro", STEPS))

    assert calls == [("hotkey", ("ctrl", "c")), ("sleep", 0.15), ("press", "enter"), ("write", "hi"), ("press", "playpause")]


def test_failing_step_stops_the_rest_of_the_macro():
    gui = MagicMock()
    gui.press.side_effect = OSError("input blocked")
    executor = ActionExecutor(pyautogui_module=gui, keyboard_module=None, sleep=lambda s: None)
    with pytest.raises(OSError):
        executor.execute(ActionDefinition("macro", [{"type": "key", "value": "a"}, {"type": "text", "value": "never"}]))
    gui.write.assert_not_called()


def test_macro_binding_persists_through_settings(tmp_path):
    manager = SettingsManager(tmp_path / "settings.json")
    bindings = dict(manager.settings.gesture_bindings)
    bindings["Fist"] = ActionDefinition("macro", STEPS[:3])
    manager.update(gesture_bindings=bindings)
    reloaded = SettingsManager(tmp_path / "settings.json").settings.gesture_bindings["Fist"]
    assert reloaded.type == "macro" and len(reloaded.value) == 3


def test_parse_macro_accepts_existing_steps():
    steps = (MacroStep("key", "a"), MacroStep("wait", "10"))
    assert parse_macro(steps) == steps


def test_macro_editor_builds_and_validates_steps(qtbot):
    from handwave.ui.macro_editor import MacroEditorDialog

    dialog = MacroEditorDialog(gesture="Fist")
    qtbot.addWidget(dialog)
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("hotkey"))
    dialog.text_value.setText("ctrl+shift+s")
    assert dialog.add_step()
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("wait"))
    dialog.text_value.setText("20000")
    assert not dialog.add_step()  # over the 10 s limit
    assert "10000" in dialog.error.text() or "10 seconds" in dialog.error.text()
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("media"))
    assert dialog.add_step()
    assert [step.type for step in dialog.steps()] == ["hotkey", "media"]
    dialog.step_list.setCurrentRow(1)
    dialog._move(-1)
    assert [step.type for step in dialog.steps()] == ["media", "hotkey"]


def test_settings_row_saves_macro_steps(qtbot):
    from handwave.ui.settings_dialog import ActionEditorRow

    row = ActionEditorRow("Fist", ActionDefinition("macro", STEPS[:2]), True)
    qtbot.addWidget(row)
    assert row.macro_button.text() == "Edit macro · 2 steps"
    data = row.action_dict()
    assert data["type"] == "macro"
    assert ActionDefinition.from_data(data).value == ActionDefinition("macro", STEPS[:2]).value
