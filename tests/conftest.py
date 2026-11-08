"""Shared test configuration and suite classification."""

from __future__ import annotations

import pytest

# Loaded before pytest-qt imports PyQt6: share the newest C++ runtime across
# Qt, OpenCV and MediaPipe exactly as the app does (handwave/_runtime.py).
import handwave  # noqa: F401


UI_MODULES = {"test_main_window.py", "test_settings_dialog.py"}
INTEGRATION_MODULES = {
    "test_camera_manager.py",
    "test_integration_configuration.py",
    "test_release_config.py",
    "test_startup_manager.py",
}
BENCHMARK_MODULES = {"test_pipeline_benchmark.py", "test_performance_pipeline.py"}


@pytest.fixture(autouse=True)
def _isolate_user_settings(tmp_path, monkeypatch):
    """Never read or write the developer's real settings, profiles or gestures in tests."""
    from handwave.config.settings_manager import SettingsManager

    from handwave.config.profile_manager import ProfileManager
    from handwave.config.template_manager import TemplateManager
    from handwave.gestures.custom_gesture_store import CustomGestureStore

    user = tmp_path / "user-settings"
    monkeypatch.setattr(SettingsManager, "DEFAULT_PATH", user / "settings.json")
    for store in (ProfileManager, TemplateManager, CustomGestureStore):
        monkeypatch.setattr(store, "DEFAULT_PATH", user / store.DEFAULT_PATH.name)
        monkeypatch.setattr(store, "LEGACY_SOURCE_PATH", user / "no-legacy" / store.DEFAULT_PATH.name)


# These modules specify Windows behaviour (pyautogui media keys, Win/Alt
# hotkeys, the keyboard fallback). Pin them to Windows so the macOS CI job
# runs the same specifications; macOS behaviour lives in test_macos_support.py.
WINDOWS_BEHAVIOUR_MODULES = {
    "test_action_executor.py", "test_action_mapper.py", "test_action_queue.py",
    "test_gesture_filter.py", "test_integration_configuration.py", "test_macros.py",
    "test_swipe_recognizer.py",
}


@pytest.fixture(autouse=True)
def _windows_behaviour(request, monkeypatch):
    if request.node.path.name in WINDOWS_BEHAVIOUR_MODULES:
        monkeypatch.setattr("handwave.platforms.is_macos", lambda: False)
        monkeypatch.setattr("handwave.platforms.is_windows", lambda: True)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Assign every test to one explicit framework layer by module purpose."""
    for item in items:
        filename = item.path.name
        if filename in BENCHMARK_MODULES:
            marker = pytest.mark.benchmark
        elif filename in UI_MODULES:
            marker = pytest.mark.ui
        elif filename in INTEGRATION_MODULES:
            marker = pytest.mark.integration
        else:
            marker = pytest.mark.unit
        item.add_marker(marker)
