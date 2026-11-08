"""Capture the screenshots used in the README and docs from the real app.

The dashboard shots feed real HaGRID photos (faces blurred) through HandWave's
own MediaPipe + GestureEngine pipeline, so the landmarks, recognised gesture,
confidence and latency on screen are all real. Those images are adaptations
of HaGRID and are written to docs/demo/ under the HaGRID licence (see
docs/demo/NOTICE.md). Screens with no photo go to docs/images/ (MIT).

    python scripts/capture_docs_screenshots.py --hagrid-dir <HaGRID sample>

Windows briefly appear on screen so the real system fonts are used. Look at
every image before committing it.
"""

from __future__ import annotations

import argparse
import csv
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import handwave  # noqa: F401,E402  (loads native libraries in the right order)
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PyQt6.QtCore import QObject, pyqtSignal  # noqa: E402
from PyQt6.QtWidgets import QApplication, QTabWidget  # noqa: E402

from handwave.actions.action_definition import MEDIA_ACTIONS  # noqa: E402
from handwave.config.gesture_config import DEFAULT_GESTURE_BINDINGS  # noqa: E402
from handwave.config.settings_manager import SettingsManager  # noqa: E402
from handwave.diagnostics.pipeline_metrics import DiagnosticsMonitor, PipelineMetrics  # noqa: E402
from handwave.ui import motion  # noqa: E402

IMAGES = ROOT / "docs" / "images"
DEMO = ROOT / "docs" / "demo"
PREDICTIONS = ROOT / "benchmarks" / "results" / "hagrid" / "predictions.csv"
FRAME_W, FRAME_H = 640, 480
# Poses shown on the dashboards, in order of preference.
HERO_GESTURES = ("Open Palm", "Peace Sign", "Thumbs Up")


class DemoCamera(QObject):
    """Stands in for CameraManager; frames and results come from the real engine."""

    frame_ready = pyqtSignal(object)
    started = pyqtSignal()
    stopped = pyqtSignal()
    error = pyqtSignal(str)
    recognition_updated = pyqtSignal(str, str, str)
    diagnostics_updated = pyqtSignal(object)
    confidence_updated = pyqtSignal(float)
    is_running = False

    def start_camera(self) -> None:
        self.is_running = True
        self.started.emit()

    def stop_camera(self) -> None:
        self.is_running = False
        self.stopped.emit()

    def update_settings(self, settings) -> None:
        pass


class DemoClapDetector(QObject):
    double_clap = pyqtSignal()
    error = pyqtSignal(str)
    started = pyqtSignal()
    stopped = pyqtSignal()

    def start(self) -> None:
        self.started.emit()

    def stop(self) -> None:
        self.stopped.emit()


def action_label(gesture: str) -> str:
    binding = DEFAULT_GESTURE_BINDINGS.get(gesture, "none")
    return MEDIA_ACTIONS.get(binding, "No action") if isinstance(binding, str) else str(binding.get("value"))


def crop_around_hand(image: np.ndarray, bbox) -> np.ndarray:
    """A 4:3 crop centred on the hand, so the hand fills the preview like a webcam shot."""
    h, w = image.shape[:2]
    x, y, bw, bh = bbox
    cx, cy = (x + bw / 2) * w, (y + bh / 2) * h
    crop_w = min(w, max(bw * w * 2.6, bh * h * 2.6 * 4 / 3))
    crop_h = min(h, crop_w * 3 / 4)
    crop_w = crop_h * 4 / 3
    x0 = int(min(max(0, cx - crop_w / 2), w - crop_w))
    y0 = int(min(max(0, cy - crop_h / 2), h - crop_h))
    crop = image[y0:y0 + int(crop_h), x0:x0 + int(crop_w)]
    return cv2.resize(crop, (FRAME_W, FRAME_H), interpolation=cv2.INTER_CUBIC)


def real_frames(data_dir: Path, wanted: int) -> list[tuple]:
    """(annotated frame, GestureResult, latency ms, clean frame) for correctly recognised HaGRID photos."""
    from benchmarks.make_hagrid_demo import FaceBlur, _load_annotations
    from handwave.gestures.gesture_engine import GestureEngine

    rows = [r for r in csv.DictReader(PREDICTIONS.open(encoding="utf-8"))
            if r["condition"] == "Original" and r["lighting"] == "Normal"
            and r["expected"] in HERO_GESTURES and r["predicted"] == r["expected"] and r["hands_detected"] == "1"]
    boxes, paths = _load_annotations(data_dir)
    # Largest hands first: they read best at README size.
    rows.sort(key=lambda r: -(lambda b: b[2] * b[3])(boxes.get((r["image_id"], r["hagrid_label"]), (0, 0, 0, 0))))
    blur = FaceBlur()
    found: dict[str, tuple[np.ndarray, object, float]] = {}
    for row in rows:
        if row["expected"] in found or (row["image_id"], row["hagrid_label"]) not in boxes:
            continue
        frame = crop_around_hand(cv2.imread(str(paths[row["image_id"]])), boxes[(row["image_id"], row["hagrid_label"])])
        frame, faces = blur.apply(frame)
        if faces:  # prefer shots that show only the hand; faces are blurred regardless
            continue
        engine = GestureEngine(two_hand_probe=False)
        try:
            for _ in range(3):  # let tracking settle, as on a live camera
                started = time.perf_counter()
                shown, result = engine.process(frame.copy())
                latency = (time.perf_counter() - started) * 1000
        finally:
            engine.close()
        if result.name == row["expected"]:
            found[row["expected"]] = (shown, result, latency, frame)
            print(f"{row['expected']:10s} {row['image_id']}  confidence {result.confidence:.2f}  {latency:.1f} ms  faces blurred {faces}")
        if len(found) == wanted:
            break
    return [found[g] for g in HERO_GESTURES if g in found]


