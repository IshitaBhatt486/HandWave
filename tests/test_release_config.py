import re
from pathlib import Path

from handwave.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_matches_across_app_executable_and_installer():
    numeric = tuple(int(part) for part in re.match(r"(\d+)\.(\d+)\.(\d+)", __version__).groups())
    version_info = (ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    assert f"filevers=({numeric[0]}, {numeric[1]}, {numeric[2]}, 0)" in version_info
    assert f"StringStruct('ProductVersion', '{__version__}')" in version_info
    installer = (ROOT / "packaging" / "HandWave.nsi").read_text(encoding="utf-8")
    assert f'!define PRODUCT_VERSION "{__version__}"' in installer
    assert f"## {__version__}" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_build_specs_only_reference_files_that_exist():
    for spec in ("HandWave.spec", "HandWave-macos.spec"):
        text = (ROOT / "packaging" / spec).read_text(encoding="utf-8")
        for parts in re.findall(r'ROOT((?: / "[^"]+")+)', text):
            path = ROOT.joinpath(*re.findall(r'"([^"]+)"', parts))
            assert path.exists(), (spec, path)
        assert '"settings.json"' not in text  # never bundle a developer's local settings


def test_builds_bundle_licences_for_every_gpl_and_apache_component():
    for spec in ("HandWave.spec", "HandWave-macos.spec"):
        assert "LICENSE_DATAS" in (ROOT / "packaging" / spec).read_text(encoding="utf-8").split("datas=")[1]

    import importlib.util

    module_spec = importlib.util.spec_from_file_location("collect_licenses", ROOT / "scripts" / "collect_licenses.py")
    collect_licenses = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(collect_licenses)
    text = collect_licenses.render()
    assert "GNU GENERAL PUBLIC LICENSE" in text and "Version 3, 29 June 2007" in text
    for component in ("PyQt6", "PyQt6-Qt6", "mediapipe", "opencv-python", "numpy", "sounddevice"):
        assert f"- {component} " in text, component
