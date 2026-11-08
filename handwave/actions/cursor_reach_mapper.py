"""Map calibrated normalized hand reach to screen pixel coordinates."""

from __future__ import annotations

from dataclasses import dataclass

from handwave.actions.cursor_smoothing import OneEuroFilter2D


@dataclass(frozen=True)
class CursorReach:
    """Calibrated camera-space bounds, expressed in the 0..1 landmark space."""

    center_x: float
    center_y: float
    left_limit: float
    right_limit: float
    top_limit: float
    bottom_limit: float
    dead_zone_percent: float = 0.0

    def __post_init__(self) -> None:
        values = (self.center_x, self.center_y, self.left_limit, self.right_limit, self.top_limit, self.bottom_limit)
        if any(not 0.0 <= value <= 1.0 for value in values):
            raise ValueError("Cursor reach values must be between 0 and 1")
        if not self.left_limit < self.center_x < self.right_limit:
            raise ValueError("Horizontal limits must surround center_x")
        if not self.top_limit < self.center_y < self.bottom_limit:
            raise ValueError("Vertical limits must surround center_y")
        if not 0.0 <= self.dead_zone_percent < 100.0:
            raise ValueError("Dead zone percent must be between 0 and 100")


def normalize_reach(value: float, lower: float, center: float, upper: float) -> float:
    """Map lower/center/upper to 0/0.5/1, preserving asymmetric reach.

    A side with no usable reach (a provisional profile mid-calibration, where
    the captured limit equals or crosses the center) maps to the center
    instead of dividing by zero.
    """
    if value <= center:
        span = center - lower
        normalized = 0.5 if span <= 0 else 0.5 * (value - lower) / span
    else:
        span = upper - center
        normalized = 0.5 if span <= 0 else 0.5 + 0.5 * (value - center) / span
    return max(0.0, min(1.0, normalized))


def apply_dead_zone(normalized: float, dead_zone_percent: float) -> float:
    """Hold the cursor at center, then smoothly rescale movement outside it."""
    half_zone = dead_zone_percent / 200.0
    if abs(normalized - 0.5) <= half_zone:
        return 0.5
    if normalized < 0.5:
        return 0.5 * normalized / (0.5 - half_zone)
    return 0.5 + 0.5 * (normalized - 0.5 - half_zone) / (0.5 - half_zone)


def map_cursor_reach(
    current_hand_x: float,
    current_hand_y: float,
    reach: CursorReach,
    screen_width: int,
    screen_height: int,
) -> tuple[int, int]:
    """Return safely clamped pixel coordinates for any positive screen size."""
    if screen_width <= 0 or screen_height <= 0:
        raise ValueError("Screen dimensions must be positive")
    normalized_x = apply_dead_zone(normalize_reach(current_hand_x, reach.left_limit, reach.center_x, reach.right_limit), reach.dead_zone_percent)
    normalized_y = apply_dead_zone(normalize_reach(current_hand_y, reach.top_limit, reach.center_y, reach.bottom_limit), reach.dead_zone_percent)
    return (
        min(screen_width - 1, max(0, round(normalized_x * (screen_width - 1)))),
        min(screen_height - 1, max(0, round(normalized_y * (screen_height - 1)))),
    )


class SmoothedCursorReachMapper:
    """Stateful reach mapper that filters hand input before dead-zone mapping."""

    def __init__(self, reach: CursorReach, smoothing: str = "medium") -> None:
        self.reach = reach
        self.filter = OneEuroFilter2D(smoothing)

    def map(self, hand_x: float, hand_y: float, timestamp: float, screen_width: int, screen_height: int) -> tuple[int, int]:
        x, y = self.filter.update(hand_x, hand_y, timestamp)
        return map_cursor_reach(x, y, self.reach, screen_width, screen_height)

    def reset(self) -> None:
        self.filter.reset()
