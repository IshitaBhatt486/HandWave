"""Real-time diagnostics workspace for HandWave."""

from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget
from handwave.ui.gesture_icons import gesture_text


class DiagnosticsPage(QWidget):
    """Present live pipeline health without coupling to processing internals."""

    METRICS = (
        ("camera_fps", "Camera FPS", "0.0", "frames / second"),
        ("recognition_fps", "Recognition FPS", "0.0", "frames / second"),
        ("latency", "Latency", "0.0 ms", "capture to recognition"),
        ("cpu", "CPU", "0.0%", "process utilization"),
        ("memory", "Memory", "0.0 MB", "working set"),
        ("threads", "Active threads", "0", "pipeline workers"),
        ("cursor_overlay", "Cursor overlay", "Idle", "visual-assist state"),
        ("overlay_fps", "Overlay FPS", "0.0", "overlay renders / second"),
        ("overlay_cpu", "Overlay CPU", "0.000%", "paint-time CPU estimate"),
        ("overlay_memory", "Overlay memory", "0.0 KB", "ARGB overlay surface estimate"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._values: dict[str, QLabel] = {}

        title = QLabel("Diagnostics")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Live performance and recognition diagnostics")
        subtitle.setObjectName("pageSubtitle")

        self.live_status = QLabel("●  PAUSED")
        self.live_status.setObjectName("diagnosticsStatus")

        heading = QGridLayout()
        heading.addWidget(title, 0, 0)
        heading.addWidget(self.live_status, 0, 1)
        heading.addWidget(subtitle, 1, 0, 1, 2)
        heading.setColumnStretch(0, 1)

        metric_grid = QGridLayout()
        metric_grid.setSpacing(14)
        for index, (key, label, initial, caption) in enumerate(self.METRICS):
            card = QFrame()
            card.setObjectName("metricCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 16, 18, 16)
            name = QLabel(label.upper())
            name.setObjectName("metricName")
            value = QLabel(initial)
            value.setObjectName("metricValue")
            detail = QLabel(caption)
            detail.setObjectName("metricCaption")
            card_layout.addWidget(name)
            card_layout.addWidget(value)
            card_layout.addWidget(detail)
            metric_grid.addWidget(card, index // 3, index % 3)
            self._values[key] = value

        gesture_card = QFrame()
        gesture_card.setObjectName("metricCard")
        gesture_layout = QVBoxLayout(gesture_card)
        gesture_layout.setContentsMargins(20, 18, 20, 18)
        gesture_name = QLabel("CURRENT GESTURE")
        gesture_name.setObjectName("metricName")
        self.current_gesture = QLabel("No gesture detected")
        self.current_gesture.setObjectName("currentGestureValue")
        self.gesture_detail = QLabel("Raw  Unknown   •   Stable  Unknown")
        self.gesture_detail.setObjectName("metricCaption")
        gesture_layout.addWidget(gesture_name)
        gesture_layout.addWidget(self.current_gesture)
        gesture_layout.addWidget(self.gesture_detail)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 26)
        layout.setSpacing(18)
        layout.addLayout(heading)
        layout.addLayout(metric_grid)
        layout.addWidget(gesture_card)
        layout.addStretch()

    def update_metrics(self, metrics: object) -> None:
        self._values["camera_fps"].setText(f"{metrics.camera_fps:.1f}")
        self._values["recognition_fps"].setText(f"{metrics.recognition_fps:.1f}")
        self._values["latency"].setText(f"{metrics.latency_ms:.1f} ms")
        self._values["cpu"].setText(f"{metrics.cpu_percent:.1f}%")
        self._values["memory"].setText(f"{metrics.memory_mb:.1f} MB")
        self._values["threads"].setText(str(metrics.active_threads))

    def update_gesture(self, raw: str, stable: str) -> None:
        current = stable if stable != "Unknown" else raw
        self.current_gesture.setText(
            "No gesture detected" if current == "Unknown" else gesture_text(current)
        )
        self.gesture_detail.setText(f"Raw  {raw}   •   Stable  {stable}")

    def update_microphone(self, status: object) -> None:
        """Retain the diagnostics hook without exposing microphone/clap controls."""

    def update_cursor_overlay(self, state: object, metrics: object) -> None:
        """Show overlay-local measurements; no pipeline worker is sampled here."""
        self._values["cursor_overlay"].setText(str(getattr(state, "value", state)).replace("_", " ").title())
        self._values["overlay_fps"].setText(f"{getattr(metrics, 'render_fps', 0.0):.1f}")
        self._values["overlay_cpu"].setText(f"{getattr(metrics, 'paint_cpu_percent', 0.0):.3f}%")
        self._values["overlay_memory"].setText(f"{getattr(metrics, 'framebuffer_kb', 0.0):.1f} KB")

    def set_pipeline_active(self, active: bool) -> None:
        self.live_status.setText("●  LIVE" if active else "●  PAUSED")
        self.live_status.setStyleSheet("color: #10b981;" if active else "")
        if not active:
            self._values["threads"].setText("0")
