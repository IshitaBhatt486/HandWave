"""Guided, local-only microphone calibration for double-clap detection."""
from __future__ import annotations

import statistics
from enum import IntEnum

from PyQt6.QtCore import QTimer

from handwave import platforms
from PyQt6.QtWidgets import QDialog, QFormLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout


class Step(IntEnum): IDLE = 0; NOISE = 1; CLAPS = 2; TEST = 3


class MicrophoneDialog(QDialog):
    """Four-step wizard; only scalar levels are measured or persisted."""
    NOISE_DURATION_MS, REQUIRED_CLAPS = 3000, 5

    def __init__(self, detector, settings_manager=None, parent=None) -> None:
        super().__init__(parent); self.detector, self.settings_manager = detector, settings_manager
        self.setWindowTitle("HandWave Microphone Calibration")
        self.setMinimumWidth(420)
        self.step_label, self.microphone, self.health = QLabel(), QLabel(), QLabel()
        self.rms, self.peak, self.confidence, self.sensitivity = QLabel(), QLabel(), QLabel(), QLabel()
        self.instructions = QLabel("Press Recalibrate to adapt HandWave to this microphone."); self.instructions.setWordWrap(True)
        self.progress, self.recalibrate, self.reset = QProgressBar(), QPushButton("Recalibrate"), QPushButton("Reset Calibration")
        self.close_button = QPushButton("Close")
        self.recalibrate.clicked.connect(self.start_wizard); self.reset.clicked.connect(self.reset_calibration); self.close_button.clicked.connect(self.accept)
        form = QFormLayout(); form.setHorizontalSpacing(28); form.setVerticalSpacing(10)
        for title, value in (("Wizard",self.step_label),("Microphone",self.microphone),("Health",self.health),("Live RMS",self.rms),("Live peak",self.peak),("Confidence",self.confidence),("Sensitivity",self.sensitivity)): form.addRow(title,value)
        self.progress.setTextVisible(False); self.progress.setFixedHeight(3)
        title = QLabel("Microphone"); title.setObjectName("cardTitle")
        subtitle = QLabel("Double-clap to turn recognition on or off."); subtitle.setObjectName("cardSubtitle")
        layout=QVBoxLayout(self); layout.setContentsMargins(30, 26, 30, 26); layout.setSpacing(14)
        layout.addWidget(title); layout.addWidget(subtitle); layout.addSpacing(10); layout.addLayout(form); layout.addSpacing(6); layout.addWidget(self.instructions); layout.addWidget(self.progress); layout.addWidget(self.recalibrate); layout.addWidget(self.reset); layout.addWidget(self.close_button)
        self._step, self._elapsed, self._noise, self._claps, self._last_callback, self._last_clap_callback, self._confidence = Step.IDLE, 0, [], [], 0, -10, 0
        self._timer=QTimer(self); self._timer.setInterval(100); self._timer.timeout.connect(self._tick); self._timer.start()
        if hasattr(detector, "double_clap"):
            detector.double_clap.connect(self._test_passed)
        if hasattr(detector, "error"):
            detector.error.connect(self._microphone_error)
        if not detector.is_listening: detector.start()
        self._refresh()

    def done(self, result: int) -> None:
        """Release the polling timer and detector connections on close.

        The dialog is parented to the main window, so without this every
        closed dialog would keep polling and receiving double-clap signals.
        """
        self._timer.stop()
        for signal, slot in (("double_clap", self._test_passed), ("error", self._microphone_error)):
            if hasattr(self.detector, signal):
                try:
                    getattr(self.detector, signal).disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        super().done(result)

    def start_wizard(self) -> None:
        if not self.detector.is_listening:
            self.instructions.setText("Waiting for automatic microphone connection."); return
        self._step, self._elapsed, self._noise, self._claps = Step.NOISE, 0, [], []
        self.progress.setRange(0,self.NOISE_DURATION_MS); self.progress.setValue(0); self.recalibrate.setEnabled(False)
        self.instructions.setText("Step 1 of 4: stay quiet while background noise is measured.")

    def reset_calibration(self) -> None:
        try:
            if self.settings_manager:
                s=self.settings_manager.update(clap_min_peak=.02,clap_rms_threshold=0.,clap_noise_multiplier=2.5,double_clap_min_interval=.12,double_clap_max_interval=1.)
                self.detector.configure(device=s.microphone_device,min_peak=s.clap_min_peak,rms_threshold=s.clap_rms_threshold,noise_multiplier=s.clap_noise_multiplier,min_clap_separation=s.double_clap_min_interval,max_clap_separation=s.double_clap_max_interval)
        except (OSError, ValueError) as exc:
            self.instructions.setText(f"Could not reset calibration: {exc}"); return
        self._step=Step.IDLE; self._confidence=0; self.instructions.setText("Calibration reset to the default sensitivity."); self._refresh()

    def _tick(self) -> None:
        s=self.detector.status()
        if s.callback_count != self._last_callback:
            self._last_callback=s.callback_count
            # Prefer the loudest block since the last poll: audio blocks arrive
            # roughly every 23 ms, far faster than this 100 ms UI timer.
            levels = self.detector.consume_levels() if hasattr(self.detector, "consume_levels") else None
            peak, peak_rms, mean_rms = levels if levels else (s.input_level, s.rms, s.rms)
            if self._step == Step.NOISE: self._noise.append(mean_rms)
            elif self._step == Step.CLAPS and self._is_clap(peak, peak_rms, s.callback_count): self._claps.append((peak,peak_rms)); self._last_clap_callback=s.callback_count; self.progress.setValue(len(self._claps))
        if self._step == Step.NOISE:
            self._elapsed += self._timer.interval(); self.progress.setValue(self._elapsed)
            if self._elapsed >= self.NOISE_DURATION_MS: self._start_claps()
        elif self._step == Step.CLAPS and len(self._claps) >= self.REQUIRED_CLAPS: self._save_profile()
        self._refresh(s)

    def _is_clap(self, peak: float, rms: float, callback_count: int) -> bool:
        noise=max(statistics.fmean(self._noise) if self._noise else .002,.002)
        return peak >= max(.02,noise*3) and rms >= noise*1.2 and callback_count-self._last_clap_callback >= 4

    def _start_claps(self) -> None:
        self._step=Step.CLAPS; self.progress.setRange(0,self.REQUIRED_CLAPS); self.progress.setValue(0)
        self.instructions.setText("Step 2 of 4: perform 5 normal, separate claps.")

    def _save_profile(self) -> None:
        if not self._noise or len(self._claps) < self.REQUIRED_CLAPS:
            self._step=Step.IDLE; self.recalibrate.setEnabled(True)
            self.instructions.setText("Calibration needs live microphone samples. Check the microphone status and try again.")
            return
        noise=max(statistics.fmean(self._noise),.001); peaks,levels=zip(*self._claps)
        peak=max(.01,statistics.median(peaks)*.35,noise*3); rms=max(.001,statistics.median(levels)*.30,noise*1.5)
        self._confidence=min(100,round(40+min(60,statistics.median(peaks)/noise*4))); self._step=Step.TEST
        try:
            if self.settings_manager:
                s=self.settings_manager.update(clap_min_peak=peak,clap_rms_threshold=rms,double_clap_min_interval=.12,double_clap_max_interval=1.)
                self.detector.configure(device=s.microphone_device,min_peak=peak,rms_threshold=rms,noise_multiplier=s.clap_noise_multiplier,min_clap_separation=.12,max_clap_separation=1.)
            else: self.detector.min_peak,self.detector.rms_threshold=peak,rms
        except (OSError, ValueError) as exc:
            self._step=Step.IDLE; self.recalibrate.setEnabled(True)
            self.instructions.setText(f"Calibration could not be saved: {exc}")
            return
        self.instructions.setText("Step 3 complete: thresholds saved. Step 4: double-clap now to test detection."); self.recalibrate.setEnabled(True)

    def _test_passed(self) -> None:
        if self._step == Step.TEST:
            self._step = Step.IDLE
            self.instructions.setText("Step 4 complete: double-clap detected. Calibration is ready.")

    def _microphone_error(self, message: str) -> None:
        if self._step != Step.IDLE:
            self._step=Step.IDLE; self.recalibrate.setEnabled(True)
        self.instructions.setText(f"Microphone error: {message}")

    def _refresh(self,s=None) -> None:
        s=s or self.detector.status(); names={Step.IDLE:"Ready",Step.NOISE:"1. Background noise",Step.CLAPS:"2. Five claps",Step.TEST:"4. Test double-clap"}
        self.step_label.setText(names[self._step]); self.microphone.setText(s.device or f"{platforms.os_label()} default"); self.rms.setText(f"{s.rms:.5f}"); self.peak.setText(f"{s.input_level:.5f}")
        self.confidence.setText(f"{self._confidence}%"); self.sensitivity.setText(f"Peak {getattr(self.detector,'min_peak',.02):.3f}  •  RMS {getattr(self.detector,'rms_threshold',0):.3f}")
        self.health.setText("Connected • Listening" if s.available and s.stream_status in {"running","degraded"} else "Microphone error" if s.error else "No microphone detected")
