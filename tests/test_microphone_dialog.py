from types import SimpleNamespace
from unittest.mock import MagicMock

from handwave.services.clap_detector import ClapState
from handwave.ui.microphone_dialog import MicrophoneDialog


class FakeDetector:
    def __init__(self, *, listening: bool, error: str | None = None) -> None:
        self.is_listening = listening
        self.start = MagicMock()
        self.state = ClapState.IDLE
        self._status = SimpleNamespace(
            available=listening,
            stream_status="running" if listening else "stopped",
            error=error,
            noise_floor=0.01,
            input_level=0.02,
            threshold=0.03,
            device="Test microphone",
            rms=0.01,
            callback_count=0,
        )

    def status(self):
        return self._status


def test_dialog_starts_microphone_automatically_and_has_no_retry_button(qtbot):
    detector = FakeDetector(listening=False)
    dialog = MicrophoneDialog(detector)
    qtbot.addWidget(dialog)

    detector.start.assert_called_once()
    assert [button.text() for button in dialog.findChildren(type(dialog.recalibrate))] == [
        "Recalibrate", "Reset Calibration", "Close"
    ]
    assert dialog.health.text() == "No microphone detected"


def test_wizard_counts_a_clap_that_happened_between_ui_polls(qtbot):
    detector = FakeDetector(listening=True)
    dialog = MicrophoneDialog(detector)
    qtbot.addWidget(dialog)
    dialog._timer.stop()
    dialog._noise = [0.002] * 10
    dialog._start_claps()

    # The latest block is quiet, but a loud block arrived since the last poll.
    detector._status.callback_count = 5
    detector._status.input_level, detector._status.rms = 0.003, 0.002
    detector.consume_levels = MagicMock(return_value=(0.4, 0.05, 0.01))
    dialog._tick()

    assert dialog._claps == [(0.4, 0.05)]


def test_closing_dialog_stops_polling_and_disconnects_detector(qtbot):
    from PyQt6.QtCore import QObject, pyqtSignal

    class SignalDetector(QObject):
        double_clap = pyqtSignal()
        error = pyqtSignal(str)

    detector = SignalDetector()
    fake = FakeDetector(listening=True)
    detector.is_listening, detector.start, detector.status = True, fake.start, fake.status
    dialog = MicrophoneDialog(detector)
    qtbot.addWidget(dialog)
    assert detector.receivers(detector.double_clap) == 1

    dialog.accept()

    assert not dialog._timer.isActive()
    assert detector.receivers(detector.double_clap) == 0


def test_dialog_reports_listening_and_error_states(qtbot):
    detector = FakeDetector(listening=True)
    dialog = MicrophoneDialog(detector)
    qtbot.addWidget(dialog)
    assert dialog.health.text() == "Connected • Listening"

    detector._status.available = False
    detector._status.stream_status = "error"
    detector._status.error = "access denied"
    dialog._refresh()
    assert dialog.health.text() == "Microphone error"
