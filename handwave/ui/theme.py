"""HandWave's visual language: one palette per theme and one stylesheet.

Minimal and quiet: a warm near-black (or ivory) canvas, hairline rules
instead of boxes, light display type, generous space, and a single
champagne/bronze accent reserved for what is live or actionable.
Widgets express state through a ``tone`` property ("idle", "live",
"pending", "error") rather than inline colours, so both themes stay
consistent.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0e0e0f", "surface": "#151516", "raised": "#1c1c1e",
        "line": "#2a2a2d", "line_soft": "#1f1f22",
        "text": "#ece7df", "muted": "#948e84", "faint": "#5f5b54",
        "accent": "#c9a96e", "accent_hover": "#d9bd8a", "accent_press": "#b39257", "on_accent": "#15120c",
        "accent_soft": "rgba(201, 169, 110, 0.10)",
        "pending": "#a89371", "error": "#d4907f", "preview": "#09090a",
    },
    "light": {
        "bg": "#f6f3ee", "surface": "#fcfaf6", "raised": "#eee9e1",
        "line": "#ddd6ca", "line_soft": "#e9e3d9",
        "text": "#1c1a17", "muted": "#776f63", "faint": "#a79f92",
        "accent": "#9c7a3c", "accent_hover": "#876830", "accent_press": "#755a29", "on_accent": "#fcfaf6",
        "accent_soft": "rgba(156, 122, 60, 0.10)",
        "pending": "#a38a5c", "error": "#b5654f", "preview": "#ebe5db",
    },
}

# Windows (Segoe) first, then macOS (San Francisco via Qt's system-font alias).
DISPLAY_FONT = "'Segoe UI Variable Display', 'Segoe UI Light', 'Segoe UI', '.AppleSystemUIFont', 'Helvetica Neue'"
TEXT_FONT = "'Segoe UI Variable Text', 'Segoe UI', '.AppleSystemUIFont', 'Helvetica Neue'"
MONO_FONT = "'Cascadia Mono', 'Consolas', 'SF Mono', 'Menlo'"


def palette(mode: str) -> dict[str, str]:
    return PALETTES["light" if mode == "light" else "dark"]


def set_tone(widget: QWidget, tone: str) -> None:
    """Apply a semantic state colour defined by the stylesheet."""
    if widget.property("tone") == tone:
        return
    widget.setProperty("tone", tone)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def _check_image(color: str) -> str:
    """A crisp checkmark PNG for checkbox indicators (generated once, cached)."""
    folder = Path(tempfile.gettempdir()) / "handwave-theme"
    path = folder / f"check-{color.strip('#')}.png"
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        pixmap = QPixmap(28, 28)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        tick = QPainterPath(QPointF(7, 14.5))
        tick.lineTo(12, 19.5)
        tick.lineTo(21, 9)
        painter.drawPath(tick)
        painter.end()
        pixmap.save(str(path))
    return path.as_posix()


def stylesheet(mode: str = "dark") -> str:
    p = palette(mode)
    check = _check_image(p["on_accent"])
    return f"""
        /* ---------- canvas & type ---------- */
        QMainWindow, QDialog, QMessageBox {{ background: {p['bg']}; }}
        QWidget {{ background: {p['bg']}; color: {p['text']}; font-family: {TEXT_FONT}; font-size: 13px; }}
        QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
        QToolTip {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['line']}; padding: 6px 8px; }}

        /* ---------- header ---------- */
        QLabel#brand {{ font-family: {DISPLAY_FONT}; font-size: 30px; font-weight: 300; letter-spacing: 1px; }}
        QLabel#tagline {{ color: {p['faint']}; font-size: 11px; letter-spacing: 2px; }}
        QFrame#statusBadge {{ background: transparent; border: none; }}
        QLabel#statusText {{ color: {p['muted']}; font-size: 12px; letter-spacing: 0.5px; }}
        QLabel#statusDot {{ font-size: 9px; color: {p['faint']}; }}
        QLabel#statusDot[tone="live"] {{ color: {p['accent']}; }}
        QLabel#statusDot[tone="pending"] {{ color: {p['pending']}; }}
        QLabel#statusDot[tone="error"] {{ color: {p['error']}; }}

        /* ---------- quiet status rule ---------- */
        QFrame#statusStrip {{ background: transparent; border: none; border-top: 1px solid {p['line_soft']};
                              border-bottom: 1px solid {p['line_soft']}; }}
        QLabel#systemIndicator {{ color: {p['faint']}; font-size: 10px; font-weight: 600; letter-spacing: 1.6px; }}
        QLabel#systemIndicator[tone="live"] {{ color: {p['accent']}; }}
        QLabel#systemIndicator[tone="pending"] {{ color: {p['pending']}; }}
        QLabel#systemIndicator[tone="error"] {{ color: {p['error']}; }}

        /* ---------- workspace ---------- */
        QScrollArea#workspaceScroll, QWidget#workspace {{ background: {p['bg']}; border: none; }}
        QFrame#card {{ background: transparent; border: none; }}
        QFrame#sidebar {{ background: transparent; border: none; border-left: 1px solid {p['line_soft']}; }}
        QFrame#sidebar[tone="stacked"] {{ border-left: none; border-top: 1px solid {p['line_soft']}; }}
        QLabel#cardTitle {{ font-family: {DISPLAY_FONT}; font-size: 20px; font-weight: 300; }}
        QLabel#cardSubtitle {{ color: {p['muted']}; font-size: 12px; }}
        QLabel#privacyNotice {{ color: {p['faint']}; font-size: 11px; }}
        QLabel#preview {{ background: {p['preview']}; border: 1px solid {p['line_soft']}; border-radius: 12px;
                          color: {p['faint']}; font-size: 12px; letter-spacing: 1.5px; }}
        QLabel#sectionLabel {{ color: {p['faint']}; font-size: 10px; font-weight: 600; letter-spacing: 2px; }}
        QLabel#liveGesture {{ font-family: {DISPLAY_FONT}; font-size: 28px; font-weight: 300; color: {p['text']}; }}
        QLabel#liveGesture[tone="idle"] {{ color: {p['faint']}; }}
        QLabel#liveGestureDetail, QLabel#confidenceLabel {{ color: {p['muted']}; font-size: 12px; }}
        QProgressBar {{ background: {p['line_soft']}; border: none; border-radius: 2px; color: {p['muted']};
                        text-align: right; font-size: 11px; }}
        QProgressBar::chunk {{ background: {p['accent']}; border-radius: 2px; }}
        QProgressBar#confidenceBar {{ border-radius: 1px; }}
        QProgressBar#confidenceBar::chunk {{ border-radius: 1px; }}
        QListWidget#activityList {{ background: transparent; border: none; outline: none; color: {p['text']}; }}
        QListWidget#activityList::item {{ padding: 9px 0; border-bottom: 1px solid {p['line_soft']}; }}
        QListWidget#activityList::item:selected {{ background: {p['accent_soft']}; color: {p['text']}; }}
        QLabel#diagnostics {{ color: {p['muted']}; font-family: {MONO_FONT}; font-size: 11px; line-height: 150%; }}

        /* ---------- buttons ---------- */
        QPushButton {{ background: transparent; color: {p['text']}; border: 1px solid {p['line']};
                       border-radius: 6px; padding: 9px 18px; font-size: 12px; }}
        QPushButton:hover {{ border-color: {p['faint']}; }}
        QPushButton:pressed {{ background: {p['raised']}; }}
        QPushButton:disabled {{ color: {p['faint']}; border-color: {p['line_soft']}; }}
        QPushButton:default {{ border-color: {p['accent']}; color: {p['accent']}; }}
        QPushButton#primaryButton {{ background: {p['accent']}; color: {p['on_accent']}; border: 1px solid {p['accent']};
                                     font-weight: 600; letter-spacing: 0.4px; padding: 10px 22px; }}
        QPushButton#primaryButton:hover {{ background: {p['accent_hover']}; border-color: {p['accent_hover']}; }}
        QPushButton#primaryButton:pressed {{ background: {p['accent_press']}; }}
        QPushButton#primaryButton:disabled {{ background: {p['raised']}; color: {p['faint']}; border-color: {p['raised']}; }}
        QPushButton#ghostButton, QPushButton#themeButton, QPushButton#helpButton {{
            border: none; color: {p['muted']}; padding: 8px 10px; }}
        QPushButton#ghostButton:hover, QPushButton#themeButton:hover, QPushButton#helpButton:hover {{ color: {p['text']}; }}
        QPushButton#ghostButton:pressed, QPushButton#themeButton:pressed, QPushButton#helpButton:pressed {{
            color: {p['accent']}; background: transparent; }}

        /* ---------- page tabs ---------- */
        QTabWidget#mainPages::pane {{ border: none; background: {p['bg']}; }}
        QTabWidget#mainPages::tab-bar {{ left: 30px; }}
        QTabWidget#mainPages > QTabBar {{ background: {p['bg']}; }}
        QTabWidget#mainPages > QTabBar::tab {{ background: transparent; color: {p['faint']}; border: none;
            border-bottom: 1px solid transparent; padding: 16px 2px 10px 2px; margin-right: 26px;
            font-size: 11px; font-weight: 600; letter-spacing: 1.6px; }}
        QTabWidget#mainPages > QTabBar::tab:hover {{ color: {p['muted']}; }}
        QTabWidget#mainPages > QTabBar::tab:selected {{ color: {p['text']}; border-bottom-color: {p['accent']}; }}

        /* ---------- dialog tabs & forms ---------- */
        QTabWidget::pane {{ border: none; border-top: 1px solid {p['line_soft']}; background: {p['bg']}; top: -1px; }}
        QTabBar::tab {{ background: transparent; color: {p['muted']}; border: none; border-bottom: 1px solid transparent;
                        padding: 10px 12px; font-size: 12px; }}
        QTabBar::tab:hover {{ color: {p['text']}; }}
        QTabBar::tab:selected {{ color: {p['text']}; border-bottom-color: {p['accent']}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {p['surface']}; color: {p['text']};
            border: 1px solid {p['line']}; border-radius: 6px; padding: 6px 10px; min-height: 18px;
            selection-background-color: {p['accent']}; selection-color: {p['on_accent']}; }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {p['accent']}; }}
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
            color: {p['faint']}; background: transparent; border-color: {p['line_soft']}; }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox QAbstractItemView {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['line']};
            selection-background-color: {p['accent_soft']}; selection-color: {p['text']}; outline: none; padding: 4px; }}
        QCheckBox {{ spacing: 10px; }}
        QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {p['faint']}; border-radius: 4px; background: transparent; }}
        QCheckBox::indicator:hover {{ border-color: {p['accent']}; }}
        QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; image: url("{check}"); }}
        QCheckBox::indicator:disabled {{ border-color: {p['line']}; }}
        QLabel#note {{ color: {p['faint']}; font-size: 11px; }}
        QGroupBox {{ border: 1px solid {p['line_soft']}; border-radius: 10px; margin-top: 14px; padding-top: 12px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {p['muted']}; }}

        /* ---------- diagnostics page ---------- */
        QLabel#pageTitle {{ font-family: {DISPLAY_FONT}; font-size: 30px; font-weight: 300; }}
        QLabel#pageSubtitle {{ color: {p['muted']}; font-size: 12px; }}
        QLabel#diagnosticsStatus {{ color: {p['faint']}; font-size: 10px; font-weight: 600; letter-spacing: 1.6px; }}
        QLabel#diagnosticsStatus[tone="live"] {{ color: {p['accent']}; }}
        QFrame#metricCard {{ background: transparent; border: none; border-top: 1px solid {p['line']}; }}
        QLabel#metricName {{ color: {p['faint']}; font-size: 10px; font-weight: 600; letter-spacing: 1.8px; }}
        QLabel#metricValue {{ font-family: {DISPLAY_FONT}; font-size: 30px; font-weight: 300; }}
        QLabel#metricCaption {{ color: {p['faint']}; font-size: 11px; }}
        QLabel#currentGestureValue {{ font-family: {DISPLAY_FONT}; font-size: 34px; font-weight: 300; color: {p['accent']}; }}

        /* ---------- help & onboarding ---------- */
        QDialog#helpDialog, QDialog#onboarding {{ background: {p['bg']}; }}
        QLabel#helpTitle, QLabel#onboardingTitle {{ font-family: {DISPLAY_FONT}; font-size: 30px; font-weight: 300; }}
        QLabel#helpSubtitle, QLabel#helpCardBody, QLabel#onboardingCopy {{ color: {p['muted']}; font-size: 13px; }}
        QFrame#helpCard {{ background: transparent; border: none; border-top: 1px solid {p['line']}; }}
        QLabel#helpCardTitle {{ font-size: 14px; font-weight: 600; }}
        QLabel#eyebrow {{ color: {p['accent']}; font-size: 10px; font-weight: 600; letter-spacing: 2px; }}
        QLabel#onboardingHero {{ font-family: {DISPLAY_FONT}; font-size: 46px; font-weight: 300; letter-spacing: 0.5px; }}
        QLabel#note[tone="error"] {{ color: {p['error']}; }}

        /* ---------- chrome ---------- */
        QMenu {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['line']}; padding: 6px; }}
        QMenu::item {{ padding: 8px 28px 8px 12px; border-radius: 4px; background: transparent; }}
        QMenu::item:selected {{ background: {p['accent_soft']}; color: {p['text']}; }}
        QMenu::separator {{ height: 1px; background: {p['line_soft']}; margin: 6px 8px; }}
        QStatusBar {{ background: {p['bg']}; color: {p['faint']}; font-size: 11px; border-top: 1px solid {p['line_soft']}; }}
        QStatusBar::item {{ border: none; }}
        QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
        QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
        QScrollBar::handle {{ background: {p['line']}; border-radius: 2px; min-height: 32px; min-width: 32px; }}
        QScrollBar::handle:hover {{ background: {p['faint']}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
    """
