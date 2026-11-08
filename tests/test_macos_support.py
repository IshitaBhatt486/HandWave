"""macOS support (EXPERIMENTAL) — simulated on any OS with fake PyObjC modules.

These tests pin down *what HandWave asks macOS to do* (event codes, API calls,
plist contents). They cannot prove the behaviour on a real Mac; that is what
the macOS test checklist in docs/macos.md is for.
"""

import plistlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from handwave import platforms
from handwave.actions.action_definition import ActionDefinition
from handwave.actions.action_executor import ActionExecutor
from handwave.platforms import macos


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(platforms, "is_macos", lambda: True)
    monkeypatch.setattr(platforms, "is_windows", lambda: False)


@pytest.fixture
def fake_pyobjc(monkeypatch):
    """Install recording stand-ins for AppKit, Quartz and AVFoundation."""
    posted = []

    class FakeEvent:
        def __init__(self, args):
            self.args = args

        def CGEvent(self):  # noqa: N802
            return self

    appkit = types.ModuleType("AppKit")
    appkit.NSEvent = types.SimpleNamespace(
        otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_=lambda *args: FakeEvent(args)
    )
    quartz = types.ModuleType("Quartz")
    quartz.kCGHIDEventTap = "hid-tap"
    quartz.CGEventPost = lambda tap, event: posted.append((tap, event.args))
    quartz.kCGWindowListOptionOnScreenOnly, quartz.kCGWindowListExcludeDesktopElements, quartz.kCGNullWindowID = 1, 16, 0
    quartz.CGWindowListCopyWindowInfo = lambda options, window: [
        {"kCGWindowOwnerPID": 99, "kCGWindowLayer": 25, "kCGWindowName": "menu"},
        {"kCGWindowOwnerPID": 42, "kCGWindowLayer": 0, "kCGWindowName": "Daily standup"},
    ]
    avf = types.ModuleType("AVFoundation")
    avf.AVMediaTypeVideo, avf.AVMediaTypeAudio = "vide", "soun"
    avf.busy = {"vide": False, "soun": False}
    avf.AVCaptureDevice = types.SimpleNamespace(
        devicesWithMediaType_=lambda media: [types.SimpleNamespace(isInUseByAnotherApplication=lambda: avf.busy[media])]
    )
    for name, module in (("AppKit", appkit), ("Quartz", quartz), ("AVFoundation", avf)):
        monkeypatch.setitem(sys.modules, name, module)
    return types.SimpleNamespace(posted=posted, appkit=appkit, quartz=quartz, avf=avf)


# ------------------------------------------------------------------ actions

@pytest.mark.parametrize("action,code", [("play_pause", 16), ("next_track", 17), ("previous_track", 18),
                                         ("volume_up", 0), ("volume_down", 1), ("mute", 7)])
def test_media_keys_post_system_defined_key_down_then_up(fake_pyobjc, action, code):
    macos.post_media_key(action)
    (tap_down, down), (tap_up, up) = fake_pyobjc.posted
    assert tap_down == tap_up == "hid-tap"
    assert down[0] == 14 and down[6] == 8  # NSSystemDefined, NX_SUBTYPE_AUX_CONTROL_BUTTONS
    assert down[7] == (code << 16) | (0xA << 8)  # key down
    assert up[7] == (code << 16) | (0xB << 8)  # key up


def test_unknown_media_action_is_rejected(fake_pyobjc):
    with pytest.raises(ValueError):
        macos.post_media_key("rewind")


def test_executor_uses_native_media_keys_and_mac_modifiers(mac):
    gui, poster, launcher = MagicMock(), MagicMock(), MagicMock()
    keyboard = MagicMock()
    executor = ActionExecutor(pyautogui_module=gui, keyboard_module=keyboard, program_launcher=launcher, media_key_poster=poster)

    executor.execute(ActionDefinition("media", "play_pause"))
    executor.execute(ActionDefinition("hotkey", "win+shift+s"))
    executor.execute(ActionDefinition("hotkey", "alt+tab"))
    executor.execute(ActionDefinition("command", "Safari.app", hold_duration=1.5))

    poster.assert_called_once_with("play_pause")
    gui.press.assert_not_called()
    assert [call.args for call in gui.hotkey.call_args_list] == [("command", "shift", "s"), ("option", "tab")]
    launcher.assert_called_once_with(["open", "-a", "Safari.app"], shell=False)
    assert executor._keyboard is None  # the keyboard package needs root on macOS





