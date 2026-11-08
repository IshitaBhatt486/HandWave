import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QProgressBar, QWidget

from handwave.ui import motion


@pytest.fixture(autouse=True)
def _restore_motion():
    yield
    motion.set_reduced_motion(False)


def test_progress_glides_to_target(qtbot):
    bar = QProgressBar(); qtbot.addWidget(bar)
    motion.animate_value(bar, 80)
    assert bar.value() < 80  # not an instant jump
    qtbot.waitUntil(lambda: bar.value() == 80, timeout=1000)


def test_reduced_motion_makes_changes_instant(qtbot):
    motion.set_reduced_motion(True)
    bar = QProgressBar(); qtbot.addWidget(bar)
    motion.animate_value(bar, 80)
    assert bar.value() == 80
    label = QLabel("x"); qtbot.addWidget(label)
    motion.emphasize(label)
    assert label.graphicsEffect() is None


def test_emphasis_detaches_its_effect_when_done(qtbot):
    label = QLabel("Peace Sign"); qtbot.addWidget(label)
    motion.emphasize(label, duration=40)
    assert label.graphicsEffect() is not None
    qtbot.waitUntil(lambda: label.graphicsEffect() is None, timeout=1000)


def test_crossfade_overlay_cleans_itself_up(qtbot):
    page = QWidget(); page.resize(200, 120); qtbot.addWidget(page); page.show()
    qtbot.waitExposed(page)
    motion.crossfade(page, 40)
    assert any(isinstance(child, QLabel) for child in page.children())
    qtbot.waitUntil(lambda: not any(isinstance(child, QLabel) for child in page.children()), timeout=1000)


def test_list_fade_in_survives_rows_being_evicted(qtbot):
    widget = QListWidget(); qtbot.addWidget(widget)
    for index in range(20):
        item = QListWidgetItem(f"row {index}")
        widget.insertItem(0, item)
        motion.fade_in_item(item, QColor("#ffffff"), duration=60)
        while widget.count() > 5:
            widget.takeItem(widget.count() - 1)
    qtbot.wait(150)  # animations finish without touching deleted rows
    assert widget.count() == 5


def test_faded_row_follows_the_theme_afterwards(qtbot):
    widget = QListWidget(); qtbot.addWidget(widget)
    item = QListWidgetItem("Open Palm")
    widget.insertItem(0, item)
    motion.fade_in_item(item, QColor("#f4efe6"), duration=40)
    assert item.data(Qt.ItemDataRole.ForegroundRole) is not None  # tinted while fading
    qtbot.waitUntil(lambda: item.data(Qt.ItemDataRole.ForegroundRole) is None, timeout=1000)


def test_toast_shows_then_hides(qtbot):
    parent = QWidget(); parent.resize(400, 300); qtbot.addWidget(parent); parent.show()
    toast = motion.Toast(parent)
    toast.show_message("Settings saved", duration_ms=50)
    assert toast.isVisible() and toast.text == "Settings saved"
    qtbot.waitUntil(lambda: not toast.isVisible(), timeout=2000)
