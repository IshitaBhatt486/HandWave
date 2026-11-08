"""Poll the foreground application and resolve which profile should be active.

This module only ever computes data (which profile, why, and the resulting
effective settings). It never touches the camera or MediaPipe, so applying its
result is always a config-diff, never a pipeline restart.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from handwave.config.profile_manager import ProfileManager
from handwave.config.settings_manager import AppSettings
from handwave.services.app_matcher import AppMatch, select_profile
from handwave.services.foreground_app import ForegroundAppInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProfileSwitchEvent:
    """A snapshot of one poll's outcome, suitable for diagnostics display."""

    foreground: ForegroundAppInfo
    match: AppMatch
    effective_settings: AppSettings
    changed: bool
    timestamp: float


class ProfileSwitcher:
    """Determine and track the effective profile for the current foreground app."""

    def __init__(
        self,
        profile_manager: ProfileManager,
        foreground_provider: Callable[[], ForegroundAppInfo],
        global_settings_provider: Callable[[], AppSettings],
        on_change: Callable[[ProfileSwitchEvent], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        enabled: bool = True,
    ) -> None:
        self._profile_manager = profile_manager
        self._foreground_provider = foreground_provider
        self._global_settings_provider = global_settings_provider
        self._on_change = on_change
        self._clock = clock
        self.enabled = enabled
        self.last_event: ProfileSwitchEvent | None = None
        self.last_switch_time: float | None = None

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def poll(self) -> ProfileSwitchEvent:
        """Re-evaluate the foreground app and return the resulting profile match.

        Safe to call at any rate: repeated polls while nothing changed are
        idempotent and cheap (no filesystem or pipeline work beyond the
        injected foreground lookup).
        """
        foreground = self._foreground_provider()
        global_settings = self._global_settings_provider()

        if not self.enabled:
            explicit = self._profile_manager.get_active_profile()
            reason = "explicit_selection" if explicit is not None else "auto_switch_disabled"
            match = AppMatch(explicit, reason)
        else:
            match = select_profile(
                self._profile_manager.list_profiles(), foreground.executable, foreground.window_title
            )
            if match.profile is None:
                explicit = self._profile_manager.get_active_profile()
                if explicit is not None:
                    match = AppMatch(explicit, "explicit_selection")

        effective_settings = match.profile.resolve(global_settings) if match.profile else global_settings

        previous_id = self._profile_id(self.last_event.match if self.last_event else None)
        current_id = self._profile_id(match)
        changed = (
            self.last_event is None
            or current_id != previous_id
            or effective_settings != self.last_event.effective_settings
        )
        now = self._clock()
        if changed:
            self.last_switch_time = now

        event = ProfileSwitchEvent(
            foreground=foreground,
            match=match,
            effective_settings=effective_settings,
            changed=changed,
            timestamp=now,
        )
        self.last_event = event
        if changed and self._on_change is not None:
            try:
                self._on_change(event)
            except Exception:
                logger.exception("Profile switch callback failed")
        return event

    @staticmethod
    def _profile_id(match: AppMatch | None) -> str | None:
        if match is None or match.profile is None:
            return None
        return match.profile.profile_id