def test_open_application_command():
    assert macos.open_application_command(["Safari.app"]) == ["open", "-a", "Safari.app"]
    assert macos.open_application_command(["Spotify"]) == ["open", "-a", "Spotify"]
    assert macos.open_application_command(["/Applications/Zoom.app", "--x"]) == ["open", "-a", "/Applications/Zoom.app", "--args", "--x"]
    assert macos.open_application_command(["/usr/bin/say", "hi"]) == ["/usr/bin/say", "hi"]


def test_cmd_and_option_aliases_are_valid_modifiers():
    assert ActionDefinition("hotkey", "cmd+opt+esc").value == "command+option+esc"


def test_default_bindings_use_mac_navigation_shortcuts():
    from handwave.config.gesture_config import default_gesture_bindings

    mac_bindings = default_gesture_bindings(macos=True)
    assert mac_bindings["Swipe Left"]["value"] == "ctrl+left"  # previous Space
    assert mac_bindings["Hand Swipe Up"]["value"] == "ctrl+up"  # Mission Control
    assert mac_bindings["Finger Swipe Up"]["value"] == "command+tab"
    for action in mac_bindings.values():
        ActionDefinition.from_data(action)  # all valid
    assert default_gesture_bindings(macos=False)["Swipe Left"]["value"] == "win+ctrl+left"


def test_macro_presets_use_command_on_mac():
    from handwave.ui.macro_editor import presets

    assert presets(macos=True)["Copy, then paste"][0] == ("hotkey", "command+c")
    assert presets(macos=True)["Screenshot a region"] == [("hotkey", "command+shift+4")]
    assert presets(macos=False)["Copy, then paste"][0] == ("hotkey", "ctrl+c")


# ------------------------------------------------------------------ system

def test_frontmost_app_reads_workspace_and_window_title(fake_pyobjc):
    app = types.SimpleNamespace(
        executableURL=lambda: types.SimpleNamespace(path=lambda: "/Applications/zoom.us.app/Contents/MacOS/zoom.us"),
        processIdentifier=lambda: 42,
        localizedName=lambda: "zoom.us",
    )
    fake_pyobjc.appkit.NSWorkspace = types.SimpleNamespace(sharedWorkspace=lambda: types.SimpleNamespace(frontmostApplication=lambda: app))
    assert macos.frontmost_app() == ("/Applications/zoom.us.app/Contents/MacOS/zoom.us", "Daily standup")


def test_foreground_lookup_uses_mac_path_and_never_raises(mac, monkeypatch):
    from handwave.services import foreground_app

    monkeypatch.setattr("handwave.platforms.macos.frontmost_app", lambda: ("/Applications/Spotify.app/Contents/MacOS/Spotify", "Spotify"))
    assert foreground_app.get_foreground_app() == foreground_app.ForegroundAppInfo("/Applications/Spotify.app/Contents/MacOS/Spotify", "Spotify")
    monkeypatch.setattr("handwave.platforms.macos.frontmost_app", MagicMock(side_effect=RuntimeError("no AppKit")))
    assert foreground_app.get_foreground_app() == foreground_app.ForegroundAppInfo(None, None)


def test_camera_and_microphone_use_by_other_apps(fake_pyobjc):
    assert not macos.device_in_use_by_another_app("video")
    fake_pyobjc.avf.busy["vide"] = True
    assert macos.device_in_use_by_another_app("video")
    assert not macos.device_in_use_by_another_app("audio")


