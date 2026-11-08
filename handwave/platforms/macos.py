"""macOS implementations of HandWave's system integrations (EXPERIMENTAL).

Status: written against Apple's documented APIs but **not yet verified on a
Mac** by the maintainers. See docs/macos.md for the testing checklist and how
to contribute fixes.

Everything here imports PyObjC lazily, inside the functions, so importing this
module is safe on any OS and Windows never loads it.

Required permissions (System Settings → Privacy & Security):

* **Camera** and **Microphone** for recognition and double-clap.
* **Accessibility** for sending keys, media keys, clicks and typed text.
* **Screen Recording** (optional) so window titles can be read for
  application profiles; without it only the app name is matched.
"""

from __future__ import annotations

import ctypes
import logging
import subprocess

logger = logging.getLogger(__name__)

# IOKit/hidsystem/ev_keymap.h — the keys on a Mac keyboard's media row.
NX_KEYTYPE = {
    "volume_up": 0,      # NX_KEYTYPE_SOUND_UP
    "volume_down": 1,    # NX_KEYTYPE_SOUND_DOWN
    "mute": 7,           # NX_KEYTYPE_MUTE
    "play_pause": 16,    # NX_KEYTYPE_PLAY
    "next_track": 17,    # NX_KEYTYPE_NEXT
    "previous_track": 18,  # NX_KEYTYPE_PREVIOUS
}
_NS_SYSTEM_DEFINED = 14  # NSEventTypeSystemDefined
_AUX_CONTROL_BUTTONS = 8  # NX_SUBTYPE_AUX_CONTROL_BUTTONS
_KEY_DOWN, _KEY_UP = 0xA, 0xB


def post_media_key(action: str) -> None:
    """Press and release a media key exactly like the keyboard's media row.

    Uses a system-defined NSEvent posted to the HID event tap, which is how
    macOS itself routes play/pause, track and volume keys (so it controls the
    Now Playing app, not only Apple Music). Requires Accessibility permission.
    """
    if action not in NX_KEYTYPE:
        raise ValueError(f"Unsupported media action on macOS: {action}")
    from AppKit import NSEvent  # pyobjc-framework-Cocoa
    import Quartz  # pyobjc-framework-Quartz

    key = NX_KEYTYPE[action]
    for state in (_KEY_DOWN, _KEY_UP):
        event = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            _NS_SYSTEM_DEFINED, (0, 0), state << 8, 0, 0, None, _AUX_CONTROL_BUTTONS,
            (key << 16) | (state << 8), -1,
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event.CGEvent())


def frontmost_app() -> tuple[str | None, str | None]:
    """Return (executable path, window title) of the frontmost app, best effort."""
    try:
        from AppKit import NSWorkspace
    except ImportError:
        return None, None
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None, None
    executable_url = app.executableURL()
    executable = str(executable_url.path()) if executable_url is not None else None
    title = None
    try:
        import Quartz

        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        ) or []
        pid = app.processIdentifier()
        for window in windows:
            if window.get("kCGWindowOwnerPID") == pid and window.get("kCGWindowLayer", 1) == 0:
                # Empty unless Screen Recording permission is granted.
                title = window.get("kCGWindowName") or None
                break
    except Exception:  # Window titles are optional; the app name still matches.
        logger.debug("Window title lookup failed", exc_info=True)
    return executable, title or (str(app.localizedName()) if app.localizedName() else None)


def device_in_use_by_another_app(kind: str) -> bool:
    """True if any camera ("video") or microphone ("audio") is busy in another app.

    AVCaptureDevice reports use by *other* processes only, so HandWave's own
    camera and microphone never count.
    """
    try:
        import AVFoundation
    except ImportError:
        return False
    media = AVFoundation.AVMediaTypeVideo if kind == "video" else AVFoundation.AVMediaTypeAudio
    try:
        devices = AVFoundation.AVCaptureDevice.devicesWithMediaType_(media) or []
        return any(device.isInUseByAnotherApplication() for device in devices)
    except Exception:
        logger.debug("Capture-device query failed", exc_info=True)
        return False


def running_process_names() -> set[str]:
    """Lower-cased names of running apps and processes."""
    names: set[str] = set()
    try:
        from AppKit import NSWorkspace

        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if app.localizedName():
                names.add(str(app.localizedName()).lower())
            url = app.executableURL()
            if url is not None:
                names.add(str(url.lastPathComponent()).lower())
    except ImportError:
        pass
    try:  # background helpers (e.g. Zoom's CptHost) have no NSRunningApplication
        output = subprocess.run(["ps", "-axco", "command"], capture_output=True, text=True, timeout=2).stdout
        names.update(line.strip().lower() for line in output.splitlines()[1:] if line.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return names


def resident_memory_bytes() -> int:
    """Current resident memory of this process (Mach task_info), or peak RSS."""
    try:
        libsystem = ctypes.CDLL("/usr/lib/libSystem.B.dylib")

        class TimeValue(ctypes.Structure):
            _fields_ = [("seconds", ctypes.c_int32), ("microseconds", ctypes.c_int32)]

        class MachTaskBasicInfo(ctypes.Structure):
            _fields_ = [
                ("virtual_size", ctypes.c_uint64), ("resident_size", ctypes.c_uint64),
                ("resident_size_max", ctypes.c_uint64), ("user_time", TimeValue),
                ("system_time", TimeValue), ("policy", ctypes.c_int32), ("suspend_count", ctypes.c_int32),
            ]

        mach_task_basic_info = 20
        info = MachTaskBasicInfo()
        count = ctypes.c_uint32(ctypes.sizeof(info) // 4)
        task = ctypes.c_uint32.in_dll(libsystem, "mach_task_self_")
        libsystem.task_info.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        if libsystem.task_info(task, mach_task_basic_info, ctypes.byref(info), ctypes.byref(count)) == 0:
            return int(info.resident_size)
    except (OSError, ValueError, AttributeError):
        logger.debug("task_info failed; using peak RSS", exc_info=True)
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)  # bytes on macOS


def open_application_command(argv: list[str]) -> list[str]:
    """Launch ``.app`` bundles and bare app names through ``open -a``."""
    if argv and (argv[0].endswith(".app") or ("/" not in argv[0] and argv[0][:1].isupper())):
        return ["open", "-a", argv[0], *(["--args", *argv[1:]] if len(argv) > 1 else [])]
    return argv
