"""Edit a gesture macro: an ordered list of input steps."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
)

from handwave.actions.action_definition import (
    MACRO_STEP_TYPES,
    MAX_MACRO_STEPS,
    MAX_MACRO_WAIT_MS,
    MEDIA_ACTIONS,
    MOUSE_ACTIONS,
    MacroStep,
    parse_macro,
)
from handwave.ui import motion

PLACEHOLDERS = {
    "key": "e.g. enter, space, f5",
    "hotkey": "e.g. ctrl+shift+s",
    "text": "Text to type",
    "wait": "Milliseconds, e.g. 250",
}

def presets(macos: bool | None = None) -> dict[str, list[tuple[str, str]]]:
    """Starter macros using the host OS's shortcuts (Ctrl on Windows, ⌘ on macOS)."""
    from handwave import platforms

    mod = "command" if (platforms.is_macos() if macos is None else macos) else "ctrl"
    screenshot = "command+shift+4" if mod == "command" else "win+shift+s"
    return {
        "Copy, then paste": [("hotkey", f"{mod}+c"), ("wait", "150"), ("hotkey", f"{mod}+v")],
        "Screenshot a region": [("hotkey", screenshot)],
        "Mute and pause": [("media", "mute"), ("media", "play_pause")],
        "New browser tab and search": [("hotkey", f"{mod}+t"), ("wait", "200"), ("text", "")],
    }


PRESETS = presets()


