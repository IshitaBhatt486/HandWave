# Application profiles

## Model

A `Profile` (`handwave/config/profile.py`) is a sparse override layer, not a
full copy of global settings:

```python
Profile(
    name="Spotify",
    app_executable="spotify.exe",       # normalized: lowercase basename
    app_window_title_pattern=None,       # optional, more specific matcher
    enabled=True,
    gesture_sensitivity=None,            # None = inherit global value
    gesture_cooldown=None,
    gesture_bindings={"Open Palm": "play_pause"},   # only overridden gestures
    enabled_gestures={},
)
```

`Profile.resolve(global_settings)` returns an `AppSettings`-shaped object with
overrides layered on top — unset fields (`None`, or gestures absent from the
sparse dicts) come from `global_settings` unchanged. `Profile.duplicate()` and
`Profile.copy_overrides_from(other)` always build fresh dicts, so two profiles
never share a mutable `gesture_bindings`/`enabled_gestures` reference.

## Persistence

`ProfileManager` (`handwave/config/profile_manager.py`) persists the profile
list plus an `active_profile_id` (explicit selection) to
`profiles.json` in the per-user config folder, with the same schema-version/atomic-write/backup-recovery
pattern as `SettingsManager` (see [architecture.md](architecture.md)). CRUD:
`create_profile`, `update_profile`, `duplicate_profile`,
`copy_settings_from(target, source)`, `reset_overrides`, `delete_profile`,
`set_enabled`, `set_active_profile`, `import_profile`/`export_profile`
(single-profile JSON files, always assigned a fresh id on import to avoid
collisions).

## Automatic switching

`handwave/services/foreground_app.py` reads the foreground window's process
image name and title via `ctypes` (`user32`/`kernel32`) — never a window
title alone, since titles change constantly.
`handwave/services/app_matcher.py::select_profile` matches deterministically:

```mermaid
flowchart TD
    F[Foreground app<br/>e.g. spotify.exe + window title] --> A{Auto-switch on?}
    A -->|no| E
    A -->|yes| B{Enabled profile with matching<br/>executable and title pattern?}
    B -->|yes| W[that profile<br/>window_title_match]
    B -->|no| C{Enabled profile with<br/>matching executable?}
    C -->|yes| X[that profile<br/>executable_match]
    C -->|no| E{Profile selected by hand?}
    E -->|yes| S[selected profile<br/>explicit_selection]
    E -->|no| G[Global settings<br/>global_fallback]
```

1. explicitly disabled profiles are never selected
2. an executable match with a matching window-title pattern (most specific)
3. an executable-only match
4. no match → the explicitly selected profile, then Global

`ProfileSwitcher` (`handwave/services/profile_switcher.py`) polls this on a
timer (`MainWindow.PROFILE_POLL_INTERVAL_MS`, only while recognition is
running) and only recomputes *configuration* — applying a switch calls
`CameraManager.apply_profile_settings()`, which swaps `ActionMapper`'s
cooldown/bindings in place. The capture thread and MediaPipe are never
restarted. The "Automatically switch application profiles" setting
(`AppSettings.auto_switch_profiles`) disables this polling in favor of
whatever profile was explicitly selected.

## Diagnostics

The dashboard shows `Active profile: <name>`; the diagnostics text includes
foreground app, active profile, and match reason
(`executable_match` / `window_title_match` / `explicit_selection` /
`auto_switch_disabled` / `global_fallback`).

## Not built yet

There's no editor for profiles in the app. Everything above works and is
tested, but creating a profile currently means using `ProfileManager` from
Python or editing `profiles.json` in the config folder. An editor would be a
welcome contribution.
