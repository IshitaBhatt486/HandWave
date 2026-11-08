# -*- mode: python ; coding: utf-8 -*-

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
# HandWave uses MediaPipe's hand-landmarker APIs, not its optional GenAI
# converter or upstream test suite. Their discovery pulls in optional torch
# imports and unnecessarily makes release analysis noisy and slow.
mediapipe_hidden = [
    module for module in mediapipe_hidden
    if ".genai" not in module and ".test" not in module
]
# HandWave only runs MediaPipe Hands, which needs the hand-landmark and palm-
# detection graphs/models. Face, pose, iris, holistic, selfie and objectron
# models (~32 MB) are never loaded.
HAND_MODULES = ("mediapipe/modules/hand_landmark/", "mediapipe/modules/palm_detection/")
mediapipe_data = [
    (source, target) for source, target in mediapipe_data
    if "mediapipe/modules/" not in target.replace("\\", "/") + "/"
    or any((target.replace("\\", "/") + "/").startswith(prefix) for prefix in HAND_MODULES)
]
# Verified by listing sys.modules in a running HandWave: jax/jaxlib/scipy are
# never imported (collect_all's optional MediaPipe submodules dragged them in,
# ~300 MB uncompressed). matplotlib itself stays: its base package is still
# imported (only matplotlib.pyplot is deferred, see handwave/vision/lazy_imports.py).
UNUSED_PACKAGES = ["jax", "jaxlib", "scipy", "ml_dtypes", "opt_einsum"]
mediapipe_hidden = [
    module for module in mediapipe_hidden
    if not any(module == name or module.startswith(name + ".") for name in UNUSED_PACKAGES)
]

a = Analysis(
    [str(ROOT / "handwave" / "main.py")],
    pathex=[str(ROOT)],
    binaries=mediapipe_binaries,
    # Do not bundle handwave/config/settings.json: it is a developer's local
    # settings file, and the app would copy it into every user's profile.
    datas=mediapipe_data + [(str(ROOT / "handwave" / "assets" / "handwave.ico"), "handwave/assets")] + LICENSE_DATAS,
    hiddenimports=mediapipe_hidden,
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
    a.binaries,
    a.datas,
    [],
    name="HandWave",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # packed executables are a common antivirus false positive
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "handwave" / "assets" / "handwave.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)
