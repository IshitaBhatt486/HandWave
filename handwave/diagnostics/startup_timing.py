"""Development-only startup instrumentation.

Enabled by setting ``HANDWAVE_STARTUP_PROFILE=1`` before launch. Disabled (the
default), ``mark()`` is a no-op with negligible overhead, so this stays safe
to leave instrumented in the normal startup path.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

ENV_VAR = "HANDWAVE_STARTUP_PROFILE"


def is_enabled() -> bool:
    return os.environ.get(ENV_VAR, "") not in ("", "0", "false", "False")


class StartupTimer:
    """Records named checkpoints as elapsed seconds since construction."""

    def __init__(self, enabled: bool | None = None, clock: Callable[[], float] = time.perf_counter) -> None:
        self.enabled = is_enabled() if enabled is None else enabled
        self._clock = clock
        self._start = clock()
        self.marks: list[tuple[str, float]] = []

    def mark(self, label: str) -> float:
        """Record a checkpoint; returns the elapsed seconds (0.0 when disabled)."""
        if not self.enabled:
            return 0.0
        elapsed = self._clock() - self._start
        self.marks.append((label, elapsed))
        return elapsed

    def report(self) -> str:
        """A human-readable table of checkpoints and the deltas between them."""
        if not self.marks:
            return "(startup profiling disabled or no checkpoints recorded)"
        lines = ["Startup timing report:"]
        previous = 0.0
        for label, elapsed in self.marks:
            delta = elapsed - previous
            lines.append(f"  {elapsed:7.3f}s  (+{delta:6.3f}s)  {label}")
            previous = elapsed
        return "\n".join(lines)
