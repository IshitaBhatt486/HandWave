from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from handwave.services.clap_detector import ClapDetector, ClapState


def _clap(amplitude=1.0, size=256, at=20):
    block = np.zeros(size, dtype=np.float32)
    block[at] = amplitude
    return block


def _quiet_noise(rng, level=0.02, size=256):
    return rng.normal(0, level, size).astype(np.float32)


def test_double_clap_enables_then_disables_system(qtbot):
    detector = ClapDetector()
    enabled = [False]
    detector.double_clap.connect(lambda: enabled.__setitem__(0, not enabled[0]))

    assert not detector.process_audio(_clap(), timestamp=1.0)
    assert detector.process_audio(_clap(), timestamp=1.5)
    assert enabled[0]

    assert not detector.process_audio(_clap(), timestamp=2.0)
    assert detector.process_audio(_clap(), timestamp=2.5)
    assert not enabled[0]


def test_uneven_but_valid_claps_still_trigger():
    detector = ClapDetector()
    assert not detector.process_audio(_clap(), timestamp=0.0)
    assert detector.process_audio(_clap(), timestamp=0.25)  # close to the minimum separation

    detector.reset()
    assert not detector.process_audio(_clap(), timestamp=10.0)
    assert detector.process_audio(_clap(), timestamp=10.95)  # close to the maximum separation


def test_too_fast_claps_do_not_trigger():
    detector = ClapDetector()
    detections = []
    detector.double_clap.connect(lambda: detections.append(True))
    detector.process_audio(_clap(), timestamp=0.0)
    detector.process_audio(_clap(), timestamp=0.08)  # inside the refractory/min-separation window
    assert detections == []


def test_too_slow_claps_do_not_trigger():
    detector = ClapDetector()
    detections = []
    detector.double_clap.connect(lambda: detections.append(True))
    detector.process_audio(_clap(), timestamp=0.0)
    detector.process_audio(_clap(), timestamp=1.2)
    assert detections == []





def test_normal_speech_and_background_noise_do_not_trigger():
    detector = ClapDetector()
    detections = []
    detector.double_clap.connect(lambda: detections.append(True))
    time_axis = np.linspace(0, 1, 256, endpoint=False)

    for index in range(30):
        speech = 0.45 * np.sin(2 * np.pi * (3 + index % 4) * time_axis)
        detector.process_audio(speech, timestamp=index * 0.05)
    rng = np.random.default_rng(4)
    for index in range(30, 60):
        noise = rng.normal(0, 0.03, 256)
        detector.process_audio(noise, timestamp=index * 0.05)

    assert detections == []


def test_repeated_double_claps_keep_working():
    detector = ClapDetector()
    count = [0]
    detector.double_clap.connect(lambda: count.__setitem__(0, count[0] + 1))
    for round_start in (0.0, 5.0, 10.0):
        detector.process_audio(_clap(), timestamp=round_start)
        assert detector.process_audio(_clap(), timestamp=round_start + 0.4)
    assert count[0] == 3


def test_state_machine_transitions_and_reset():
    detector = ClapDetector()
    assert detector.state == ClapState.IDLE
    detector.process_audio(_clap(), timestamp=0.0)
    assert detector.state == ClapState.WAITING_FOR_SECOND_CLAP
    detector.process_audio(_clap(), timestamp=0.4)
    assert detector.state == ClapState.IDLE

    detector.process_audio(_clap(), timestamp=10.0)
    assert detector.state == ClapState.WAITING_FOR_SECOND_CLAP
    detector.reset()
    assert detector.state == ClapState.IDLE











def test_status_reports_input_level_and_availability():
    detector = ClapDetector()
    status_before = detector.status()
    assert status_before.available is False
    assert status_before.input_level == 0.0

    detector.process_audio(_clap(amplitude=0.6), timestamp=0.0)
    status_after = detector.status()
    assert status_after.input_level == pytest.approx(0.6)
    assert status_after.rms > 0
    assert status_after.last_clap_time == pytest.approx(0.0)


def test_configurable_double_clap_window_and_threshold():
    detector = ClapDetector(min_peak=0.05, min_clap_separation=0.2, max_clap_separation=0.8)
    assert not detector.process_audio(_clap(0.1), timestamp=0.0)
    assert detector.process_audio(_clap(0.1), timestamp=0.5)
    detector.configure(device=None, min_peak=0.08, noise_multiplier=3.0, min_clap_separation=0.3, max_clap_separation=0.9)
    assert detector.min_peak == pytest.approx(0.08)
    assert detector.min_clap_separation == pytest.approx(0.3)


