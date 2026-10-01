"""HandWave application entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from handwave.ui.main_window import MainWindow
from handwave.config.settings_manager import SettingsManager
from handwave.services.startup_manager import WindowsStartupManager
from handwave.startup_timing import StartupTimer
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

        app.setWindowIcon(QIcon(str(resource_path("handwave/assets/handwave.ico"))))
        settings = SettingsManager(startup_manager=WindowsStartupManager())
        settings.synchronize_startup()
        _startup_timer.mark("settings loaded")
        window = MainWindow(settings_manager=settings)
        _startup_timer.mark("MainWindow constructed")
        window.clap_detector.start()
        _startup_timer.mark("microphone init requested")
        window.show()
        # Recognition is enabled by default; schedule it after the event loop
        # begins so the dashboard can render immediately.
        QTimer.singleShot(0, window.start_camera)
        _startup_timer.mark("UI visible; recognition start requested")
        QTimer.singleShot(0, window.show_onboarding_if_needed)
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
