"""Pause recognition automatically while other apps need the camera or a call is on.

Three independent, user-configurable triggers:

1. **Specified apps** – any program in ``pause_for_apps`` is running.
2. **Camera in use** – another app is using the webcam right now.
3. **In a call** – a known calling app is using the microphone, or Zoom's
   meeting process is running.

Detection is local and read-only:

* Camera/microphone use comes from Windows' privacy bookkeeping under
  ``HKCU\\...\\CapabilityAccessManager\\ConsentStore\\{webcam,microphone}``:
  an app whose ``LastUsedTimeStop`` is 0 is using the device *now*. This is
  the same data behind the camera/microphone icons in the taskbar.
* Running programs come from a ToolHelp process snapshot (``ctypes``).

HandWave's own process is always excluded, so its own camera and microphone
use never triggers a pause. Checks run on a background thread every few
seconds, so they never stall the UI or recognition.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from collections.abc import Callable, Iterable
from ctypes import wintypes
from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

CONSENT_STORE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"

# Programs that indicate a call when they use the microphone. Browsers are
# included because Google Meet and other web calls run inside them.
CALL_APPS = {
    "zoom.exe": "Zoom", "cpthost.exe": "Zoom", "ms-teams.exe": "Teams", "teams.exe": "Teams",
    "msteams": "Teams", "discord.exe": "Discord", "skype.exe": "Skype", "slack.exe": "Slack",
    "webex.exe": "Webex", "ciscocollabhost.exe": "Webex", "atmgr.exe": "Webex",
    "whatsapp.exe": "WhatsApp", "whatsappdesktop": "WhatsApp", "facetime": "FaceTime",
    "chrome.exe": "a browser call", "msedge.exe": "a browser call", "firefox.exe": "a browser call",
    "brave.exe": "a browser call", "opera.exe": "a browser call",
}
# Processes that only exist while a meeting is in progress.
MEETING_PROCESSES = {"cpthost.exe": "Zoom"}

# macOS process/app names (lower-cased). Browsers count as call apps because
# Meet and other web calls run in them.
MAC_CALL_APPS = {
    "zoom.us": "Zoom", "microsoft teams": "Teams", "msteams": "Teams", "discord": "Discord",
    "slack": "Slack", "facetime": "FaceTime", "webex": "Webex", "whatsapp": "WhatsApp",
    "skype": "Skype", "google chrome": "a browser call", "safari": "a browser call",
    "firefox": "a browser call", "microsoft edge": "a browser call", "arc": "a browser call", "brave browser": "a browser call",
}
MAC_MEETING_PROCESSES = {"cpthost": "Zoom"}

FRIENDLY_NAMES = {
    "windowscamera": "the Camera app", "zoom.exe": "Zoom", "cpthost.exe": "Zoom", "ms-teams.exe": "Teams",
    "msteams": "Teams", "teams.exe": "Teams", "discord.exe": "Discord", "obs64.exe": "OBS",
    "obs32.exe": "OBS", "chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox",
    "skype.exe": "Skype", "slack.exe": "Slack",
}


def friendly_name(app: str) -> str:
    key = app.lower()
    for marker, name in FRIENDLY_NAMES.items():
        if marker in key:
            return name
    base = key.rsplit("\\", 1)[-1].rsplit("#", 1)[-1]
    return base.split("_", 1)[0].removesuffix(".exe").capitalize() or app


def own_executables() -> set[str]:
    """Paths/names that identify HandWave itself (exe build or Python)."""
    names = set()
    for path in {sys.executable, getattr(sys, "_base_executable", ""), os.path.realpath(sys.executable)}:
        if path:
            names.add(path.lower())
            names.add(os.path.basename(path).lower())
    names.add("handwave.exe")
    return names


# --------------------------------------------------------------------- probes

def apps_using_device(device: str, exclude: set[str] | None = None, registry=None) -> list[str]:
    """Apps currently using ``device`` ("webcam" or "microphone"), best effort."""
    exclude = exclude if exclude is not None else own_executables()
    if registry is None:
        try:
            import winreg as registry  # noqa: N813
        except ImportError:
            return []
    users: list[str] = []
    base = f"{CONSENT_STORE}\\{device}"

    def in_use(path: str) -> bool:
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, path) as key:
                start = registry.QueryValueEx(key, "LastUsedTimeStart")[0]
                stop = registry.QueryValueEx(key, "LastUsedTimeStop")[0]
                return bool(start) and stop == 0
        except OSError:
            return False

    def children(path: str) -> list[str]:
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, path) as key:
                names, index = [], 0
                while True:
                    try:
                        names.append(registry.EnumKey(key, index))
                    except OSError:
                        return names
                    index += 1
        except OSError:
            return []

    for name in children(base):
        if name == "NonPackaged":
            for exe_key in children(f"{base}\\NonPackaged"):
                exe_path = exe_key.replace("#", "\\").lower()
                if exe_path in exclude or os.path.basename(exe_path) in exclude:
                    continue
                if in_use(f"{base}\\NonPackaged\\{exe_key}"):
                    users.append(exe_path)
        elif in_use(f"{base}\\{name}"):
            users.append(name.lower())  # packaged (Store) app family name
    return users


def running_processes() -> set[str]:
    """Lower-cased image names of all running processes (ToolHelp snapshot)."""
    if os.name != "nt":
        return set()

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return set()
    names: set[str] = set()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.lower())
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return names


# ---------------------------------------------------------------------- logic

@dataclass(frozen=True)
class PauseRules:
    camera_in_use: bool = True
    during_calls: bool = True
    apps: tuple[str, ...] = ()

    @property
    def any(self) -> bool:
        return self.camera_in_use or self.during_calls or bool(self.apps)


def evaluate_macos(
    rules: PauseRules,
    processes: Callable[[], set[str]] | None = None,
    in_use_by_another_app: Callable[[str], bool] | None = None,
) -> str | None:
    """macOS rules (EXPERIMENTAL): AVFoundation tells us *whether* another app
    uses the camera/microphone, but not which one, so calls are inferred from
    the microphone being busy while a calling app is running."""
    if not rules.any:
        return None
    from handwave.platforms import macos

    processes = processes or macos.running_process_names
    in_use_by_another_app = in_use_by_another_app or macos.device_in_use_by_another_app
    running = processes() if (rules.apps or rules.during_calls) else set()
    for app in rules.apps:
        if app in running:
            return f"{friendly_name(app)} is running"
    if rules.camera_in_use and in_use_by_another_app("video"):
        return "another app is using the camera"
    if rules.during_calls:
        for process, name in MAC_MEETING_PROCESSES.items():
            if process in running:
                return f"you're in a {name} meeting"
        if in_use_by_another_app("audio"):
            for app, name in MAC_CALL_APPS.items():
                if app in running:
                    return "you're in a call" if name == "a browser call" else f"you're in a {name} call"
    return None


def evaluate(
    rules: PauseRules,
    processes: Callable[[], set[str]] | None = None,
    devices: Callable[[str], Iterable[str]] | None = None,
) -> str | None:
    """Return a short, human reason to pause, or ``None`` to keep running."""
    if not rules.any:
        return None
    from handwave import platforms

    if processes is None and devices is None and platforms.is_macos():
        return evaluate_macos(rules)
    processes = processes or running_processes
    devices = devices or apps_using_device
    running = processes() if (rules.apps or rules.during_calls) else set()
    for app in rules.apps:
        if app in running:
            return f"{friendly_name(app)} is running"
    if rules.camera_in_use:
        users = list(devices("webcam"))
        if users:
            return f"{friendly_name(users[0])} is using the camera"
    if rules.during_calls:
        for process, name in MEETING_PROCESSES.items():
            if process in running:
                return f"you're in a {name} meeting"
        for user in devices("microphone"):
            for marker, name in CALL_APPS.items():
                if marker in user:
                    return "you're in a call" if name == "a browser call" else f"you're in a {name} call"
    return None


class AutoPauseMonitor(QObject):
    """Poll the rules on a background thread and report changes on the UI thread.

    ``reason_changed`` carries the pause reason, or an empty string when the
    conditions clear. It is emitted only when the reason changes.
    """

    reason_changed = pyqtSignal(str)
    INTERVAL_SECONDS = 2.5

    def __init__(self, rules: PauseRules | None = None, evaluator: Callable[[PauseRules], str | None] | None = None) -> None:
        super().__init__()
        self._rules = rules or PauseRules()
        self._evaluate = evaluator or evaluate
        self._reason = ""
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def reason(self) -> str:
        return self._reason

    def configure(self, rules: PauseRules) -> None:
        self._rules = rules
        self._wake.set()  # re-check promptly with the new rules

    def check_now(self) -> str:
        """Evaluate synchronously (used once at startup) and publish any change."""
        self._publish(self._safe_evaluate())
        return self._reason

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="HandWave auto-pause", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self._publish(self._safe_evaluate())
            self._wake.wait(self.INTERVAL_SECONDS)
            self._wake.clear()

    def _safe_evaluate(self) -> str:
        try:
            return self._evaluate(self._rules) or ""
        except Exception:  # Detection is best effort; never break the app.
            logger.debug("Auto-pause check failed", exc_info=True)
            return self._reason

    def _publish(self, reason: str) -> None:
        if reason != self._reason:
            self._reason = reason
            logger.info("Auto-pause condition: %s", reason or "cleared")
            # Emitting from the worker thread is safe: the connection to the
            # UI-thread receivers is queued automatically by Qt.
            self.reason_changed.emit(reason)