def test_start_validates_and_reports_selected_microphone(qtbot):
    detector = ClapDetector(device=3)
    stream = MagicMock()
    module = MagicMock()
    module.query_devices.return_value = {"name": "Test microphone", "max_input_channels": 1}
    module.InputStream.return_value = stream
    with patch("handwave.services.clap_detector.sd", module):
        detector.start()
    assert module.query_devices.call_args.args == (3, "input")
    assert detector.status().device == "Test microphone"
    assert detector.status().stream_status == "running"
    detector.stop()


def test_default_fallback_never_uses_stereo_mix_for_clap_capture():
    detector = ClapDetector()
    module = MagicMock()
    module.default.device = [1, 3]
    module.query_devices.return_value = [
        {"name": "Microphone Array", "max_input_channels": 2},
        {"name": "Stereo Mix", "max_input_channels": 2},
        {"name": "Speaker loopback", "max_input_channels": 2},
        {"name": "USB Microphone", "max_input_channels": 1},
    ]
    with patch("handwave.services.clap_detector.sd", module):
        assert detector._input_candidates() == [1, 0, 3]


def test_start_without_sounddevice_reports_a_clear_error(qtbot):
    detector = ClapDetector()
    errors = []
    detector.error.connect(errors.append)

    with patch("handwave.services.clap_detector.sd", None):
        detector.start()

    assert not detector.is_listening
    assert "sounddevice" in errors[0]
    assert detector.status().error is not None


def test_recoverable_input_overflow_does_not_stop_audio_capture(qtbot):
    detector = ClapDetector()
    detector._stream = MagicMock()
    detector._stream_status = "running"
    faults = []
    detector.stream_fault.connect(faults.append)

    detector._audio_callback(np.zeros(256, dtype=np.float32), 256, None, "input overflow")

    assert detector.is_listening
    assert detector.status().stream_status == "degraded"
    assert faults == []


def test_device_failure_is_recovered_from_without_crashing(qtbot):
    detector = ClapDetector()
    errors = []
    detector.error.connect(errors.append)
    failing_module = MagicMock()
    failing_module.InputStream.side_effect = OSError("device unavailable")

    with patch("handwave.services.clap_detector.sd", failing_module):
        detector.start()
    assert not detector.is_listening
    assert errors  # a clear, non-fatal error was reported

    working_stream = MagicMock()
    working_module = MagicMock()
    working_module.InputStream.return_value = working_stream
    with patch("handwave.services.clap_detector.sd", working_module):
        detector.retry()

    assert detector.is_listening
    assert detector.status().error is None


def test_stop_keeps_camera_independent_no_exception_on_double_stop(qtbot):
    detector = ClapDetector()
    detector.stop()  # never started; must not raise
    working_module = MagicMock()
    with patch("handwave.services.clap_detector.sd", working_module):
        detector.start()
    detector.stop()
    detector.stop()  # idempotent
    assert not detector.is_listening


def test_process_audio_never_stores_raw_samples():
    """Privacy: only scalar levels are retained, never the sample array itself."""
    detector = ClapDetector()
    detector.process_audio(_clap(), timestamp=0.0)
    for value in vars(detector).values():
        assert not isinstance(value, np.ndarray)


@pytest.mark.parametrize("amplitude", [0.06, 0.3, 0.9])
def test_adaptive_detector_accepts_quiet_normal_and_loud_double_claps(amplitude):
    detector = ClapDetector()
    rng = np.random.default_rng(42)
    for index in range(12):
        detector.process_audio(_quiet_noise(rng, level=0.005), timestamp=index * 0.05)
    assert not detector.process_audio(_clap(amplitude), timestamp=1.0)
    assert detector.process_audio(_clap(amplitude), timestamp=1.45)


def test_continuous_loud_sound_and_random_keyboard_peaks_do_not_trigger():
    detector = ClapDetector()
    loud = np.full(256, 0.4, dtype=np.float32)
    for index in range(20):
        assert not detector.process_audio(loud, timestamp=index * 0.05)
    rng = np.random.default_rng(5)
    for index in range(20, 50):
        keyboard = _quiet_noise(rng, level=0.03)
        keyboard[::32] = 0.09  # repeated small mechanical peaks, not a transient clap pair
        assert not detector.process_audio(keyboard, timestamp=index * 0.05)


def test_consume_levels_reports_loudest_block_since_last_poll():
    detector = ClapDetector()
    assert detector.consume_levels() is None

    quiet = np.full(256, 0.01, dtype=np.float32)
    detector.process_audio(quiet, timestamp=0.0)
    detector.process_audio(_clap(0.5), timestamp=0.02)
    detector.process_audio(quiet, timestamp=0.04)

    peak, peak_rms, mean_rms = detector.consume_levels()
    assert peak == pytest.approx(0.5)
    assert peak_rms > 0.01
    assert 0.01 < mean_rms < peak_rms
    assert detector.consume_levels() is None
