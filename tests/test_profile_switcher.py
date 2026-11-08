from unittest.mock import MagicMock


from handwave.config.profile_manager import ProfileManager
from handwave.config.settings_manager import AppSettings
from handwave.services.foreground_app import ForegroundAppInfo
from handwave.services.profile_switcher import ProfileSwitcher


def test_global_template_resolution_change_reapplies_same_profile(tmp_path):
    manager = ProfileManager(tmp_path / "profiles.json")
    manager.create_profile("Chrome", app_executable="chrome.exe")
    settings = [AppSettings(), AppSettings(gesture_cooldown=2.0)]
    calls = []
    switcher = ProfileSwitcher(
        manager,
        foreground_provider=lambda: ForegroundAppInfo("chrome.exe", None),
        global_settings_provider=lambda: settings.pop(0),
        on_change=calls.append,
    )

    first = switcher.poll()
    second = switcher.poll()

    assert first.match.profile.profile_id == second.match.profile.profile_id
    assert second.changed is True
    assert len(calls) == 2


def _switcher(tmp_path, foreground_sequence, enabled=True, on_change=None, times=None):
    manager = ProfileManager(tmp_path / "profiles.json")
    foreground_iter = iter(foreground_sequence)
    clock_iter = iter(times) if times is not None else None
    return (
        ProfileSwitcher(
            manager,
            foreground_provider=lambda: next(foreground_iter),
            global_settings_provider=lambda: AppSettings(),
            on_change=on_change,
            clock=(clock_iter.__next__ if clock_iter is not None else __import__("time").monotonic),
            enabled=enabled,
        ),
        manager,
    )


def test_exact_match_activates_matching_profile(tmp_path):
    switcher, manager = _switcher(tmp_path, [ForegroundAppInfo("spotify.exe", "Spotify")])
    manager.create_profile("Spotify", app_executable="spotify.exe")

    event = switcher.poll()

    assert event.match.profile.name == "Spotify"
    assert event.match.reason == "executable_match"
    assert event.changed is True


def test_unmatched_application_falls_back_to_global(tmp_path):
    switcher, manager = _switcher(tmp_path, [ForegroundAppInfo("notepad.exe", "Untitled")])
    manager.create_profile("Spotify", app_executable="spotify.exe")

    event = switcher.poll()

    assert event.match.profile is None
    assert event.match.reason == "global_fallback"
    assert event.effective_settings == AppSettings()


def test_profile_switches_when_foreground_app_changes(tmp_path, ):
    switcher, manager = _switcher(
        tmp_path,
        [ForegroundAppInfo("spotify.exe", "Spotify"), ForegroundAppInfo("chrome.exe", "Chrome")],
    )
    manager.create_profile("Spotify", app_executable="spotify.exe")
    manager.create_profile("Chrome", app_executable="chrome.exe")

    first = switcher.poll()
    second = switcher.poll()

    assert first.match.profile.name == "Spotify"
    assert second.match.profile.name == "Chrome"
    assert second.changed is True


def test_rapid_switching_back_and_forth_is_tracked_each_time(tmp_path):
    switcher, manager = _switcher(
        tmp_path,
        [
            ForegroundAppInfo("spotify.exe", "Spotify"),
            ForegroundAppInfo("chrome.exe", "Chrome"),
            ForegroundAppInfo("spotify.exe", "Spotify"),
        ],
        times=(0.0, 0.1, 0.2),
    )
    manager.create_profile("Spotify", app_executable="spotify.exe")
    manager.create_profile("Chrome", app_executable="chrome.exe")

    results = [switcher.poll().match.profile.name for _ in range(3)]

    assert results == ["Spotify", "Chrome", "Spotify"]
    assert switcher.last_switch_time == 0.2


def test_disabled_profile_is_skipped_in_favor_of_global(tmp_path):
    switcher, manager = _switcher(tmp_path, [ForegroundAppInfo("spotify.exe", None)])
    manager.create_profile("Spotify", app_executable="spotify.exe", enabled=False)

    event = switcher.poll()

    assert event.match.profile is None
    assert event.match.reason == "global_fallback"


def test_conflicting_matches_resolve_deterministically(tmp_path):
    switcher, manager = _switcher(tmp_path, [ForegroundAppInfo("chrome.exe", None)] * 2)
    a = manager.create_profile("A", app_executable="chrome.exe")
    b = manager.create_profile("B", app_executable="chrome.exe")
    expected = min((a, b), key=lambda p: p.profile_id).name

    event = switcher.poll()

    assert event.match.profile.name == expected


def test_explicit_selection_used_when_no_app_match(tmp_path):
    switcher, manager = _switcher(tmp_path, [ForegroundAppInfo("notepad.exe", None)])
    spotify = manager.create_profile("Spotify", app_executable="spotify.exe")
    manager.set_active_profile(spotify.profile_id)

    event = switcher.poll()

    assert event.match.profile.name == "Spotify"
    assert event.match.reason == "explicit_selection"


def test_disabling_automatic_switching_keeps_explicit_selection(tmp_path):
    switcher, manager = _switcher(
        tmp_path, [ForegroundAppInfo("chrome.exe", None)], enabled=False
    )
    spotify = manager.create_profile("Spotify", app_executable="spotify.exe")
    manager.create_profile("Chrome", app_executable="chrome.exe")  # matches, but auto-switch is off
    manager.set_active_profile(spotify.profile_id)

    event = switcher.poll()

    assert event.match.profile.name == "Spotify"
    assert event.match.reason == "explicit_selection"


def test_settings_change_toggles_auto_switch_at_runtime(tmp_path):
    switcher, manager = _switcher(tmp_path, [ForegroundAppInfo("chrome.exe", None)] * 2)
    manager.create_profile("Chrome", app_executable="chrome.exe")

    switcher.set_enabled(False)
    disabled_event = switcher.poll()
    switcher.set_enabled(True)

    assert disabled_event.match.profile is None
    assert disabled_event.match.reason == "auto_switch_disabled"


def test_on_change_callback_fires_only_when_profile_changes(tmp_path):
    calls = []
    switcher, manager = _switcher(
        tmp_path,
        [ForegroundAppInfo("chrome.exe", None), ForegroundAppInfo("chrome.exe", None)],
        on_change=calls.append,
    )
    manager.create_profile("Chrome", app_executable="chrome.exe")

    switcher.poll()
    switcher.poll()

    assert len(calls) == 1  # second poll: same profile, no new callback


def test_callback_failure_does_not_raise_or_block_polling(tmp_path):
    switcher, manager = _switcher(
        tmp_path,
        [ForegroundAppInfo("chrome.exe", None), ForegroundAppInfo("notepad.exe", None)],
        on_change=MagicMock(side_effect=RuntimeError("boom")),
    )
    manager.create_profile("Chrome", app_executable="chrome.exe")

    switcher.poll()  # must not raise despite the failing callback
    second = switcher.poll()
    assert second.match.profile is None


def test_poll_never_touches_camera_or_recognition_state(tmp_path):
    """The switcher only ever computes data; applying it is the caller's job."""
    switcher, manager = _switcher(tmp_path, [ForegroundAppInfo("chrome.exe", None)])
    manager.create_profile("Chrome", app_executable="chrome.exe")
    event = switcher.poll()
    assert not hasattr(event, "camera")
    assert not hasattr(switcher, "camera")
