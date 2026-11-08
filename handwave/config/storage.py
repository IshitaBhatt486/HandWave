"""Migration of user data from older locations."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def migrate_legacy_file(legacy: Path, target: Path) -> Path:
    """Copy ``legacy`` to ``target`` once, if only the old file exists. Returns ``target``.

    Older versions kept profiles, templates and custom gestures inside the
    source tree when run from a checkout; they now live in the per-user
    config folder (see ``handwave.platforms.config_dir``).
    """
    if legacy.is_file() and not target.exists():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy, target)
            logger.info("Moved %s to %s", legacy, target)
        except OSError:
            logger.warning("Could not migrate %s", legacy, exc_info=True)
    return target
