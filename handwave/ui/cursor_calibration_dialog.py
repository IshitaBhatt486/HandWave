"""Accessible cursor reach calibration wizard using normalized fingertip positions."""

from __future__ import annotations

import statistics
from enum import IntEnum

from PyQt6.QtCore import QRectF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QProgressBar, QVBoxLayout, QWidget
from handwave.actions.cursor_reach_mapper import apply_dead_zone, normalize_reach
from handwave.services.monitor_layout import MonitorLayout
from handwave import platforms


class CalibrationStep(IntEnum):
    WELCOME = 0; CENTER = 1; LEFT = 2; RIGHT = 3; TOP = 4; BOTTOM = 5; VALIDATION = 6; RESULTS = 7


class ReachPreview(QWidget):
    """Draw the requested target and the completed comfortable movement box."""
    def __init__(self, parent=None) -> None:
        super().__init__(parent); self.step = CalibrationStep.WELCOME; self.profile: dict[str, float] | None = None
        self.frame: QImage | None = None; self.hand: tuple[float, float] | None = None; self.dead_zone_percent = 10; self.validation_target: tuple[float, float] | None = None
        self.setMinimumSize(380, 230); self.setAccessibleName("Cursor reach calibration preview")

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0e0e0f"))
        if self.frame is not None:
            painter.drawImage(self.rect(), self.frame)
        bounds = self.rect().adjusted(24, 24, -24, -24)
        if self.profile:
            p = self.profile; painter.setPen(QPen(QColor("#c9a96e"), 2)); painter.setBrush(QColor(201, 169, 110, 34))
            # QRectF: the reach box is fractional; int-only drawRect overloads
            # raise TypeError, which aborts the app from inside paintEvent.
            painter.drawRect(QRectF(bounds.left()+p["left"]*bounds.width(), bounds.top()+p["top"]*bounds.height(), (p["right"]-p["left"])*bounds.width(), (p["bottom"]-p["top"])*bounds.height()))
            painter.setBrush(QColor("#fbbf24")); painter.drawEllipse(int(bounds.left()+p["center_x"]*bounds.width()-8), int(bounds.top()+p["center_y"]*bounds.height()-8), 16, 16)
        capture_targets = {CalibrationStep.CENTER:(.5,.5), CalibrationStep.LEFT:(.15,.5), CalibrationStep.RIGHT:(.85,.5), CalibrationStep.TOP:(.5,.15), CalibrationStep.BOTTOM:(.5,.85)}
        if self.step in capture_targets:
            target = capture_targets[self.step]
            x,y = bounds.left()+target[0]*bounds.width(), bounds.top()+target[1]*bounds.height()
            painter.setPen(QPen(QColor("#c9a96e"), 3)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawEllipse(int(x-22),int(y-22),44,44)
            painter.setBrush(QColor("#c9a96e")); painter.drawEllipse(int(x-5),int(y-5),10,10)
        if self.hand:
            x,y = bounds.left()+self.hand[0]*bounds.width(), bounds.top()+self.hand[1]*bounds.height()
            painter.setPen(QPen(QColor("#f97316"), 2)); painter.setBrush(QColor("#fb923c")); painter.drawEllipse(int(x-7),int(y-7),14,14)
        # The screen mockup is deliberately independent of OS cursor APIs.
        screen = self.rect().adjusted(self.width()-172, 18, -18, -self.height()+112)
        painter.setPen(QPen(QColor("#e2e8f0"), 2)); painter.setBrush(QColor(15, 23, 42, 220)); painter.drawRoundedRect(screen, 5, 5)
        zone = self.dead_zone_percent / 100
        painter.setPen(QPen(QColor("#94a3b8"), 1, Qt.PenStyle.DashLine)); painter.setBrush(QColor(148, 163, 184, 35))
        painter.drawRect(int(screen.center().x()-screen.width()*zone/2), int(screen.center().y()-screen.height()*zone/2), int(screen.width()*zone), int(screen.height()*zone))
        if self.hand:
            u,v = self._map_to_virtual_cursor(*self.hand)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor("#fbbf24")); painter.drawEllipse(int(screen.left()+u*screen.width()-5), int(screen.top()+v*screen.height()-5), 10, 10)
        if self.validation_target:
            tx,ty=self.validation_target; painter.setPen(QPen(QColor("#c9a96e"), 2)); painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(int(screen.left()+tx*screen.width()-10), int(screen.top()+ty*screen.height()-10), 20, 20)
        painter.setPen(QColor("#e2e8f0")); painter.drawText(screen.adjusted(5, 4, -5, -4), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, "Virtual screen")
        painter.end()

    def _map_to_virtual_cursor(self, x: float, y: float) -> tuple[float, float]:
        p = self.profile or {"left": .1, "right": .9, "top": .1, "bottom": .9, "center_x": .5, "center_y": .5}
        return (apply_dead_zone(normalize_reach(x,p["left"],p["center_x"],p["right"]),self.dead_zone_percent), apply_dead_zone(normalize_reach(y,p["top"],p["center_y"],p["bottom"]),self.dead_zone_percent))


