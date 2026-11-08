"""Validated JSON settings storage."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from handwave.actions.action_definition import ActionDefinition
from handwave import platforms
from handwave.services.startup_manager import WindowsStartupManager
from handwave.config.atomic_write import atomic_replace
from handwave.config.gesture_config import (
    GESTURES,
    complete_bindings,
    complete_enabled,
)

SCHEMA_VERSION = 3


def normalize_app_names(value: object) -> tuple[str, ...]:
    """Validate a list of program names, e.g. ``["obs64.exe", "Zoom"]``.

    Names are lower-cased, paths are reduced to the file name, and duplicates
    are dropped (order kept). On Windows ``.exe`` is added when missing; on
    macOS app names such as ``zoom.us`` or ``OBS`` are kept as given.
    """
    windows = not platforms.is_macos()
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError("pause_for_apps must be a list of program names")
    names: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("pause_for_apps entries must be program names")
        name = item.strip().strip('"').replace("/", "\\").rsplit("\\", 1)[-1].lower()
        if not name:
            continue
        if windows and not name.endswith(".exe"):
            name += ".exe"
        if len(name) > 128 or any(char in name for char in '<>:"|?*\0'):
            raise ValueError(f"Invalid program name: {item!r}")
        if name not in names:
            names.append(name)
    if len(names) > 32:
        raise ValueError("pause_for_apps may list at most 32 programs")
    return tuple(names)


@dataclass(frozen=True)
class AppSettings:
    camera_index: int = 0
    gesture_sensitivity: float = 0.6
    gesture_cooldown: float = 1.0
    startup_enabled: bool = False
    overlay_enabled: bool = True
    gesture_bindings: dict[str, ActionDefinition] = field(default_factory=complete_bindings)
    enabled_gestures: dict[str, bool] = field(default_factory=complete_enabled)
    theme: str = "dark"
    auto_switch_profiles: bool = True
    exit_on_close: bool = False
    show_fingerprint_indicator: bool = True
    fingerprint_indicator_size: int = 18
    fingerprint_indicator_opacity: float = 1.0
    fingerprint_indicator_fade_duration_ms: int = 250
    microphone_device: int | None = None  # None uses the Windows default input.
    clap_min_peak: float = 0.02
    clap_rms_threshold: float = 0.0
    clap_noise_multiplier: float = 2.5
    double_clap_min_interval: float = 0.12
    double_clap_max_interval: float = 1.0
    cursor_reach_calibration: dict[str, float] | None = None
    cursor_dead_zone_percent: int = 10
    cursor_smoothing: str = "medium"
    # Cursor calibration is independent of the desktop layout, but the target
    # area is not.  Persist both the user's choice and a layout fingerprint so
    # a moved or disconnected display can be detected before cursor control is
    # enabled in a future cursor-control feature.
    cursor_target_mode: str = "primary"
    cursor_target_monitor_id: str | None = None
    cursor_monitor_layout_fingerprint: str = ""
    cursor_assist_overlay_enabled: bool = True
    cursor_assist_overlay_size: int = 22
    cursor_assist_overlay_opacity: float = 0.72
    # Launch behaviour, hands-free activation, motion and auto-pause.
    start_camera_on_launch: bool = True
    double_clap_enabled: bool = True
    reduce_motion: bool = False
    pause_when_camera_in_use: bool = True
    pause_during_calls: bool = True
    pause_for_apps: tuple[str, ...] = ()
    # Performance: lite MediaPipe model (~35% faster, ~3 pts less accurate on
    # HaGRID) and the developer text overlay on the camera preview.
    fast_hand_model: bool = False
    debug_overlay: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.camera_index, int) or isinstance(self.camera_index, bool) or self.camera_index < 0:
            raise ValueError("camera_index must be a non-negative integer")
        if (
            not isinstance(self.gesture_sensitivity, (int, float))
            or isinstance(self.gesture_sensitivity, bool)
            or not 0.0 <= self.gesture_sensitivity <= 1.0
        ):
            raise ValueError("gesture_sensitivity must be between 0 and 1")
        if (
            not isinstance(self.gesture_cooldown, (int, float))
            or isinstance(self.gesture_cooldown, bool)
            or self.gesture_cooldown < 0
        ):
            raise ValueError("gesture_cooldown cannot be negative")
        if not isinstance(self.startup_enabled, bool) or not isinstance(self.overlay_enabled, bool):
            raise ValueError("startup_enabled and overlay_enabled must be booleans")
        if not isinstance(self.auto_switch_profiles, bool):
            raise ValueError("auto_switch_profiles must be a boolean")
        if not isinstance(self.exit_on_close, bool):
            raise ValueError("exit_on_close must be a boolean")
        normalized_bindings = complete_bindings(self.gesture_bindings)
        object.__setattr__(self, "gesture_bindings", normalized_bindings)
        if set(normalized_bindings) != set(GESTURES):
            raise ValueError("gesture_bindings must contain every supported gesture")
        if set(self.enabled_gestures) != set(GESTURES):
            raise ValueError("enabled_gestures must contain every supported gesture")
        if any(not isinstance(enabled, bool) for enabled in self.enabled_gestures.values()):
            raise ValueError("enabled_gestures values must be booleans")
        if self.theme not in {"dark", "light"}:
            raise ValueError("theme must be 'dark' or 'light'")
        if not isinstance(self.show_fingerprint_indicator, bool):
            raise ValueError("show_fingerprint_indicator must be a boolean")
        if not isinstance(self.fingerprint_indicator_size, int) or not 8 <= self.fingerprint_indicator_size <= 48:
            raise ValueError("fingerprint_indicator_size must be between 8 and 48")
        if not isinstance(self.fingerprint_indicator_opacity, (int, float)) or not 0.2 <= self.fingerprint_indicator_opacity <= 1.0:
            raise ValueError("fingerprint_indicator_opacity must be between 0.2 and 1.0")
        if not isinstance(self.fingerprint_indicator_fade_duration_ms, int) or not 50 <= self.fingerprint_indicator_fade_duration_ms <= 2000:
            raise ValueError("fingerprint_indicator_fade_duration_ms must be between 50 and 2000")
        if self.microphone_device is not None and (not isinstance(self.microphone_device, int) or self.microphone_device < 0):
            raise ValueError("microphone_device must be a non-negative integer or None")
        if not isinstance(self.clap_min_peak, (int, float)) or not 0.001 <= self.clap_min_peak <= 1.0:
            raise ValueError("clap_min_peak must be between 0.001 and 1.0")
        if not isinstance(self.clap_rms_threshold, (int, float)) or not 0.0 <= self.clap_rms_threshold <= 1.0:
            raise ValueError("clap_rms_threshold must be between 0 and 1")
        if not isinstance(self.clap_noise_multiplier, (int, float)) or not 1.0 <= self.clap_noise_multiplier <= 20.0:
            raise ValueError("clap_noise_multiplier must be between 1 and 20")
        if not isinstance(self.double_clap_min_interval, (int, float)) or not 0.05 <= self.double_clap_min_interval <= 2.0:
            raise ValueError("double_clap_min_interval must be between 0.05 and 2 seconds")
        if not isinstance(self.double_clap_max_interval, (int, float)) or not self.double_clap_min_interval < self.double_clap_max_interval <= 3.0:
            raise ValueError("double_clap_max_interval must exceed the minimum and be at most 3 seconds")
        calibration = self.cursor_reach_calibration
        if calibration is not None:
            required = {"center_x", "center_y", "left", "right", "top", "bottom"}
            if not isinstance(calibration, dict) or set(calibration) != required:
                raise ValueError("cursor_reach_calibration must contain the six reach coordinates")
            if any(not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0 for value in calibration.values()):
                raise ValueError("cursor reach coordinates must be between 0 and 1")
            if not calibration["left"] < calibration["center_x"] < calibration["right"]:
                raise ValueError("cursor reach calibration must surround center horizontally")
            if not calibration["top"] < calibration["center_y"] < calibration["bottom"]:
                raise ValueError("cursor reach calibration must surround center vertically")
            object.__setattr__(self, "cursor_reach_calibration", dict(calibration))
        if not isinstance(self.cursor_dead_zone_percent, int) or self.cursor_dead_zone_percent not in {5, 10, 15}:
            raise ValueError("cursor_dead_zone_percent must be 5, 10, or 15")
        if self.cursor_smoothing not in {"low", "medium", "high"}:
            raise ValueError("cursor_smoothing must be low, medium, or high")
        if self.cursor_target_mode not in {"primary", "all"}:
            raise ValueError("cursor_target_mode must be primary or all")
        if self.cursor_target_monitor_id is not None and not isinstance(self.cursor_target_monitor_id, str):
            raise ValueError("cursor_target_monitor_id must be a string or None")
        if not isinstance(self.cursor_monitor_layout_fingerprint, str):
            raise ValueError("cursor_monitor_layout_fingerprint must be a string")
        if not isinstance(self.cursor_assist_overlay_enabled, bool):
            raise ValueError("cursor_assist_overlay_enabled must be a boolean")
        if not isinstance(self.cursor_assist_overlay_size, int) or not 18 <= self.cursor_assist_overlay_size <= 24:
            raise ValueError("cursor_assist_overlay_size must be between 18 and 24")
        if not isinstance(self.cursor_assist_overlay_opacity, (int, float)) or not 0.2 <= self.cursor_assist_overlay_opacity <= 1.0:
            raise ValueError("cursor_assist_overlay_opacity must be between 0.2 and 1")
        for name in ("start_camera_on_launch", "double_clap_enabled", "reduce_motion",
                     "pause_when_camera_in_use", "pause_during_calls", "fast_hand_model", "debug_overlay"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        object.__setattr__(self, "pause_for_apps", normalize_app_names(self.pause_for_apps))


class SettingsManager:
    """Load and atomically save application settings across restarts."""

    # Always use the current device/user profile, including source checkouts.
    # Keeping mutable calibration beside installed code breaks on read-only
    # locations and loses settings when a checkout is replaced.
    # %APPDATA%\HandWave on Windows; ~/Library/Application Support/HandWave on macOS.
    DEFAULT_PATH = platforms.config_dir() / "settings.json"
    LEGACY_SOURCE_PATH = Path(__file__).with_name("settings.json")
    FIELDS = set(AppSettings.__dataclass_fields__)

    def __init__(
        self,
        path: str | Path | None = None,
        startup_manager: WindowsStartupManager | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else self.DEFAULT_PATH
        self._backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.startup_manager = startup_manager
        self._loaded_legacy_source = False
        self.settings = self.load()
        if self._loaded_legacy_source:
            # Complete the migration immediately so calibration survives source
            # updates and is available to every launch of this device account.
            self.save()

    def load(self) -> AppSettings:
        candidates = [self.path, self._backup_path]
        if self.path == self.DEFAULT_PATH and not self.path.exists() and self.LEGACY_SOURCE_PATH.exists():
            candidates.append(self.LEGACY_SOURCE_PATH)
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
                values = self._migrate(raw)
                values["gesture_bindings"] = complete_bindings(values.get("gesture_bindings"))
                values["enabled_gestures"] = complete_enabled(values.get("enabled_gestures"))
                settings = AppSettings(**values)
                self._loaded_legacy_source = candidate == self.LEGACY_SOURCE_PATH
                return settings
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
        return AppSettings()

    @classmethod
    def _migrate(cls, raw: dict[str, Any]) -> dict[str, Any]:
        """Upgrade old settings in memory while retaining unknown-key filtering.

        Version 1 and unversioned files predate cursor target selection.
        Version 2 predates the visual cursor-assist preferences. Defaults retain
        the former primary-monitor behavior. Saving writes schema version 3.
        """
        version = raw.get("schema_version", 1)
        if not isinstance(version, int) or version < 1:
            raise ValueError("Unsupported settings schema version")
        values = {key: value for key, value in raw.items() if key in cls.FIELDS}
        if version < 2:
            values.setdefault("cursor_target_mode", "primary")
            values.setdefault("cursor_target_monitor_id", None)
            values.setdefault("cursor_monitor_layout_fingerprint", "")
        if version < 3:
            values.setdefault("cursor_assist_overlay_enabled", True)
            values.setdefault("cursor_assist_overlay_size", 22)
            values.setdefault("cursor_assist_overlay_opacity", 0.72)
        return values

    def update(self, **changes: Any) -> AppSettings:
        unknown = set(changes) - self.FIELDS
        if unknown:
            raise KeyError(f"Unknown settings: {', '.join(sorted(unknown))}")
        updated = replace(self.settings, **changes)
        self.settings = updated
        self.save()
        return updated

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                self._backup_path.write_bytes(self.path.read_bytes())
            except OSError:
                pass
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload: dict[str, Any] = {"schema_version": SCHEMA_VERSION, **asdict(self.settings)}
        payload["gesture_bindings"] = {
            gesture: action.to_dict()
            for gesture, action in self.settings.gesture_bindings.items()
        }
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        atomic_replace(temporary, self.path)

    def set_startup_enabled(self, enabled: bool) -> AppSettings:
        """Toggle both the persisted setting and Windows Startup launcher."""
        if not isinstance(enabled, bool):
            raise ValueError("startup_enabled must be a boolean")
        if self.startup_manager is not None:
            self.startup_manager.set_enabled(enabled)
        return self.update(startup_enabled=enabled)

    def synchronize_startup(self) -> None:
        """Repair the Startup launcher to match the persisted setting on launch."""
        if self.startup_manager is not None:
            self.startup_manager.set_enabled(self.settings.startup_enabled)