def test_mac_auto_pause_rules():
    from handwave.services.auto_pause import PauseRules, evaluate_macos

    busy = {"video": False, "audio": False}
    probe = lambda kind: busy[kind]  # noqa: E731
    assert evaluate_macos(PauseRules(apps=("obs",)), processes=lambda: {"obs"}, in_use_by_another_app=probe) == "Obs is running"
    assert evaluate_macos(PauseRules(), processes=lambda: {"finder"}, in_use_by_another_app=probe) is None
    busy["video"] = True
    assert evaluate_macos(PauseRules(), processes=lambda: set(), in_use_by_another_app=probe) == "another app is using the camera"
    busy["video"], busy["audio"] = False, True
    assert evaluate_macos(PauseRules(), processes=lambda: {"zoom.us"}, in_use_by_another_app=probe) == "you're in a Zoom call"
    assert evaluate_macos(PauseRules(), processes=lambda: {"google chrome"}, in_use_by_another_app=probe) == "you're in a call"
    assert evaluate_macos(PauseRules(), processes=lambda: {"cpthost"}, in_use_by_another_app=probe) == "you're in a Zoom meeting"
    assert evaluate_macos(PauseRules(during_calls=False), processes=lambda: {"zoom.us"}, in_use_by_another_app=probe) is None


def test_auto_pause_dispatches_to_mac_rules(mac, monkeypatch):
    from handwave.services import auto_pause

    monkeypatch.setattr(auto_pause, "evaluate_macos", lambda rules: "from mac")
    assert auto_pause.evaluate(auto_pause.PauseRules()) == "from mac"


def test_program_names_keep_mac_app_names(mac):
    from handwave.config.settings_manager import normalize_app_names

    assert normalize_app_names(["OBS", "zoom.us", "/Applications/Slack.app/Contents/MacOS/Slack"]) == ("obs", "zoom.us", "slack")


def test_launch_agent_plist(tmp_path):
    from handwave.services.startup_manager import MacLaunchAgentManager

    manager = MacLaunchAgentManager(agents_folder=tmp_path, executable="/usr/local/bin/python3", project_root="/src/handwave")
    assert not manager.is_enabled
    manager.set_enabled(True)
    payload = plistlib.loads(manager.launcher_path.read_bytes())
    assert manager.launcher_path.name == "com.handwave.app.plist"
    assert payload["ProgramArguments"] == ["/usr/local/bin/python3", "-m", "handwave.main"]
    assert payload["RunAtLoad"] is True and payload["WorkingDirectory"] == "/src/handwave"
    manager.set_enabled(False)
    assert not manager.is_enabled


def test_startup_manager_and_camera_backend_follow_the_os(mac):
    import cv2

    from handwave.services.startup_manager import MacLaunchAgentManager, default_startup_manager
    from handwave.vision.camera_manager import CameraWorker

    assert isinstance(default_startup_manager(), MacLaunchAgentManager)
    assert CameraWorker.capture_backend() == cv2.CAP_AVFOUNDATION


def test_mac_storage_location(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert platforms.app_data_dir() == Path.home() / "Library" / "Application Support" / "HandWave"
    assert platforms.config_dir().name == "config"


def test_microphone_permission_hint_points_to_system_settings(mac):
    from handwave.services.clap_detector import ClapDetector

    detector = ClapDetector()
    detector._report_stream_error(OSError("Permission denied"), "test")
    assert "System Settings > Privacy & Security > Microphone" in detector.status().error


@pytest.mark.skipif(sys.platform != "darwin", reason="needs a real Mac")
def test_resident_memory_is_measured_on_a_real_mac():
    assert macos.resident_memory_bytes() > 10 * 1024 * 1024





def test_user_facing_text_uses_mac_terms(mac, qtbot):
    from handwave.config.settings_manager import AppSettings
    from handwave.ui.onboarding import OnboardingDialog

    assert platforms.os_label() == "macOS"
    dialog = OnboardingDialog(AppSettings())
    qtbot.addWidget(dialog)
    assert dialog.startup_card.text() == "Start HandWave at login"
    assert "menu bar" in dialog.startup_card.description


def test_default_shortcuts_follow_the_platform_at_call_time(monkeypatch):
    # Defaults used to be frozen at import, so a process that imported them as
    # macOS kept Mac shortcuts even after switching to Windows behaviour.
    from handwave.actions.action_mapper import ActionMapper

    for is_mac, expected in ((True, ("ctrl", "left")), (False, ("win", "ctrl", "left"))):
        monkeypatch.setattr(platforms, "is_macos", lambda value=is_mac: value)
        gui = MagicMock()
        ActionMapper(clock=lambda: 10.0, pyautogui_module=gui).execute("Swipe Left")
        gui.hotkey.assert_called_once_with(*expected)
