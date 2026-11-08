#!/usr/bin/env bash
# Build HandWave.app on macOS (EXPERIMENTAL — see docs/macos.md).
# Usage: bash scripts/build_macos.sh   (on a Mac)
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "$(uname)" != "Darwin" ]]; then
  echo "build_macos.sh must run on macOS." >&2
  exit 1
fi

PYTHON="${PYTHON:-python3.11}"
if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt

echo "== Tests (macOS) =="
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --no-cov -p no:cacheprovider || {
  echo "Some tests failed on macOS. Please include this output in a macOS test report:" >&2
  echo "https://github.com/IshitaBhatt486/GestureControl/issues/new?template=macos-test-report.md" >&2
  exit 1
}

echo "== PyInstaller =="
.venv/bin/python -m PyInstaller packaging/HandWave-macos.spec --clean -y
echo
echo "Built: dist/HandWave.app"
echo "First launch: right-click HandWave.app > Open (the app is not notarised)."
echo "Then allow Camera, Microphone and Accessibility in System Settings > Privacy & Security."
