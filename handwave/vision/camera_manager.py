"""Asynchronous capture, recognition, and action pipeline."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import cv2

from handwave.vision.overlay_text import put_text
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from handwave.actions.action_queue import ActionQueue, ActionWorker
from handwave.application.recognition_runtime import RecognitionActionRuntime
from handwave.config.settings_manager import AppSettings
from handwave.diagnostics.pipeline_metrics import DiagnosticsMonitor, PipelineMetrics

if TYPE_CHECKING:
    # Importing mediapipe (transitively, via GestureEngine) costs ~0.7s. Deferring
    # it to GestureWorker.run() keeps that cost off the app-startup/UI-visible
    # path entirely, paying it only when recognition actually starts, on the
    # background gesture thread (never blocking the UI thread).
    from handwave.gestures.gesture_engine import GestureEngine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BufferedFrame:
    """A captured frame plus passive profiling metadata."""

    frame: object
    captured_at: float
    camera_fps: float


class LatestFrameBuffer:
    """Bounded thread-safe buffer that replaces stale, unprocessed frames."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._packet: BufferedFrame | None = None
        self._closed = False
        self.frames_dropped = 0

    def put(
        self,
        frame,
        captured_at: float | None = None,
        camera_fps: float = 0.0,
    ) -> None:
        with self._condition:
            if self._closed:
                return
            if self._packet is not None:
                self.frames_dropped += 1
            self._packet = BufferedFrame(
                frame=frame,
                captured_at=time.perf_counter() if captured_at is None else captured_at,
                camera_fps=camera_fps,
            )
            self._condition.notify()

    def get(self, timeout: float = 0.1):
        packet = self.get_packet(timeout)
        return None if packet is None else packet.frame

    def get_packet(self, timeout: float = 0.1) -> BufferedFrame | None:
        """Return the latest frame and its profiling metadata."""
        with self._condition:
            if self._packet is None and not self._closed:
                self._condition.wait(timeout)
            packet, self._packet = self._packet, None
            return packet

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._packet = None
            self._condition.notify_all()


class CameraWorker(QObject):
    """Capture-only worker; processing never blocks webcam reads."""

    opened = pyqtSignal()
    stopped = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, camera_index: int, stop_event: threading.Event, buffer: LatestFrameBuffer | None = None) -> None:
        super().__init__()
        self.camera_index = camera_index
        self.stop_event = stop_event
        self.buffer = buffer or LatestFrameBuffer()
        self.capture: cv2.VideoCapture | None = None
        self._last_capture_time: float | None = None
        self._camera_fps = 0.0

    MAX_CONSECUTIVE_READ_FAILURES = 15  # about half a second at 30 fps

    @staticmethod
    def capture_backend() -> int:
        """DirectShow on Windows, AVFoundation on macOS (EXPERIMENTAL), auto elsewhere."""
        from handwave import platforms

        if platforms.is_windows():
            return cv2.CAP_DSHOW
        if platforms.is_macos():
            return cv2.CAP_AVFOUNDATION
        return cv2.CAP_ANY

    def _open(self) -> bool:
        self.capture = cv2.VideoCapture(self.camera_index, self.capture_backend())
        if not self.capture.isOpened():
            return False
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.capture.set(cv2.CAP_PROP_FPS, 30)
        # Keep at most one frame queued in the driver so reads are never stale.
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return True

    def _reopen(self) -> bool:
        logger.warning("Webcam stopped returning frames; reopening it")
        if self.capture is not None:
            self.capture.release()
        return self._open()

    @pyqtSlot()
    def run(self) -> None:
        try:
            self._open()
            if not self.capture.isOpened():
                raise RuntimeError(
                    f"Could not open webcam {self.camera_index}. Check camera permissions and availability."
                )
            self.opened.emit()
            failures = 0
            reopened = False
            while not self.stop_event.is_set():
                ok, frame = self.capture.read()
                if not ok or frame is None:
                    # DirectShow drivers occasionally drop a read (USB hiccup,
                    # exposure change). Ride out short glitches and reopen the
                    # device once before reporting an error to the user.
                    failures += 1
                    if failures < self.MAX_CONSECUTIVE_READ_FAILURES:
                        self.stop_event.wait(0.01)
                        continue
                    if reopened or not self._reopen():
                        raise RuntimeError("The webcam stopped returning frames.")
                    reopened, failures = True, 0
                    continue
                failures = 0
                captured_at = time.perf_counter()
                if self._last_capture_time is not None:
                    elapsed = captured_at - self._last_capture_time
                    if elapsed > 0:
                        current_fps = 1.0 / elapsed
                        self._camera_fps = (
                            current_fps
                            if self._camera_fps == 0
                            else 0.8 * self._camera_fps + 0.2 * current_fps
                        )
                self._last_capture_time = captured_at
                height, width = frame.shape[:2]
                if width > 640:
                    scale = 640 / width
                    frame = cv2.resize(
                        frame,
                        (640, max(1, int(height * scale))),
                        interpolation=cv2.INTER_AREA,
                    )
                self.buffer.put(frame, captured_at, self._camera_fps)
        except Exception as exc:
            logger.exception("Camera capture failed")
            self.error.emit(str(exc))
        finally:
            if self.capture is not None:
                self.capture.release()
                self.capture = None
            self.buffer.close()
            self.stopped.emit()


