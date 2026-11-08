"""First-run setup: a short, friendly flow that configures HandWave.

Inspired by conversational onboarding flows (one clear question per step,
large selectable cards, visible progress, always skippable). Every choice
maps directly to a setting; nothing is applied until the user finishes.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from handwave.config.gesture_config import GESTURES
from handwave.config.settings_manager import AppSettings
from handwave.ui import motion
from handwave import platforms
from handwave.ui.theme import palette

MEDIA_GESTURES = ("Open Palm", "Thumbs Up", "Thumbs Down", "Peace Sign", "Pointing",
                  "Pointing Up", "Pointing Down", "Pointing Left", "Pointing Right")
NAVIGATION_GESTURES = tuple(gesture for gesture in GESTURES if "Swipe" in gesture)


class StepProgress(QWidget):
    """Segmented progress bar; the active segment fills smoothly."""

    def __init__(self, steps: int, parent=None) -> None:
        super().__init__(parent)
        self._steps, self._position = steps, 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(320)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._set_position)
        self.colors = (QColor("#2a2a2d"), QColor("#c9a96e"))
        self.setFixedHeight(4)

    def _set_position(self, value: float) -> None:
        self._position = float(value)
        self.update()

    def set_step(self, index: int) -> None:
        target = float(index + 1)
        if motion.reduced_motion():
            self._set_position(target)
            return
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(target)
        self._animation.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gap = 6
        width = (self.width() - gap * (self._steps - 1)) / self._steps
        track, fill = self.colors
        for index in range(self._steps):
            x = index * (width + gap)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track)
            painter.drawRoundedRect(QRectF(x, 0, width, self.height()), 2, 2)
            share = max(0.0, min(1.0, self._position - index))
            if share > 0:
                painter.setBrush(fill)
                painter.drawRoundedRect(QRectF(x, 0, width * share, self.height()), 2, 2)
        painter.end()


class OptionCard(QAbstractButton):
    """A large selectable card with animated hover and selection states."""

    def __init__(self, title: str, description: str = "", glyph: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText(title)
        self.setAccessibleName(title)
        self.setAccessibleDescription(description)
        self.description, self.glyph = description, glyph
        self._hover = 0.0
        self._check = 0.0
        self.colors = palette("dark")
        # Bound methods, not lambdas: Qt drops these connections automatically
        # when the card is destroyed, so no callback can reach a dead widget.
        self._hover_animation = self._make_animation(self._on_hover_value)
        self._check_animation = self._make_animation(self._on_check_value)
        self.toggled.connect(self._on_toggled)
        self.setMinimumHeight(84 if description else 58)

    def _make_animation(self, callback) -> QVariantAnimation:
        animation = QVariantAnimation(self)
        animation.setDuration(180)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(callback)
        return animation

    def _on_hover_value(self, value: float) -> None:
        self._set("_hover", value)

    def _on_check_value(self, value: float) -> None:
        self._set("_check", value)

    def _on_toggled(self, checked: bool) -> None:
        self._run(self._check_animation, "_check", 1.0 if checked else 0.0)

    def _set(self, name: str, value: float) -> None:
        setattr(self, name, float(value))
        self.update()

    def _run(self, animation: QVariantAnimation, name: str, target: float) -> None:
        if motion.reduced_motion():
            self._set(name, target)
            return
        animation.stop()
        animation.setStartValue(getattr(self, name))
        animation.setEndValue(target)
        animation.start()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._run(self._hover_animation, "_hover", 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._run(self._hover_animation, "_hover", 0.0)
        super().leaveEvent(event)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(260, self.minimumHeight())

    @staticmethod
    def _mix(a: QColor, b: QColor, t: float) -> QColor:
        return QColor(
            round(a.red() + (b.red() - a.red()) * t),
            round(a.green() + (b.green() - a.green()) * t),
            round(a.blue() + (b.blue() - a.blue()) * t),
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        c = {key: QColor(value) for key, value in self.colors.items() if not value.startswith("rgba")}
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        surface = self._mix(c["bg"], c["surface"], 0.6 + 0.4 * self._hover)
        accent_wash = QColor(c["accent"]); accent_wash.setAlphaF(0.08 * self._check)
        border = self._mix(self._mix(c["line_soft"], c["faint"], self._hover * 0.6), c["accent"], self._check)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(surface)
        painter.drawRoundedRect(rect, 12, 12)
        painter.setBrush(accent_wash)
        painter.drawRoundedRect(rect, 12, 12)

        left = 22
        if self.glyph:
            painter.setPen(self._mix(c["muted"], c["accent"], self._check))
            glyph_font = QFont(self.font()); glyph_font.setPointSizeF(17)
            painter.setFont(glyph_font)
            painter.drawText(QRectF(20, 0, 30, self.height()), Qt.AlignmentFlag.AlignVCenter, self.glyph)
            left = 60
        title_font = QFont(self.font()); title_font.setPointSizeF(11); title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(c["text"])
        if self.description:
            painter.drawText(QRectF(left, 16, self.width() - left - 56, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
            body = QFont(self.font()); body.setPointSizeF(9.5)
            painter.setFont(body)
            painter.setPen(c["muted"])
            painter.drawText(QRectF(left, 40, self.width() - left - 56, self.height() - 48),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, self.description)
        else:
            painter.drawText(QRectF(left, 0, self.width() - left - 56, self.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())

        # Selection indicator: a ring that fills with a check as it animates in.
        size = 18
        box = QRectF(self.width() - size - 22, (self.height() - size) / 2, size, size)
        painter.setPen(QPen(self._mix(c["faint"], c["accent"], self._check), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(box)
        if self._check > 0.01:
            inner = box.adjusted(3, 3, -3, -3)
            inner_size = inner.width() * self._check
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(c["accent"])
            painter.drawEllipse(QRectF(inner.center().x() - inner_size / 2, inner.center().y() - inner_size / 2, inner_size, inner_size))
        painter.end()


class OnboardingDialog(QDialog):
    """Set up HandWave in a few steps. ``completed`` fires on finish or skip."""

    completed = pyqtSignal()

    def __init__(self, settings: AppSettings | None = None, parent=None, startup_enabled: bool | None = None) -> None:
        super().__init__(parent)
        self.settings = settings or AppSettings()
        self.skipped = False
        self.setWindowTitle("Welcome to HandWave")
        self.setModal(True)
        self.setFixedSize(760, 600)
        self.setObjectName("onboarding")
        self._cards: list[OptionCard] = []

        self.progress = StepProgress(5)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._welcome_page())
        self.pages.addWidget(self._gestures_page())
        self.pages.addWidget(self._camera_page())
        self.pages.addWidget(self._activation_page())
        self.pages.addWidget(self._privacy_page(startup_enabled))
        self.pages.addWidget(self._appearance_page())
        self.pages.addWidget(self._done_page())

        self.back_button = motion.UnderlineButton("Back")
        self.back_button.setObjectName("ghostButton")
        self.skip_button = motion.UnderlineButton("Skip setup")
        self.skip_button.setObjectName("ghostButton")
        self.next_button = QPushButton("Get started")
        self.next_button.setObjectName("primaryButton")
        self.next_button.setDefault(True)
        self.next_button.setCursor(Qt.CursorShape.PointingHandCursor)
        controls = QHBoxLayout()
        controls.addWidget(self.skip_button)
        controls.addStretch()
        controls.addWidget(self.back_button)
        controls.addSpacing(8)
        controls.addWidget(self.next_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 34, 48, 30)
        layout.setSpacing(0)
        layout.addWidget(self.progress)
        layout.addSpacing(30)
        layout.addWidget(self.pages, 1)
        layout.addSpacing(18)
        layout.addLayout(controls)

        self.back_button.clicked.connect(self._back)
        self.next_button.clicked.connect(self._next)
        self.skip_button.clicked.connect(self.skip)
        self.apply_theme(self.settings.theme)
        self._sync_controls()
        motion.animate_dialog(self, rise=14, duration=240)

    # ------------------------------------------------------------- pages
    def _page(self, eyebrow: str, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel(eyebrow); label.setObjectName("eyebrow")
        heading = QLabel(title); heading.setObjectName("onboardingTitle"); heading.setWordWrap(True)
        copy = QLabel(subtitle); copy.setObjectName("onboardingCopy"); copy.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(heading)
        layout.addWidget(copy)
        layout.addSpacing(22)
        return page, layout

    def _card(self, title: str, description: str = "", glyph: str = "", checked: bool = False) -> OptionCard:
        card = OptionCard(title, description, glyph)
        card.setChecked(checked)
        card._check = 1.0 if checked else 0.0
        self._cards.append(card)
        return card

    def _welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch()
        mark = QLabel("HandWave"); mark.setObjectName("onboardingHero"); mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Control your computer with a wave of your hand.")
        title.setObjectName("onboardingTitle"); title.setAlignment(Qt.AlignmentFlag.AlignCenter); title.setWordWrap(True)
        copy = QLabel("Let's set things up. It takes less than a minute, and you can change anything later in Settings.")
        copy.setObjectName("onboardingCopy"); copy.setAlignment(Qt.AlignmentFlag.AlignCenter); copy.setWordWrap(True)
        privacy = QLabel("Everything runs on this device. No video or audio ever leaves it.")
        privacy.setObjectName("note"); privacy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for widget in (mark, title, copy):
            layout.addWidget(widget)
            layout.addSpacing(10)
        layout.addSpacing(18)
        layout.addWidget(privacy)
        layout.addStretch()
        return page

    def _gestures_page(self) -> QWidget:
        page, layout = self._page("STEP 1 OF 5", "What should your hands control?", "Pick as many as you like.")
        enabled = self.settings.enabled_gestures
        self.media_card = self._card("Music and video", "Play, pause, skip tracks and change volume with simple hand poses.", "♫",
                                     checked=any(enabled.get(g, False) for g in MEDIA_GESTURES))
        self.navigation_card = self._card("Desktop navigation", "Swipe to switch virtual desktops and windows.", "⇄",
                                          checked=any(enabled.get(g, False) for g in NAVIGATION_GESTURES))
        layout.addWidget(self.media_card)
        layout.addSpacing(10)
        layout.addWidget(self.navigation_card)
        layout.addStretch()
        return page

    def _camera_page(self) -> QWidget:
        page, layout = self._page("STEP 2 OF 5", "Which camera should HandWave use?",
                                  "Most laptops have one built-in camera. Pick another if you use an external webcam.")
        grid = QGridLayout()
        grid.setSpacing(10)
        self.camera_group = QButtonGroup(self)
        self.camera_group.setExclusive(True)
        for index, name in enumerate(("Built-in camera", "Second camera", "Third camera")):
            card = self._card(name, checked=index == self.settings.camera_index)
            self.camera_group.addButton(card, index)
            grid.addWidget(card, 0, index)
        if self.camera_group.checkedButton() is None:
            self.camera_group.button(0).setChecked(True)
        layout.addLayout(grid)
        layout.addSpacing(16)
        self.autostart_card = self._card("Turn on the camera when HandWave opens",
                                         "Start recognising gestures right away. Turn off to start it yourself each time.",
                                         checked=self.settings.start_camera_on_launch)
        layout.addWidget(self.autostart_card)
        layout.addStretch()
        return page

    def _activation_page(self) -> QWidget:
        page, layout = self._page("STEP 3 OF 5", "Turn HandWave on and off hands-free?",
                                  "Clap twice to start or stop recognition, without touching the keyboard.")
        self.clap_card = self._card("Double-clap to toggle recognition",
                                    "Uses your microphone to detect two quick claps. Only loudness is measured; no audio is recorded or stored.",
                                    checked=self.settings.double_clap_enabled)
        layout.addWidget(self.clap_card)
        layout.addStretch()
        return page

    def _privacy_page(self, startup_enabled: bool | None) -> QWidget:
        page, layout = self._page("STEP 4 OF 5", "When should HandWave step aside?",
                                  "HandWave pauses itself and resumes automatically when the moment has passed.")
        self.camera_in_use_card = self._card("When another app uses my camera", "So your video calls and recordings get the camera.",
                                             checked=self.settings.pause_when_camera_in_use)
        self.calls_card = self._card("During calls", "Zoom, Teams, Discord, Meet and other call apps.",
                                     checked=self.settings.pause_during_calls)
        self.startup_card = self._card(
            "Start HandWave at login" if platforms.is_macos() else "Start HandWave with Windows",
            "Open quietly in the menu bar when you sign in." if platforms.is_macos() else "Open quietly in the system tray when you sign in.",
                                       checked=self.settings.startup_enabled if startup_enabled is None else startup_enabled)
        for card in (self.camera_in_use_card, self.calls_card):
            layout.addWidget(card)
            layout.addSpacing(10)
        layout.addSpacing(8)
        layout.addWidget(self.startup_card)
        layout.addStretch()
        return page

    def _appearance_page(self) -> QWidget:
        page, layout = self._page("STEP 5 OF 5", "Make it yours", "Choose a look. You can switch any time with the button in the header.")
        row = QHBoxLayout()
        row.setSpacing(10)
        self.theme_group = QButtonGroup(self)
        self.dark_card = self._card("Dark", "Warm black, champagne accents.", checked=self.settings.theme == "dark")
        self.light_card = self._card("Light", "Soft ivory, bronze accents.", checked=self.settings.theme == "light")
        for theme_id, card in enumerate((self.dark_card, self.light_card)):
            self.theme_group.addButton(card, theme_id)
            row.addWidget(card)
            card.setProperty("theme_mode", ("dark", "light")[theme_id])
            card.toggled.connect(self._on_theme_card)
        layout.addLayout(row)
        layout.addSpacing(16)
        self.motion_card = self._card("Reduce motion", "Turn off animations and transitions.", checked=self.settings.reduce_motion)
        layout.addWidget(self.motion_card)
        layout.addStretch()
        return page

    def _done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch()
        heading = QLabel("You're all set"); heading.setObjectName("onboardingHero"); heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary = QLabel(); self.summary.setObjectName("onboardingCopy"); self.summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary.setWordWrap(True)
        tip = QLabel("Tip: hold a gesture for a moment until it turns gold on the dashboard.")
        tip.setObjectName("note"); tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        layout.addSpacing(14)
        layout.addWidget(self.summary)
        layout.addSpacing(22)
        layout.addWidget(tip)
        layout.addStretch()
        return page

    # -------------------------------------------------------- behaviour
    def apply_theme(self, mode: str) -> None:
        """Preview the theme live while choosing it."""
        from handwave.ui.theme import stylesheet

        colors = palette(mode)
        self.setStyleSheet(stylesheet(mode))
        self.progress.colors = (QColor(colors["line"]), QColor(colors["accent"]))
        for card in self._cards:
            card.colors = colors
            card.update()
        motion.UnderlineButton.set_accent(colors["accent"])
        self.progress.update()

    def _on_theme_card(self, checked: bool) -> None:
        card = self.sender()
        if checked and card is not None:
            self.apply_theme(str(card.property("theme_mode")))

    def values(self) -> dict[str, object]:
        """Settings changes chosen in the flow (startup is applied separately)."""
        enabled = dict(self.settings.enabled_gestures)
        bindings = self.settings.gesture_bindings
        for group, card in ((MEDIA_GESTURES, self.media_card), (NAVIGATION_GESTURES, self.navigation_card)):
            for gesture in group:
                if gesture in enabled:
                    enabled[gesture] = card.isChecked() and bindings[gesture].type != "none"
        return {
            "enabled_gestures": enabled,
            "camera_index": max(0, self.camera_group.checkedId()),
            "start_camera_on_launch": self.autostart_card.isChecked(),
            "double_clap_enabled": self.clap_card.isChecked(),
            "pause_when_camera_in_use": self.camera_in_use_card.isChecked(),
            "pause_during_calls": self.calls_card.isChecked(),
            "theme": "light" if self.light_card.isChecked() else "dark",
            "reduce_motion": self.motion_card.isChecked(),
        }

    @property
    def startup_enabled(self) -> bool:
        return self.startup_card.isChecked()

    def _go(self, index: int) -> None:
        index = max(0, min(self.pages.count() - 1, index))
        if index == self.pages.currentIndex():
            return
        forward = index > self.pages.currentIndex()
        if index == self.pages.count() - 1:
            self._update_summary()
        motion.crossfade(self.pages, 200)
        self.pages.setCurrentIndex(index)
        page = self.pages.currentWidget()
        if not motion.reduced_motion():
            end = page.pos()
            slide = QPropertyAnimation(page, b"pos", page)
            slide.setDuration(260)
            slide.setStartValue(end + QPoint(36 if forward else -36, 0))
            slide.setEndValue(end)
            slide.setEasingCurve(QEasingCurve.Type.OutCubic)
            page._hw_slide = slide
            slide.start()
        self._sync_controls()

    def _back(self) -> None:
        self._go(self.pages.currentIndex() - 1)

    def _next(self) -> None:
        if self.pages.currentIndex() == self.pages.count() - 1:
            self.finish()
            return
        self._go(self.pages.currentIndex() + 1)

    def _sync_controls(self) -> None:
        index, last = self.pages.currentIndex(), self.pages.count() - 1
        self.back_button.setVisible(0 < index < last)
        self.skip_button.setVisible(index < last)
        self.next_button.setText("Get started" if index == 0 else "Finish" if index == last else "Continue")
        self.progress.set_step(min(index, 5) - 1)  # step N fills N segments
        self.progress.setVisible(0 < index < last)

    def _update_summary(self) -> None:
        values = self.values()
        controls = [name for name, on in (("media", self.media_card.isChecked()), ("desktop navigation", self.navigation_card.isChecked())) if on]
        lines = [
            f"Gestures control {' and '.join(controls)}." if controls else "All gestures are off for now. Turn them on in Settings.",
            "The camera turns on when HandWave opens." if values["start_camera_on_launch"] else "Start the camera from the dashboard when you need it.",
            "Clap twice to turn recognition on or off." if values["double_clap_enabled"] else "Double-clap is off.",
        ]
        pauses = [text for text, on in (("another app uses the camera", values["pause_when_camera_in_use"]), ("you're in a call", values["pause_during_calls"])) if on]
        if pauses:
            lines.append(f"HandWave pauses when {' or '.join(pauses)}.")
        self.summary.setText("\n".join(lines))

    def skip(self) -> None:
        """Keep current settings and close, like the final step but without changes."""
        self.skipped = True
        self.completed.emit()
        self.accept()

    def finish(self) -> None:
        self.completed.emit()
        self.accept()
