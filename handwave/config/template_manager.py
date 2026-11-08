"""Atomic persistence and CRUD for reusable HandWave templates."""

from __future__ import annotations

from handwave import platforms
from handwave.config.storage import migrate_legacy_file

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from handwave.config.atomic_write import atomic_replace
from handwave.config.template import Template

SCHEMA_VERSION = 1
logger = logging.getLogger(__name__)


class TemplateManager:
    LEGACY_SOURCE_PATH = Path(__file__).with_name("templates.json")
    DEFAULT_PATH = platforms.config_dir() / "templates.json"

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else migrate_legacy_file(self.LEGACY_SOURCE_PATH, self.DEFAULT_PATH)
        self._backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.templates: dict[str, Template] = {}
        self.active_template_id: str | None = None
        self._load()
        if not self.templates:
            general = Template(name="General")
            self.templates[general.template_id] = general
            self.active_template_id = general.template_id
            self._save()
        elif self.active_template_id is None:
            self.active_template_id = next(iter(self.templates))
            self._save()

    def _load(self) -> None:
        for candidate in (self.path, self._backup_path):
            if not candidate.exists():
                continue
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("Template store must be an object")
                version = raw.get("schema_version", 0)
                if version == 0:
                    raw = {
                        "schema_version": 1,
                        "templates": raw.get("templates", []),
                        "active_template_id": raw.get("active_template_id"),
                    }
                if raw["schema_version"] != SCHEMA_VERSION:
                    raise ValueError("Unsupported templates schema version")
                loaded = [Template.from_data(item) for item in raw.get("templates", [])]
                self.templates = {template.template_id: template for template in loaded}
                active = raw.get("active_template_id")
                self.active_template_id = active if active in self.templates else None
                if candidate == self._backup_path:
                    logger.warning("Recovered templates from backup after primary file failure")
                return
            except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError):
                logger.exception("Failed to load templates from %s", candidate)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                self._backup_path.write_bytes(self.path.read_bytes())
            except OSError:
                logger.exception("Failed to refresh templates backup file")
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "templates": [template.to_dict() for template in self.templates.values()],
            "active_template_id": self.active_template_id,
        }
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        atomic_replace(temporary, self.path)

    def list_templates(self) -> list[Template]:
        return list(self.templates.values())

    def get_template(self, template_id: str) -> Template | None:
        return self.templates.get(template_id)

    def get_active_template(self) -> Template:
        return self.templates[self.active_template_id]

    def create_template(self, name: str, **changes: Any) -> Template:
        template = Template(name=name, **changes)
        self.templates[template.template_id] = template
        self._save()
        return template

    def update_template(self, template_id: str, **changes: Any) -> Template:
        template = replace(self._require(template_id), **changes)
        self.templates[template_id] = template
        self._save()
        return template

    def duplicate_template(self, template_id: str, name: str | None = None) -> Template:
        template = self._require(template_id).duplicate(name)
        self.templates[template.template_id] = template
        self._save()
        return template

    def delete_template(self, template_id: str) -> None:
        if len(self.templates) == 1:
            raise ValueError("At least one template is required")
        self._require(template_id)
        del self.templates[template_id]
        if self.active_template_id == template_id:
            self.active_template_id = next(iter(self.templates))
        self._save()

    def set_active_template(self, template_id: str) -> None:
        self._require(template_id)
        self.active_template_id = template_id
        self._save()

    def export_template(self, template_id: str, path: str | Path) -> None:
        template = self._require(template_id)
        Path(path).write_text(json.dumps(template.to_dict(), indent=2) + "\n", encoding="utf-8")

    def import_template(self, path: str | Path) -> Template:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Imported template must be an object")
        raw.pop("template_id", None)
        template = Template.from_data(raw)
        self.templates[template.template_id] = template
        self._save()
        return template

    def _require(self, template_id: str) -> Template:
        if template_id not in self.templates:
            raise KeyError(f"Unknown template id: {template_id}")
        return self.templates[template_id]
