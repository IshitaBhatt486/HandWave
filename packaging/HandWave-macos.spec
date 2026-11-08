# -*- mode: python ; coding: utf-8 -*-
# macOS .app bundle (EXPERIMENTAL; untested by the maintainers, see docs/macos.md).
# Build on a Mac with:  bash scripts/build_macos.sh

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent  # the spec lives in packaging/

# Licence texts for everything bundled (required by the GPL, LGPL and Apache
# licences of PyQt6, Qt, OpenCV, MediaPipe and others); see scripts/collect_licenses.py.
sys.path.insert(0, str(ROOT.joinpath("scripts")))
from collect_licenses import write as write_third_party_licenses  # noqa: E402

LICENSE_DATAS = [
    (str(write_third_party_licenses(ROOT.joinpath("build", "THIRD_PARTY_LICENSES.txt"))), "."),
    (str(ROOT / "LICENSE"), "."),
]

mediapipe_data, mediapipe_binaries, mediapipe_hidden = collect_all("mediapipe")
mediapipe_hidden = [
    module for module in mediapipe_hidden
    if ".genai" not in module and ".test" not in module
]
# Same slimming as the Windows build (packaging/HandWave.spec): Hands models only, and
# packages never imported at runtime.
HAND_MODULES = ("mediapipe/modules/hand_landmark/", "mediapipe/modules/palm_detection/")
mediapipe_data = [
    (source, target) for source, target in mediapipe_data
    if "mediapipe/modules/" not in target.replace("\\", "/") + "/"
    or any((target.replace("\\", "/") + "/").startswith(prefix) for prefix in HAND_MODULES)
]
UNUSED_PACKAGES = ["jax", "jaxlib", "scipy", "ml_dtypes", "opt_einsum", "keyboard"]
mediapipe_hidden = [
    module for module in mediapipe_hidden
    if not any(module == name or module.startswith(name + ".") for name in UNUSED_PACKAGES)
]

a = Analysis(
    [str(ROOT / "handwave" / "main.py")],
    pathex=[str(ROOT)],
    binaries=mediapipe_binaries,
    datas=mediapipe_data + [(str(ROOT / "handwave" / "assets" / "handwave.png"), "handwave/assets")] + LICENSE_DATAS,
    hiddenimports=mediapipe_hidden + ["AppKit", "Quartz", "AVFoundation"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "pytestqt", *UNUSED_PACKAGES],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HandWave",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="HandWave")
app = BUNDLE(
    coll,
    name="HandWave.app",
    icon=str(ROOT / "handwave" / "assets" / "handwave.png"),
    bundle_identifier="com.handwave.app",
    info_plist={
        "CFBundleName": "HandWave",
        "CFBundleDisplayName": "HandWave",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        # macOS terminates apps that touch the camera/microphone without these.
        "NSCameraUsageDescription": "HandWave watches your hand gestures. Video is processed on this Mac and never leaves it.",
        "NSMicrophoneUsageDescription": "HandWave listens for a double clap to turn recognition on or off. Only loudness is measured; no audio is recorded.",
    },
)
