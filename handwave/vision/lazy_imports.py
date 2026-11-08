"""Keep MediaPipe from loading matplotlib, which HandWave never uses.

``mediapipe`` imports ``mediapipe.python.solutions.drawing_utils``, which runs
``import matplotlib.pyplot as plt`` at import time only to support a 3-D
plotting helper (``plot_landmarks``). Measured on Windows: +41 MB of memory
and ~0.7-1.0 s of import time at every recognition start, more than the rest
of MediaPipe's Python layer.

``install_matplotlib_placeholder()`` registers a lightweight placeholder for
``matplotlib.pyplot`` (the expensive part). It loads the real module on the
first actual attribute access, so anything that genuinely uses it (the
benchmark charts, ``plot_landmarks``) keeps working unchanged.

The base ``matplotlib`` package is still imported normally. Skipping it as
well exposed an intermittent native crash in the test suite (a worker thread
faulting with no Python frames) that we could not root-cause, while importing
the package kept 10/10 full runs clean; see docs/performance.md.
"""

from __future__ import annotations

import importlib
import sys
import types

_NAMES = ("matplotlib.pyplot",)


class _Placeholder(types.ModuleType):
    """Stands in for a module until something actually uses it."""

    def __getattr__(self, attribute: str):
        if attribute.startswith("__") and attribute not in ("__path__", "__file__", "__version__"):
            raise AttributeError(attribute)
        return getattr(_load_real(self.__name__), attribute)


def _load_real(name: str):
    for placeholder in _NAMES:
        if isinstance(sys.modules.get(placeholder), _Placeholder):
            del sys.modules[placeholder]
    return importlib.import_module(name)


def install_matplotlib_placeholder() -> bool:
    """Install the placeholders unless matplotlib is already loaded. Returns True if installed."""
    if any(name in sys.modules for name in _NAMES):
        return False
    # ``import matplotlib.pyplot as plt`` imports the real package, then finds
    # the placeholder in sys.modules (the package has no ``pyplot`` attribute
    # until the real submodule is imported).
    sys.modules["matplotlib.pyplot"] = _Placeholder("matplotlib.pyplot")
    return True


def is_placeholder(module: object) -> bool:
    return isinstance(module, _Placeholder)
