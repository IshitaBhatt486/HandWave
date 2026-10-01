"""Card-based, in-app user guide."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QFrame, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget


class HelpDialog(QDialog):
    """A concise reference that stays available while using HandWave."""

    CARDS = (
        ("1. Start recognition", "Select Enable Recognition. The button changes to Disable Recognition when the camera is live."),
        ("2. Use gestures", "Hold a static gesture briefly. Point up, down, left, or right; swipe in the same directions for motion controls."),
        ("3. Customize actions", "Open Settings > Gestures & Actions to enable gestures and choose media keys, hotkeys, mouse actions, or text."),
        ("4. Background and exit", "Closing normally keeps HandWave in the tray. Enable Settings > General > Exit HandWave when I close the window to fully terminate it."),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("HandWave Help")
        self.setMinimumSize(560, 520)
        self.setObjectName("helpDialog")
        heading = QLabel("How to use HandWave")
        heading.setObjectName("helpTitle")
        subtitle = QLabel("A quick guide to recognition, gestures, and controls.")
        subtitle.setObjectName("helpSubtitle")
        cards = QWidget()
        cards_layout = QVBoxLayout(cards)
        cards_layout.setContentsMargins(4, 4, 4, 4)
        cards_layout.setSpacing(10)
        for title, body in self.CARDS:
            card = QFrame()
            card.setObjectName("helpCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 13, 16, 13)
            title_label = QLabel(title); title_label.setObjectName("helpCardTitle")
            body_label = QLabel(body); body_label.setObjectName("helpCardBody"); body_label.setWordWrap(True)
            card_layout.addWidget(title_label); card_layout.addWidget(body_label)
            cards_layout.addWidget(card)
        cards_layout.addStretch()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(cards)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.addWidget(heading); layout.addWidget(subtitle); layout.addWidget(scroll, 1); layout.addWidget(close)
