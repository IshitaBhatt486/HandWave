"""Small, cheap motion primitives for HandWave's micro-interactions.

Performance rules every helper follows:

* Animations are short (120–280 ms) and run on Qt's animation timer; nothing
  blocks the event loop.
* No graphics effect stays attached to a live widget. Opacity effects are
  removed when an animation ends, and page/theme transitions fade a
  *snapshot* overlay instead of the live camera page, so the preview never
  pays for off-screen compositing.
* ``set_reduced_motion(True)`` turns every helper into an instant change.
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QTimer,
    QVariantAnimation,
    Qt,
)
from PyQt6 import sip
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QListWidgetItem, QPushButton, QWidget

_reduced = False
EASE = QEasingCurve.Type.OutCubic


def set_reduced_motion(enabled: bool) -> None:
    global _reduced
    _reduced = bool(enabled)


def reduced_motion() -> bool:
    return _reduced


def _keep(owner: QObject, attribute: str, animation) -> None:
    """Hold a reference so the animation is not garbage-collected mid-flight."""
    previous = getattr(owner, attribute, None)
    if previous is not None:
        try:
            previous.stop()
        except RuntimeError:
            pass
    setattr(owner, attribute, animation)


# ------------------------------------------------------------- transitions

def crossfade(widget: QWidget, duration: int = 220) -> None:
    """Fade from a snapshot of ``widget`` to whatever it shows next.

    Call immediately *before* changing the widget (switching page, theme...).
    """
    if _reduced or not widget.isVisible() or widget.width() < 2:
        return
    snapshot = widget.grab()
    overlay = QLabel(widget)
    overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    overlay.setPixmap(snapshot)
    overlay.setGeometry(widget.rect())
    overlay.show()
    overlay.raise_()
    effect = QGraphicsOpacityEffect(overlay)
    overlay.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", overlay)
    animation.setDuration(duration)
    animation.setStartValue(1.0)
    animation.setEndValue(0.0)
    animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
    animation.finished.connect(overlay.deleteLater)
    animation.start()


def emphasize(widget: QWidget, duration: int = 260, start: float = 0.25) -> None:
    """A soft fade-up that marks a changed value (e.g. a new gesture)."""
    if _reduced:
        return
    previous = getattr(widget, "_hw_emphasis", None)
    if previous is not None and not sip.isdeleted(previous):
        previous.stop()
    animation = _Emphasis(widget, duration, start)
    widget._hw_emphasis = animation
    animation.start()


class _Emphasis(QPropertyAnimation):
    """Opacity fade-up that removes its effect when done.

    The cleanup slot is a method of this animation (a child of the widget),
    not a lambda, so Qt can never run it while the widget is being destroyed.
    """

    def __init__(self, widget: QWidget, duration: int, start: float) -> None:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        super().__init__(effect, b"opacity", widget)
        self.setDuration(duration)
        self.setStartValue(start)
        self.setEndValue(1.0)
        self.setEasingCurve(EASE)
        self.finished.connect(self._detach)

    def _detach(self) -> None:
        widget = self.parent()
        if isinstance(widget, QWidget):
            widget.setGraphicsEffect(None)  # render the label directly again


def animate_value(widget: QWidget, value: int, duration: int = 180) -> None:
    """Glide a progress bar (or any ``value`` property) to its new value."""
    current = widget.property("value")
    if _reduced or current is None or abs(int(current) - int(value)) <= 1:
        widget.setProperty("value", int(value))
        return
    animation = QPropertyAnimation(widget, b"value", widget)
    animation.setDuration(duration)
    animation.setStartValue(int(current))
    animation.setEndValue(int(value))
    animation.setEasingCurve(EASE)
    _keep(widget, "_hw_value_animation", animation)
    animation.start()


def fade_in_item(item: QListWidgetItem, color: QColor, duration: int = 320) -> None:
    """Fade a freshly inserted list row in from transparent."""
    if _reduced:
        return
    list_widget = item.listWidget()
    if list_widget is None:
        return
    fade = _RowFade(list_widget, list_widget.row(item), color, duration)
    fade.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)


class _RowFade(QVariantAnimation):
    """Fade one list row's text from transparent to ``color``.

    Safety, because rows and lists can disappear mid-animation:

    * The row is tracked by a persistent model index, never by its item: an
      evicted row deletes its QListWidgetItem (not a QObject), and touching it
      would crash. A persistent index simply becomes invalid.
    * The update slot is a method of this animation, not a lambda, so Qt never
      calls it while the animation is being destroyed with its list.
    * ``finished`` is not used: the final ``valueChanged`` already lands on 1.0.
    """

    def __init__(self, list_widget, row: int, color: QColor, duration: int) -> None:
        super().__init__(list_widget)
        self._model = list_widget.model()
        self._row = QPersistentModelIndex(self._model.index(row, 0))
        self._color = QColor(color)
        self.setDuration(duration)
        self.setStartValue(0.0)
        self.setEndValue(1.0)
        self.setEasingCurve(EASE)
        self.valueChanged.connect(self._step)
        self._step(0.0)

    def _step(self, progress) -> None:
        if sip.isdeleted(self._model) or not self._row.isValid():
            self.stop()
            return
        index = QModelIndex(self._row)
        if float(progress) >= 1.0:
            # Hand the colour back to the stylesheet; a fixed colour would stay
            # behind after a theme switch (ivory text on the ivory light theme).
            self._model.setData(index, None, Qt.ItemDataRole.ForegroundRole)
            return
        tinted = QColor(self._color)
        tinted.setAlphaF(max(0.0, float(progress)))
        self._model.setData(index, QBrush(tinted), Qt.ItemDataRole.ForegroundRole)


class _DialogEntrance(QObject):
    """Fade a window in with a short upward settle the first time it shows."""

    def __init__(self, window: QWidget, rise: int, duration: int) -> None:
        super().__init__(window)
        self._rise, self._duration, self._done = rise, duration, False

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Show and not self._done:
            self._done = True
            # A bound method of this QObject (a child of the window): Qt drops
            # the call if the window is destroyed before it runs.
            QTimer.singleShot(0, self._animate)
        return False

    def _animate(self) -> None:
        window = self.parent()
        if window is None or not window.isVisible():
            if window is not None:
                window.setWindowOpacity(1.0)
            return
        end = window.pos()
        fade = QPropertyAnimation(window, b"windowOpacity", window)
        fade.setDuration(self._duration)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(EASE)
        settle = QPropertyAnimation(window, b"pos", window)
        settle.setDuration(self._duration + 60)
        settle.setStartValue(end + QPoint(0, self._rise))
        settle.setEndValue(end)
        settle.setEasingCurve(EASE)
        window._hw_entrance = (fade, settle)
        fade.start()
        settle.start()


def animate_dialog(window: QWidget, rise: int = 10, duration: int = 200) -> QWidget:
    """Give a dialog/window a gentle entrance. Returns the window for chaining."""
    if not _reduced:
        window.setWindowOpacity(0.0)
        window.installEventFilter(_DialogEntrance(window, rise, duration))
    return window


# ---------------------------------------------------------------- widgets

class UnderlineButton(QPushButton):
    """A quiet text button whose accent underline grows in on hover."""

    accent = QColor("#c9a96e")

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._progress = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(170)
        self._animation.setEasingCurve(EASE)
        self._animation.valueChanged.connect(self._set_progress)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @classmethod
    def set_accent(cls, color: str) -> None:
        cls.accent = QColor(color)

    def _set_progress(self, value: float) -> None:
        self._progress = float(value)
        self.update()

    def _run(self, target: float) -> None:
        if _reduced:
            self._set_progress(target)
            return
        self._animation.stop()
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(target)
        self._animation.start()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._run(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._run(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._progress <= 0.01:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        metrics = self.fontMetrics()
        text_width = metrics.horizontalAdvance(self.text())
        width = text_width * self._progress
        x = (self.width() - text_width) / 2 + (text_width - width) / 2
        y = self.height() / 2 + metrics.height() / 2 + 2
        painter.setPen(QPen(self.accent, 1))
        painter.drawLine(int(x), int(y), int(x + width), int(y))
        painter.end()


class Toast(QWidget):
    """A small notification that drops in, waits, then fades away."""

    top_offset = 74

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()
        self._text = ""
        self._colors = {"surface": QColor("#1c1c1e"), "line": QColor("#2a2a2d"), "text": QColor("#ece7df"), "accent": QColor("#c9a96e")}
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._slide = QPropertyAnimation(self, b"pos", self)
        for animation in (self._fade, self._slide):
            animation.setEasingCurve(EASE)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._leave)
        self._fade.finished.connect(self._after_fade)

    def set_colors(self, surface: str, line: str, text: str, accent: str) -> None:
        self._colors = {"surface": QColor(surface), "line": QColor(line), "text": QColor(text), "accent": QColor(accent)}
        self.update()

    @property
    def text(self) -> str:
        return self._text

    def show_message(self, text: str, duration_ms: int = 3200) -> None:
        self._text = text
        metrics = self.fontMetrics()
        self.resize(metrics.horizontalAdvance(text) + 58, 40)
        parent = self.parentWidget()
        # Top centre, in the header's open space, so it never covers controls.
        end = QPoint((parent.width() - self.width()) // 2, self.top_offset)
        self.raise_()
        self.show()
        self._hide_timer.start(duration_ms)
        if _reduced:
            self.move(end)
            self._effect.setOpacity(1.0)
            return
        self._slide.stop(); self._fade.stop()
        self._slide.setDuration(260); self._slide.setStartValue(end - QPoint(0, 12)); self._slide.setEndValue(end)
        self._fade.setDuration(200); self._fade.setStartValue(self._effect.opacity() if self.isVisible() else 0.0); self._fade.setEndValue(1.0)
        self._slide.start(); self._fade.start()

    def _leave(self) -> None:
        if _reduced:
            self.hide()
            return
        self._fade.stop()
        self._fade.setDuration(260)
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _after_fade(self) -> None:
        if self._effect.opacity() <= 0.01:
            self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(self._colors["line"], 1))
        painter.setBrush(self._colors["surface"])
        painter.drawRoundedRect(rect, 20, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._colors["accent"])
        painter.drawEllipse(QRectF(20, self.height() / 2 - 3, 6, 6))
        painter.setPen(self._colors["text"])
        painter.drawText(self.rect().adjusted(36, 0, -18, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
        painter.end()
