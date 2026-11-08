"""Load the newest Microsoft C++ runtime before any native library.

PyQt6 6.7 ships its own ``msvcp140.dll`` (14.26, from 2020). Whichever copy
loads first serves the whole process, and Qt is usually first. OpenCV and
MediaPipe are built with newer Visual Studio releases (14.40+), whose
``std::mutex`` is incompatible with that old runtime; mixing them causes
access violations in native worker threads (reproduced in HandWave's test
suite). Loading the system's (newer, backward-compatible) runtime first
makes every module share it.

This must run before PyQt6, cv2 or mediapipe are imported; ``handwave``
calls it on package import.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

RUNTIME_DLLS = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll")
MINIMUM_VERSION = (14, 40)  # first runtime with the new std::mutex layout


def _file_version(path: str) -> tuple[int, int] | None:
    import ctypes
    from ctypes import wintypes

    version = ctypes.WinDLL("version")
    size = version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return None
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, data):
        return None
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(data, "\\", ctypes.byref(pointer), ctypes.byref(length)):
        return None
    most_significant = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD * 13)).contents[2]
    return most_significant >> 16, most_significant & 0xFFFF


def preload_msvc_runtime() -> list[str]:
    """Load the system C++ runtime if it is new enough. Returns the DLLs loaded."""
    if os.name != "nt":
        return []
    if any(name in sys.modules for name in ("PyQt6.QtCore", "cv2", "mediapipe")):
        logger.debug("C++ runtime preload skipped: native libraries already loaded")
        return []
    import ctypes

    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    msvcp = os.path.join(system32, "msvcp140.dll")
    if not os.path.isfile(msvcp):
        return []
    try:
        version = _file_version(msvcp)
    except OSError:
        version = None
    if version is None or version < MINIMUM_VERSION:
        return []
    loaded = []
    for name in RUNTIME_DLLS:
        path = os.path.join(system32, name)
        if os.path.isfile(path):
            try:
                ctypes.WinDLL(path)
                loaded.append(name)
            except OSError:
                logger.debug("Could not preload %s", path, exc_info=True)
    return loaded


def prepare_native_libraries() -> None:
    """Fix the load order of native libraries before Qt is imported.

    1. Load the newest Microsoft C++ runtime (see ``preload_msvc_runtime``).
    2. Load OpenCV before PyQt6. With Qt first, the test suite crashes
       intermittently in a native worker thread (access violation, no Python
       frames); loading OpenCV first made 3/3 full runs pass versus 3/3
       crashes. The exact cause is not known; keep this order.
    """
    preload_msvc_runtime()
    if "PyQt6.QtCore" not in sys.modules:
        try:
            import cv2  # noqa: F401
        except ImportError:  # OpenCV missing: the camera reports a clear error later
            pass
