import numpy as np
import pytest

from benchmarks.benchmark_hagrid import (
    NO_GESTURE, NOT_DETECTED, Prediction, apply_condition, classify_lighting, summarize,
)

BOX = (0.25, 0.25, 0.5, 0.5)


def _image(scene: int, hand: int) -> np.ndarray:
    image = np.full((100, 100, 3), scene, dtype=np.uint8)
    image[25:75, 25:75] = hand
    return image


@pytest.mark.parametrize("scene,hand,expected", [
    (60, 60, "Low light"), (100, 100, "Dim"), (140, 140, "Normal"), (200, 200, "Bright"), (230, 90, "Backlit"),
])
def test_lighting_buckets_use_hand_region_luma(scene, hand, expected):
    assert classify_lighting(_image(scene, hand), BOX)[0] == expected


def test_lighting_conditions_change_photometry_but_not_shape():
    image = _image(140, 140)
    rng = np.random.default_rng(0)
    assert apply_condition(image, "Original", rng) is image
    dark = apply_condition(image, "Low light + noise", rng)
    bright = apply_condition(image, "Overexposed", rng)
    side = apply_condition(image, "Harsh side light", rng)
    assert dark.shape == image.shape and dark.dtype == np.uint8
    assert dark.mean() < image.mean() < bright.mean()
    assert side[:, :10].mean() < side[:, -10:].mean()
    with pytest.raises(ValueError):
        apply_condition(image, "Moonlight", rng)


def _p(label, expected, predicted, condition="Original", lighting="Normal", direction=""):
    return Prediction("id-" + label + predicted + condition, label, expected, condition, lighting, 120.0, 120.0,
                      predicted, direction, 0.9, 0 if predicted == NOT_DETECTED else 1, 20.0)


def test_summary_separates_accuracy_detection_and_false_triggers():
    rows = [
        _p("like", "Thumbs Up", "Thumbs Up"),
        _p("like", "Thumbs Up", NOT_DETECTED),
        _p("one", "Pointing", "Pointing", direction="Up"),
        _p("one", "Pointing", "Fist", lighting="Backlit"),
        _p("rock", "", NO_GESTURE),
        _p("four", "", "Open Palm"),
    ]
    summary = summarize(rows)

    assert summary["per_gesture"]["Thumbs Up"]["accuracy"] == 50.0
    assert summary["per_gesture"]["Thumbs Up"]["detection_rate"] == 50.0
    assert summary["per_gesture"]["Thumbs Up"]["accuracy_when_detected"] == 100.0
    assert summary["pointing_up_direction_rate"] == 100.0
    assert summary["confusion"]["rows"]["Pointing"]["Fist"] == 1
    assert summary["false_triggers"]["four"]["triggered_as"] == {"Open Palm": 1}
    assert summary["overall_false_trigger_rate"] == 50.0
    assert summary["by_natural_lighting"]["Backlit"]["accuracy"] == 0.0
