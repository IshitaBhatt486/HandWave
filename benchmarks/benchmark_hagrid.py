"""Benchmark HandWave's static gesture recognition on HaGRID images.

Runs the app's real ``GestureEngine`` (MediaPipe Hands + HandWave's built-in
pose rules) over annotated HaGRID images and reports per-gesture accuracy,
false-trigger rates on non-HandWave poses, latency, and robustness across
natural and synthetic lighting conditions.

Dataset: HaGRID (Kapitanov et al.), https://github.com/hukenovs/hagrid,
distributed under its own attribution/share-alike licence
(https://github.com/hukenovs/hagrid/blob/master/license/en_us.pdf).
The images are NOT stored in this repository; download them first (see
docs/benchmarks/HAGRID_BENCHMARK_REPORT.md) and pass ``--data-dir``.

Usage::

    python -m benchmarks.benchmark_hagrid --data-dir %LOCALAPPDATA%\\HandWave\\datasets\\hagrid-sample-30k-384p
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from handwave.config.settings_manager import AppSettings
from handwave.gestures.gesture_engine import GestureEngine

# HaGRID label -> the HandWave gesture it should trigger.
POSITIVE_CLASSES = {
    "palm": "Open Palm",
    "stop": "Open Palm",
    "fist": "Fist",
    "like": "Thumbs Up",
    "dislike": "Thumbs Down",
    "peace": "Peace Sign",
    "one": "Pointing",
}
# HaGRID poses HandWave has no gesture for: any recognized gesture here would
# fire an unintended action ("false trigger").
NEGATIVE_CLASSES = ("call", "four", "mute", "ok", "rock", "three", "three2", "two_up", "two_up_inverted")

NOT_DETECTED = "Not detected"
NO_GESTURE = "No gesture"

# Natural-lighting buckets from the luma (BT.601 Y, 0-255) of the gesture's
# bounding box. "Backlit" = scene notably brighter than the hand.
BACKLIT_DELTA = 35.0
LUMA_BUCKETS = ((80.0, "Low light"), (120.0, "Dim"), (170.0, "Normal"), (256.0, "Bright"))
NATURAL_ORDER = ("Low light", "Dim", "Normal", "Bright", "Backlit")

SYNTHETIC_CONDITIONS = ("Original", "Low light + noise", "Overexposed", "Warm tungsten", "Harsh side light")


@dataclass
class Sample:
    image_id: str
    hagrid_label: str
    expected: str  # HandWave gesture, or "" for negative classes
    path: Path
    bbox: tuple[float, float, float, float]  # normalized x, y, w, h


@dataclass
class Prediction:
    image_id: str
    hagrid_label: str
    expected: str
    condition: str
    lighting: str
    hand_luma: float
    scene_luma: float
    predicted: str
    direction: str
    confidence: float
    hands_detected: int
    latency_ms: float


# --------------------------------------------------------------------------- data

def _find_annotations(data_dir: Path) -> dict[str, Path]:
    found = {}
    for path in data_dir.rglob("*.json"):
        if path.stem in POSITIVE_CLASSES or path.stem in NEGATIVE_CLASSES:
            found[path.stem] = path
    return found


def _index_images(data_dir: Path) -> dict[str, Path]:
    return {path.stem: path for path in data_dir.rglob("*.jpg")}


def load_samples(data_dir: Path, per_class: int, seed: int) -> list[Sample]:
    annotations = _find_annotations(data_dir)
    if not annotations:
        raise SystemExit(f"No HaGRID annotation JSON files found under {data_dir}")
    images = _index_images(data_dir)
    rng = random.Random(seed)
    samples: list[Sample] = []
    for label in (*POSITIVE_CLASSES, *NEGATIVE_CLASSES):
        if label not in annotations:
            print(f"warning: no annotations for {label!r}; skipping")
            continue
        data = json.loads(annotations[label].read_text(encoding="utf-8"))
        ids = sorted(image_id for image_id in data if image_id in images)
        rng.shuffle(ids)
        count = per_class if label in POSITIVE_CLASSES else max(1, per_class // 2)
        for image_id in ids[:count]:
            entry = data[image_id]
            # The first box carrying this file's label is the gesture hand;
            # other boxes are typically the second hand in "no_gesture".
            try:
                box_index = entry["labels"].index(label)
            except ValueError:
                continue
            samples.append(Sample(
                image_id, label, POSITIVE_CLASSES.get(label, ""), images[image_id],
                tuple(float(v) for v in entry["bboxes"][box_index]),
            ))
    return samples


# ----------------------------------------------------------------------- lighting

def _bbox_pixels(bbox, shape) -> tuple[int, int, int, int]:
    h, w = shape[:2]
    x, y, bw, bh = bbox
    x0, y0 = max(0, int(x * w)), max(0, int(y * h))
    x1, y1 = min(w, int((x + bw) * w)), min(h, int((y + bh) * h))
    return x0, y0, max(x0 + 1, x1), max(y0 + 1, y1)


def luma(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)[:, :, 0]


def classify_lighting(image: np.ndarray, bbox) -> tuple[str, float, float]:
    y = luma(image)
    x0, y0, x1, y1 = _bbox_pixels(bbox, image.shape)
    hand = float(y[y0:y1, x0:x1].mean())
    scene = float(y.mean())
    if scene - hand >= BACKLIT_DELTA:
        return "Backlit", hand, scene
    for upper, name in LUMA_BUCKETS:
        if hand < upper:
            return name, hand, scene
    return "Bright", hand, scene


def apply_condition(image: np.ndarray, condition: str, rng: np.random.Generator) -> np.ndarray:
    """Deterministic photometric stress tests that keep the pose unchanged."""
    img = image.astype(np.float32)
    if condition == "Original":
        return image
    if condition == "Low light + noise":
        # ~2 stops underexposed with gamma and sensor noise, as a dim webcam.
        img = 255.0 * (img / 255.0) ** 1.6 * 0.35 + rng.normal(0, 4.0, img.shape)
    elif condition == "Overexposed":
        img = img * 1.7 + 35.0
    elif condition == "Warm tungsten":
        img = img * np.array([0.55, 0.85, 1.12], dtype=np.float32) * 0.85  # BGR
    elif condition == "Harsh side light":
        ramp = np.linspace(0.25, 1.35, img.shape[1], dtype=np.float32)
        img = img * ramp[None, :, None]
    else:
        raise ValueError(condition)
    return np.clip(img, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------- inference

class Recognizer:
    """HandWave's GestureEngine with MediaPipe in still-image mode.

    The live app runs MediaPipe in video (tracking) mode. Independent
    photographs have no temporal continuity, so tracking state would leak
    between unrelated images; still-image mode is equivalent to the first
    frame of a live session. All pose rules are the app's own code.
    """

    def __init__(self, sensitivity: float, model_complexity: int = 1) -> None:
        # Unrelated still images: no tracking, no two-hand probe.
        self.engine = GestureEngine(sensitivity=sensitivity, overlay_enabled=False, two_hand_probe=False)
        self.engine._hands.close()
        self.engine._hands = mp.solutions.hands.Hands(
            static_image_mode=True, max_num_hands=2, model_complexity=model_complexity,
            min_detection_confidence=sensitivity, min_tracking_confidence=sensitivity,
        )

    def predict(self, image: np.ndarray, bbox) -> tuple[str, str, float, int, float]:
        started = time.perf_counter()
        _, result = self.engine.process(image.copy())
        latency_ms = (time.perf_counter() - started) * 1000.0
        if not result.hands:
            return NOT_DETECTED, "", 0.0, 0, latency_ms
        # Pick the detected hand that belongs to the annotated gesture box.
        x, y, w, h = bbox
        pad_x, pad_y = w * 0.25, h * 0.25

        def score(hand) -> float:
            cx, cy = hand.centroid
            inside = (x - pad_x) <= cx <= (x + w + pad_x) and (y - pad_y) <= cy <= (y + h + pad_y)
            return (0.0 if inside else 10.0) + abs(cx - (x + w / 2)) + abs(cy - (y + h / 2))

        hand = min(result.hands, key=score)
        if score(hand) >= 10.0:
            return NOT_DETECTED, "", 0.0, len(result.hands), latency_ms
        detection = self.engine.detect_gesture(hand.landmarks)
        name = detection.name if detection.name and detection.name != "Unknown" else NO_GESTURE
        direction = ""
        if name.startswith("Pointing"):
            direction = name.removeprefix("Pointing").strip()
            name = "Pointing"
        return name, direction, float(detection.confidence or 0.0), len(result.hands), latency_ms

    def close(self) -> None:
        self.engine.close()


# ------------------------------------------------------------------------ metrics

def _pct(numerator: int, denominator: int) -> float:
    return 100.0 * numerator / denominator if denominator else float("nan")


def summarize(predictions: list[Prediction]) -> dict:
    natural = [p for p in predictions if p.condition == "Original"]
    positives = [p for p in natural if p.expected]
    negatives = [p for p in natural if not p.expected]

    def accuracy_block(rows: list[Prediction]) -> dict:
        detected = [r for r in rows if r.predicted != NOT_DETECTED]
        correct = sum(r.predicted == r.expected for r in rows)
        return {
            "n": len(rows),
            "detection_rate": _pct(len(detected), len(rows)),
            "accuracy": _pct(correct, len(rows)),
            "accuracy_when_detected": _pct(sum(r.predicted == r.expected for r in detected), len(detected)),
        }

    per_gesture = {}
    for gesture in dict.fromkeys(POSITIVE_CLASSES.values()):
        per_gesture[gesture] = accuracy_block([p for p in positives if p.expected == gesture])
    per_hagrid = {label: accuracy_block([p for p in positives if p.hagrid_label == label]) for label in POSITIVE_CLASSES}

    pointing = [p for p in positives if p.hagrid_label == "one" and p.predicted == "Pointing"]
    pointing_up = _pct(sum(p.direction == "Up" for p in pointing), len(pointing))

    labels = list(dict.fromkeys(POSITIVE_CLASSES.values())) + [NO_GESTURE, NOT_DETECTED]
    confusion = {g: Counter() for g in dict.fromkeys(POSITIVE_CLASSES.values())}
    for p in positives:
        confusion[p.expected][p.predicted] += 1

    false_triggers = {}
    for label in NEGATIVE_CLASSES:
        rows = [p for p in negatives if p.hagrid_label == label]
        if not rows:
            continue
        triggered = [r for r in rows if r.predicted not in (NOT_DETECTED, NO_GESTURE)]
        false_triggers[label] = {
            "n": len(rows),
            "false_trigger_rate": _pct(len(triggered), len(rows)),
            "triggered_as": dict(Counter(r.predicted for r in triggered).most_common()),
        }
    all_triggered = sum(1 for p in negatives if p.predicted not in (NOT_DETECTED, NO_GESTURE))

    by_lighting = {}
    for bucket in NATURAL_ORDER:
        rows = [p for p in positives if p.lighting == bucket]
        if rows:
            block = accuracy_block(rows)
            block["median_hand_luma"] = statistics.median(r.hand_luma for r in rows)
            by_lighting[bucket] = block

    synthetic = {}
    paired_ids = {p.image_id for p in predictions if p.condition != "Original"}
    for condition in SYNTHETIC_CONDITIONS:
        rows = [p for p in predictions if p.condition == condition and p.expected and p.image_id in paired_ids]
        if rows:
            block = accuracy_block(rows)
            block["per_gesture"] = {
                g: accuracy_block([r for r in rows if r.expected == g])["accuracy"]
                for g in dict.fromkeys(POSITIVE_CLASSES.values())
            }
            synthetic[condition] = block

    latencies = [p.latency_ms for p in natural]
    return {
        "overall": accuracy_block(positives),
        "per_gesture": per_gesture,
        "per_hagrid_class": per_hagrid,
        "pointing_up_direction_rate": pointing_up,
        "confusion": {"labels": labels, "rows": {g: {l: confusion[g][l] for l in labels} for g in confusion}},
        "false_triggers": false_triggers,
        "overall_false_trigger_rate": _pct(all_triggered, len(negatives)),
        "negatives_n": len(negatives),
        "by_natural_lighting": by_lighting,
        "synthetic_lighting": synthetic,
        "latency_ms": {
            "n": len(latencies),
            "mean": statistics.fmean(latencies),
            "p50": float(np.percentile(latencies, 50)),
            "p95": float(np.percentile(latencies, 95)),
            "max": max(latencies),
        },
    }


# ------------------------------------------------------------------------- charts

BLUE, ORANGE = "#2a78d6", "#eb6834"
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def _axes(title: str, width: float = 7.2, height: float = 3.6):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(width, height), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", color=INK, fontsize=11, fontweight="bold", pad=24)
    return fig, ax


def _bars(ax, labels, values, color, offset=0.0, width=0.6, annotate=True):
    xs = np.arange(len(labels)) + offset
    bars = ax.bar(xs, values, width=width, color=color, edgecolor=SURFACE, linewidth=1.5)
    if annotate:
        for x, v in zip(xs, values):
            if not np.isnan(v):
                ax.text(x, v + 1.5, f"{v:.0f}%", ha="center", va="bottom", fontsize=7.5, color=INK)
    return bars


def render_charts(summary: dict, out_dir: Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    files = []

    gestures = list(summary["per_gesture"])
    fig, ax = _axes("Recognition accuracy per gesture (natural HaGRID images)")
    width = 0.38
    _bars(ax, gestures, [summary["per_gesture"][g]["detection_rate"] for g in gestures], BLUE, -width / 2, width)
    _bars(ax, gestures, [summary["per_gesture"][g]["accuracy"] for g in gestures], ORANGE, width / 2, width)
    ax.set_xticks(range(len(gestures)), gestures)
    ax.set_ylim(0, 112)
    ax.set_ylabel("% of images", color=MUTED, fontsize=8)
    ax.legend(["Hand detected", "Correct gesture"], frameon=False, fontsize=8, loc="lower left", ncols=2,
              labelcolor=INK, bbox_to_anchor=(-0.01, 1.0), handlelength=1.2)
    fig.tight_layout()
    files.append("accuracy_per_gesture.png"); fig.savefig(out_dir / files[-1], facecolor=SURFACE); plt.close(fig)

    lighting = list(summary["by_natural_lighting"])
    fig, ax = _axes("Accuracy by natural lighting condition")
    _bars(ax, lighting, [summary["by_natural_lighting"][b]["accuracy"] for b in lighting], BLUE)
    ax.set_xticks(range(len(lighting)), [f"{b}\n(n={summary['by_natural_lighting'][b]['n']})" for b in lighting])
    ax.set_ylim(0, 112)
    ax.set_ylabel("% correct", color=MUTED, fontsize=8)
    fig.tight_layout()
    files.append("accuracy_natural_lighting.png"); fig.savefig(out_dir / files[-1], facecolor=SURFACE); plt.close(fig)

    conditions = list(summary["synthetic_lighting"])
    fig, ax = _axes("Accuracy under synthetic lighting (same images)")
    _bars(ax, conditions, [summary["synthetic_lighting"][c]["detection_rate"] for c in conditions], BLUE, -width / 2, width)
    _bars(ax, conditions, [summary["synthetic_lighting"][c]["accuracy"] for c in conditions], ORANGE, width / 2, width)
    ax.set_xticks(range(len(conditions)), [c.replace(" + ", "\n+ ").replace(" side", "\nside") for c in conditions])
    ax.set_ylim(0, 112)
    ax.set_ylabel("% of images", color=MUTED, fontsize=8)
    ax.legend(["Hand detected", "Correct gesture"], frameon=False, fontsize=8, loc="lower left", ncols=2,
              labelcolor=INK, bbox_to_anchor=(-0.01, 1.0), handlelength=1.2)
    fig.tight_layout()
    files.append("accuracy_synthetic_lighting.png"); fig.savefig(out_dir / files[-1], facecolor=SURFACE); plt.close(fig)

    labels = [l for l in summary["false_triggers"]]
    fig, ax = _axes("False triggers on poses HandWave does not use")
    _bars(ax, labels, [summary["false_triggers"][l]["false_trigger_rate"] for l in labels], BLUE)
    ax.set_xticks(range(len(labels)), labels, rotation=20)
    ax.set_ylim(0, 112)
    ax.set_ylabel("% of images that fired a gesture", color=MUTED, fontsize=8)
    fig.tight_layout()
    files.append("false_triggers.png"); fig.savefig(out_dir / files[-1], facecolor=SURFACE); plt.close(fig)
    return files


# ------------------------------------------------------------------------- report

def write_results_markdown(summary: dict, meta: dict, charts: list[str], path: Path, chart_rel: str) -> None:
    def f(v: float) -> str:
        return "—" if v != v else f"{v:.1f}%"

    o, lat = summary["overall"], summary["latency_ms"]
    lines = [
        "# HaGRID benchmark — generated results",
        "",
        "> Generated by `python -m benchmarks.benchmark_hagrid`. Do not edit by hand;",
        "> see [HAGRID_BENCHMARK_REPORT.md](HAGRID_BENCHMARK_REPORT.md) for the analysis.",
        "",
        f"- Dataset: {meta['dataset']} ({meta['images_evaluated']} annotated hands, seed {meta['seed']})",
        f"- Engine: HandWave `GestureEngine`, MediaPipe Hands still-image mode, sensitivity {meta['sensitivity']}",
        f"- Machine: {meta['machine']}",
        f"- Run: {meta['timestamp']}",
        "",
        "## Headline",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Gesture accuracy (all 6 HandWave poses) | {f(o['accuracy'])} of {o['n']} |",
        f"| Hand detection rate | {f(o['detection_rate'])} |",
        f"| Accuracy when a hand was detected | {f(o['accuracy_when_detected'])} |",
        f"| False-trigger rate on other poses | {f(summary['overall_false_trigger_rate'])} of {summary['negatives_n']} |",
        f"| Latency per frame (p50 / p95) | {lat['p50']:.1f} ms / {lat['p95']:.1f} ms |",
        f"| \"one\" classified as Pointing **Up** | {f(summary['pointing_up_direction_rate'])} |",
        "",
        "## Per gesture",
        "",
        "| HandWave gesture | Images | Hand detected | Correct | Correct when detected |",
        "|---|---|---|---|---|",
    ]
    for g, b in summary["per_gesture"].items():
        lines.append(f"| {g} | {b['n']} | {f(b['detection_rate'])} | {f(b['accuracy'])} | {f(b['accuracy_when_detected'])} |")
    lines += ["", "| HaGRID class | Expected | Images | Correct |", "|---|---|---|---|"]
    for label, b in summary["per_hagrid_class"].items():
        lines.append(f"| `{label}` | {POSITIVE_CLASSES[label]} | {b['n']} | {f(b['accuracy'])} |")

    labels = summary["confusion"]["labels"]
    lines += ["", "## Confusion matrix (rows = expected, columns = predicted)", "",
              "| Expected \\ Predicted | " + " | ".join(labels) + " |",
              "|---|" + "---|" * len(labels)]
    for g, row in summary["confusion"]["rows"].items():
        lines.append(f"| {g} | " + " | ".join(str(row[l]) for l in labels) + " |")

    lines += ["", "## Natural lighting", "",
              f"Bucketed by the mean luma (0–255) of the gesture's bounding box; *Backlit* = scene ≥ {BACKLIT_DELTA:.0f} luma brighter than the hand.",
              "", "| Condition | Images | Median hand luma | Hand detected | Correct |", "|---|---|---|---|---|"]
    for bucket, b in summary["by_natural_lighting"].items():
        lines.append(f"| {bucket} | {b['n']} | {b['median_hand_luma']:.0f} | {f(b['detection_rate'])} | {f(b['accuracy'])} |")

    lines += ["", "## Synthetic lighting (paired: identical images, photometric change only)", "",
              "| Condition | Images | Hand detected | Correct | " + " | ".join(summary["per_gesture"]) + " |",
              "|---|---|---|---|" + "---|" * len(summary["per_gesture"])]
    for condition, b in summary["synthetic_lighting"].items():
        lines.append(f"| {condition} | {b['n']} | {f(b['detection_rate'])} | {f(b['accuracy'])} | "
                     + " | ".join(f(v) for v in b["per_gesture"].values()) + " |")

    lines += ["", "## False triggers (poses HandWave should ignore)", "",
              "| HaGRID class | Images | Fired a gesture | Fired as |", "|---|---|---|---|"]
    for label, b in summary["false_triggers"].items():
        fired = ", ".join(f"{k} ×{v}" for k, v in b["triggered_as"].items()) or "—"
        lines.append(f"| `{label}` | {b['n']} | {f(b['false_trigger_rate'])} | {fired} |")

    lines += ["", "## Latency", "",
              f"`GestureEngine.process` on {lat['n']} images at the dataset's 384p resolution: "
              f"mean {lat['mean']:.1f} ms, p50 {lat['p50']:.1f} ms, p95 {lat['p95']:.1f} ms, max {lat['max']:.1f} ms.",
              "", "## Charts", ""]
    lines += [f"![{c}]({chart_rel}/{c})" for c in charts]
    lines += ["", "<sub>Source: charts generated by `benchmarks/benchmark_hagrid.py` from HandWave's results on HaGRID. They contain no HaGRID images.</sub>"]
    lines += ["", "---", "", "Images: [HaGRID](https://github.com/hukenovs/hagrid) by A. Kapitanov, A. Makhlyarchuk, "
              "K. Kvanchiani et al., used under the [HaGRID licence](https://github.com/hukenovs/hagrid/blob/master/license/en_us.pdf); "
              "sample via [cj-mills/hagrid-sample-30k-384p](https://huggingface.co/datasets/cj-mills/hagrid-sample-30k-384p) (downscaled). "
              "No dataset images are included in this report.", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_report(summary: dict, meta: dict, out: Path, report: Path) -> None:
    import os

    charts = render_charts(summary, out)
    rel = os.path.relpath(out, report.parent).replace("\\", "/")
    write_results_markdown(summary, meta, charts, report, rel)


# --------------------------------------------------------------------------- main

def run(args: argparse.Namespace) -> dict:
    import platform

    samples = load_samples(args.data_dir, args.per_class, args.seed)
    print(f"Loaded {len(samples)} annotated hands")
    recognizer = Recognizer(args.sensitivity, args.model_complexity)
    rng = np.random.default_rng(args.seed)
    predictions: list[Prediction] = []
    synthetic_budget: Counter = Counter()
    started = time.perf_counter()
    try:
        for index, sample in enumerate(samples, 1):
            image = cv2.imread(str(sample.path))
            if image is None:
                continue
            lighting, hand_luma, scene_luma = classify_lighting(image, sample.bbox)
            conditions = ["Original"]
            if sample.expected and synthetic_budget[sample.hagrid_label] < args.synthetic_per_class:
                synthetic_budget[sample.hagrid_label] += 1
                conditions = list(SYNTHETIC_CONDITIONS)
            for condition in conditions:
                variant = apply_condition(image, condition, rng)
                predicted, direction, confidence, hands, latency = recognizer.predict(variant, sample.bbox)
                predictions.append(Prediction(
                    sample.image_id, sample.hagrid_label, sample.expected, condition,
                    lighting, hand_luma, scene_luma, predicted, direction, confidence, hands, latency,
                ))
            if index % 200 == 0:
                print(f"  {index}/{len(samples)} images ({time.perf_counter() - started:.0f}s)")
    finally:
        recognizer.close()

    summary = summarize(predictions)
    meta = {
        "dataset": "HaGRID sample 30k (384p)",
        "images_evaluated": len(samples),
        "per_class": args.per_class,
        "synthetic_per_class": args.synthetic_per_class,
        "seed": args.seed,
        "sensitivity": args.sensitivity,
        "model_complexity": args.model_complexity,
        "machine": f"{platform.processor() or platform.machine()}, {platform.system()} {platform.release()}, Python {platform.python_version()}, MediaPipe {mp.__version__}",
        "timestamp": time.strftime("%Y-%m-%d %H:%M"),
        "wall_time_s": round(time.perf_counter() - started, 1),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(predictions[0])))
        writer.writeheader()
        writer.writerows(asdict(p) for p in predictions)
    (args.out / "summary.json").write_text(json.dumps({"meta": meta, **summary}, indent=2), encoding="utf-8")
    _write_report(summary, meta, args.out, args.report)
    print(json.dumps({"overall": summary["overall"], "false_trigger_rate": summary["overall_false_trigger_rate"],
                      "latency_ms": summary["latency_ms"]}, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, help="Extracted HaGRID sample directory")
    parser.add_argument("--report-only", action="store_true", help="Rebuild charts and report from an existing summary.json")
    parser.add_argument("--per-class", type=int, default=250, help="Images per HandWave-gesture class (negatives use half)")
    parser.add_argument("--synthetic-per-class", type=int, default=80, help="Images per class also run under synthetic lighting")
    parser.add_argument("--sensitivity", type=float, default=AppSettings().gesture_sensitivity)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--model-complexity", type=int, choices=(0, 1), default=1, help="MediaPipe hand model: 1 full (default), 0 lite")
    parser.add_argument("--out", type=Path, default=Path("benchmarks/results/hagrid"))
    parser.add_argument("--report", type=Path, default=Path("docs/benchmarks/hagrid-results.md"))
    args = parser.parse_args()
    if args.report_only:
        saved = json.loads((args.out / "summary.json").read_text(encoding="utf-8"))
        meta = saved.pop("meta")
        _write_report(saved, meta, args.out, args.report)
        return
    if args.data_dir is None:
        parser.error("--data-dir is required unless --report-only is given")
    run(args)


if __name__ == "__main__":
    main()
