"""Write THIRD_PARTY_LICENSES.txt for everything bundled into HandWave builds.

Walks the runtime dependencies in requirements.txt (and their dependencies),
skips packages the build excludes, and copies each package's licence and
NOTICE files. The PyInstaller specs call this, so the file always matches the
installed versions. Run it directly to inspect the output:

    python scripts/collect_licenses.py [output-path]
"""

from __future__ import annotations

import importlib.metadata as metadata
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Installed as MediaPipe dependencies but excluded from the build (see packaging/HandWave.spec).
NOT_BUNDLED = {"jax", "jaxlib", "scipy", "ml-dtypes", "opt-einsum", "opencv-contrib-python"}
LICENSE_FILE = re.compile(r"(licen[cs]e|copying|notice|authors)", re.IGNORECASE)
TEXT_SUFFIXES = {"", ".txt", ".md", ".rst", ".apache", ".bsd", ".external"}
# These wheels ship no licence file; their metadata says GPL v3 (or later).
GPL_TEXT = ROOT / "packaging" / "licenses" / "GPL-3.0.txt"
GPL_WITHOUT_TEXT = {"pyqt6", "mouseinfo"}

HEADER = """HandWave third-party licences
=============================

HandWave's own source code is MIT-licensed (see LICENSE in the repository:
https://github.com/IshitaBhatt486/HandWave).

This program as distributed (HandWave.exe / HandWave.app) also contains the
components listed below. Because it includes PyQt6, MouseInfo and PyMsgBox,
which are licensed under the GNU General Public License version 3, the
combined program is distributed under the terms of the GPL v3. Its complete
corresponding source code is the HandWave repository at the matching version
tag, together with the published source of each component below.

Qt (via PyQt6-Qt6) and FFmpeg (inside OpenCV) are used under the LGPL v3 and
LGPL v2.1. You can replace them by running HandWave from source with your own
builds of those libraries; see docs/development.md.

The program is provided WITHOUT ANY WARRANTY, to the extent permitted by law.

The bundled Python runtime is under the PSF License, and the Microsoft Visual
C++ runtime DLLs are redistributed under Microsoft's redistribution terms.
"""


def _name(requirement: str) -> str | None:
    """Package name from a requirement string, or None if its marker excludes this platform."""
    if ";" in requirement:
        requirement, marker = requirement.split(";", 1)
        if "extra" in marker:
            return None
        try:
            from packaging.markers import Marker

            if not Marker(marker).evaluate():
                return None
        except Exception:  # packaging unavailable: include rather than miss a licence
            pass
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return match.group(1) if match else None


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def bundled_distributions() -> list[metadata.Distribution]:
    roots = [
        _name(line) for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    pending = [name for name in roots if name]
    seen: dict[str, metadata.Distribution] = {}
    while pending:
        key = _normalise(pending.pop())
        if key in seen or key in NOT_BUNDLED:
            continue
        try:
            dist = metadata.distribution(key)
        except metadata.PackageNotFoundError:
            continue
        seen[key] = dist
        pending.extend(name for name in map(_name, dist.requires or []) if name)
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def _licence_label(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    label = meta.get("License-Expression") or ""
    if not label:
        short = (meta.get("License") or "").strip()
        label = short if short and "\n" not in short and len(short) < 80 else ""
    if not label:
        classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License")]
        label = ", ".join(classifiers)
    return label or "see licence text below"


def _licence_texts(dist: metadata.Distribution) -> list[tuple[str, str]]:
    texts, seen = [], set()
    for file in dist.files or []:
        name = Path(str(file)).name
        if not LICENSE_FILE.search(name) or Path(name).suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = Path(dist.locate_file(file)).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text and text not in seen:  # wheels often carry the same file twice
            seen.add(text)
            texts.append((str(file), text))
    if not texts and _normalise(dist.metadata["Name"]) in GPL_WITHOUT_TEXT:
        texts.append(("GNU General Public License v3", GPL_TEXT.read_text(encoding="utf-8")))
    if not texts and "\n" in (dist.metadata.get("License") or ""):
        texts.append(("License metadata", dist.metadata["License"]))
    return texts


def render() -> str:
    dists = bundled_distributions()
    lines = [HEADER, "Components", "----------", ""]
    for dist in dists:
        meta = dist.metadata
        url = meta.get("Home-page") or next(
            (u.split(",", 1)[1].strip() for u in meta.get_all("Project-URL") or []), "")
        lines.append(f"- {meta['Name']} {dist.version}: {_licence_label(dist)}  {url}".rstrip())
    for dist in dists:
        for path, text in _licence_texts(dist):
            lines += ["", "=" * 78, f"{dist.metadata['Name']} {dist.version} — {path}", "=" * 78, "", text.strip()]
    return "\n".join(lines) + "\n"


def write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8")
    return path


if __name__ == "__main__":
    out = write(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "THIRD_PARTY_LICENSES.txt")
    print(out)
