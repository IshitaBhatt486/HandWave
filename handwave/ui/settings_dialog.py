"""User-facing gesture binding and recognition settings editor."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from handwave.actions.action_definition import (
    ACTION_TYPES,
    MEDIA_ACTIONS,
    MOUSE_ACTIONS,
    ActionDefinition,
)
from handwave.config.gesture_config import GESTURES
from handwave.config.settings_manager import AppSettings
from handwave.ui.gesture_icons import gesture_icon
from handwave.ui.macro_editor import MacroEditorDialog
from handwave.ui import motion
from handwave import platforms
from handwave.services.auto_pause import running_processes

_TEXT_VALUE_TYPES = {"key", "hotkey", "text", "command"}


class ActionEditorRow(QWidget):
    """One gesture's enabled state plus its full action definition editor."""

    def __init__(self, gesture: str, binding: ActionDefinition, enabled: bool) -> None:
        super().__init__()
        self.gesture = gesture

        self.enabled_checkbox = QCheckBox(gesture)
        self.enabled_checkbox.setIcon(gesture_icon(gesture))
        self.enabled_checkbox.setAccessibleName(gesture)
        self.enabled_checkbox.setChecked(enabled)

        self.type_combo = QComboBox()
        for action_type, label in ACTION_TYPES.items():
            self.type_combo.addItem(label, action_type)

        self.media_combo = QComboBox()
        for value, label in MEDIA_ACTIONS.items():
            self.media_combo.addItem(label, value)

        self.mouse_combo = QComboBox()
        for value, label in MOUSE_ACTIONS.items():
            self.mouse_combo.addItem(label, value)

        self.text_value = QLineEdit()
        from handwave import platforms

        self.text_value.setPlaceholderText(
            "e.g. command+shift+s, space, hello world, Safari.app" if platforms.is_macos()
            else "e.g. ctrl+shift+s, Space, hello world, notepad.exe"
        )

        self.value_stack = QStackedWidget()
        self.value_stack.addWidget(QLabel(""))
        self.value_stack.addWidget(self.media_combo)
        self.value_stack.addWidget(self.text_value)
        self.value_stack.addWidget(self.text_value)  # hotkey (shared widget, index unused directly)
        self.value_stack.addWidget(self.mouse_combo)
        self.value_stack.addWidget(self.text_value)
        self.value_stack.addWidget(self.text_value)
        self._macro_steps: tuple = ()
        self.macro_button = QPushButton("Add steps…")
        self.macro_button.setToolTip("Edit the sequence of inputs this gesture performs")
        self.macro_button.clicked.connect(self.edit_macro)
        self.value_stack.addWidget(self.macro_button)

        self.hold_spin = QDoubleSpinBox()
        self.hold_spin.setRange(0.0, 10.0)
        self.hold_spin.setSingleStep(0.1)
        self.hold_spin.setSuffix(" s")
        self.hold_spin.setToolTip("Hold duration before this gesture's action fires")

        self.cooldown_spin = QDoubleSpinBox()
        self.cooldown_spin.setRange(0.0, 60.0)
        self.cooldown_spin.setSingleStep(0.1)
        self.cooldown_spin.setSuffix(" s")
        self.cooldown_spin.setSpecialValueText("Default")
        self.cooldown_spin.setToolTip("Per-gesture cooldown override; 0 uses the global cooldown")

        self._load(binding)
        self.enabled_checkbox.toggled.connect(self._set_row_enabled)
        self.type_combo.currentIndexChanged.connect(self._sync_value_widget)
        self._set_row_enabled(enabled)
        self._sync_value_widget()

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.enabled_checkbox, 2)
        row.addWidget(self.type_combo, 2)
        row.addWidget(self.value_stack, 3)
        # Wide enough for "Default" and "10.0 s"; with a stretch share they were cut to "fault".
        for spin in (self.hold_spin, self.cooldown_spin):
            spin.setFixedWidth(self.spin_width())
            row.addWidget(spin)

    @staticmethod
    def spin_width() -> int:
        from PyQt6.QtGui import QFontMetrics
        from PyQt6.QtWidgets import QApplication

        return QFontMetrics(QApplication.font()).horizontalAdvance("Default") + 64

    def _load(self, binding: ActionDefinition) -> None:
        self.type_combo.setCurrentIndex(self.type_combo.findData(binding.type))
        if binding.type == "media":
            self.media_combo.setCurrentIndex(self.media_combo.findData(binding.value))
        elif binding.type == "mouse":
            self.mouse_combo.setCurrentIndex(self.mouse_combo.findData(binding.value))
        elif binding.type == "macro":
            self._macro_steps = tuple(binding.value)
        elif binding.type in _TEXT_VALUE_TYPES:
            value = binding.value
            self.text_value.setText(" ".join(value) if isinstance(value, tuple) else str(value))
        # Confirmation is deliberately not exposed in settings.  Existing
        # confirmed actions retain their safe, effective hold duration.
        self.hold_spin.setValue(binding.effective_hold_duration)
        self.cooldown_spin.setValue(binding.cooldown if binding.cooldown is not None else 0.0)

    def _current_type(self) -> str:
        return str(self.type_combo.currentData())

    def _sync_value_widget(self) -> None:
        action_type = self._current_type()
        widget = {
            "none": self.value_stack.widget(0),
            "media": self.media_combo,
            "key": self.text_value,
            "hotkey": self.text_value,
            "mouse": self.mouse_combo,
            "text": self.text_value,
            "command": self.text_value,
            "macro": self.macro_button,
        }[action_type]
        self.value_stack.setCurrentWidget(widget)
        self._sync_macro_label()
        dangerous = action_type == "command" or (
            action_type == "hotkey" and self.text_value.text().strip().lower() in {"alt+f4", "ctrl+alt+delete"}
        )
        if dangerous and self.hold_spin.value() < ActionDefinition.CONFIRMATION_HOLD:
            self.hold_spin.setValue(ActionDefinition.CONFIRMATION_HOLD)

    def _sync_macro_label(self) -> None:
        count = len(self._macro_steps)
        self.macro_button.setText(f"Edit macro · {count} step{'s' if count != 1 else ''}" if count else "Add steps…")

    def edit_macro(self) -> bool:
        """Open the macro editor; returns True when the user saved steps."""
        dialog = MacroEditorDialog(self._macro_steps, self.gesture, self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self._macro_steps = dialog.steps()
        self._sync_macro_label()
        return True

    def _set_row_enabled(self, enabled: bool) -> None:
        for widget in (
            self.type_combo,
            self.value_stack,
            self.hold_spin,
            self.cooldown_spin,
        ):
            widget.setEnabled(enabled)
        if enabled:
            self._sync_value_widget()

    def action_dict(self) -> dict[str, object]:
        action_type = self._current_type()
        if action_type == "media":
            value: object = self.media_combo.currentData()
        elif action_type == "mouse":
            value = self.mouse_combo.currentData()
        elif action_type == "macro":
            value = [step.to_dict() for step in self._macro_steps]
        elif action_type in _TEXT_VALUE_TYPES:
            value = self.text_value.text()
        else:
            value = ""
        cooldown = self.cooldown_spin.value()
        value_text = str(value).strip().lower()
        if action_type == "command" or (action_type == "hotkey" and value_text in {"alt+f4", "ctrl+alt+delete"}):
            self.hold_spin.setValue(max(self.hold_spin.value(), ActionDefinition.CONFIRMATION_HOLD))
        return {
            "type": action_type,
            "value": value,
            "requires_confirmation": False,
            "hold_duration": self.hold_spin.value(),
            "cooldown": cooldown if cooldown > 0.0 else None,
        }


class SettingsDialog(QDialog):
    """Edit persisted settings, organized into sections by concern.

    Sections reflect what is actually implemented today: gestures and their
    actions share one editor row per gesture (the model is 1:1, not two
    independent lists), so they live in a single "Gestures & Actions" tab
    rather than being split artificially. Startup behavior stays on the tray
    menu (its own toggle already round-trips through
    ``SettingsManager.set_startup_enabled``, which also updates the Windows
    Startup launcher — duplicating it here risked the two falling out of
    sync). Guided microphone calibration lives in the dashboard's Microphone
    dialog; this tab exposes the resulting double-clap controls directly.
    """

    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("HandWave Settings")
        self.setMinimumWidth(760)
        self.setMinimumHeight(560)
        self._gesture_rows: dict[str, ActionEditorRow] = {}

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(settings), "General")
        tabs.addTab(self._build_camera_tab(settings), "Camera")
        tabs.addTab(self._build_microphone_tab(settings), "Microphone")
        tabs.addTab(self._build_auto_pause_tab(settings), "Auto-pause")
        tabs.addTab(self._build_cursor_control_tab(settings), "Cursor Control")
        tabs.addTab(self._build_gestures_tab(settings), "Gestures && Actions")
        tabs.addTab(self._build_appearance_tab(settings), "Appearance")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # Generous, consistent breathing room on every page.
        for index in range(tabs.count()):
            page_layout = tabs.widget(index).layout()
            if page_layout is not None:
                page_layout.setContentsMargins(4, 24, 4, 8)
                page_layout.setSpacing(14)
                if isinstance(page_layout, QFormLayout):
                    page_layout.setHorizontalSpacing(28)
                    page_layout.setVerticalSpacing(16)
                    page_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 18, 28, 22)
        layout.setSpacing(18)
        layout.addWidget(tabs)
        layout.addWidget(buttons)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

    def _build_general_tab(self, settings: AppSettings) -> QWidget:
        self.sensitivity = QDoubleSpinBox()
        self.sensitivity.setRange(0.0, 1.0)
        self.sensitivity.setSingleStep(0.05)
        self.sensitivity.setDecimals(2)
        self.sensitivity.setValue(settings.gesture_sensitivity)
        self.sensitivity.setToolTip("MediaPipe hand detection and tracking confidence threshold")

        self.cooldown = QDoubleSpinBox()
        self.cooldown.setRange(0.0, 60.0)
        self.cooldown.setSingleStep(0.1)
        self.cooldown.setSuffix(" s")
        self.cooldown.setValue(settings.gesture_cooldown)
        self.cooldown.setToolTip("Global minimum time between actions; a gesture can override this")

        self.auto_switch_profiles = QCheckBox("Automatically switch application profiles")
        self.auto_switch_profiles.setChecked(settings.auto_switch_profiles)
        self.auto_switch_profiles.setToolTip(
            "Apply a matching application profile's overrides when that application is focused"
        )
        self.exit_on_close = QCheckBox("Exit HandWave when I close the window")
        self.exit_on_close.setChecked(settings.exit_on_close)
        self.exit_on_close.setToolTip("Stops recognition and the microphone instead of keeping HandWave in the system tray")

        self.start_camera_on_launch = QCheckBox("Turn on the camera when HandWave opens")
        self.start_camera_on_launch.setChecked(settings.start_camera_on_launch)
        self.start_camera_on_launch.setToolTip("Start recognising gestures as soon as HandWave starts")

        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow(self.start_camera_on_launch)
        form.addRow("Sensitivity", self.sensitivity)
        form.addRow("Cooldown", self.cooldown)
        form.addRow(self.auto_switch_profiles)
        form.addRow(self.exit_on_close)
        return widget

    def _build_camera_tab(self, settings: AppSettings) -> QWidget:
        self.camera_index = QSpinBox()
        self.camera_index.setRange(0, 8)
        self.camera_index.setValue(settings.camera_index)
        self.camera_index.setToolTip("Index of the capture device to use, in OS enumeration order")

        self.fast_hand_model = QCheckBox("Faster hand model")
        self.fast_hand_model.setChecked(settings.fast_hand_model)
        self.fast_hand_model.setToolTip(
            "Uses MediaPipe's lite model: about a third less processing per frame, "
            "about 3 points less accurate on the HaGRID benchmark (78.5% vs 81.2%). Good for older laptops."
        )
        self.debug_overlay = QCheckBox("Show debug details on the camera preview")
        self.debug_overlay.setChecked(settings.debug_overlay)
        self.debug_overlay.setToolTip("Finger states, FPS and pinch distance drawn on the preview (for troubleshooting)")

        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow("Camera index", self.camera_index)
        form.addRow(self.fast_hand_model)
        form.addRow(self.debug_overlay)
        note = QLabel("Applies the next time recognition is enabled.")
        note.setWordWrap(True)
        note.setObjectName("note")
        form.addRow(note)
        return widget

    def _build_microphone_tab(self, settings: AppSettings) -> QWidget:
        self.microphone_device = QSpinBox()
        self.microphone_device.setRange(-1, 64)
        self.microphone_device.setSpecialValueText(f"{platforms.os_label()} default")
        self.microphone_device.setValue(-1 if settings.microphone_device is None else settings.microphone_device)
        self.clap_min_peak = QDoubleSpinBox(); self.clap_min_peak.setRange(0.001, 1.0); self.clap_min_peak.setDecimals(3); self.clap_min_peak.setSingleStep(0.005); self.clap_min_peak.setValue(settings.clap_min_peak)
        self.clap_noise_multiplier = QDoubleSpinBox(); self.clap_noise_multiplier.setRange(1.0, 20.0); self.clap_noise_multiplier.setSingleStep(0.1); self.clap_noise_multiplier.setValue(settings.clap_noise_multiplier)
        self.double_clap_min_interval = QDoubleSpinBox(); self.double_clap_min_interval.setRange(0.05, 2.0); self.double_clap_min_interval.setSingleStep(0.05); self.double_clap_min_interval.setSuffix(" s"); self.double_clap_min_interval.setValue(settings.double_clap_min_interval)
        self.double_clap_max_interval = QDoubleSpinBox(); self.double_clap_max_interval.setRange(0.10, 3.0); self.double_clap_max_interval.setSingleStep(0.05); self.double_clap_max_interval.setSuffix(" s"); self.double_clap_max_interval.setValue(settings.double_clap_max_interval)
        self.double_clap_enabled = QCheckBox("Double-clap turns recognition on or off")
        self.double_clap_enabled.setChecked(settings.double_clap_enabled)
        widget = QWidget(); form = QFormLayout(widget)
        form.addRow(self.double_clap_enabled)
        form.addRow("Microphone device index", self.microphone_device)
        form.addRow("Clap minimum peak", self.clap_min_peak)
        form.addRow("Noise multiplier", self.clap_noise_multiplier)
        form.addRow("Minimum double-clap interval", self.double_clap_min_interval)
        form.addRow("Maximum double-clap interval", self.double_clap_max_interval)
        note = QLabel("Clap twice to turn recognition on or off. Use the dashboard's Microphone button to see live levels and run guided calibration. Changes apply immediately after saving.")
        note.setWordWrap(True); form.addRow(note)
        return widget

    def _build_auto_pause_tab(self, settings: AppSettings) -> QWidget:
        """When HandWave should release the camera and pause by itself."""
        self.pause_when_camera_in_use = QCheckBox("Pause when another app is using the camera")
        self.pause_when_camera_in_use.setChecked(settings.pause_when_camera_in_use)
        self.pause_during_calls = QCheckBox("Pause during calls (Zoom, Teams, Discord, Meet…)")
        self.pause_during_calls.setChecked(settings.pause_during_calls)
        self.pause_apps = QListWidget()
        self.pause_apps.setObjectName("activityList")
        self.pause_apps.setAccessibleName("Programs that pause HandWave")
        self.pause_apps.setMinimumHeight(120)
        for name in settings.pause_for_apps:
            self.pause_apps.addItem(name)
        self.pause_app_input = QComboBox()
        self.pause_app_input.setEditable(True)
        self.pause_app_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        from handwave import platforms

        macos = platforms.is_macos()
        self.pause_app_input.lineEdit().setPlaceholderText("App name, e.g. OBS or zoom.us" if macos else "Program name, e.g. obs64.exe")
        try:
            if macos:
                from handwave.platforms.macos import running_process_names

                running = sorted(running_process_names())
            else:
                running = sorted(name for name in running_processes() if name.endswith('.exe'))
        except OSError:
            running = []
        self.pause_app_input.addItems(running)
        self.pause_app_input.setCurrentIndex(-1)
        add = QPushButton("Add")
        remove = motion.UnderlineButton("Remove selected")
        remove.setObjectName("ghostButton")
        add.clicked.connect(self._add_pause_app)
        remove.clicked.connect(self._remove_pause_apps)
        self.pause_app_error = QLabel("")
        self.pause_app_error.setObjectName("note")
        add_row = QHBoxLayout()
        add_row.addWidget(self.pause_app_input, 1)
        add_row.addWidget(add)
        add_row.addWidget(remove)
        note = QLabel("HandWave releases the camera while any of these is true, then resumes on its own. "
                     "Turning recognition on yourself always takes priority.")
        note.setObjectName("note")
        note.setWordWrap(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.pause_when_camera_in_use)
        layout.addWidget(self.pause_during_calls)
        layout.addSpacing(10)
        layout.addWidget(QLabel("PAUSE WHILE THESE PROGRAMS ARE RUNNING", objectName="sectionLabel"))
        layout.addWidget(self.pause_apps, 1)
        layout.addLayout(add_row)
        layout.addWidget(self.pause_app_error)
        layout.addWidget(note)
        return widget

    def _remove_pause_apps(self) -> None:
        for item in self.pause_apps.selectedItems():
            self.pause_apps.takeItem(self.pause_apps.row(item))

    def _add_pause_app(self) -> None:
        from handwave.config.settings_manager import normalize_app_names

        text = self.pause_app_input.currentText()
        try:
            names = normalize_app_names([text])
        except ValueError as exc:
            self.pause_app_error.setText(str(exc))
            return
        existing = {self.pause_apps.item(i).text() for i in range(self.pause_apps.count())}
        for name in names:
            if name not in existing:
                self.pause_apps.addItem(name)
        self.pause_app_error.setText("")
        self.pause_app_input.setCurrentIndex(-1)
        self.pause_app_input.clearEditText()

    def _build_cursor_control_tab(self, settings: AppSettings) -> QWidget:
        """Controls that affect the visual, calibrated cursor feedback."""
        self.show_cursor_overlay = QCheckBox("Show Cursor Overlay")
        self.show_cursor_overlay.setChecked(settings.cursor_assist_overlay_enabled)
        self.show_cursor_overlay.setAccessibleName("Show Cursor Overlay")
        self.show_cursor_overlay.setToolTip(
            "Show a click-through visual marker at HandWave's calibrated cursor position"
        )
        note = QLabel(
            f"The overlay is visual feedback only. It does not replace or move the {platforms.os_label()} cursor."
        )
        note.setWordWrap(True)
        note.setObjectName("note")
        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow(self.show_cursor_overlay)
        form.addRow(note)
        return widget

    def _build_gestures_tab(self, settings: AppSettings) -> QWidget:
        gestures = QWidget()
        gesture_layout = QVBoxLayout(gestures)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        # Same widths and stretch factors as ActionEditorRow, so the columns line up.
        for text, stretch in (("Gesture", 2), ("Action type", 2), ("Value", 3)):
            header.addWidget(QLabel(text), stretch)
        for text in ("Hold", "Cooldown"):
            label = QLabel(text)
            label.setFixedWidth(ActionEditorRow.spin_width())
            header.addWidget(label)
        gesture_layout.addLayout(header)
        for gesture in GESTURES:
            row = ActionEditorRow(
                gesture,
                settings.gesture_bindings[gesture],
                settings.enabled_gestures[gesture],
            )
            gesture_layout.addWidget(row)
            self._gesture_rows[gesture] = row
        gesture_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(gestures)

        note = QLabel(
            "Program launches and potentially destructive combinations (e.g. Alt+F4) "
            "always require a hold."
        )
        note.setWordWrap(True)
        note.setObjectName("note")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(scroll, 1)
        layout.addWidget(note)
        return container

    def _build_appearance_tab(self, settings: AppSettings) -> QWidget:
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(settings.theme))

        self.show_fingerprint_indicator = QCheckBox("Show fingerprint indicator")
        self.show_fingerprint_indicator.setChecked(settings.show_fingerprint_indicator)
        self.show_fingerprint_indicator.setToolTip(
            "Shows a touchless fingertip-tracking dot over the camera preview; it does not indicate real touch"
        )
        self.fingerprint_indicator_size = QSpinBox()
        self.fingerprint_indicator_size.setRange(8, 48)
        self.fingerprint_indicator_size.setSuffix(" px")
        self.fingerprint_indicator_size.setValue(settings.fingerprint_indicator_size)
        self.fingerprint_indicator_opacity = QDoubleSpinBox()
        self.fingerprint_indicator_opacity.setRange(0.2, 1.0)
        self.fingerprint_indicator_opacity.setSingleStep(0.05)
        self.fingerprint_indicator_opacity.setValue(settings.fingerprint_indicator_opacity)
        self.fingerprint_indicator_fade_duration_ms = QSpinBox()
        self.fingerprint_indicator_fade_duration_ms.setRange(50, 2000)
        self.fingerprint_indicator_fade_duration_ms.setSingleStep(50)
        self.fingerprint_indicator_fade_duration_ms.setSuffix(" ms")
        self.fingerprint_indicator_fade_duration_ms.setValue(settings.fingerprint_indicator_fade_duration_ms)

        widget = QWidget()
        form = QFormLayout(widget)
        self.reduce_motion = QCheckBox("Reduce motion")
        self.reduce_motion.setChecked(settings.reduce_motion)
        self.reduce_motion.setToolTip("Turn off animations and transitions")
        form.addRow("Theme", self.theme_combo)
        form.addRow(self.reduce_motion)
        form.addRow(self.show_fingerprint_indicator)
        form.addRow("Indicator size", self.fingerprint_indicator_size)
        form.addRow("Indicator opacity", self.fingerprint_indicator_opacity)
        form.addRow("Indicator fade", self.fingerprint_indicator_fade_duration_ms)
        return widget

    def values(self) -> dict[str, object]:
        return {
            "gesture_sensitivity": self.sensitivity.value(),
            "gesture_cooldown": self.cooldown.value(),
            "auto_switch_profiles": self.auto_switch_profiles.isChecked(),
            "exit_on_close": self.exit_on_close.isChecked(),
            "camera_index": self.camera_index.value(),
            "theme": self.theme_combo.currentData(),
            "show_fingerprint_indicator": self.show_fingerprint_indicator.isChecked(),
            "fingerprint_indicator_size": self.fingerprint_indicator_size.value(),
            "fingerprint_indicator_opacity": self.fingerprint_indicator_opacity.value(),
            "fingerprint_indicator_fade_duration_ms": self.fingerprint_indicator_fade_duration_ms.value(),
            "microphone_device": None if self.microphone_device.value() < 0 else self.microphone_device.value(),
            "clap_min_peak": self.clap_min_peak.value(),
            "clap_noise_multiplier": self.clap_noise_multiplier.value(),
            "double_clap_min_interval": self.double_clap_min_interval.value(),
            "double_clap_max_interval": self.double_clap_max_interval.value(),
            "cursor_assist_overlay_enabled": self.show_cursor_overlay.isChecked(),
            "start_camera_on_launch": self.start_camera_on_launch.isChecked(),
            "double_clap_enabled": self.double_clap_enabled.isChecked(),
            "reduce_motion": self.reduce_motion.isChecked(),
            "pause_when_camera_in_use": self.pause_when_camera_in_use.isChecked(),
            "pause_during_calls": self.pause_during_calls.isChecked(),
            "fast_hand_model": self.fast_hand_model.isChecked(),
            "debug_overlay": self.debug_overlay.isChecked(),
            "pause_for_apps": tuple(self.pause_apps.item(i).text() for i in range(self.pause_apps.count())),
            "gesture_bindings": {
                gesture: row.action_dict() for gesture, row in self._gesture_rows.items()
            },
            "enabled_gestures": {
                gesture: row.enabled_checkbox.isChecked()
                for gesture, row in self._gesture_rows.items()
            },
        }
