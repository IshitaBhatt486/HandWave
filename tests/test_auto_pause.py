from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from handwave.config.settings_manager import SettingsManager
from handwave.services.auto_pause import AutoPauseMonitor, PauseRules, apps_using_device, evaluate
from handwave.ui.main_window import MainWindow


class FakeRegistry:
    """Minimal winreg stand-in: {path: {"keys": [...], "values": {...}}}."""

    HKEY_CURRENT_USER = object()

    def __init__(self, tree):
        self.tree = tree

    class _Key:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, root, path):  # noqa: N802
        if path not in self.tree:
            raise OSError(path)
        return self._Key(path)

    def EnumKey(self, key, index):  # noqa: N802
        keys = self.tree[key.path].get("keys", [])
        if index >= len(keys):
            raise OSError("no more")
        return keys[index]

    def QueryValueEx(self, key, name):  # noqa: N802
        values = self.tree[key.path].get("values", {})
        if name not in values:
            raise OSError(name)
        return values[name], 11


BASE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"


def _registry(**apps):
    tree = {BASE: {"keys": ["Microsoft.WindowsCamera_8wekyb3d8bbwe", "NonPackaged"]},
            BASE + r"\Microsoft.WindowsCamera_8wekyb3d8bbwe": {"values": {"LastUsedTimeStart": 5, "LastUsedTimeStop": 9}},
            BASE + r"\NonPackaged": {"keys": list(apps)}}
    for key, stop in apps.items():
        tree[BASE + "\\NonPackaged\\" + key] = {"values": {"LastUsedTimeStart": 5, "LastUsedTimeStop": stop}}
    return FakeRegistry(tree)


def test_camera_users_are_read_from_registry_excluding_handwave():
    registry = _registry(**{"C:#Zoom#zoom.exe": 0, "C:#Py#python.exe": 0, "C:#Old#obs64.exe": 77})
    users = apps_using_device("webcam", exclude={"python.exe"}, registry=registry)
    assert users == [r"c:\zoom\zoom.exe"]  # stopped apps and HandWave itself are ignored


def test_missing_registry_means_nobody_uses_the_camera():
    assert apps_using_device("webcam", exclude=set(), registry=FakeRegistry({})) == []


@pytest.mark.parametrize("rules,running,camera,mic,expected", [
    (PauseRules(apps=("obs64.exe",)), {"obs64.exe"}, [], [], "OBS is running"),
    (PauseRules(), set(), [r"c:\zoom\zoom.exe"], [], "Zoom is using the camera"),
    (PauseRules(), {"cpthost.exe"}, [], [], "you're in a Zoom meeting"),
    (PauseRules(), set(), [], ["msteams_8wekyb3d8bbwe"], "you're in a Teams call"),
    (PauseRules(), set(), [], [r"c:\chrome\chrome.exe"], "you're in a call"),
    (PauseRules(camera_in_use=False), set(), [r"c:\zoom\zoom.exe"], [], None),
    (PauseRules(during_calls=False), {"cpthost.exe"}, [], ["discord.exe"], None),
    (PauseRules(False, False, ()), {"obs64.exe"}, ["x"], ["discord.exe"], None),
    (PauseRules(), set(), [], [r"c:\tools\recorder.exe"], None),
])
def test_rules_produce_clear_reasons(rules, running, camera, mic, expected):
    devices = {"webcam": camera, "microphone": mic}
    assert evaluate(rules, processes=lambda: running, devices=lambda d: devices[d]) == expected


def test_specified_apps_take_priority_over_camera_use():
    reason = evaluate(PauseRules(apps=("obs64.exe",)), processes=lambda: {"obs64.exe"}, devices=lambda d: ["zoom.exe"])
    assert reason == "OBS is running"


def test_monitor_only_signals_changes_and_survives_probe_errors(qtbot):
    results = iter(["Zoom is using the camera", "Zoom is using the camera", RuntimeError("boom"), None])

    def evaluator(rules):
        value = next(results)
        if isinstance(value, Exception):
            raise value
        return value

    monitor = AutoPauseMonitor(evaluator=evaluator)
    seen = []
    monitor.reason_changed.connect(seen.append)
    for _ in range(4):
        monitor.check_now()
    assert seen == ["Zoom is using the camera", ""]


