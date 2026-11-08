"""Local, Windows-only lookup of the foreground application.

Limitations: relies on ``user32``/``kernel32`` via ``ctypes`` and reads another
process's image path via ``PROCESS_QUERY_LIMITED_INFORMATION``. This can fail
for elevated/protected processes (permission denied) or when no window has
focus (e.g. the desktop itself); callers must treat a failure as "unknown
foreground app", never as a crash.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForegroundAppInfo:
    """The best-effort identity of whatever window currently has focus."""

    executable: str | None
    window_title: str | None


def get_foreground_app() -> ForegroundAppInfo:
    """Return the foreground window's process image name and title.

    Returns ``ForegroundAppInfo(None, None)`` whenever the lookup cannot be
    performed (non-Windows platform, no foreground window, access denied),
    rather than raising.
    """
    from handwave import platforms

    if platforms.is_macos():
        try:
            from handwave.platforms.macos import frontmost_app

            return ForegroundAppInfo(*frontmost_app())
        except Exception:  # experimental macOS path: never break profile switching
            logger.debug("macOS foreground lookup failed", exc_info=True)
            return ForegroundAppInfo(None, None)
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ForegroundAppInfo(None, None)

        length = user32.GetWindowTextLengthW(hwnd)
        title = None
        if length > 0:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value or None

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ForegroundAppInfo(None, title)

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return ForegroundAppInfo(None, title)
        try:
            path_buffer = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(len(path_buffer))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, path_buffer, ctypes.byref(size)):
                return ForegroundAppInfo(None, title)
            return ForegroundAppInfo(path_buffer.value or None, title)
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError, ValueError):
        logger.debug("Foreground application lookup failed", exc_info=True)
        return ForegroundAppInfo(None, None)
