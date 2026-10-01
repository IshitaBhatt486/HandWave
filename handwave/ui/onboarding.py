"""First-run walkthrough for HandWave."""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class OnboardingDialog(QDialog):
    completed = pyqtSignal()

    PAGES = (
        ("Welcome to HandWave", "Control media naturally with hand gestures and motion—without touching your keyboard."),
        ("Fast, reliable recognition", "Hold a gesture briefly until it becomes stable. Pinch vertically for volume, or swipe for tracks."),
        ("Always within reach", "Close the window to keep recognition available in the system tray."),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to HandWave")
        self.setModal(True)
        self.setFixedSize(560, 340)
        self.setObjectName("onboarding")
        self.pages = QStackedWidget()
        for index, (title, body) in enumerate(self.PAGES, start=1):
            page = QWidget()
            layout = QVBoxLayout(page)
            eyebrow = QLabel(f"GETTING STARTED  ·  {index} OF {len(self.PAGES)}")
            eyebrow.setObjectName("eyebrow")
            heading = QLabel(title)
            heading.setObjectName("onboardingTitle")
            copy = QLabel(body)
            copy.setObjectName("onboardingCopy")
            copy.setWordWrap(True)
            layout.addStretch()
            layout.addWidget(eyebrow)
            layout.addWidget(heading)
            layout.addWidget(copy)
            layout.addStretch()
            self.pages.addWidget(page)

        self.back_button = QPushButton("Back")
        self.skip_button = QPushButton("Skip")
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("primaryButton")
        self.back_button.setEnabled(False)
        controls = QHBoxLayout()
        controls.addWidget(self.skip_button)
        controls.addStretch()
        controls.addWidget(self.back_button)
        controls.addWidget(self.next_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.addWidget(self.pages, 1)
        layout.addLayout(controls)
        self.back_button.clicked.connect(self._back)
        self.next_button.clicked.connect(self._next)
        self.skip_button.clicked.connect(self.finish)

        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        self._fade = QPropertyAnimation(effect, b"opacity", self)
        self._fade.setDuration(220)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._fade.start()

    def _back(self) -> None:
        self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1))
        self._sync_controls()

    def _next(self) -> None:
        if self.pages.currentIndex() == self.pages.count() - 1:
            self.finish()
            return
        self.pages.setCurrentIndex(self.pages.currentIndex() + 1)
        self._sync_controls()

    def _sync_controls(self) -> None:
        self.back_button.setEnabled(self.pages.currentIndex() > 0)
        self.next_button.setText("Get Started" if self.pages.currentIndex() == self.pages.count() - 1 else "Next")

    def finish(self) -> None:
        self.completed.emit()
        self.accept()