def save(widget, path: Path) -> None:
    for _ in range(5):
        QApplication.processEvents()
        time.sleep(0.05)
    if not widget.grab().save(str(path), "PNG"):
        raise RuntimeError(f"Unable to save screenshot: {path}")
    print("wrote", path.relative_to(ROOT))


def measure(frame: np.ndarray) -> tuple[float, float, float, float]:
    """Median latency (ms), frames/s, CPU % and memory (MB) over 3 s of recognition paced at 30 fps."""
    from handwave.gestures.gesture_engine import GestureEngine

    engine, monitor, latencies = GestureEngine(two_hand_probe=False), DiagnosticsMonitor(), []
    begin = time.perf_counter()
    deadline = begin + 3.0
    try:
        while time.perf_counter() < deadline:
            started = time.perf_counter()
            engine.process(frame.copy())
            latencies.append((time.perf_counter() - started) * 1000)
            time.sleep(max(0.0, 1 / 30 - (time.perf_counter() - started)))
    finally:
        engine.close()
    cpu, memory = monitor.update()
    fps = len(latencies) / (time.perf_counter() - begin)
    return float(np.median(latencies[len(latencies) // 2:])), fps, cpu, memory


def dashboards(window, camera, frames, raw_frame) -> None:
    for _, result, _, _ in frames[1:][::-1] + frames[:1]:  # history, newest last
        window.update_activity(result.name, result.name, action_label(result.name))
        time.sleep(1.1)  # distinct timestamps, as when gestures are made one after another
    frame, result, latency, _ = frames[0]
    latency, fps, cpu, memory = measure(raw_frame)
    camera.frame_ready.emit(frame)
    camera.confidence_updated.emit(result.confidence)
    camera.diagnostics_updated.emit(PipelineMetrics(
        camera_fps=30.0,
        recognition_fps=fps,
        latency_ms=latency,
        cpu_percent=cpu,
        memory_mb=memory,
        active_threads=3,
        hands_detected=result.hands_detected,
    ))
    save(window, DEMO / "dashboard-dark.png")
    window.pages.setCurrentIndex(1)
    save(window, DEMO / "diagnostics-dark.png")
    window.pages.setCurrentIndex(0)
    window.toggle_theme()
    save(window, DEMO / "dashboard-light.png")
    window.toggle_theme()


def dialogs(window, settings) -> None:
    from handwave.ui.macro_editor import PRESETS, MacroEditorDialog
    from handwave.actions.action_definition import parse_macro
    from handwave.ui.onboarding import OnboardingDialog
    from handwave.ui.settings_dialog import SettingsDialog

    onboarding = OnboardingDialog(settings.settings, window)
    onboarding.setStyleSheet(window.styleSheet())
    onboarding.show()
    save(onboarding, IMAGES / "onboarding.png")
    onboarding.pages.setCurrentIndex(4)
    onboarding._sync_controls()
    save(onboarding, IMAGES / "onboarding-auto-pause.png")
    onboarding.close()

    dialog = SettingsDialog(replace(settings.settings, pause_for_apps=("obs64.exe", "Photos.exe")), window)
    dialog.setStyleSheet(window.styleSheet())
    dialog.resize(860, 640)
    dialog.show()
    tabs = dialog.findChild(QTabWidget)
    for name, file in (("Gestures && Actions", "settings-gestures.png"), ("Auto-pause", "settings-auto-pause.png")):
        tabs.setCurrentIndex(next(i for i in range(tabs.count()) if tabs.tabText(i) == name))
        save(dialog, IMAGES / file)
    dialog.close()

    steps = parse_macro([{"type": kind, "value": value} for kind, value in PRESETS["Copy, then paste"]])
    macro = MacroEditorDialog(steps, "Peace Sign", window)
    macro.setStyleSheet(window.styleSheet())
    macro.show()
    save(macro, IMAGES / "macro-editor.png")
    macro.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hagrid-dir", type=Path, help="HaGRID sample folder; without it only the photo-free screens are captured")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    frames = real_frames(args.hagrid_dir, len(HERO_GESTURES)) if args.hagrid_dir else []

    from handwave.ui.main_window import MainWindow

    with tempfile.TemporaryDirectory() as temporary:
        settings = SettingsManager(Path(temporary) / "settings.json")
        camera, microphone = DemoCamera(), DemoClapDetector()
        window = MainWindow(camera_manager=camera, clap_detector=microphone, settings_manager=settings)
        window.resize(1280, 820)
        motion.set_reduced_motion(True)  # MainWindow applies the saved setting; capture settled frames
        window.show()
        microphone.start()
        camera.start_camera()
        if frames:
            dashboards(window, camera, [f[:3] + (None,) for f in frames], frames[0][3])
        dialogs(window, settings)
        window.hide()
        window.deleteLater()
        QApplication.processEvents()
    app.quit()


if __name__ == "__main__":
    main()
