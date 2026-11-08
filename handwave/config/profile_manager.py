"""Validated, atomic persistence for application profiles."""

from __future__ import annotations

from handwave import platforms
from handwave.config.storage import migrate_legacy_file

import json
import logging
from pathlib import Path
from typing import Any

from handwave.config.atomic_write import atomic_replace
from handwave.config.profile import Profile

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Upgrade an on-disk payload to the current schema, in place."""
    version = raw.get("schema_version", 0)
    if version == 0:
        raw = {"schema_version": 1, "profiles": raw.get("profiles", []), "active_profile_id": raw.get("active_profile_id")}
        version = 1
    if version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported profiles schema version: {version}")
    return raw


class ProfileManager:
    """Load and atomically persist the application-profile list across restarts."""

    LEGACY_SOURCE_PATH = Path(__file__).with_name("profiles.json")
    DEFAULT_PATH = platforms.config_dir() / "profiles.json"

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else migrate_legacy_file(self.LEGACY_SOURCE_PATH, self.DEFAULT_PATH)
        self._backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.profiles: dict[str, Profile] = {}
        self.active_profile_id: str | None = None
        self._load()

    def _load(self) -> None:
        for candidate in (self.path, self._backup_path):
            if not candidate.exists():
                continue
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
                raw = _migrate(raw)
                profiles = [Profile.from_data(item) for item in raw.get("profiles", [])]
                self.profiles = {profile.profile_id: profile for profile in profiles}
                self.active_profile_id = raw.get("active_profile_id")
                if candidate == self._backup_path:
                    logger.warning("Recovered profiles from backup after primary file failure")
                return
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                logger.exception("Failed to load profiles from %s", candidate)
                continue
        self.profiles = {}
        self.active_profile_id = None

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "profiles": [profile.to_dict() for profile in self.profiles.values()],
            "active_profile_id": self.active_profile_id,
        }
        if self.path.exists():
            try:
                self._backup_path.write_bytes(self.path.read_bytes())
            except OSError:
                logger.exception("Failed to refresh profiles backup file")
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        atomic_replace(temporary, self.path)

    def list_profiles(self) -> list[Profile]:
        return list(self.profiles.values())

    def get_profile(self, profile_id: str) -> Profile | None:
        return self.profiles.get(profile_id)

    def create_profile(self, name: str, **kwargs: Any) -> Profile:
        profile = Profile(name=name, **kwargs)
        self.profiles[profile.profile_id] = profile
        self._save()
        return profile

    def update_profile(self, profile_id: str, **changes: Any) -> Profile:
        existing = self._require(profile_id)
        from dataclasses import replace

        updated = replace(existing, **changes)
        self.profiles[profile_id] = updated
        self._save()
        return updated

    def duplicate_profile(self, profile_id: str, name: str | None = None) -> Profile:
        existing = self._require(profile_id)
        copy = existing.duplicate(name=name)
        self.profiles[copy.profile_id] = copy
        self._save()
        return copy

    def copy_settings_from(self, target_profile_id: str, source_profile_id: str) -> Profile:
        """Adopt another profile's overrides as an independent copy (no shared references)."""
        target = self._require(target_profile_id)
        source = self._require(source_profile_id)
        updated = target.copy_overrides_from(source)
        self.profiles[target_profile_id] = updated
        self._save()
        return updated

    def reset_overrides(self, profile_id: str) -> Profile:
        existing = self._require(profile_id)
        updated = existing.reset_overrides()
        self.profiles[profile_id] = updated
        self._save()
        return updated

    def delete_profile(self, profile_id: str) -> None:
        self._require(profile_id)
        del self.profiles[profile_id]
        if self.active_profile_id == profile_id:
            self.active_profile_id = None
        self._save()

    def set_enabled(self, profile_id: str, enabled: bool) -> Profile:
        return self.update_profile(profile_id, enabled=enabled)

    def set_active_profile(self, profile_id: str | None) -> None:
        if profile_id is not None:
            self._require(profile_id)
        self.active_profile_id = profile_id
        self._save()

    def get_active_profile(self) -> Profile | None:
        if self.active_profile_id is None:
            return None
        return self.profiles.get(self.active_profile_id)

    def export_profile(self, profile_id: str, path: str | Path) -> None:
        profile = self._require(profile_id)
        Path(path).write_text(json.dumps(profile.to_dict(), indent=2) + "\n", encoding="utf-8")

    def import_profile(self, path: str | Path) -> Profile:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Imported profile must be a JSON object")
        raw = dict(raw)
        raw.pop("profile_id", None)  # always assign a fresh id to avoid collisions
        profile = Profile.from_data(raw)
        self.profiles[profile.profile_id] = profile
        self._save()
        return profile

    def _require(self, profile_id: str) -> Profile:
        try:
            return self.profiles[profile_id]
        except KeyError:
            raise KeyError(f"Unknown profile id: {profile_id}") from None
