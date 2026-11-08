"""Platform detection and per-OS locations.

HandWave targets Windows; macOS support is **experimental** (see
docs/macos.md). Platform checks read ``sys.platform`` at call time so tests
can exercise both paths on any machine.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


def os_label() -> str:
    """Name of the OS for user-facing text."""
    return "macOS" if is_macos() else "Windows"


def app_data_dir() -> Path:
    """Per-user folder for HandWave's settings, profiles and templates."""
    if is_macos():
        return Path.home() / "Library" / "Application Support" / "HandWave"
    if is_windows():
        roaming = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        return (Path(roaming) if roaming else Path.home() / "AppData" / "Roaming") / "HandWave"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "HandWave"


def config_dir() -> Path:
    return app_data_dir() / "config"