class GestureWorker(QObject):
    """Consumes only the latest frame and performs all landmark/action work."""

    METRICS_INTERVAL_SECONDS = 0.25
    # Pace by capture timestamps, not by sleeping. The old "sleep until 33 ms
    # after each loop" added 6-7 ms of frame age with a normal 30 fps camera
    # (+-3 ms timing jitter). Processing every frame the moment it arrives, and
    # skipping only frames closer than 25 ms to the last one, keeps 30 fps
    # cameras at ~0 ms wait while still capping a 60 fps camera near 30/s.
    MIN_FRAME_INTERVAL_SECONDS = 0.025

    frame_ready = pyqtSignal(object)
    stopped = pyqtSignal()
    error = pyqtSignal(str)
    activity = pyqtSignal(str, str, str)
    metrics_ready = pyqtSignal(object)
    confidence_ready = pyqtSignal(float)
    action_outcome = pyqtSignal(object)
    fingertips_ready = pyqtSignal(object)
    hands_ready = pyqtSignal(object)

    def __init__(
        self,
        buffer: LatestFrameBuffer,
        stop_event: threading.Event,
        settings: AppSettings,
        action_queue: ActionQueue | None = None,
        custom_gestures: list[object] | None = None,
    ) -> None:
        super().__init__()
        self.buffer = buffer
        self.stop_event = stop_event
        self.settings = settings
        self.engine: GestureEngine | None = None
        self.action_queue = action_queue
        self.custom_gestures = custom_gestures or []
        dispatcher = action_queue.submit if action_queue is not None else None
        self.runtime = RecognitionActionRuntime(settings, dispatcher)
        self.diagnostics_monitor = DiagnosticsMonitor()
        self._last_recognition_time: float | None = None
        self._recognition_fps = 0.0
        self._last_metrics_emit = float("-inf")
        self._last_processed_capture = float("-inf")

    @pyqtSlot()
    def run(self) -> None:
        try:
            from handwave.gestures.gesture_engine import GestureEngine

            from handwave.gestures.custom_gesture import CustomGestureMatcher
            self.engine = GestureEngine(
                sensitivity=self.settings.gesture_sensitivity,
                overlay_enabled=self.settings.overlay_enabled,
                custom_matcher=CustomGestureMatcher(self.custom_gestures),
                model_complexity=0 if self.settings.fast_hand_model else 1,
                debug_text=self.settings.debug_overlay,
            )
            while not self.stop_event.is_set():
                packet = self.buffer.get_packet()
                if packet is None:
                    continue
                if packet.captured_at - self._last_processed_capture < self.MIN_FRAME_INTERVAL_SECONDS:
                    continue  # camera faster than ~40 fps: skip this one, the next arrives shortly
                self._last_processed_capture = packet.captured_at
                annotated, gesture = self.engine.process(packet.frame)
                recognized_at = time.perf_counter()
                if self._last_recognition_time is not None:
                    elapsed = recognized_at - self._last_recognition_time
                    if elapsed > 0:
                        current_fps = 1.0 / elapsed
                        self._recognition_fps = (
                            current_fps
                            if self._recognition_fps == 0
                            else 0.8 * self._recognition_fps + 0.2 * current_fps
                        )
                self._last_recognition_time = recognized_at
                dispatch = self.runtime.evaluate(gesture)
                filtered = dispatch.filtered
                self.fingertips_ready.emit([
                    (hand.landmarks.get_landmarks()[8].x, hand.landmarks.get_landmarks()[8].y)
                    for hand in gesture.hands
                ])
                self.hands_ready.emit(gesture.hands)
                cpu, memory = self.diagnostics_monitor.update()
                if self.settings.overlay_enabled and self.settings.debug_overlay:
                    put_text(annotated, f"Stable: {filtered.stable_gesture}", (16, 128), 0.7, 1)
                    put_text(annotated, f"CPU: {cpu:.1f}%  Memory: {memory:.1f} MB", (16, 384), 0.6, 1)
                    put_text(annotated, f"Motion: {dispatch.swipe.diagnostic}", (16, 412), 0.5, 1)
                self.activity.emit(gesture.name, filtered.stable_gesture, dispatch.action if dispatch.executed else "")
                outcome = self.runtime.action_mapper.last_outcome
                routine_gates = {"gesture not re-armed", "cooldown active", "hold duration not met"}
                if (
                    dispatch.action != "Unknown"
                    and outcome is not None
                    and (outcome.executed or outcome.blocked_reason not in routine_gates)
                ):
                    self.action_outcome.emit(outcome)
                self.confidence_ready.emit(gesture.confidence)
                if recognized_at - self._last_metrics_emit >= self.METRICS_INTERVAL_SECONDS:
                    self._last_metrics_emit = recognized_at
                    self.metrics_ready.emit(PipelineMetrics(
                    camera_fps=packet.camera_fps,
                    recognition_fps=self._recognition_fps,
                    latency_ms=(time.perf_counter() - packet.captured_at) * 1000.0,
                    cpu_percent=cpu,
                    memory_mb=memory,
                    dropped_frames=self.buffer.frames_dropped,
                    hands_detected=gesture.hands_detected,
                    left_hand_pose=gesture.two_hand.left_pose,
                    right_hand_pose=gesture.two_hand.right_pose,
                    two_hand_gesture=gesture.two_hand.name,
                    motion_gesture=dispatch.swipe.name,
                    motion_source=dispatch.swipe.diagnostic,
                    ))
                self.frame_ready.emit(annotated)
        except Exception as exc:
            logger.exception("Gesture processing failed")
            self.error.emit(str(exc))
        finally:
            if self.engine is not None:
                self.engine.close()
                self.engine = None
            self.stopped.emit()

    @property
    def action_mapper(self):
        """Compatibility access to the session action mapper."""
        return self.runtime.action_mapper

    @action_mapper.setter
    def action_mapper(self, mapper) -> None:
        self.runtime.action_mapper = mapper


