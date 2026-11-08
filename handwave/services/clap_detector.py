"""Microphone-backed double-clap detector.

Privacy: only scalar peak/RMS levels are ever computed from each audio block.
No audio samples are stored, buffered beyond the current block, or written to
disk at any point.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

import numpy as np
from PyQt6.QtCore import QMetaObject, QObject, QTimer, Qt, pyqtSignal, pyqtSlot

try:
    import sounddevice as sd
except ImportError:  # Provides a clear runtime error before dependencies are installed.
    sd = None

logger = logging.getLogger(__name__)


class ClapState(Enum):
    """Explicit double-clap state machine (see ``ClapDetector.state``)."""

    IDLE = auto()
    WAITING_FOR_SECOND_CLAP = auto()


@dataclass(frozen=True)
class MicrophoneStatus:
    """A diagnostics snapshot suitable for a settings/calibration UI."""

    available: bool
    input_level: float
    noise_floor: float
    threshold: float
    device: str | None = None
    rms: float = 0.0
    stream_status: str = "stopped"
    last_clap_time: float | None = None
    callback_count: int = 0
    error: str | None = None




class ClapDetector(QObject):
    """Detect two sharp audio peaks between 200 ms and 1000 ms apart.

    State machine: ``IDLE`` -> (sharp peak) -> ``WAITING_FOR_SECOND_CLAP`` ->
    either a second sharp peak inside the timing window confirms the double
    clap and returns to ``IDLE``, or the window expires and it returns to
    ``IDLE`` without firing.
    """

    double_clap = pyqtSignal()
    error = pyqtSignal(str)
    started = pyqtSignal()
    stopped = pyqtSignal()
    stream_fault = pyqtSignal(str)

    REFRACTORY_INTERVAL = 0.08

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        min_peak: float = 0.02,
        rms_threshold: float = 0.0,
        noise_multiplier: float = 2.5,
        device: int | None = None,
        min_clap_separation: float = 0.12,
        max_clap_separation: float = 1.0,
    ) -> None:
        super().__init__()
        self._clock = clock
        self.min_peak = min_peak
        self.rms_threshold = rms_threshold
        self.noise_multiplier = noise_multiplier
        self.device = device
        self.min_clap_separation = min_clap_separation
        self.max_clap_separation = max_clap_separation
        # New detectors have no ambient sample yet.  Starting at 0.02 made the
        # effective threshold 0.12, which missed ordinary laptop-microphone
        # claps before the adaptive baseline had time to settle.
        self._noise_floor = 0.002
        self._first_clap_time: float | None = None
        self._last_peak_time = float("-inf")
        self._stream = None
        self._last_input_level = 0.0
        self._last_error: str | None = None
        self._last_rms = 0.0
        # Loudest block (and its RMS) plus the RMS sum since the last
        # ``consume_levels`` call, so a slower UI poll cannot miss a short clap.
        self._poll_peak = 0.0
        self._poll_peak_rms = 0.0
        self._poll_rms_sum = 0.0
        self._poll_blocks = 0
        self._device_name: str | None = None
        self._sample_rate: float | None = None
        self._stream_status = "stopped"
        self._last_clap_time: float | None = None
        self._callback_count = 0
        self._last_callback_time: float | None = None
        self._recovery_attempts = 0
        self._recovery_timer = QTimer(self)
        self._recovery_timer.setSingleShot(True)
        self._recovery_timer.timeout.connect(self._recover_stream)
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setInterval(2_000)
        self._watchdog_timer.timeout.connect(self._check_callback_health)
        self.stream_fault.connect(self._handle_callback_failure, Qt.ConnectionType.QueuedConnection)

    @property
    def is_listening(self) -> bool:
        return self._stream is not None

    @property
    def state(self) -> ClapState:
        return ClapState.IDLE if self._first_clap_time is None else ClapState.WAITING_FOR_SECOND_CLAP

    @property
    def threshold(self) -> float:
        return max(self.min_peak, self._noise_floor * self.noise_multiplier)

    def status(self) -> MicrophoneStatus:
        """A point-in-time diagnostics snapshot for a "Test microphone" UI."""
        return MicrophoneStatus(
            available=self.is_listening,
            input_level=self._last_input_level,
            noise_floor=self._noise_floor,
            threshold=self.threshold,
            device=self._device_name,
            rms=self._last_rms,
            stream_status=self._stream_status,
            last_clap_time=self._last_clap_time,
            callback_count=self._callback_count,
            error=self._last_error,
        )

    def consume_levels(self) -> tuple[float, float, float] | None:
        """Return ``(max_peak, rms_of_that_block, mean_rms)`` since the last call.

        Returns ``None`` when no audio block arrived in between. Only scalar
        levels are kept; audio samples are never retained.
        """
        if self._poll_blocks == 0:
            return None
        levels = (self._poll_peak, self._poll_peak_rms, self._poll_rms_sum / self._poll_blocks)
        self._poll_peak = self._poll_peak_rms = self._poll_rms_sum = 0.0
        self._poll_blocks = 0
        return levels

    def configure(
        self, *, device: int | None, min_peak: float, noise_multiplier: float, rms_threshold: float = 0.0,
        min_clap_separation: float, max_clap_separation: float,
    ) -> None:
        """Apply validated persisted controls; restart when the input device changes."""
        if min_clap_separation >= max_clap_separation:
            raise ValueError("Minimum double-clap interval must be below the maximum")
        device_changed = self.device != device
        self.device, self.min_peak, self.rms_threshold, self.noise_multiplier = device, min_peak, rms_threshold, noise_multiplier
        self.min_clap_separation, self.max_clap_separation = min_clap_separation, max_clap_separation
        if device_changed and self.is_listening:
            logger.info("Microphone selection changed; restarting clap stream")
            self.retry()

    def reset(self) -> None:
        """Return to ``IDLE`` without touching the microphone stream or calibration."""
        self._first_clap_time = None
        self._last_peak_time = float("-inf")

    @pyqtSlot()
    def start(self) -> None:
        """Start microphone capture; safe to call more than once."""
        if self._stream is not None:
            return
        if sd is None:
            message = "Microphone support requires the 'sounddevice' package"
            logger.error(message)
            self._last_error = message
            self.error.emit(message)
            return
        try:
            last_error: Exception | None = None
            for device_index in self._input_candidates():
                try:
                    self._resolve_input_device(device_index)
                    stream = sd.InputStream(
                        device=device_index,
                        channels=1,
                        # Many Windows MME devices reject 44.1 kHz even though their
                        # default endpoint is usable at 48 kHz. Detection is based on
                        # normalized block amplitudes, not an assumed sample rate.
                        samplerate=self._sample_rate,
                        blocksize=1024,
                        dtype="float32",
                        callback=self._audio_callback,
                    )
                    stream.start()
                    self._stream = stream
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning("Microphone %s could not start: %s", device_index, exc)
            if self._stream is None:
                raise last_error or OSError("No input microphone could be opened")
            self._last_error = None
            self._stream_status = "running"
            self._last_callback_time = self._clock()
            self._watchdog_timer.start()
            self._recovery_attempts = 0
            logger.info("Clap detector stream started: device=%s (%s), sample_rate=%s, blocksize=1024", device_index, self._device_name, self._sample_rate)
            self.started.emit()
        except Exception as exc:
            self._stream = None
            self._stream_status = "error"
            self._report_stream_error(exc, "Unable to start clap detector")
            self._schedule_recovery()

    def retry(self) -> None:
        """Re-attempt device initialization after a failure or disconnection."""
        self.stop()
        self.start()

    @pyqtSlot()
    def stop(self) -> None:
        """Stop and release microphone capture."""
        stream, self._stream = self._stream, None
        self._recovery_timer.stop()
        self._watchdog_timer.stop()
        self._stream_status = "stopped"
        if stream is not None:
            try:
                stream.stop()
                stream.close()
                self.stopped.emit()
            except Exception:
                logger.exception("Unable to cleanly close microphone stream")

    def _input_candidates(self) -> list[int | None]:
        """Try the default then physical microphones, never playback loopback."""
        requested = self.device
        if requested is None:
            default = getattr(sd.default, "device", None)
            # sounddevice exposes a DeviceList here, not necessarily a native
            # list/tuple. Its first entry is the default input device.
            try:
                requested = default[0]
            except (TypeError, IndexError):
                requested = default
        if self.device is not None:
            return [requested]
        try:
            candidates: list[int | None] = [requested]
            for index, info in enumerate(sd.query_devices()):
                name = str(info.get("name", "")).lower()
                # "Stereo Mix" and virtual speaker endpoints are valid PortAudio
                # inputs but cannot hear a user's physical clap. Do not silently
                # substitute them when a microphone fails.
                is_microphone = "microphone" in name
                if is_microphone and info.get("max_input_channels", 0) > 0 and index not in candidates:
                    candidates.append(index)
            return candidates
        except Exception:
            return [requested]

    def _resolve_input_device(self, requested: int | None) -> int | None:
        """Validate the configured/default input and retain a useful diagnostics name."""
        info = sd.query_devices(requested, "input")
        if int(info.get("max_input_channels", 0)) < 1:
            raise OSError(f"Selected microphone {requested!r} has no input channels")
        self._device_name = str(info.get("name", requested))
        rate = float(info.get("default_samplerate", 0) or 0)
        self._sample_rate = rate if rate > 0 else None
        logger.info("Clap detector selected microphone: index=%s name=%s default_sample_rate=%s", requested, self._device_name, self._sample_rate)
        return requested

    def _report_stream_error(self, exc: Exception, context: str) -> None:
        message = str(exc)
        if "permission" in message.lower() or "access" in message.lower():
            from handwave import platforms

            if platforms.is_macos():
                message += ". Check System Settings > Privacy & Security > Microphone and allow HandWave (or your terminal)."
            else:
                message += ". Check Windows Settings > Privacy & security > Microphone and allow desktop apps."
        self._last_error = message
        logger.exception("%s: %s", context, message)
        self.error.emit(message)

    def _schedule_recovery(self) -> None:
        if self._recovery_timer.isActive():
            return
        self._recovery_attempts += 1
        delay_ms = min(30_000, 1_000 * (2 ** min(self._recovery_attempts - 1, 5)))
        logger.warning("Microphone recovery scheduled in %d ms (attempt %d)", delay_ms, self._recovery_attempts)
        self._recovery_timer.start(delay_ms)

    @pyqtSlot()
    def _recover_stream(self) -> None:
        if self._stream is None:
            logger.info("Attempting microphone recovery")
            self.start()

    @pyqtSlot()
    def _check_callback_health(self) -> None:
        """Detect unplugged/stalled devices that no longer invoke PortAudio."""
        if self._stream is None or self._last_callback_time is None:
            return
        if self._clock() - self._last_callback_time > 5.0:
            self._stream_status = "stalled"
            message = "Microphone stream stopped delivering audio callbacks; reconnecting"
            logger.warning(message)
            self.error.emit(message)
            self.stop()
            self._schedule_recovery()

    @pyqtSlot(str)
    def _handle_callback_failure(self, message: str) -> None:
        """Run recovery on the QObject's Qt thread, never PortAudio's thread."""
        self._stream_status = "error"
        self._last_error = message
        logger.error("Audio callback failed: %s", message)
        self.error.emit(message)
        self.stop()
        self._schedule_recovery()

    def _audio_callback(self, samples, frames, timing, status) -> None:
        self._callback_count += 1
        self._last_callback_time = self._clock()
        if self._callback_count == 1:
            logger.info("Microphone audio callback is running")
        if status:
            logger.warning("Microphone stream status: %s", status)
            self._stream_status = "degraded"
            # Input overflows are recoverable PortAudio diagnostics.  The
            # callback remains alive (and is the only evidence needed by the
            # watchdog), so stopping the stream here turns a transient warning
            # into a permanent double-clap failure.  Recovery is reserved for
            # callback exceptions or a five-second callback stall.
        try:
            if self.process_audio(samples, emit_signal=False):
                # PortAudio callbacks are not Qt threads. Queue the public
                # signal onto this QObject's (GUI) thread before receivers run.
                QMetaObject.invokeMethod(self, "_emit_double_clap", Qt.ConnectionType.QueuedConnection)
        except Exception as exc:  # Never let an exception kill PortAudio's callback thread.
            self.stream_fault.emit(str(exc))

    def process_audio(self, samples, timestamp: float | None = None, *, emit_signal: bool = True) -> bool:
        """Process one normalized float audio block; returns true on a double clap."""
        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            return False
        now = self._clock() if timestamp is None else timestamp
        absolute = np.abs(audio)
        peak = float(np.max(absolute))
        rms = float(np.sqrt(np.mean(audio * audio)))
        self._last_input_level = peak
        self._last_rms = rms
        if peak >= self._poll_peak:
            self._poll_peak, self._poll_peak_rms = peak, rms
        self._poll_rms_sum += rms
        self._poll_blocks += 1
        if self._callback_count == 1 or self._callback_count % 200 == 0:
            logger.debug("Microphone audio received: callbacks=%d peak=%.5f rms=%.5f threshold=%.5f", self._callback_count, peak, rms, self.threshold)

        # A clap must be both sharp and materially above the locally observed
        # noise floor. The small floor only rejects sensor quantization noise;
        # it is never sufficient by itself to recognize a quiet clap.
        crest_factor = peak / max(rms, 1e-6)
        local_baseline = max(self._noise_floor, 0.002)
        relative_peak = peak / local_baseline
        sharp_peak = peak >= self.threshold and rms >= self.rms_threshold and relative_peak >= 2.0 and crest_factor >= 3.0
        if not sharp_peak:
            # Adapt promptly at startup/device changes, but only from blocks
            # that were already classified as non-transient background sound.
            self._noise_floor = 0.85 * self._noise_floor + 0.15 * rms
            if self._first_clap_time is not None and now - self._first_clap_time > self.max_clap_separation:
                logger.debug("First clap expired after %.0f ms", (now - self._first_clap_time) * 1000)
                self._first_clap_time = None
            return False

        if now - self._last_peak_time < self.REFRACTORY_INTERVAL:
            return False
        self._last_peak_time = now

        logger.info("Clap detected: peak=%.5f rms=%.5f threshold=%.5f", peak, rms, self.threshold)
        self._last_clap_time = now
        if self._first_clap_time is None or now - self._first_clap_time > self.max_clap_separation:
            self._first_clap_time = now
            return False

        interval = now - self._first_clap_time
        if interval < self.min_clap_separation:
            logger.debug("Clap ignored: %.0f ms is below configured minimum", interval * 1000)
            return False

        self._first_clap_time = None
        logger.info("Double clap detected (%.0f ms apart); toggle queued=%s", interval * 1000, not emit_signal)
        if emit_signal:
            self._emit_double_clap()
        return True

    @pyqtSlot()
    def _emit_double_clap(self) -> None:
        logger.info("Double-clap toggle sent to Qt receivers")
        self.double_clap.emit()
