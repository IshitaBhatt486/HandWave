import pytest

from handwave.actions.cursor_reach_mapper import CursorReach, SmoothedCursorReachMapper, apply_dead_zone, map_cursor_reach, normalize_reach


@pytest.fixture
def reach():
    return CursorReach(.5, .5, .2, .8, .1, .9)


def test_calibrated_limits_and_center_cover_full_screen(reach):
    assert map_cursor_reach(.2, .1, reach, 1920, 1080) == (0, 0)
    assert map_cursor_reach(.5, .5, reach, 1920, 1080) == (960, 540)
    assert map_cursor_reach(.8, .9, reach, 1920, 1080) == (1919, 1079)


def test_asymmetric_reach_keeps_center_at_fifty_percent():
    assert normalize_reach(.3, .1, .3, .9) == pytest.approx(.5)
    assert normalize_reach(.1, .1, .3, .9) == pytest.approx(0)
    assert normalize_reach(.9, .1, .3, .9) == pytest.approx(1)


def test_values_outside_comfortable_reach_are_clamped(reach):
    assert map_cursor_reach(-5, 5, reach, 1280, 720) == (0, 719)


def test_dead_zone_holds_center_and_rescales_remaining_travel():
    assert apply_dead_zone(.45, 10) == pytest.approx(.5)
    assert apply_dead_zone(.55, 10) == pytest.approx(.5)
    assert apply_dead_zone(.0, 10) == pytest.approx(.0)
    assert apply_dead_zone(1.0, 10) == pytest.approx(1.0)


def test_any_positive_monitor_resolution_is_supported(reach):
    assert map_cursor_reach(.5, .5, reach, 3840, 2160) == (1920, 1080)
    assert map_cursor_reach(.5, .5, reach, 1, 1) == (0, 0)


def test_invalid_bounds_and_screen_sizes_are_rejected(reach):
    with pytest.raises(ValueError):
        CursorReach(.5, .5, .6, .8, .1, .9)
    with pytest.raises(ValueError):
        map_cursor_reach(.5, .5, reach, 0, 1080)


def test_stateful_mapper_applies_configured_smoothing(reach):
    mapper = SmoothedCursorReachMapper(reach, "high")
    assert mapper.map(.5, .5, 0, 1000, 1000) == (500, 500)
    # A high-smoothing step remains between center and the requested right edge.
    assert 500 < mapper.map(.8, .5, 1/30, 1000, 1000)[0] < 999


def test_normalize_reach_handles_degenerate_provisional_spans():
    from handwave.actions.cursor_reach_mapper import normalize_reach

    # Mid-calibration a reach limit can equal or cross the center.
    assert normalize_reach(0.4, 0.5, 0.5, 0.9) == 0.5
    assert normalize_reach(0.7, 0.1, 0.5, 0.5) == 0.5
    assert normalize_reach(0.7, 0.1, 0.5, 0.3) == 0.5