class CameraManager(QObject):
    """Own asynchronous capture, recognition, and action stages."""

    frame_ready = pyqtSignal(object)
    started = pyqtSignal()
    stopped = pyqtSignal()
    error = pyqtSignal(str)
    recognition_updated = pyqtSignal(str, str, str)
    diagnostics_updated = pyqtSignal(object)
    confidence_updated = pyqtSignal(float)
    action_outcome_updated = pyqtSignal(object)
    fingertips_updated = pyqtSignal(object)
    hands_updated = pyqtSignal(object)

    def __init__(self, camera_index: int = 0, settings: AppSettings | None = None) -> None:
        super().__init__()
        self.settings = settings or AppSettings(camera_index=camera_index)
        self.camera_index = self.settings.camera_index
        self._capture_thread: QThread | None = None
        self._gesture_thread: QThread | None = None
        self._action_thread: QThread | None = None
        self._capture_worker: CameraWorker | None = None
        self._gesture_worker: GestureWorker | None = None
        self._action_worker: ActionWorker | None = None
        self._stop_event = threading.Event()
        self._buffer: LatestFrameBuffer | None = None
        self._action_queue: ActionQueue | None = None
        self._threads_finished = 0
        self._had_error = False
        self.custom_gestures: list[object] = []

    @property
    def is_running(self) -> bool:
        return self._capture_thread is not None

    def start_camera(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._had_error = False
        self._threads_finished = 0
        self._buffer = LatestFrameBuffer()
        self._action_queue = ActionQueue()
        self._capture_thread = QThread(self)
        self._gesture_thread = QThread(self)
        self._action_thread = QThread(self)
        self._capture_worker = CameraWorker(self.camera_index, self._stop_event, self._buffer)
        self._gesture_worker = GestureWorker(
            self._buffer,
            self._stop_event,
            self.settings,
            self._action_queue,
            self.custom_gestures,
        )
        self._action_worker = ActionWorker(self._action_queue)
        self._capture_worker.moveToThread(self._capture_thread)
        self._gesture_worker.moveToThread(self._gesture_thread)
        self._action_worker.moveToThread(self._action_thread)
        self._capture_thread.started.connect(self._capture_worker.run)
        self._gesture_thread.started.connect(self._gesture_worker.run)
        self._action_thread.started.connect(self._action_worker.run)
        self._capture_worker.opened.connect(self.started)
        self._gesture_worker.frame_ready.connect(self.frame_ready)
        self._gesture_worker.activity.connect(self.recognition_updated)
        self._gesture_worker.metrics_ready.connect(self._forward_metrics)
        self._gesture_worker.confidence_ready.connect(self.confidence_updated)
        self._gesture_worker.action_outcome.connect(self.action_outcome_updated)
        self._gesture_worker.fingertips_ready.connect(self.fingertips_updated)
        self._gesture_worker.hands_ready.connect(self.hands_updated)
        for worker, thread in (
            (self._capture_worker, self._capture_thread),
            (self._gesture_worker, self._gesture_thread),
            (self._action_worker, self._action_thread),
        ):
            worker.error.connect(self._on_worker_error)
            worker.stopped.connect(worker.deleteLater)
            worker.stopped.connect(thread.quit)
            thread.finished.connect(self._on_thread_finished)
            thread.finished.connect(thread.deleteLater)
        self._gesture_worker.stopped.connect(self._close_action_queue)
        self._capture_thread.start()
        self._gesture_thread.start()
        self._action_thread.start()

    def stop_camera(self) -> None:
        """Request asynchronous shutdown and return immediately to the UI."""
        if not self.is_running:
            return
        self._stop_event.set()
        if self._buffer is not None:
            self._buffer.close()
        if self._action_queue is not None:
            self._action_queue.close(discard_pending=True)

    def update_settings(self, settings: AppSettings) -> None:
        """Use persisted settings the next time recognition starts."""
        self.settings = settings
        self.camera_index = settings.camera_index

    def update_custom_gestures(self, definitions: list[object]) -> None:
        """Replace local custom definitions; a running engine updates in place."""
        self.custom_gestures = list(definitions)
        if self._gesture_worker is not None:
            self._gesture_worker.custom_gestures = list(definitions)
            if self._gesture_worker.engine is not None:
                from handwave.gestures.custom_gesture import CustomGestureMatcher
                self._gesture_worker.engine.custom_matcher = CustomGestureMatcher(definitions)

    def apply_profile_settings(self, effective_settings: AppSettings) -> None:
        """Apply a profile's resolved settings without restarting capture or recognition.

        Only the action-mapping configuration (cooldown/bindings/enabled gestures) is
        swapped in place on the running gesture worker; the camera thread, capture
        loop, and MediaPipe instance are left untouched.
        """
        self.settings = effective_settings
        if self._action_queue is not None:
            self._action_queue.discard_pending()
        if self._gesture_worker is not None:
            self._gesture_worker.action_mapper.apply_settings(
                cooldown=effective_settings.gesture_cooldown,
                gesture_bindings=effective_settings.gesture_bindings,
                enabled_gestures=effective_settings.enabled_gestures,
            )

    @pyqtSlot(object)
    def _forward_metrics(self, metrics: PipelineMetrics) -> None:
        threads = sum(
            1
            for thread in (
                self._capture_thread,
                self._gesture_thread,
                self._action_thread,
            )
            if thread is not None and thread.isRunning()
        )
        self.diagnostics_updated.emit(replace(metrics, active_threads=threads))

    @pyqtSlot()
    def _close_action_queue(self) -> None:
        if self._action_queue is not None:
            self._action_queue.close(discard_pending=True)

    @pyqtSlot()
    def _on_thread_finished(self) -> None:
        self._threads_finished += 1
        if self._threads_finished == 3:
            self._cleanup()
            self.stopped.emit()

    @pyqtSlot(str)
    def _on_worker_error(self, message: str) -> None:
        if not self._had_error:
            self._had_error = True
            self.error.emit(message)
        self._stop_event.set()
        if self._buffer is not None:
            self._buffer.close()
        if self._action_queue is not None:
            self._action_queue.close(discard_pending=True)

    def _cleanup(self) -> None:
        self._capture_worker = None
        self._gesture_worker = None
        self._action_worker = None
        self._capture_thread = None
        self._gesture_thread = None
        self._action_thread = None
        self._buffer = None
        self._action_queue = None
