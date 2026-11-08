"""HandWave application entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from handwave.ui.main_window import MainWindow
from handwave.config.settings_manager import SettingsManager
from handwave import platforms
from handwave.services.startup_manager import default_startup_manager
from handwave.diagnostics.startup_timing import StartupTimer
from handwave.version import __version__

_startup_timer = StartupTimer()
_startup_timer.mark("process start / imports resolved")


def resource_path(relative: str) -> Path:
    """Resolve bundled PyInstaller resources and source-tree assets."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / relative


def configure_logging() -> None:
    """Configure console and file logging for the application."""
    log_dir = Path.home() / ".handwave"
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "handwave.log", encoding="utf-8"))
    except OSError:
        # Console logging still works if the user's home directory is read-only.
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def main() -> int:
    configure_logging()
    logger = logging.getLogger(__name__)
    _startup_timer.mark("logging configured")
    try:
        app = QApplication(sys.argv)
        _startup_timer.mark("QApplication created")
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName("HandWave")
        app.setOrganizationName("HandWave")
        app.setApplicationVersion(__version__)
        from PyQt6.QtGui import QIcon

        icon = "handwave/assets/handwave.png" if platforms.is_macos() else "handwave/assets/handwave.ico"
        app.setWindowIcon(QIcon(str(resource_path(icon))))
        settings = SettingsManager(startup_manager=default_startup_manager())
        settings.synchronize_startup()
        _startup_timer.mark("settings loaded")
        window = MainWindow(settings_manager=settings)
        _startup_timer.mark("MainWindow constructed")
        window.show()
        # After the event loop starts (so the dashboard renders first):
        # first-run setup, then microphone, auto-pause and — if enabled in
        # settings — the camera.
        QTimer.singleShot(0, window.launch)
        _startup_timer.mark("UI visible; launch sequence scheduled")
        if _startup_timer.enabled:
            logger.info("%s", _startup_timer.report())
        logger.info("HandWave started")
        return app.exec()
    except Exception as exc:  # Last-resort GUI startup guard.
        logger.exception("HandWave failed to start")
        if QApplication.instance() is not None:
            QMessageBox.critical(None, "HandWave", f"Unable to start HandWave:\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
