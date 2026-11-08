import tracemalloc

import numpy as np

from handwave.vision.camera_manager import DiagnosticsMonitor, LatestFrameBuffer


def test_latest_frame_buffer_skips_stale_frames_and_stays_bounded():
    buffer = LatestFrameBuffer()
    frames = [np.full((8, 8, 3), value, dtype=np.uint8) for value in range(10)]
    for frame in frames:
        buffer.put(frame)

    latest = buffer.get()
    assert np.array_equal(latest, frames[-1])
    assert buffer.frames_dropped == 9
    assert buffer.get(timeout=0) is None


def test_accelerated_30_minute_buffer_soak_has_no_growth():
    """Simulate 30 FPS for 30 minutes without wall-clock waiting."""
    buffer = LatestFrameBuffer()
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for index in range(30 * 60 * 30):
        buffer.put(frame)
        if index % 3 == 0:
            buffer.get(timeout=0)
    buffer.get(timeout=0)
    after = tracemalloc.take_snapshot()
    growth = sum(stat.size_diff for stat in after.compare_to(before, "filename"))
    tracemalloc.stop()

    assert growth < 1_000_000
    assert buffer._packet is None


def test_buffer_preserves_capture_profiling_metadata():
    buffer = LatestFrameBuffer()
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    buffer.put(frame, captured_at=12.5, camera_fps=29.7)

    packet = buffer.get_packet(timeout=0)

    assert packet is not None
    assert packet.frame is frame
    assert packet.captured_at == 12.5
    assert packet.camera_fps == 29.7


def test_diagnostics_reports_cpu_and_memory_estimates():
    wall = iter((0.0, 2.0))
    cpu = iter((0.0, 0.2))
    monitor = DiagnosticsMonitor(clock=wall.__next__, cpu_clock=cpu.__next__)
    cpu_percent, memory_mb = monitor.update()
    assert cpu_percent >= 0
    assert memory_mb >= 0


def test_working_set_is_actually_measured_on_windows():
    """Regression: undeclared ctypes signatures made this always return 0."""
    import os
    import pytest
    from handwave.diagnostics.pipeline_metrics import DiagnosticsMonitor

    if os.name != "nt":
        pytest.skip("Windows-only measurement")
    assert DiagnosticsMonitor._working_set_bytes() > 10 * 1024 * 1024


def test_process_uses_the_newer_system_cpp_runtime():
    """Regression: PyQt6 6.7's 2020 msvcp140 crashed newer OpenCV/MediaPipe threads."""
    import ctypes
    import os
    from ctypes import wintypes

    import pytest

    if os.name != "nt":
        pytest.skip("Windows-only")
    import cv2  # noqa: F401
    import PyQt6.QtWidgets  # noqa: F401
    from handwave._runtime import MINIMUM_VERSION, _file_version

    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    buffer = ctypes.create_unicode_buffer(1024)
    kernel32.GetModuleFileNameW(kernel32.GetModuleHandleW("msvcp140.dll"), buffer, 1024)
    assert _file_version(buffer.value) >= MINIMUM_VERSION, buffer.value