class CursorCalibrationDialog(QDialog):
    """Seven-screen cursor reach wizard fed by ``CameraManager.fingertips_updated``."""
    virtual_cursor_position = pyqtSignal(int, int, bool)
    COUNTDOWN_SECONDS, HOLD_MS = 3, 700
    VALIDATION_TARGETS = ((.5,.5),(.15,.15),(.85,.15),(.15,.85),(.85,.85))
    _TEXT = {
        CalibrationStep.CENTER: ("Center position", "Place your hand where it feels natural."),
        CalibrationStep.LEFT: ("Left reach", "Move your hand as far left as comfortable."),
        CalibrationStep.RIGHT: ("Right reach", "Move your hand as far right as comfortable."),
        CalibrationStep.TOP: ("Top reach", "Move your hand as high as comfortable."),
        CalibrationStep.BOTTOM: ("Bottom reach", "Move your hand as low as comfortable."),
    }

    def __init__(self, settings_manager, parent=None) -> None:
        super().__init__(parent); self.settings_manager = settings_manager
        self.setWindowTitle("Cursor Reach Calibration"); self.setMinimumWidth(520); self.setModal(True)
        self.title, self.instruction, self.countdown = QLabel(), QLabel(), QLabel()
        self.title.setObjectName("cardTitle"); self.instruction.setWordWrap(True); self.countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.countdown.setAccessibleName("Calibration countdown")
        self.preview, self.progress = ReachPreview(), QProgressBar(); self.progress.setRange(0, 7)
        self.score, self.coverage, self.stability = QLabel(), QLabel(), QLabel()
        self.score.setAccessibleName("Calibration score"); self.coverage.setAccessibleName("Reach coverage"); self.stability.setAccessibleName("Stability score")
        self.dead_zone = QComboBox(); self.dead_zone.addItems(["5%", "10%", "15%"])
        self.dead_zone.setCurrentText(f"{settings_manager.settings.cursor_dead_zone_percent}%")
        self.preview.dead_zone_percent = settings_manager.settings.cursor_dead_zone_percent
        self.dead_zone.setAccessibleName("Cursor center dead zone")
        self.dead_zone.currentTextChanged.connect(self._set_dead_zone)
        self.smoothing = QComboBox(); self.smoothing.addItems(["Low", "Medium", "High"])
        self.smoothing.setCurrentText(settings_manager.settings.cursor_smoothing.title())
        self.smoothing.setAccessibleName("Cursor smoothing level")
        self.target_mode = QComboBox(); self.target_mode.addItem("Primary monitor only", "primary"); self.target_mode.addItem("All monitors", "all")
        self.target_mode.setCurrentIndex(0 if settings_manager.settings.cursor_target_mode == "primary" else 1)
        self.target_mode.setAccessibleName("Cursor calibration monitor target")
        self.monitor_status = QLabel(); self.monitor_status.setAccessibleName("Detected monitor layout")
        self._layout = MonitorLayout.current()
        self._update_monitor_status()
        self.target_mode.currentIndexChanged.connect(self._update_monitor_status)
        self.start, self.redo, self.accept_button, self.cancel = QPushButton("Start Calibration"), QPushButton("Redo Calibration"), QPushButton("Save Calibration"), QPushButton("Cancel")
        self.retry_step = QPushButton("Retry Step")
        self.start.clicked.connect(self.start_calibration); self.redo.clicked.connect(self.start_calibration); self.accept_button.clicked.connect(self.accept_calibration); self.cancel.clicked.connect(self.reject)
        self.retry_step.clicked.connect(self._retry_step)
        actions=QHBoxLayout(); actions.addWidget(self.start); actions.addWidget(self.retry_step); actions.addWidget(self.redo); actions.addWidget(self.accept_button); actions.addStretch(); actions.addWidget(self.cancel)
        dead_zone_row=QHBoxLayout(); dead_zone_row.addWidget(QLabel("Center dead zone")); dead_zone_row.addWidget(self.dead_zone); dead_zone_row.addStretch()
        smoothing_row=QHBoxLayout(); smoothing_row.addWidget(QLabel("Cursor smoothing")); smoothing_row.addWidget(self.smoothing); smoothing_row.addStretch()
        target_row=QHBoxLayout(); target_row.addWidget(QLabel("Cursor target")); target_row.addWidget(self.target_mode); target_row.addStretch()
        metrics=QHBoxLayout(); metrics.addWidget(self.score); metrics.addWidget(self.coverage); metrics.addWidget(self.stability)
        layout=QVBoxLayout(self); layout.setSpacing(14); layout.addWidget(self.title); layout.addWidget(self.instruction); layout.addWidget(self.preview); layout.addWidget(self.countdown); layout.addWidget(self.progress); layout.addWidget(self.monitor_status); layout.addLayout(metrics); layout.addLayout(target_row); layout.addLayout(dead_zone_row); layout.addLayout(smoothing_row); layout.addLayout(actions)
        self._step, self._remaining_ms, self._samples, self._values = CalibrationStep.WELCOME, 0, [], {}
        self._step_failed, self._welcome_message = False, ""
        self._validation_index, self._validation_samples, self._validation_results = 0, [], []
        self._timer=QTimer(self); self._timer.setInterval(100); self._timer.timeout.connect(self._advance)
        self._render()

    def feed_fingertips(self, fingertips: object) -> None:
        """Receive camera-thread-safe emitted normalized index-fingertip positions."""
        if not isinstance(fingertips, list) or not fingertips: return
        x,y = fingertips[0]
        self.preview.hand=(float(x),float(y)); self.preview.update()
        if self._step in self._TEXT and self._remaining_ms <= self.HOLD_MS: self._samples.append((float(x),float(y)))
        elif self._step == CalibrationStep.VALIDATION:
            self._emit_calibration_overlay(self._record_validation_point())
            return
        self._emit_calibration_overlay()

    def feed_frame(self, frame: object) -> None:
        """Render the live camera frame only inside the calibration preview."""
        if frame is None or not hasattr(frame, "shape"): return
        height, width = frame.shape[:2]
        rgb = frame[:, :, ::-1].copy()
        self.preview.frame = QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()
        self.preview.update()

    def start_calibration(self) -> None:
        self._step, self._values, self._welcome_message = CalibrationStep.CENTER, {}, ""
        self._validation_score = 0; self._validation_results = []; self._begin_step()

    def _begin_step(self) -> None:
        self._step_failed=False; self._samples=[]; self._remaining_ms=(self.COUNTDOWN_SECONDS*1000)+self.HOLD_MS; self._timer.start(); self._render()

    def _retry_step(self) -> None:
        if self._step in self._TEXT: self._begin_step()

    def _advance(self) -> None:
        self._remaining_ms -= self._timer.interval()
        if self._remaining_ms > 0: self._render(); return
        self._timer.stop()
        if len(self._samples) < 3:
            self._step_failed=True; self._render()
            self.instruction.setText("Hand not detected steadily. Keep your index finger visible, then select Retry Step."); return
        x=statistics.median(point[0] for point in self._samples); y=statistics.median(point[1] for point in self._samples)
        if self._step == CalibrationStep.CENTER:
            self._values["center_x"], self._values["center_y"] = x, y
        elif self._step == CalibrationStep.LEFT:
            self._values["left"] = x
        elif self._step == CalibrationStep.RIGHT:
            self._values["right"] = x
        elif self._step == CalibrationStep.TOP:
            self._values["top"] = y
        else:
            self._values["bottom"] = y
        self._step=CalibrationStep(self._step+1)
        if self._step == CalibrationStep.VALIDATION:
            problem = self._reach_problem()
            if problem:
                self._step, self._welcome_message = CalibrationStep.WELCOME, problem; self._render(); return
            self._start_validation()
        else: self._begin_step()

    MIN_REACH = 0.03

    def _reach_problem(self) -> str:
        """Explain why the captured reach cannot form a usable cursor box."""
        v = self._values
        if not v["left"] + self.MIN_REACH <= v["center_x"] <= v["right"] - self.MIN_REACH:
            return "Left and right reach must be on either side of the center position. Start the calibration again and move further left and right."
        if not v["top"] + self.MIN_REACH <= v["center_y"] <= v["bottom"] - self.MIN_REACH:
            return "Top and bottom reach must be above and below the center position. Start the calibration again and move further up and down."
        return ""

    def accept_calibration(self) -> None:
        if self._step != CalibrationStep.RESULTS: return
        if getattr(self, "_validation_score", 0) < 70 or len(self._validation_results) != len(self.VALIDATION_TARGETS):
            self.instruction.setText("Recalibration recommended before saving.")
            return
        try: self.settings_manager.update(cursor_reach_calibration=self._values, cursor_dead_zone_percent=int(self.dead_zone.currentText().removesuffix("%")), cursor_smoothing=self.smoothing.currentText().lower(), cursor_target_mode=self.target_mode.currentData(), cursor_target_monitor_id=self._layout.primary.identifier if self.target_mode.currentData() == "primary" else None, cursor_monitor_layout_fingerprint=self._layout.fingerprint)
        except ValueError as exc: self.instruction.setText(f"Calibration needs redo: {exc}"); return
        self.accept()

    def _start_validation(self) -> None:
        self._validation_index, self._validation_samples, self._validation_results = 0, [], []
        self._render()

    def _record_validation_point(self) -> tuple[float, float] | None:
        if self.preview.hand is None: return None
        cursor = self.preview._map_to_virtual_cursor(*self.preview.hand)
        target = self.VALIDATION_TARGETS[self._validation_index]
        distance = ((cursor[0]-target[0])**2 + (cursor[1]-target[1])**2) ** .5
        on_target = distance <= .12
        if on_target:
            self._validation_samples.append(distance)
        if len(self._validation_samples) < 6: return target if on_target else None
        accuracy = max(0., 100*(1-statistics.fmean(self._validation_samples)/.12))
        stability = max(0., 100*(1-(statistics.pstdev(self._validation_samples)/.05)))
        self._validation_results.append((accuracy, stability)); self._validation_index += 1; self._validation_samples=[]
        if self._validation_index >= len(self.VALIDATION_TARGETS): self._finish_validation()
        else: self._render()
        return target if on_target else None

    def _emit_calibration_overlay(self, snap_target: tuple[float, float] | None = None) -> None:
        """Send provisional cursor coordinates to the click-through overlay."""
        if self.preview.hand is None:
            return
        x, y = self.preview._map_to_virtual_cursor(*self.preview.hand)
        if snap_target is not None:
            x, y = snap_target
        target = self._layout.target(self.target_mode.currentData())
        self.virtual_cursor_position.emit(
            target.x + round(x * (target.width - 1)),
            target.y + round(y * (target.height - 1)),
            snap_target is not None,
        )

    def _finish_validation(self) -> None:
        accuracy=statistics.fmean(result[0] for result in self._validation_results)
        stability=statistics.fmean(result[1] for result in self._validation_results)
        coverage=100*len(self._validation_results)/len(self.VALIDATION_TARGETS)
        self._validation_score=(accuracy*.5)+(coverage*.3)+(stability*.2)
        self._step=CalibrationStep.RESULTS; self._render()

    def _set_dead_zone(self, value: str) -> None:
        self.preview.dead_zone_percent = int(value.removesuffix("%")); self.preview.update()

    def _update_monitor_status(self) -> None:
        target = self._layout.target(self.target_mode.currentData())
        label = "primary monitor" if self.target_mode.currentData() == "primary" else "all monitors"
        self.monitor_status.setText(f"Using {label}: {target.width} × {target.height} px ({len(self._layout.monitors)} detected)")

    def _render(self) -> None:
        self.preview.validation_target=self.VALIDATION_TARGETS[self._validation_index] if self._step == CalibrationStep.VALIDATION else None
        self.preview.step=self._step; self.preview.profile=self._display_profile(); self.preview.update()
        self.progress.setValue(min(int(self._step),7)); self.start.setVisible(self._step == CalibrationStep.WELCOME); self.redo.setVisible(self._step in {CalibrationStep.VALIDATION, CalibrationStep.RESULTS}); self.accept_button.setVisible(self._step == CalibrationStep.RESULTS)
        self.retry_step.setVisible(self._step in self._TEXT and self._step_failed)
        score=getattr(self,"_validation_score",0); results=self._validation_results
        stability=statistics.fmean(item[1] for item in results) if results else 0
        self.score.setText(f"Calibration Score  {score:.0f}%"); self.coverage.setText(f"Reach Coverage  {len(results)}/{len(self.VALIDATION_TARGETS)}"); self.stability.setText(f"Stability Score  {stability:.0f}%")
        if self._step == CalibrationStep.WELCOME: self.title.setText("Cursor reach calibration"); self.instruction.setText(self._welcome_message or "We will learn the limits of your comfortable hand movement. Keep your index finger visible to the camera."); self.countdown.setText("")
        elif self._step == CalibrationStep.VALIDATION:
            self.title.setText("Validate your calibration"); self.instruction.setText(f"Move the virtual cursor to target {self._validation_index+1} of {len(self.VALIDATION_TARGETS)} and hold it steady."); self.countdown.setText(f"Virtual cursor only — {platforms.os_label()} cursor will not move")
        elif self._step == CalibrationStep.RESULTS:
            valid=score >= 70 and len(results) == len(self.VALIDATION_TARGETS) and stability >= 60
            self.title.setText("Calibration validation results"); self.instruction.setText("Calibration is ready to save." if valid else "Recalibration recommended: reach accuracy or stability was too low."); self.countdown.setText("Results ready")
            self.accept_button.setEnabled(valid)
        else:
            title,text=self._TEXT[self._step]; self.title.setText(title); self.instruction.setText(text)
            self.countdown.setText(f"Hold position — capture in {max(0,(self._remaining_ms-self.HOLD_MS+999)//1000)}" if self._remaining_ms>self.HOLD_MS else "Capturing stable position…")

    def _display_profile(self) -> dict[str, float]:
        """Use captured reach where available and safe provisional bounds otherwise."""
        return {"center_x": self._values.get("center_x", .5), "center_y": self._values.get("center_y", .5), "left": self._values.get("left", .1), "right": self._values.get("right", .9), "top": self._values.get("top", .1), "bottom": self._values.get("bottom", .9)}
