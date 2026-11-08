"""Polished HandWave desktop dashboard and tray controller."""

from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSettings, QTime, QTimer, Qt, pyqtSlot
from PyQt6.QtGui import QAction, QCloseEvent, QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from handwave.config.profile_manager import ProfileManager
from handwave.config.template_manager import TemplateManager
from handwave.gestures.custom_gesture_store import CustomGestureStore
from handwave.config.settings_manager import SettingsManager
from handwave.services.action_history import ActionHistory
from handwave.services.activation_service import ActivationService
from handwave.services.clap_detector import ClapDetector
from handwave.services.foreground_app import get_foreground_app
from handwave.services.profile_switcher import ProfileSwitchEvent, ProfileSwitcher
from handwave.ui.onboarding import OnboardingDialog
from handwave.ui.diagnostics_page import DiagnosticsPage
from handwave.ui.fingerprint_indicator import FingerprintIndicator
from handwave.ui.settings_dialog import SettingsDialog
from handwave.ui.templates_dialog import TemplatesDialog
from handwave.ui.custom_gestures_dialog import CustomGesturesDialog
from handwave.ui.microphone_dialog import MicrophoneDialog
from handwave.ui.cursor_calibration_dialog import CursorCalibrationDialog
from handwave.ui.cursor_assist_overlay import CursorAssistOverlay, CursorAssistState
from handwave.actions.cursor_reach_mapper import CursorReach, SmoothedCursorReachMapper
from handwave.services.monitor_layout import MonitorLayout
from handwave.ui.help_dialog import HelpDialog
from handwave.ui.gesture_icons import gesture_icon
from handwave.ui.theme import palette, set_tone, stylesheet as theme_stylesheet
from handwave.ui import motion
from handwave import platforms
from handwave.services.auto_pause import AutoPauseMonitor, PauseRules
from handwave.vision.camera_manager import CameraManager

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Application dashboard, activity timeline, onboarding, and tray lifecycle."""

    MAX_LOG_ITEMS = 50

    PROFILE_POLL_INTERVAL_MS = 1500

    def __init__(
        self,
        camera_manager: CameraManager | None = None,
        clap_detector: ClapDetector | None = None,
        settings_manager: SettingsManager | None = None,
        onboarding_settings: QSettings | None = None,
        profile_manager: ProfileManager | None = None,
        template_manager: TemplateManager | None = None,
        custom_gesture_store: CustomGestureStore | None = None,
        foreground_app_provider=None,
    ) -> None:
        super().__init__()
        self.settings_manager = settings_manager or SettingsManager()
        motion.set_reduced_motion(self.settings_manager.settings.reduce_motion)
        # Auto-pause: HandWave stops itself while the camera is needed elsewhere
        # and resumes afterwards. A manual choice always wins (see user_start).
        self.auto_pause = AutoPauseMonitor(self._pause_rules(self.settings_manager.settings))
        self._auto_paused = False
        self._pause_reason = ""
        self._pause_overridden = ""
        self._camera_starting = False
        self._services_started = False
        self._launch_pending = False
        self.camera = camera_manager or CameraManager(settings=self.settings_manager.settings)
        self.activation = ActivationService()
        self.clap_detector = clap_detector or ClapDetector(
            device=self.settings_manager.settings.microphone_device,
            min_peak=self.settings_manager.settings.clap_min_peak,
            rms_threshold=self.settings_manager.settings.clap_rms_threshold,
            noise_multiplier=self.settings_manager.settings.clap_noise_multiplier,
            min_clap_separation=self.settings_manager.settings.double_clap_min_interval,
            max_clap_separation=self.settings_manager.settings.double_clap_max_interval,
        )
        self.onboarding_settings = onboarding_settings or QSettings("HandWave", "HandWave")
        self.onboarding_dialog: OnboardingDialog | None = None
        self.profile_manager = profile_manager or ProfileManager()
        self.template_manager = template_manager or TemplateManager()
        self.custom_gesture_store = custom_gesture_store or CustomGestureStore()
        self.camera.update_custom_gestures(self.custom_gesture_store.list_gestures()) if hasattr(self.camera, "update_custom_gestures") else None
        self.profile_switcher = ProfileSwitcher(
            self.profile_manager,
            foreground_provider=foreground_app_provider or get_foreground_app,
            global_settings_provider=lambda: self.template_manager.get_active_template().resolve(self.settings_manager.settings),
            on_change=self._on_profile_switch,
            enabled=self.settings_manager.settings.auto_switch_profiles,
        )
        self._profile_poll_timer = QTimer(self)
        self._profile_poll_timer.setInterval(self.PROFILE_POLL_INTERVAL_MS)
        self._profile_poll_timer.timeout.connect(self._poll_profile_switch)
        self._last_profile_event: ProfileSwitchEvent | None = None
        self.action_history = ActionHistory()
        self._last_confidence = 0.0
        self._exit_requested = False
        self._camera_error_pending = False
        self._last_stable_gesture = "Unknown"
        self._cursor_mapper: SmoothedCursorReachMapper | None = None
        self._cursor_mapper_signature: tuple[object, ...] | None = None
        self.cursor_assist_overlay = CursorAssistOverlay(
            self.settings_manager.settings.cursor_assist_overlay_size,
            self.settings_manager.settings.cursor_assist_overlay_opacity,
        )
        self._cursor_state_timer = QTimer(self)
        self._cursor_state_timer.setSingleShot(True)
        self._cursor_state_timer.timeout.connect(self._restore_cursor_tracking)
        # A predictable dark dashboard is the startup baseline. Theme toggles
        # still apply immediately, but no previous light-mode session changes
        # the visual default of the next launch.
        self._theme_mode = "dark"
        self._active_icon = self._make_status_icon(True)
        self._paused_icon = self._make_status_icon(False)
        self._build_ui()
        self._build_tray()
        self._connect_signals()
        self.toast = motion.Toast(self.pages)
        self._apply_theme(self._theme_mode, animate=False)
        self.auto_pause.reason_changed.connect(self._on_auto_pause_reason)
        # Preview frames are coalesced: only the newest pending frame is drawn,
        # once per event-loop pass, and nothing is drawn while not visible.
        self._pending_frame = None
        self._frame_scheduled = False
        self._preview_clip: tuple[tuple[int, int], QPainterPath] | None = None

    @staticmethod
    def _make_status_icon(active: bool) -> QIcon:
        """Tray icon: a champagne ring with a solid core when live, a quiet ring when paused."""
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#c9a96e" if active else "#8c867c")
        painter.setPen(QPen(color, 2.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(4, 4, 24, 24)
        if active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(11, 11, 10, 10)
        painter.end()
        return QIcon(pixmap)

    def _build_ui(self) -> None:
        self.setWindowTitle("HandWave")
        self.resize(1240, 820)
        self.setMinimumSize(760, 600)
        self.setStyleSheet(self._theme(self._theme_mode))

        # ---- header: wordmark left, quiet status and two text actions right
        brand = QLabel("HandWave")
        brand.setObjectName("brand")
        tagline = QLabel("TOUCHLESS MEDIA CONTROL")
        tagline.setObjectName("tagline")
        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(2)
        brand_layout.addWidget(brand)
        brand_layout.addWidget(tagline)

        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("statusDot")
        self.status_text = QLabel("Recognition Disabled")
        self.status_text.setObjectName("statusText")
        status_badge = QFrame()
        status_badge.setObjectName("statusBadge")
        status_layout = QHBoxLayout(status_badge)
        status_layout.setContentsMargins(0, 0, 18, 0)
        status_layout.setSpacing(8)
        status_layout.addWidget(self.status_dot)
        status_layout.addWidget(self.status_text)

        self.theme_button = motion.UnderlineButton()
        self.theme_button.setObjectName("themeButton")
        self.theme_button.setToolTip("Switch between dark and light appearance")
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sync_theme_button()
        self.help_button = motion.UnderlineButton("Help")
        self.help_button.setObjectName("helpButton")
        self.help_button.setToolTip("Open the HandWave user guide")
        self.help_button.setAccessibleName("Help and user guide")
        self.help_button.setCursor(Qt.CursorShape.PointingHandCursor)

        header = QHBoxLayout()
        header.setSpacing(4)
        header.addLayout(brand_layout)
        header.addStretch()
        header.addWidget(status_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.theme_button, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.help_button, 0, Qt.AlignmentFlag.AlignVCenter)

        # ---- a single hairline-ruled line of system state
        system_status = QFrame()
        system_status.setObjectName("statusStrip")
        system_status_layout = QHBoxLayout(system_status)
        system_status_layout.setContentsMargins(0, 11, 0, 11)
        system_status_layout.setSpacing(30)
        self.camera_status = QLabel("●  CAMERA IDLE")
        self.recognition_status = QLabel("●  RECOGNITION OFF")
        self.microphone_status = QLabel("●  MICROPHONE STANDBY")
        self.profile_status = QLabel("Active profile: Global")
        self.profile_status.setAccessibleName("Active application profile")
        self.microphone_status.setAccessibleName("Microphone and double-clap status")
        for indicator in (self.camera_status, self.recognition_status, self.microphone_status):
            indicator.setObjectName("systemIndicator")
            system_status_layout.addWidget(indicator)
        system_status_layout.addStretch()
        self.profile_status.setObjectName("systemIndicator")
        system_status_layout.addWidget(self.profile_status)

        # ---- camera: title, preview, one primary action and quiet text actions
        self.preview = QLabel("CAMERA PREVIEW PAUSED")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(360, 280)
        # Ignore the pixmap's size so each new frame cannot grow the layout.
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.preview.setAccessibleName("Live camera preview")
        self.preview.setAccessibleDescription("Shows the camera image and detected hand landmarks while recognition is enabled.")
        self.fingerprint_indicator = FingerprintIndicator(
            self.preview,
            enabled=self.settings_manager.settings.show_fingerprint_indicator,
            size=self.settings_manager.settings.fingerprint_indicator_size,
            opacity=self.settings_manager.settings.fingerprint_indicator_opacity,
            fade_duration_ms=self.settings_manager.settings.fingerprint_indicator_fade_duration_ms,
        )

        camera_title = QLabel("Camera")
        camera_title.setObjectName("cardTitle")
        camera_subtitle = QLabel("Live hand tracking and gesture recognition")
        camera_subtitle.setObjectName("cardSubtitle")
        self.privacy_notice = QLabel(
            "None of your video data leaves your device — it is processed on-device :)"
        )
        self.privacy_notice.setObjectName("privacyNotice")
        self.privacy_notice.setAccessibleName("Camera privacy notice")

        self.start_button = QPushButton("Enable Recognition")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setAccessibleDescription("Enable or disable camera capture and gesture recognition")
        self.settings_button = motion.UnderlineButton("Settings")
        self.templates_button = motion.UnderlineButton("Templates")
        self.custom_gestures_button = motion.UnderlineButton("Custom Gestures")
        self.microphone_button = motion.UnderlineButton("Microphone")
        self.microphone_button.setAccessibleDescription("Test the microphone and calibrate double-clap activation")
        self.cursor_calibration_button = motion.UnderlineButton("Cursor Calibration")
        self.cursor_calibration_button.setAccessibleDescription("Calibrate your comfortable hand reach for the cursor overlay")
        self.settings_button.setAccessibleDescription("Open gesture bindings and sensitivity settings")
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        controls = QHBoxLayout()
        controls.setSpacing(2)
        controls.addWidget(self.start_button)
        controls.addSpacing(14)
        for button in (self.settings_button, self.templates_button, self.custom_gestures_button,
                       self.microphone_button, self.cursor_calibration_button):
            button.setObjectName("ghostButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            controls.addWidget(button)
        controls.addStretch()

        camera_card = QFrame()
        camera_card.setObjectName("card")
        camera_layout = QVBoxLayout(camera_card)
        camera_layout.setContentsMargins(0, 0, 0, 0)
        camera_layout.setSpacing(6)
        camera_layout.addWidget(camera_title)
        camera_layout.addWidget(camera_subtitle)
        camera_layout.addSpacing(14)
        camera_layout.addWidget(self.preview, 1)
        camera_layout.addSpacing(8)
        camera_layout.addWidget(self.privacy_notice)
        camera_layout.addSpacing(14)
        camera_layout.addLayout(controls)

        # ---- sidebar: typographic sections separated by space, not boxes
        self.live_gesture = QLabel("No gesture detected")
        self.live_gesture.setObjectName("liveGesture")
        self.live_gesture.setProperty("tone", "idle")
        self.live_gesture_detail = QLabel("Raw  —")
        self.live_gesture_detail.setObjectName("liveGestureDetail")
        self.confidence_label = QLabel("Confidence  0%")
        self.confidence_label.setObjectName("confidenceLabel")
        self.confidence_bar = QProgressBar()
        self.confidence_bar.setObjectName("confidenceBar")
        self.confidence_bar.setRange(0, 100)
        self.confidence_bar.setValue(0)
        self.confidence_bar.setTextVisible(False)
        self.confidence_bar.setFixedHeight(2)
        self.confidence_bar.setAccessibleName("Gesture confidence")
        self.confidence_bar.setAccessibleDescription("Recognition confidence from zero to one hundred percent")
        self.gesture_history = QListWidget()
        self.gesture_history.setObjectName("activityList")
        self.gesture_history.setAccessibleName("Gesture history")
        self.action_log = QListWidget()
        self.action_log.setObjectName("activityList")
        self.action_log.setAccessibleName("Action log")
        for activity in (self.gesture_history, self.action_log):
            activity.setFrameShape(QFrame.Shape.NoFrame)
            activity.setMinimumHeight(96)

        diagnostics_title = QLabel("DIAGNOSTICS")
        diagnostics_title.setObjectName("sectionLabel")
        self.diagnostics = QLabel("0.0 fps camera  ·  0.0 fps recognition  ·  0.0 ms\nCPU 0.0%  ·  0.0 MB  ·  0 dropped")
        self.diagnostics.setObjectName("diagnostics")
        self.diagnostics.setAccessibleName("Pipeline diagnostics")

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(32, 4, 0, 0)
        side_layout.setSpacing(6)
        side_layout.addWidget(QLabel("LIVE GESTURE", objectName="sectionLabel"))
        side_layout.addSpacing(4)
        side_layout.addWidget(self.live_gesture)
        side_layout.addWidget(self.live_gesture_detail)
        side_layout.addSpacing(10)
        confidence_row = QHBoxLayout()
        confidence_row.addWidget(self.confidence_label)
        confidence_row.addStretch()
        side_layout.addLayout(confidence_row)
        side_layout.addWidget(self.confidence_bar)
        side_layout.addSpacing(26)
        side_layout.addWidget(QLabel("GESTURE HISTORY", objectName="sectionLabel"))
        side_layout.addWidget(self.gesture_history, 1)
        side_layout.addSpacing(18)
        side_layout.addWidget(QLabel("ACTION LOG", objectName="sectionLabel"))
        side_layout.addWidget(self.action_log, 1)
        side_layout.addSpacing(18)
        side_layout.addWidget(diagnostics_title)
        side_layout.addWidget(self.diagnostics)

        sidebar.setMinimumWidth(300)
        self._sidebar = sidebar
        self._content_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._content_layout.setSpacing(36)
        self._content_layout.addWidget(camera_card, 3)
        self._content_layout.addWidget(sidebar, 2)

        layout = QVBoxLayout()
        layout.setContentsMargins(40, 30, 40, 32)
        layout.setSpacing(24)
        layout.addLayout(header)
        layout.addWidget(system_status)
        layout.addSpacing(6)
        layout.addLayout(self._content_layout, 1)
        container = QWidget()
        container.setObjectName("workspace")
        container.setLayout(layout)
        scroll = QScrollArea()
        scroll.setObjectName("workspaceScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(container)
        self.diagnostics_page = DiagnosticsPage()
        self.pages = QTabWidget()
        self.pages.setObjectName("mainPages")
        self.pages.setDocumentMode(True)
        self.pages.addTab(scroll, "DASHBOARD")
        self.pages.addTab(self.diagnostics_page, "DIAGNOSTICS")
        self.pages.tabBar().setCursor(Qt.CursorShape.PointingHandCursor)
        self.pages.setAccessibleName("HandWave pages")
        self.setCentralWidget(self.pages)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage("Ready")

        self._status_effect = QGraphicsOpacityEffect(self.status_dot)
        self.status_dot.setGraphicsEffect(self._status_effect)
        self._status_pulse = QPropertyAnimation(self._status_effect, b"opacity", self)
        # Breathe 1 -> 0.3 -> 1 with sine easing so the loop has no visible seam.
        self._status_pulse.setDuration(1800)
        self._status_pulse.setKeyValueAt(0.0, 1.0)
        self._status_pulse.setKeyValueAt(0.5, 0.3)
        self._status_pulse.setKeyValueAt(1.0, 1.0)
        self._status_pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._status_pulse.setLoopCount(-1)
        self._set_status("Recognition Disabled", "idle")

    @staticmethod
    def _theme(mode: str = "dark") -> str:
        return theme_stylesheet(mode)

    def _build_tray(self) -> None:
        self.tray_icon = QSystemTrayIcon(self._paused_icon, self)
        self.tray_icon.setToolTip("HandWave — Paused")
        self.tray_menu = QMenu(self)
        self.open_action = QAction("Open HandWave", self)
        self.enable_action = QAction("Enable Recognition", self)
        self.disable_action = QAction("Disable Recognition", self)
        self.settings_action = QAction("Settings…", self)
        self.startup_action = QAction(
            "Launch at Login" if platforms.is_macos() else "Launch at Windows Startup", self, checkable=True
        )
        self.startup_action.setChecked(self.settings_manager.settings.startup_enabled)
        self.exit_action = QAction("Exit", self)
        self.setup_action = QAction("Run setup again…", self)
        self.enable_action.setShortcut("Alt+E")
        self.disable_action.setShortcut("Alt+P")
        self.settings_action.setShortcut("Ctrl+,")
        self.theme_action = QAction("Toggle theme", self)
        self.theme_action.setShortcut("Ctrl+T")
        self.diagnostics_action = QAction("Open diagnostics", self)
        self.diagnostics_action.setShortcut("Ctrl+D")
        self.addActions((self.enable_action, self.disable_action, self.settings_action, self.theme_action, self.diagnostics_action))
        self.disable_action.setEnabled(False)
        for action in (self.open_action, self.settings_action, self.setup_action, None, self.enable_action, self.disable_action, None, self.startup_action, None, self.exit_action):
            self.tray_menu.addSeparator() if action is None else self.tray_menu.addAction(action)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()

    def _connect_signals(self) -> None:
        self.start_button.clicked.connect(self.toggle_recognition)
        self.settings_button.clicked.connect(self.open_settings)
        self.templates_button.clicked.connect(self.open_templates)
        self.custom_gestures_button.clicked.connect(self.open_custom_gestures)
        self.microphone_button.clicked.connect(self.open_microphone_test)
        self.cursor_calibration_button.clicked.connect(self.open_cursor_calibration)
        self.theme_button.clicked.connect(self.toggle_theme)
        self.help_button.clicked.connect(self.open_help)
        self.camera.frame_ready.connect(self.update_frame)
        self.camera.frame_ready.connect(self._feed_cursor_calibration_frame)
        self.camera.started.connect(self._camera_started)
        self.camera.stopped.connect(self._camera_stopped)
        self.camera.error.connect(self._camera_error)
        if hasattr(self.camera, "recognition_updated"):
            self.camera.recognition_updated.connect(self.update_activity)
        if hasattr(self.camera, "diagnostics_updated"):
            self.camera.diagnostics_updated.connect(self.update_diagnostics)
        if hasattr(self.camera, "confidence_updated"):
            self.camera.confidence_updated.connect(self.update_confidence)
        if hasattr(self.camera, "action_outcome_updated"):
            self.camera.action_outcome_updated.connect(self._record_action_outcome)
        if hasattr(self.camera, "fingertips_updated"):
            self.camera.fingertips_updated.connect(self.fingerprint_indicator.update_fingertips)
            self.camera.fingertips_updated.connect(self._feed_cursor_calibration)
        if hasattr(self.camera, "hands_updated"):
            self.camera.hands_updated.connect(self._feed_custom_gesture_hands)
        self.open_action.triggered.connect(self.open_from_tray)
        self.enable_action.triggered.connect(self.user_start)
        self.disable_action.triggered.connect(self.user_stop)
        self.pages.tabBarClicked.connect(self._before_page_change)
        self.settings_action.triggered.connect(self.open_settings)
        self.theme_action.triggered.connect(self.toggle_theme)
        self.diagnostics_action.triggered.connect(lambda: self.show_page(1))
        self.startup_action.toggled.connect(self._set_startup_enabled)
        self.exit_action.triggered.connect(self.exit_application)
        self.setup_action.triggered.connect(self.rerun_onboarding)
        self.tray_icon.activated.connect(self._tray_activated)
        # ClapDetector queues callback-originated signals to its GUI thread;
        # keeping this default connection also supports test/in-process emitters.
        self.clap_detector.double_clap.connect(self._handle_clap_toggle)
        self.clap_detector.error.connect(self._clap_error)
        if hasattr(self.clap_detector, "started"):
            self.clap_detector.started.connect(self._microphone_started)
        if hasattr(self.clap_detector, "stopped"):
            self.clap_detector.stopped.connect(self._microphone_stopped)

    def launch(self) -> None:
        """Startup sequence: first-run setup, then microphone, auto-pause and camera.

        On first launch the camera waits until setup is finished, so the
        user's choices (camera, auto-start, pausing) apply from the start.
        """
        if self.show_onboarding_if_needed():
            self._launch_pending = True
            return
        self._start_services()

    def _start_services(self) -> None:
        if self._services_started or self._exit_requested:
            return
        self._services_started = True
        settings = self.settings_manager.settings
        if settings.double_clap_enabled:
            self.clap_detector.start()
        else:
            self._microphone_stopped()
        reason = self.auto_pause.check_now()
        self.auto_pause.start()
        if not settings.start_camera_on_launch:
            return
        if reason:
            self._auto_paused, self._pause_reason = True, reason
            self._show_auto_paused(reason)
            self.toast.show_message(f"Paused while {reason}")
        else:
            self.start_camera()

    def show_onboarding_if_needed(self) -> bool:
        if self.onboarding_settings.value("onboarding/completed", False, type=bool):
            return False
        self.onboarding_dialog = OnboardingDialog(
            self.settings_manager.settings, self, startup_enabled=self.startup_action.isChecked()
        )
        self.onboarding_dialog.completed.connect(self._complete_onboarding)
        self.onboarding_dialog.open()
        return True

    @pyqtSlot()
    def rerun_onboarding(self) -> None:
        """Open the setup flow again (e.g. for people who installed before it existed)."""
        self.open_from_tray()
        self.onboarding_settings.setValue("onboarding/completed", False)
        self.show_onboarding_if_needed()

    @pyqtSlot()
    def _complete_onboarding(self) -> None:
        self.onboarding_settings.setValue("onboarding/completed", True)
        self.onboarding_settings.sync()
        dialog = self.onboarding_dialog
        if dialog is not None and not dialog.skipped:
            try:
                settings = self.settings_manager.update(**dialog.values())
            except (OSError, TypeError, ValueError) as exc:
                logger.exception("Unable to save onboarding choices")
                QMessageBox.warning(self, "Setup choices were not saved", str(exc))
            else:
                self._apply_settings(settings)
                if dialog.startup_enabled != self.startup_action.isChecked():
                    self.startup_action.setChecked(dialog.startup_enabled)
                self.toast.show_message("You're all set")
        if self._launch_pending:
            self._launch_pending = False
            QTimer.singleShot(0, self._start_services)

    # ------------------------------------------------------------ auto-pause
    @staticmethod
    def _pause_rules(settings) -> PauseRules:
        return PauseRules(settings.pause_when_camera_in_use, settings.pause_during_calls, tuple(settings.pause_for_apps))

    @pyqtSlot(str)
    def _on_auto_pause_reason(self, reason: str) -> None:
        if not reason:
            self._pause_overridden = ""
            if self._auto_paused:
                self._auto_paused, self._pause_reason = False, ""
                self.start_camera()
                self.toast.show_message("Resumed")
            return
        if reason == self._pause_overridden:
            return  # the user turned recognition on despite this; respect that
        if self.activation.is_active or self._camera_starting:
            self._auto_paused, self._pause_reason = True, reason
            logger.info("Auto-pausing recognition: %s", reason)
            self.stop_camera()
            self.toast.show_message(f"Paused while {reason}")
        elif self._auto_paused:
            self._pause_reason = reason
            self._show_auto_paused(reason)

    def _show_auto_paused(self, reason: str) -> None:
        self._set_status(f"Paused while {reason}", "pending")
        self.camera_status.setText("●  CAMERA PAUSED")
        set_tone(self.camera_status, "pending")

    @pyqtSlot()
    def user_start(self) -> None:
        """Start because the user asked: overrides any current auto-pause reason."""
        if self.auto_pause.reason:
            self._pause_overridden = self.auto_pause.reason
        self._auto_paused, self._pause_reason = False, ""
        self.start_camera()

    @pyqtSlot()
    def user_stop(self) -> None:
        """Stop because the user asked: never auto-resume afterwards."""
        self._auto_paused, self._pause_reason = False, ""
        self.stop_camera()

    # ------------------------------------------------------------- motion
    def _before_page_change(self, index: int) -> None:
        if index != self.pages.currentIndex():
            motion.crossfade(self.pages, 200)

    def show_page(self, index: int) -> None:
        self._before_page_change(index)
        self.pages.setCurrentIndex(index)

    def _apply_theme(self, mode: str, animate: bool = True) -> None:
        if animate:
            motion.crossfade(self, 280)
        self._theme_mode = mode
        self.setStyleSheet(self._theme(mode))
        self._sync_theme_button()
        colors = palette(mode)
        motion.UnderlineButton.set_accent(colors["accent"])
        self.toast.set_colors(colors["raised"], colors["line"], colors["text"], colors["accent"])

    @pyqtSlot(str, str, str)
    def update_activity(self, raw: str, stable: str, action: str) -> None:
        shown = stable if stable != "Unknown" else "No gesture detected"
        if shown != self.live_gesture.text():
            self.live_gesture.setText(shown)
            motion.emphasize(self.live_gesture)
        set_tone(self.live_gesture, "idle" if stable == "Unknown" else "live")
        self.live_gesture_detail.setText(f"Raw  {raw if raw != 'Unknown' else '—'}")
        self.live_gesture.setAccessibleName(f"Raw {raw}; Stable {stable}")
        self.diagnostics_page.update_gesture(raw, stable)
        timestamp = QTime.currentTime().toString("HH:mm:ss")
        if stable != "Unknown" and stable != self._last_stable_gesture:
            self._prepend_bounded(self.gesture_history, f"{stable}      {timestamp}", stable)
        self._last_stable_gesture = stable
        if stable != "Unknown":
            state = CursorAssistState.CLICK_READY if "click" in action.lower() else CursorAssistState.GESTURE_DETECTED
            self.cursor_assist_overlay.set_state(state)
            self._cursor_state_timer.start(450)
        if action:
            self._prepend_bounded(self.action_log, f"{action}      {timestamp}")

    @pyqtSlot(float)
    def update_confidence(self, confidence: float) -> None:
        self._last_confidence = confidence
        percent = max(0, min(100, round(confidence * 100)))
        gliding = getattr(self.confidence_bar, "_hw_value_animation", None)
        if abs(percent - self.confidence_bar.value()) >= 8:
            motion.animate_value(self.confidence_bar, percent)
        elif gliding is None or gliding.state() != gliding.State.Running:
            self.confidence_bar.setValue(percent)  # frame-to-frame jitter: no animation
        self.confidence_label.setText(f"Confidence  {percent}%")

    @pyqtSlot(object)
    def _record_action_outcome(self, outcome: object) -> None:
        """Log a structured, bounded audit entry for every recognized gesture."""
        profile_name = None
        application = None
        if self._last_profile_event is not None:
            profile_name = (
                self._last_profile_event.match.profile.name
                if self._last_profile_event.match.profile
                else "Global"
            )
            application = self._last_profile_event.foreground.executable
        entry = self.action_history.record(
            gesture=outcome.gesture,
            confidence=self._last_confidence,
            action=outcome.action_description,
            executed=outcome.executed,
            blocked_reason=outcome.blocked_reason,
            application=application,
            profile=profile_name,
        )
        timestamp = QTime.currentTime().toString("HH:mm:ss")
        if not entry.executed:
            self._prepend_bounded(self.action_log, f"{timestamp}   Blocked: {entry.blocked_reason}")

    def _prepend_bounded(self, widget: QListWidget, text: str, gesture: str | None = None) -> None:
        from PyQt6.QtWidgets import QListWidgetItem
        item = QListWidgetItem(gesture_icon(gesture) if gesture else QIcon(), text)
        if gesture: item.setToolTip(gesture)
        widget.insertItem(0, item)
        motion.fade_in_item(item, QColor(palette(self._theme_mode)["text"]))
        while widget.count() > self.MAX_LOG_ITEMS:
            widget.takeItem(widget.count() - 1)

    @pyqtSlot(object)
    def update_diagnostics(self, metrics: object) -> None:
        """Display the latest passive pipeline profiling snapshot."""
        self.diagnostics_page.update_metrics(metrics)
        overlay_metrics = self.cursor_assist_overlay.metrics()
        self.diagnostics_page.update_cursor_overlay(self.cursor_assist_overlay.state, overlay_metrics)
        # The dashboard shows a two-line summary; the full breakdown is the
        # tooltip here and lives on the Diagnostics page.
        self.diagnostics.setText(
            f"{metrics.camera_fps:.1f} fps camera  ·  {metrics.recognition_fps:.1f} fps recognition  ·  {metrics.latency_ms:.1f} ms\n"
            f"CPU {metrics.cpu_percent:.1f}%  ·  {metrics.memory_mb:.1f} MB  ·  {metrics.dropped_frames} dropped  ·  "
            f"{metrics.hands_detected} hand{'s' if metrics.hands_detected != 1 else ''}"
        )
        self.diagnostics.setToolTip(
            f"Camera FPS       {metrics.camera_fps:5.1f}\n"
            f"Recognition FPS  {metrics.recognition_fps:5.1f}\n"
            f"Latency          {metrics.latency_ms:5.1f} ms\n"
            f"CPU              {metrics.cpu_percent:5.1f}%\n"
            f"RAM              {metrics.memory_mb:5.1f} MB\n"
            f"Dropped frames   {metrics.dropped_frames:5d}\n"
            f"Hands detected   {metrics.hands_detected:5d}\n"
            f"Left hand        {metrics.left_hand_pose or '-'}\n"
            f"Right hand       {metrics.right_hand_pose or '-'}\n"
            f"Motion gesture   {metrics.motion_gesture}\n"
            f"Motion source    {metrics.motion_source}\n"
            f"Overlay FPS      {overlay_metrics.render_fps:5.1f}\n"
            f"Overlay CPU      {overlay_metrics.paint_cpu_percent:5.3f}%\n"
            f"Overlay memory   {overlay_metrics.framebuffer_kb:5.1f} KB\n"
            + self._profile_diagnostics_text()
        )

    def _profile_diagnostics_text(self) -> str:
        event = self._last_profile_event
        if event is None:
            return "Foreground app     unknown\nActive profile      Global\nMatch reason        n/a"
        name = event.match.profile.name if event.match.profile else "Global"
        app = event.foreground.executable or "unknown"
        return f"Foreground app     {app}\nActive profile      {name}\nMatch reason        {event.match.reason}"

    @pyqtSlot()
    def _poll_profile_switch(self) -> None:
        """Re-evaluate the foreground app; ``_on_profile_switch`` fires on change."""
        event = self.profile_switcher.poll()
        self._last_profile_event = event
        name = event.match.profile.name if event.match.profile else "Global"
        self.profile_status.setText(f"Active profile: {name}")

    def _on_profile_switch(self, event: ProfileSwitchEvent) -> None:
        """Fires only when the resolved profile actually changes (see ProfileSwitcher)."""
        if hasattr(self.camera, "apply_profile_settings"):
            self.camera.apply_profile_settings(event.effective_settings)

    @pyqtSlot()
    def open_settings(self) -> None:
        dialog = motion.animate_dialog(SettingsDialog(self.settings_manager.settings, self))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            settings = self.settings_manager.update(**dialog.values())
        except (OSError, TypeError, ValueError) as exc:
            logger.exception("Unable to save settings")
            QMessageBox.warning(self, "Settings were not saved", str(exc))
            return
        self._apply_settings(settings)
        self.statusBar().showMessage("Settings saved", 4000)
        self.toast.show_message("Settings saved")

    def _apply_settings(self, settings) -> None:
        """Apply saved settings to the running app without a restart."""
        motion.set_reduced_motion(settings.reduce_motion)
        self.auto_pause.configure(self._pause_rules(settings))
        if self._services_started and hasattr(self.clap_detector, "is_listening"):
            if settings.double_clap_enabled and not self.clap_detector.is_listening:
                self.clap_detector.start()
            elif not settings.double_clap_enabled and self.clap_detector.is_listening:
                self.clap_detector.stop()
                self._microphone_stopped()
        if hasattr(self.camera, "update_settings"):
            self.camera.update_settings(settings)
        if hasattr(self.clap_detector, "configure"):
            self.clap_detector.configure(
                device=settings.microphone_device,
                min_peak=settings.clap_min_peak,
                rms_threshold=settings.clap_rms_threshold,
                noise_multiplier=settings.clap_noise_multiplier,
                min_clap_separation=settings.double_clap_min_interval,
                max_clap_separation=settings.double_clap_max_interval,
            )
        self.profile_switcher.set_enabled(settings.auto_switch_profiles)
        if settings.theme != self._theme_mode:
            self._apply_theme(settings.theme)
        self.fingerprint_indicator.configure(
            settings.show_fingerprint_indicator,
            settings.fingerprint_indicator_size,
            settings.fingerprint_indicator_opacity,
            settings.fingerprint_indicator_fade_duration_ms,
        )
        self.cursor_assist_overlay.configure(
            size=settings.cursor_assist_overlay_size,
            opacity=settings.cursor_assist_overlay_opacity,
        )
        if not settings.cursor_assist_overlay_enabled:
            self.cursor_assist_overlay.hide_overlay()
        else:
            self.cursor_assist_overlay.show_overlay()

    @pyqtSlot()
    def open_templates(self) -> None:
        dialog = motion.animate_dialog(TemplatesDialog(self.template_manager, self.settings_manager.settings, self))
        if dialog.exec():
            pass
        self._poll_profile_switch()
        self.statusBar().showMessage(f"Current template: {self.template_manager.get_active_template().name}", 4000)

    @pyqtSlot()
    def open_custom_gestures(self) -> None:
        self.custom_gestures_dialog = motion.animate_dialog(CustomGesturesDialog(self.custom_gesture_store, self))
        self.custom_gestures_dialog.exec()
        if hasattr(self.camera, "update_custom_gestures"):
            self.camera.update_custom_gestures(self.custom_gesture_store.list_gestures())

    @pyqtSlot()
    def open_microphone_test(self) -> None:
        self.microphone_dialog = motion.animate_dialog(MicrophoneDialog(self.clap_detector, self.settings_manager, self))
        try:
            self.microphone_dialog.exec()
        finally:
            self.microphone_dialog = None

    @pyqtSlot()
    def open_cursor_calibration(self) -> None:
        # Calibration is driven by live fingertips, so the camera must run.
        # Start it for the wizard and restore the previous state afterwards.
        started_for_calibration = not self.activation.is_active
        if started_for_calibration:
            self.start_camera()
        self.cursor_calibration_dialog = motion.animate_dialog(CursorCalibrationDialog(self.settings_manager, self))
        self.cursor_calibration_dialog.virtual_cursor_position.connect(self._update_calibration_overlay)
        self.cursor_assist_overlay.set_state(CursorAssistState.CALIBRATION)
        self.cursor_calibration_dialog.exec()
        self.cursor_assist_overlay.set_state(CursorAssistState.IDLE)
        if self.settings_manager.settings.cursor_reach_calibration is None:
            self.cursor_assist_overlay.hide_overlay()
        if started_for_calibration and not self._exit_requested:
            self.stop_camera()

    @staticmethod
    def _mirror_fingertips(fingertips: object) -> object:
        """Convert camera-space x to the user's point of view (selfie view).

        Webcam frames are not mirrored, so a hand moving to the user's left
        increases landmark x. Cursor reach is expressed from the user's view.
        """
        if not isinstance(fingertips, list):
            return fingertips
        return [(1.0 - float(x), float(y)) for x, y in fingertips]

    @pyqtSlot(object)
    def _feed_cursor_calibration(self, fingertips: object) -> None:
        fingertips = self._mirror_fingertips(fingertips)
        dialog = getattr(self, "cursor_calibration_dialog", None)
        if dialog is not None and dialog.isVisible():
            dialog.feed_fingertips(fingertips)
            return
        self._feed_cursor_assist(fingertips)

    @pyqtSlot(int, int, bool)
    def _update_calibration_overlay(self, global_x: int, global_y: int, snapped: bool) -> None:
        """Display the calibration-only cursor mapping, never the OS cursor."""
        self.cursor_assist_overlay.set_state(CursorAssistState.CALIBRATION)
        self.cursor_assist_overlay.update_position(global_x, global_y)

    def _feed_cursor_assist(self, fingertips: object) -> None:
        """Render the calibrated MediaPipe position without moving the OS cursor."""
        settings = self.settings_manager.settings
        profile = settings.cursor_reach_calibration
        if not settings.cursor_assist_overlay_enabled or profile is None:
            self.cursor_assist_overlay.hide_overlay()
            return
        if not isinstance(fingertips, list) or not fingertips:
            return
        try:
            if self.cursor_assist_overlay.state == CursorAssistState.IDLE:
                self.cursor_assist_overlay.set_state(CursorAssistState.TRACKING)
            hand_x, hand_y = fingertips[0]
            signature = (tuple(sorted(profile.items())), settings.cursor_dead_zone_percent, settings.cursor_smoothing)
            if self._cursor_mapper is None or signature != self._cursor_mapper_signature:
                reach = CursorReach(
                    profile["center_x"], profile["center_y"], profile["left"], profile["right"],
                    profile["top"], profile["bottom"], settings.cursor_dead_zone_percent,
                )
                self._cursor_mapper = SmoothedCursorReachMapper(reach, settings.cursor_smoothing)
                self._cursor_mapper_signature = signature
            target = MonitorLayout.current().target(settings.cursor_target_mode, settings.cursor_target_monitor_id)
            x, y = self._cursor_mapper.map(float(hand_x), float(hand_y), time.monotonic(), target.width, target.height)
            self.cursor_assist_overlay.update_position(target.x + x, target.y + y)
        except (KeyError, TypeError, ValueError, RuntimeError):
            logger.exception("Unable to update cursor assist overlay")
            self.cursor_assist_overlay.hide_overlay()

    def _restore_cursor_tracking(self) -> None:
        if self.cursor_assist_overlay.state != CursorAssistState.CALIBRATION:
            self.cursor_assist_overlay.set_state(CursorAssistState.TRACKING)

    @pyqtSlot(object)
    def _feed_cursor_calibration_frame(self, frame: object) -> None:
        dialog = getattr(self, "cursor_calibration_dialog", None)
        if dialog is not None and dialog.isVisible() and hasattr(frame, "shape"):
            # Mirror to match the user-view fingertip coordinates.
            dialog.feed_frame(frame[:, ::-1])

    @pyqtSlot()
    def open_help(self) -> None:
        motion.animate_dialog(HelpDialog(self)).exec()

    @pyqtSlot(object)
    def _feed_custom_gesture_hands(self, hands: object) -> None:
        if hasattr(self, "custom_gestures_dialog"):
            self.custom_gestures_dialog.feed_hands(hands)

    @pyqtSlot()
    def toggle_theme(self) -> None:
        mode = "light" if self._theme_mode == "dark" else "dark"
        self.settings_manager.update(theme=mode)
        self._apply_theme(mode)

    def _sync_theme_button(self) -> None:
        self.theme_button.setText("Light" if self._theme_mode == "dark" else "Dark")

    @pyqtSlot()
    def toggle_recognition(self) -> None:
        self.user_stop() if self.activation.is_active else self.user_start()

    @pyqtSlot()
    def _handle_clap_toggle(self) -> None:
        logger.info("Double-clap activation toggle received on UI thread")
        if getattr(self, "microphone_dialog", None) is not None:
            # The calibration wizard's final step is a test double-clap; it
            # must not also switch recognition on or off.
            logger.info("Double-clap toggle ignored while microphone calibration is open")
            return
        self.toggle_recognition()

    @pyqtSlot(str)
    def _clap_error(self, message: str) -> None:
        logger.warning("Clap detection unavailable: %s", message)
        self.microphone_status.setText("●  MICROPHONE UNAVAILABLE")
        set_tone(self.microphone_status, "error")

    @pyqtSlot()
    def _microphone_started(self) -> None:
        self.microphone_status.setText("●  MICROPHONE READY")
        set_tone(self.microphone_status, "live")

    @pyqtSlot()
    def _microphone_stopped(self) -> None:
        self.microphone_status.setText("●  MICROPHONE OFF")
        set_tone(self.microphone_status, "idle")

    @pyqtSlot(bool)
    def _set_startup_enabled(self, enabled: bool) -> None:
        try:
            self.settings_manager.set_startup_enabled(enabled)
        except OSError as exc:
            logger.exception("Unable to update Windows startup setting")
            self.startup_action.blockSignals(True)
            self.startup_action.setChecked(not enabled)
            self.startup_action.blockSignals(False)
            QMessageBox.warning(self, "Startup setting", str(exc))

    @pyqtSlot(QSystemTrayIcon.ActivationReason)
    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_from_tray()

    @pyqtSlot()
    def open_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _set_tray_active(self, active: bool) -> None:
        self.tray_icon.setIcon(self._active_icon if active else self._paused_icon)
        self.tray_icon.setToolTip(f"HandWave — {'Active' if active else 'Paused'}")
        self.enable_action.setEnabled(not active)
        self.disable_action.setEnabled(active)

    def _set_status(self, text: str, tone: str, animate: bool = False) -> None:
        self.status_text.setText(text)
        set_tone(self.status_dot, tone)
        self._status_pulse.stop()
        self._status_effect.setOpacity(1.0)
        if animate:
            self._status_pulse.start()

    @pyqtSlot()
    def start_camera(self) -> None:
        if self._camera_error_pending:
            return
        self._set_status("Starting recognition…", "pending", animate=True)
        self.camera_status.setText("●  CAMERA STARTING")
        set_tone(self.camera_status, "pending")
        self.start_button.setEnabled(False)
        self._camera_starting = True
        self.camera.start_camera()

    @pyqtSlot()
    def stop_camera(self) -> None:
        self.start_button.setEnabled(False)
        self._set_status("Pausing recognition…", "pending", animate=True)
        self.camera.stop_camera()

    @pyqtSlot()
    def _camera_started(self) -> None:
        self._camera_starting = False
        self.activation.activate()
        self._set_status("Recognition Enabled", "live")
        self.start_button.setEnabled(True)
        self.start_button.setText("Disable Recognition")
        self._set_tray_active(True)
        self.camera_status.setText("●  CAMERA LIVE")
        set_tone(self.camera_status, "live")
        self.recognition_status.setText("●  RECOGNITION ACTIVE")
        set_tone(self.recognition_status, "live")
        self.diagnostics_page.set_pipeline_active(True)
        self._poll_profile_switch()
        self._profile_poll_timer.start()

    @pyqtSlot()
    def _camera_stopped(self) -> None:
        self._camera_starting = False
        self._profile_poll_timer.stop()
        self.activation.deactivate()
        self.preview.clear()
        self.preview.setText("CAMERA PREVIEW PAUSED")
        self.fingerprint_indicator.update_fingertips([])
        self.cursor_assist_overlay.set_state(CursorAssistState.IDLE)
        self.cursor_assist_overlay.hide_overlay()
        camera_failed = self._camera_error_pending
        self._camera_error_pending = False
        self._set_status("Camera unavailable" if camera_failed else "Recognition Disabled", "error" if camera_failed else "idle")
        self.start_button.setEnabled(True)
        self.start_button.setText("Retry Camera" if camera_failed else "Enable Recognition")
        self._set_tray_active(False)
        self.camera_status.setText("●  CAMERA ERROR" if camera_failed else "●  CAMERA IDLE")
        set_tone(self.camera_status, "error" if camera_failed else "idle")
        self.recognition_status.setText("●  RECOGNITION OFF")
        set_tone(self.recognition_status, "idle")
        self.update_confidence(0.0)
        self.diagnostics_page.set_pipeline_active(False)
        self.diagnostics_page.update_gesture("Unknown", "Unknown")
        if self._auto_paused and not camera_failed:
            self._show_auto_paused(self._pause_reason)
        if self._exit_requested:
            self._complete_exit()

    @pyqtSlot(str)
    def _camera_error(self, message: str) -> None:
        logger.error("Camera error: %s", message)
        self._camera_starting = False
        self._profile_poll_timer.stop()
        self._camera_error_pending = True
        self.cursor_assist_overlay.set_state(CursorAssistState.IDLE)
        self.cursor_assist_overlay.hide_overlay()
        self.activation.deactivate()
        self._set_status("Camera unavailable", "error")
        self.start_button.setEnabled(False)
        self._set_tray_active(False)
        self.camera_status.setText("●  CAMERA ERROR")
        set_tone(self.camera_status, "error")
        self.recognition_status.setText("●  RECOGNITION OFF")
        set_tone(self.recognition_status, "idle")
        self.diagnostics_page.set_pipeline_active(False)
        QMessageBox.warning(self, "Camera error", message)

    @pyqtSlot(object)
    def update_frame(self, frame: object) -> None:
        """Queue a camera frame for the preview; only the newest one is drawn."""
        if frame is None:
            return
        self._pending_frame = frame
        if not self._frame_scheduled:
            self._frame_scheduled = True
            QTimer.singleShot(0, self._render_pending_frame)

    def _preview_visible(self) -> bool:
        return (
            self.isVisible()
            and not self.isMinimized()
            and self.pages.currentIndex() == 0
            and self.preview.width() > 1
        )

    def _render_pending_frame(self) -> None:
        self._frame_scheduled = False
        frame, self._pending_frame = self._pending_frame, None
        if frame is None or not self._preview_visible():
            return  # hidden, minimised or on another page: skip the work entirely
        height, width = frame.shape[:2]
        # Wrap the BGR frame directly (no colour conversion or copy); it stays
        # referenced by `frame` until painting below completes.
        image = QImage(frame.data, width, height, frame.strides[0], QImage.Format.Format_BGR888)
        target = self.preview.size()
        # Cover-fit: scale to fill the rounded frame, centre-crop the overflow,
        # clip to the frame's radius. One painter pass, cached clip path.
        scale = max(target.width() / width, target.height() / height)
        shown_w, shown_h = width * scale, height * scale
        key = (target.width(), target.height())
        if self._preview_clip is None or self._preview_clip[0] != key:
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(0.5, 0.5, target.width() - 1, target.height() - 1), 12, 12)
            self._preview_clip = (key, clip)
        framed = QPixmap(target)
        framed.fill(Qt.GlobalColor.transparent)
        painter = QPainter(framed)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setClipPath(self._preview_clip[1])
        painter.drawImage(
            QRectF((target.width() - shown_w) / 2, (target.height() - shown_h) / 2, shown_w, shown_h), image
        )
        painter.end()
        self.preview.setPixmap(framed)
        self.fingerprint_indicator.set_source_size(width, height)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "fingerprint_indicator"):
            self.fingerprint_indicator.sync_geometry()
        if not hasattr(self, "_content_layout"):
            return
        direction = (
            QBoxLayout.Direction.TopToBottom
            if event.size().width() < 980
            else QBoxLayout.Direction.LeftToRight
        )
        if self._content_layout.direction() != direction:
            self._content_layout.setDirection(direction)
            # Side-by-side: a vertical hairline divides the columns. Stacked:
            # the sidebar becomes a section under the camera with a top rule.
            stacked = direction == QBoxLayout.Direction.TopToBottom
            set_tone(self._sidebar, "stacked" if stacked else "side")
            self._sidebar.layout().setContentsMargins(0, 28, 0, 0) if stacked else self._sidebar.layout().setContentsMargins(32, 4, 0, 0)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._exit_requested:
            event.accept()
            return
        if self.settings_manager.settings.exit_on_close:
            event.ignore()
            self.exit_application()
            return
        logger.info("Hiding HandWave in the system tray")
        event.ignore()
        self.hide()

    @pyqtSlot()
    def exit_application(self) -> None:
        if self._exit_requested:
            return
        self._exit_requested = True
        logger.info("Exiting HandWave")
        self._profile_poll_timer.stop()
        self.auto_pause.stop()
        self.camera.stop_camera()
        self.clap_detector.stop()
        self.cursor_assist_overlay.hide_overlay()
        self.activation.deactivate()
        self.tray_icon.hide()
        self.hide()
        if not getattr(self.camera, "is_running", False):
            self._complete_exit()

    def _complete_exit(self) -> None:
        """Quit only after asynchronous camera workers have terminated."""
        app = QApplication.instance()
        if app is not None:
            app.quit()
