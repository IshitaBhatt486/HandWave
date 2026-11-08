"""Low-overhead, passive measurements for the recognition pipeline."""

from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineMetrics:
    """One snapshot of capture, recognition, latency, and process health."""

    camera_fps: float = 0.0
    recognition_fps: float = 0.0
    latency_ms: float = 0.0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    dropped_frames: int = 0
    active_threads: int = 0
    hands_detected: int = 0
    left_hand_pose: str | None = None
    right_hand_pose: str | None = None
    two_hand_gesture: str = "Unknown"
    motion_gesture: str = "Unknown"
    motion_source: str = "None"


class DiagnosticsMonitor:
    """Sample process CPU and working-set use without affecting recognition."""

    def __init__(self, clock=time.perf_counter, cpu_clock=time.process_time) -> None:
        self._clock = clock
        self._cpu_clock = cpu_clock
        self._last_wall = clock()
        self._last_cpu = cpu_clock()
        self.cpu_percent = 0.0
        self.memory_mb = 0.0

    def update(self) -> tuple[float, float]:
        now, cpu_now = self._clock(), self._cpu_clock()
        elapsed = now - self._last_wall
        if elapsed >= 1.0:
            cores = max(os.cpu_count() or 1, 1)
            self.cpu_percent = max(0.0, (cpu_now - self._last_cpu) / elapsed * 100.0 / cores)
            self.memory_mb = self._working_set_bytes() / (1024 * 1024)
            self._last_wall, self._last_cpu = now, cpu_now
        return self.cpu_percent, self.memory_mb

    @staticmethod
    def _working_set_bytes() -> int:
        from handwave import platforms

        if platforms.is_macos():
            from handwave.platforms.macos import resident_memory_bytes

            return resident_memory_bytes()
        if os.name != "nt":
            return 0

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        # Declare the signatures: without them ctypes passes the process handle
        # (a 64-bit pseudo-handle, -1) as a 32-bit int, the call fails on
        # 64-bit Windows, and memory always read 0 MB.
        from ctypes import wintypes

        kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return int(counters.WorkingSetSize)
        return 0
