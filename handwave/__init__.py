"""HandWave desktop application package."""

from handwave._runtime import prepare_native_libraries as _prepare_native_libraries

# Must run before any submodule imports PyQt6, OpenCV or MediaPipe.
_prepare_native_libraries()