def test_monitor_thread_starts_and_stops_cleanly(qtbot):
    monitor = AutoPauseMonitor(evaluator=lambda rules: "OBS is running")
    seen = []
    monitor.reason_changed.connect(seen.append)
    monitor.start()
    qtbot.waitUntil(lambda: seen == ["OBS is running"], timeout=2000)
    monitor.stop()
    assert monitor._thread is None


# ------------------------------------------------------------ window wiring

class FakeCamera(QObject):
    frame_ready = pyqtSignal(object)
    started = pyqtSignal()
    stopped = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.start_camera = MagicMock(side_effect=lambda: self.started.emit())
        self.stop_camera = MagicMock(side_effect=lambda: self.stopped.emit())


class FakeClap(QObject):
    double_clap = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.start, self.stop = MagicMock(), MagicMock()


def _window(qtbot, tmp_path, **settings):
    manager = SettingsManager(tmp_path / "settings.json")
    if settings:
        manager.update(**settings)
    onboarding = QSettings(str(tmp_path / "o.ini"), QSettings.Format.IniFormat)
    onboarding.setValue("onboarding/completed", True)
    camera, clap = FakeCamera(), FakeClap()
    window = MainWindow(camera_manager=camera, clap_detector=clap, settings_manager=manager, onboarding_settings=onboarding)
    qtbot.addWidget(window)
    window.auto_pause.start = MagicMock()  # no background thread in unit tests
    return window, camera, clap


def test_auto_pause_releases_camera_and_resumes_when_clear(qtbot, tmp_path):
    window, camera, _ = _window(qtbot, tmp_path)
    window.user_start()
    assert window.activation.is_active

    window.auto_pause._publish("Zoom is using the camera")
    assert not window.activation.is_active
    assert window.status_text.text() == "Paused while Zoom is using the camera"
    assert window.toast.text == "Paused while Zoom is using the camera"

    window.auto_pause._publish("")
    assert window.activation.is_active
    assert camera.start_camera.call_count == 2
    window.exit_application()


def test_manual_start_overrides_current_reason_until_it_changes(qtbot, tmp_path):
    window, camera, _ = _window(qtbot, tmp_path)
    window.auto_pause._publish("OBS is running")
    window.user_start()  # user insists
    assert window.activation.is_active
    window.auto_pause._publish("OBS is running")  # same reason: no re-pause (no change emitted anyway)
    assert window.activation.is_active
    window.auto_pause._publish("Zoom is using the camera")  # new reason: pause again
    assert not window.activation.is_active
    window.exit_application()


def test_manual_stop_is_never_auto_resumed(qtbot, tmp_path):
    window, camera, _ = _window(qtbot, tmp_path)
    window.user_start()
    window.auto_pause._publish("OBS is running")
    window.user_stop()
    window.auto_pause._publish("")
    assert not window.activation.is_active
    window.exit_application()


def test_launch_respects_auto_start_setting(qtbot, tmp_path):
    window, camera, clap = _window(qtbot, tmp_path, start_camera_on_launch=False)
    window.auto_pause._evaluate = lambda rules: None
    window.launch()
    camera.start_camera.assert_not_called()
    clap.start.assert_called_once()
    window.exit_application()


def test_launch_starts_camera_unless_a_pause_condition_is_active(qtbot, tmp_path):
    window, camera, _ = _window(qtbot, tmp_path)
    window.auto_pause._evaluate = lambda rules: "you're in a Teams call"
    window.launch()
    camera.start_camera.assert_not_called()
    assert window.status_text.text() == "Paused while you're in a Teams call"
    window.auto_pause._publish("")
    camera.start_camera.assert_called_once()
    window.exit_application()


def test_double_clap_can_be_disabled(qtbot, tmp_path):
    window, _, clap = _window(qtbot, tmp_path, double_clap_enabled=False)
    window.auto_pause._evaluate = lambda rules: None
    window.launch()
    clap.start.assert_not_called()
    assert "OFF" in window.microphone_status.text()
    window.exit_application()


def test_handwave_is_excluded_even_where_os_path_is_posix(monkeypatch):
    # The macOS CI job runs this code with posixpath, which does not split on "\".
    import posixpath
    import types

    from handwave.services import auto_pause

    monkeypatch.setattr(auto_pause, "os", types.SimpleNamespace(path=posixpath))
    registry = _registry(**{"C:#Zoom#zoom.exe": 0, "C:#Py#python.exe": 0})
    assert apps_using_device("webcam", exclude={"python.exe"}, registry=registry) == [r"c:\zoom\zoom.exe"]
