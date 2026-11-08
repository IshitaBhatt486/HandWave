"""Validated, atomic local persistence for custom gesture definitions.

Only normalized landmark-derived parameters are ever stored here — never raw
camera frames or video.
"""

from __future__ import annotations

from handwave import platforms
from handwave.config.storage import migrate_legacy_file

import json
import logging
from pathlib import Path
from typing import Any

from handwave.config.atomic_write import atomic_replace
from handwave.gestures.custom_gesture import CustomGestureDefinition

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
    version = raw.get("schema_version", 0)
    if version == 0:
        raw = {"schema_version": 1, "gestures": raw.get("gestures", [])}
        version = 1
    if version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported custom gesture schema version: {version}")
    return raw


class CustomGestureStore:
    """Load and atomically persist custom gesture definitions across restarts."""

    LEGACY_SOURCE_PATH = Path(__file__).with_name("custom_gestures.json")
    DEFAULT_PATH = platforms.config_dir() / "custom_gestures.json"

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else migrate_legacy_file(self.LEGACY_SOURCE_PATH, self.DEFAULT_PATH)
        self._backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.gestures: dict[str, CustomGestureDefinition] = {}
        self._load()

    def _load(self) -> None:
        for candidate in (self.path, self._backup_path):
            if not candidate.exists():
                continue
            try:
                raw = _migrate(json.loads(candidate.read_text(encoding="utf-8")))
                definitions = [CustomGestureDefinition.from_data(item) for item in raw.get("gestures", [])]
                self.gestures = {definition.gesture_id: definition for definition in definitions}
                if candidate == self._backup_path:
                    logger.warning("Recovered custom gestures from backup after primary file failure")
                return
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                logger.exception("Failed to load custom gestures from %s", candidate)
                continue
        self.gestures = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": SCHEMA_VERSION, "gestures": [g.to_dict() for g in self.gestures.values()]}
        if self.path.exists():
            try:
                self._backup_path.write_bytes(self.path.read_bytes())
            except OSError:
                logger.exception("Failed to refresh custom gestures backup file")
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        atomic_replace(temporary, self.path)

    def list_gestures(self) -> list[CustomGestureDefinition]:
        return list(self.gestures.values())

    def get_gesture(self, gesture_id: str) -> CustomGestureDefinition | None:
        return self.gestures.get(gesture_id)

    def add_gesture(self, definition: CustomGestureDefinition) -> CustomGestureDefinition:
        existing_names = {g.name.lower() for g in self.gestures.values()}
        if definition.name.lower() in existing_names:
            raise ValueError(f"A custom gesture named '{definition.name}' already exists")
        self.gestures[definition.gesture_id] = definition
        self._save()
        return definition

    def update_gesture(self, gesture_id: str, **changes: Any) -> CustomGestureDefinition:
        from dataclasses import replace

        existing = self._require(gesture_id)
        updated = replace(existing, **changes)
        self.gestures[gesture_id] = updated
        self._save()
        return updated

    def duplicate_gesture(self, gesture_id: str, name: str | None = None) -> CustomGestureDefinition:
        from dataclasses import replace

        import uuid

        existing = self._require(gesture_id)
        copy = replace(existing, gesture_id=uuid.uuid4().hex, name=name or f"{existing.name} (copy)")
        self.gestures[copy.gesture_id] = copy
        self._save()
        return copy

    def delete_gesture(self, gesture_id: str) -> None:
        self._require(gesture_id)
        del self.gestures[gesture_id]
        self._save()

    def set_enabled(self, gesture_id: str, enabled: bool) -> CustomGestureDefinition:
        return self.update_gesture(gesture_id, enabled=enabled)

    def _require(self, gesture_id: str) -> CustomGestureDefinition:
        try:
            return self.gestures[gesture_id]
        except KeyError:
            raise KeyError(f"Unknown custom gesture id: {gesture_id}") from None