class MacroEditorDialog(QDialog):
    """Build a macro step by step. ``steps()`` returns the validated result."""

    def __init__(self, steps: tuple[MacroStep, ...] = (), gesture: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Macro for {gesture}" if gesture else "Macro")
        self.setMinimumSize(560, 520)
        self._steps: list[MacroStep] = list(steps)

        title = QLabel(f"Macro · {gesture}" if gesture else "Macro")
        title.setObjectName("cardTitle")
        subtitle = QLabel("Steps run in order when the gesture fires. Program launches are not allowed in macros.")
        subtitle.setObjectName("cardSubtitle")
        subtitle.setWordWrap(True)

        self.step_list = QListWidget()
        self.step_list.setObjectName("activityList")
        self.step_list.setAccessibleName("Macro steps")
        self.step_list.currentRowChanged.connect(self._sync_buttons)

        self.type_combo = QComboBox()
        for step_type, label in MACRO_STEP_TYPES.items():
            self.type_combo.addItem(label, step_type)
        self.text_value = QLineEdit()
        self.media_value = QComboBox()
        for value, label in MEDIA_ACTIONS.items():
            self.media_value.addItem(label, value)
        self.mouse_value = QComboBox()
        for value, label in MOUSE_ACTIONS.items():
            self.mouse_value.addItem(label, value)
        self.value_stack = QStackedWidget()
        for widget in (self.text_value, self.media_value, self.mouse_value):
            self.value_stack.addWidget(widget)
        self.type_combo.currentIndexChanged.connect(self._sync_value_widget)
        self.text_value.returnPressed.connect(self.add_step)

        self.add_button = QPushButton("Add step")
        self.add_button.clicked.connect(self.add_step)
        self.error = QLabel("")
        self.error.setObjectName("note")
        self.error.setProperty("tone", "error")

        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Start from a preset…", None)
        for name in PRESETS:
            self.preset_combo.addItem(name, name)
        self.preset_combo.activated.connect(self._apply_preset)

        self.up_button = motion.UnderlineButton("Move up")
        self.down_button = motion.UnderlineButton("Move down")
        self.remove_button = motion.UnderlineButton("Remove")
        for button in (self.up_button, self.down_button, self.remove_button):
            button.setObjectName("ghostButton")
        self.up_button.clicked.connect(self._move_up)
        self.down_button.clicked.connect(self._move_down)
        self.remove_button.clicked.connect(self._remove)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        add_row = QHBoxLayout()
        add_row.addWidget(self.type_combo, 2)
        add_row.addWidget(self.value_stack, 3)
        add_row.addWidget(self.add_button)
        list_actions = QHBoxLayout()
        list_actions.addWidget(self.preset_combo)
        list_actions.addStretch()
        for button in (self.up_button, self.down_button, self.remove_button):
            list_actions.addWidget(button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 22)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(6)
        layout.addWidget(self.step_list, 1)
        layout.addLayout(list_actions)
        layout.addSpacing(6)
        layout.addLayout(add_row)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self._sync_value_widget()
        self._refresh()
        motion.animate_dialog(self)

    # ---------------------------------------------------------------- data
    def steps(self) -> tuple[MacroStep, ...]:
        return tuple(self._steps)

    def _current_type(self) -> str:
        return str(self.type_combo.currentData())

    def _current_value(self) -> str:
        step_type = self._current_type()
        if step_type == "media":
            return str(self.media_value.currentData())
        if step_type == "mouse":
            return str(self.mouse_value.currentData())
        return self.text_value.text()

    def add_step(self) -> bool:
        if len(self._steps) >= MAX_MACRO_STEPS:
            self.error.setText(f"A macro can have at most {MAX_MACRO_STEPS} steps.")
            return False
        try:
            step = MacroStep(self._current_type(), self._current_value())
            waits = sum(int(s.value) for s in (*self._steps, step) if s.type == "wait")
            if waits > MAX_MACRO_WAIT_MS:
                raise ValueError("Macro waits may total at most 10 seconds")
        except ValueError as exc:
            self.error.setText(str(exc))
            return False
        self._steps.append(step)
        self.text_value.clear()
        self.error.setText("")
        self._refresh(select=len(self._steps) - 1, animate=True)
        return True

    def _apply_preset(self, index: int) -> None:
        name = self.preset_combo.itemData(index)
        if not name:
            return
        try:
            self._steps = [MacroStep(kind, value) for kind, value in PRESETS[name] if value]
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        if any(kind == "text" and not value for kind, value in PRESETS[name]):
            index_of_text = self.type_combo.findData("text")
            self.type_combo.setCurrentIndex(index_of_text)
            self.text_value.setFocus()
            self.error.setText("Type the search text and press Add step.")
        self.preset_combo.setCurrentIndex(0)
        self._refresh(select=len(self._steps) - 1)

    def _move_up(self) -> None:
        self._move(-1)

    def _move_down(self) -> None:
        self._move(1)

    def _move(self, offset: int) -> None:
        row = self.step_list.currentRow()
        target = row + offset
        if 0 <= row < len(self._steps) and 0 <= target < len(self._steps):
            self._steps[row], self._steps[target] = self._steps[target], self._steps[row]
            self._refresh(select=target)

    def _remove(self) -> None:
        row = self.step_list.currentRow()
        if 0 <= row < len(self._steps):
            del self._steps[row]
            self._refresh(select=min(row, len(self._steps) - 1))

    def _accept(self) -> None:
        try:
            parse_macro(self._steps)
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()

    # ------------------------------------------------------------------ ui
    def _refresh(self, select: int = -1, animate: bool = False) -> None:
        self.step_list.clear()
        for number, step in enumerate(self._steps, start=1):
            item = QListWidgetItem(f"{number:>2}    {step.describe()}")
            self.step_list.addItem(item)
        if not self._steps:
            placeholder = QListWidgetItem("No steps yet. Add one below or start from a preset.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.step_list.addItem(placeholder)
        if 0 <= select < len(self._steps):
            self.step_list.setCurrentRow(select)
            if animate:
                motion.fade_in_item(self.step_list.item(select), self.palette().color(self.foregroundRole()))
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        row = self.step_list.currentRow()
        has = 0 <= row < len(self._steps)
        self.remove_button.setEnabled(has)
        self.up_button.setEnabled(has and row > 0)
        self.down_button.setEnabled(has and row < len(self._steps) - 1)

    def _sync_value_widget(self) -> None:
        step_type = self._current_type()
        widget = {"media": self.media_value, "mouse": self.mouse_value}.get(step_type, self.text_value)
        self.value_stack.setCurrentWidget(widget)
        self.text_value.setPlaceholderText(PLACEHOLDERS.get(step_type, ""))
