"""Lightweight, touchless fingertip-contact visualization for the camera preview."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QTimer, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget


@dataclass
class _Contact:
    position: QPointF
    opacity: float
    seen: bool = True


class FingerprintIndicator(QWidget):
    """Draw smoothed opaque dots for tracked index fingertips.

    The overlay is intentionally parented to the camera preview, so normalized
    camera coordinates map only to that visual interaction area. It represents
    a tracked fingertip in the image, never an actual touch event.
    """

    SMOOTHING = 0.35
    FRAME_INTERVAL_MS = 16

    def __init__(
        self,
        parent: QWidget,
        enabled: bool = True,
        size: int = 18,
        opacity: float = 0.9,
        fade_duration_ms: int = 250,
    ) -> None:
        super().__init__(parent)
        self._contacts: list[_Contact] = []
        self._enabled = enabled
        self._size = size
        self._target_opacity = opacity
        self._fade_duration_ms = fade_duration_ms
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._advance_fade)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setGeometry(parent.rect())
        self.raise_()
        self.setVisible(enabled)

    @property
    def contact_positions(self) -> tuple[QPointF, ...]:
        """Current logical-pixel positions, exposed for deterministic UI tests."""
        return tuple(contact.position for contact in self._contacts)

    @property
    def contact_opacities(self) -> tuple[float, ...]:
        """Current opacity values, used to verify fade behavior without pixels."""
        return tuple(contact.opacity for contact in self._contacts)

    def configure(self, enabled: bool, size: int, opacity: float, fade_duration_ms: int) -> None:
        self._enabled = enabled
        self._size = size
        self._target_opacity = opacity
        self._fade_duration_ms = fade_duration_ms
        self.setVisible(enabled)
        if not enabled:
            self._contacts.clear()
            self._timer.stop()
        self.update()

    def update_fingertips(self, fingertips: list[tuple[float, float]]) -> None:
        """Accept up to two normalized camera points and lightly smooth them."""
        if not self._enabled:
            return
        points = [self.map_normalized_point(x, y) for x, y in fingertips[:2]]
        for contact in self._contacts:
            contact.seen = False
        for index, point in enumerate(points):
            if index >= len(self._contacts):
                self._contacts.append(_Contact(point, self._target_opacity))
                continue
            contact = self._contacts[index]
            contact.position = QPointF(
                contact.position.x() + self.SMOOTHING * (point.x() - contact.position.x()),
                contact.position.y() + self.SMOOTHING * (point.y() - contact.position.y()),
            )
            contact.opacity = self._target_opacity
            contact.seen = True
        self._timer.start()
        self.update()

    def set_source_size(self, width: int, height: int) -> None:
        """Declare the camera frame size when the preview crops it to fill (cover fit)."""
        self._source_size = (width, height) if width > 0 and height > 0 else None

    def map_normalized_point(self, x: float, y: float) -> QPointF:
        """Map normalized camera coordinates into Qt logical preview pixels.

        Without a source size the frame is assumed to span the preview. With
        one, the frame is scaled to cover the preview and centre-cropped,
        matching ``MainWindow.update_frame``.
        """
        x, y = max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
        source = getattr(self, "_source_size", None)
        if source is None:
            return QPointF(x * self.width(), y * self.height())
        scale = max(self.width() / source[0], self.height() / source[1])
        shown_w, shown_h = source[0] * scale, source[1] * scale
        return QPointF(x * shown_w - (shown_w - self.width()) / 2, y * shown_h - (shown_h - self.height()) / 2)

    def sync_geometry(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.raise_()

    def _advance_fade(self) -> None:
        step = self.FRAME_INTERVAL_MS / max(1, self._fade_duration_ms) * self._target_opacity
        retained: list[_Contact] = []
        for contact in self._contacts:
            if not contact.seen:
                contact.opacity -= step
            if contact.opacity > 0.0:
                retained.append(contact)
        self._contacts = retained
        if not self._contacts:
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for contact in self._contacts:
            color = QColor("#5eead4")
            color.setAlphaF(max(0.0, min(1.0, contact.opacity)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            radius = self._size / 2
            painter.drawEllipse(contact.position, radius, radius)
        painter.end()
