"""Start-at-login integration: Windows Startup folder, macOS LaunchAgent."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from handwave.config.atomic_write import atomic_replace


class WindowsStartupManager:
    """Create or remove HandWave's launcher in the Windows Startup folder."""

    LAUNCHER_NAME = "HandWave.cmd"

    def __init__(
        self,
        startup_folder: str | Path | None = None,
        executable: str | Path | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        self.startup_folder = (
            Path(startup_folder) if startup_folder is not None else self.default_startup_folder()
        )
        self.executable = Path(executable) if executable is not None else self._default_executable()
        self.project_root = (
            Path(project_root) if project_root is not None else Path(__file__).resolve().parents[2]
        )

    @staticmethod
    def default_startup_folder() -> Path:
        roaming = os.environ.get("APPDATA")
        base = Path(roaming) if roaming else Path.home() / "AppData" / "Roaming"
        return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"

    @staticmethod
    def _default_executable() -> Path:
        executable = Path(sys.executable)
        if executable.name.lower() == "python.exe":
            pythonw = executable.with_name("pythonw.exe")
            if pythonw.exists():
                return pythonw
        return executable

    @property
    def launcher_path(self) -> Path:
        return self.startup_folder / self.LAUNCHER_NAME

    @property
    def is_enabled(self) -> bool:
        return self.launcher_path.is_file()

    def enable(self) -> None:
        self.startup_folder.mkdir(parents=True, exist_ok=True)
        if getattr(sys, "frozen", False):
            contents = "@echo off\n" f'start "" "{self.executable}"\n'
        else:
            contents = (
                "@echo off\n"
                f'cd /d "{self.project_root}"\n'
                f'start "" "{self.executable}" -m handwave.main\n'
            )
        temporary = self.launcher_path.with_suffix(".cmd.tmp")
        temporary.write_text(contents, encoding="utf-8")
        atomic_replace(temporary, self.launcher_path)

    def disable(self) -> None:
        self.launcher_path.unlink(missing_ok=True)

    def set_enabled(self, enabled: bool) -> None:
        self.enable() if enabled else self.disable()


class MacLaunchAgentManager:
    """Start HandWave at login on macOS via a per-user LaunchAgent (EXPERIMENTAL).

    Writes ``~/Library/LaunchAgents/com.handwave.app.plist``. launchd reads it
    at the next login; no admin rights are needed. Same interface as
    :class:`WindowsStartupManager`.
    """

    LABEL = "com.handwave.app"

    def __init__(
        self,
        agents_folder: str | Path | None = None,
        executable: str | Path | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        self.agents_folder = Path(agents_folder) if agents_folder is not None else Path.home() / "Library" / "LaunchAgents"
        # Plain strings: these are written verbatim into a macOS plist.
        self.executable = str(executable) if executable is not None else sys.executable
        self.project_root = str(project_root) if project_root is not None else str(Path(__file__).resolve().parents[2])

    @property
    def launcher_path(self) -> Path:
        return self.agents_folder / f"{self.LABEL}.plist"

    @property
    def is_enabled(self) -> bool:
        return self.launcher_path.is_file()

    def program_arguments(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [self.executable]
        return [self.executable, "-m", "handwave.main"]

    def enable(self) -> None:
        import plistlib

        self.agents_folder.mkdir(parents=True, exist_ok=True)
        payload = {
            "Label": self.LABEL,
            "ProgramArguments": self.program_arguments(),
            "RunAtLoad": True,
            "ProcessType": "Interactive",
        }
        if not getattr(sys, "frozen", False):
            payload["WorkingDirectory"] = self.project_root
        temporary = self.launcher_path.with_suffix(".plist.tmp")
        temporary.write_bytes(plistlib.dumps(payload))
        atomic_replace(temporary, self.launcher_path)

    def disable(self) -> None:
        self.launcher_path.unlink(missing_ok=True)

    def set_enabled(self, enabled: bool) -> None:
        self.enable() if enabled else self.disable()


def default_startup_manager():
    """The start-at-login integration for this OS."""
    from handwave import platforms

    return MacLaunchAgentManager() if platforms.is_macos() else WindowsStartupManager()
