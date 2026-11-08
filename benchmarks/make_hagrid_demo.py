"""Render a HandWave demo (GIF + MP4) from HaGRID benchmark results.

Each frame shows a HaGRID image with HandWave's landmarks and its decision:
the recognized gesture, the default media action it would fire, and the
lighting condition. Faces are blurred automatically. Run
``benchmarks.benchmark_hagrid`` first; this reads its ``predictions.csv``.

The output is an adaptation of HaGRID images and therefore carries the
HaGRID licence (attribution + share-alike), not this repository's MIT
licence. See docs/demo/NOTICE.md.
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from benchmarks.benchmark_hagrid import (
    NATURAL_ORDER, NO_GESTURE, NOT_DETECTED, POSITIVE_CLASSES, SYNTHETIC_CONDITIONS, apply_condition,
)
from handwave.actions.action_definition import MEDIA_ACTIONS
from handwave.config.gesture_config import DEFAULT_GESTURE_BINDINGS

WIDTH, HEIGHT, PANEL = 1120, 520, 400
BG, CARD, INK, MUTED, GOOD, BAD, ACCENT = "#0b0f17", "#111827", "#e8edf5", "#8d9bb0", "#10b981", "#fb7185", "#5eead4"
FONT_DIR = Path("C:/Windows/Fonts")
ATTRIBUTION = ("Images: HaGRID (Kapitanov et al.) github.com/hukenovs/hagrid, HaGRID licence (BY-SA variant). "
               "Downscaled, faces blurred, overlays added.")


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    try:
        return ImageFont.truetype(str(FONT_DIR / name), size)
    except OSError:
        return ImageFont.load_default()


def _action_for(gesture: str) -> str:
    binding = DEFAULT_GESTURE_BINDINGS.get(gesture, "none")
    if isinstance(binding, str):
        return MEDIA_ACTIONS.get(binding, "No action")
    return str(binding.get("value"))


class FaceBlur:
    def __init__(self) -> None:
        self._detector = mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.25)

    def apply(self, image: np.ndarray) -> tuple[np.ndarray, int]:
        h, w = image.shape[:2]
        result = self._detector.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        faces = 0
        for detection in result.detections or []:
            box = detection.location_data.relative_bounding_box
            # Generous margin: hair, ears and chin are identifying too.
            x0 = int(max(0, (box.xmin - box.width * 0.45) * w)); x1 = int(min(w, (box.xmin + box.width * 1.45) * w))
            y0 = int(max(0, (box.ymin - box.height * 0.7) * h)); y1 = int(min(h, (box.ymin + box.height * 1.4) * h))
            if x1 - x0 < 4 or y1 - y0 < 4:
                continue
            region = image[y0:y1, x0:x1]
            small = cv2.resize(region, (max(1, (x1 - x0) // 14), max(1, (y1 - y0) // 14)), interpolation=cv2.INTER_LINEAR)
            image[y0:y1, x0:x1] = cv2.GaussianBlur(cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST), (0, 0), 6)
            faces += 1
        return image, faces


class LandmarkDrawer:
    def __init__(self) -> None:
        self._hands = mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=2, min_detection_confidence=0.6)

    def apply(self, image: np.ndarray, bbox) -> np.ndarray:
        result = self._hands.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        x, y, bw, bh = bbox
        for landmarks in result.multi_hand_landmarks or []:
            cx = np.mean([p.x for p in landmarks.landmark]); cy = np.mean([p.y for p in landmarks.landmark])
            if not (x - bw * .25 <= cx <= x + bw * 1.25 and y - bh * .25 <= cy <= y + bh * 1.25):
                continue
            mp.solutions.drawing_utils.draw_landmarks(
                image, landmarks, mp.solutions.hands.HAND_CONNECTIONS,
                mp.solutions.drawing_utils.DrawingSpec(color=(129, 185, 16), thickness=2, circle_radius=2),
                mp.solutions.drawing_utils.DrawingSpec(color=(212, 234, 94), thickness=2),
            )
        return image


def _load_annotations(data_dir: Path) -> tuple[dict, dict]:
    import json

    boxes, paths = {}, {p.stem: p for p in data_dir.rglob("*.jpg")}
    for ann in data_dir.rglob("*.json"):
        data = json.loads(ann.read_text(encoding="utf-8"))
        for image_id, entry in data.items():
            if ann.stem in entry.get("labels", []):
                boxes[(image_id, ann.stem)] = entry["bboxes"][entry["labels"].index(ann.stem)]
    return boxes, paths


def select_examples(rows: list[dict], seed: int) -> list[tuple[str, dict]]:
    """A short narrative: each gesture, each lighting condition, synthetic sweep, honest misses."""
    rng = random.Random(seed)
    originals = [r for r in rows if r["condition"] == "Original"]
    picks: list[tuple[str, dict]] = []
    used: set[str] = set()

    def take(section: str, pool: list[dict]) -> None:
        pool = [r for r in pool if r["image_id"] not in used]
        if pool:
            choice = rng.choice(pool); used.add(choice["image_id"]); picks.append((section, choice))

    for gesture in dict.fromkeys(POSITIVE_CLASSES.values()):
        take("Gestures", [r for r in originals if r["expected"] == gesture and r["predicted"] == gesture
                          and r["lighting"] == "Normal"])
    for bucket in NATURAL_ORDER:
        if bucket != "Normal":
            take("Lighting", [r for r in originals if r["expected"] and r["predicted"] == r["expected"] and r["lighting"] == bucket])
    # Same image under every synthetic condition.
    swept = {r["image_id"] for r in rows if r["condition"] == "Harsh side light"}
    candidates = [r for r in originals if r["image_id"] in swept and r["predicted"] == r["expected"] and r["lighting"] == "Normal"]
    if candidates:
        anchor = rng.choice(candidates)
        for condition in SYNTHETIC_CONDITIONS:
            match = [r for r in rows if r["image_id"] == anchor["image_id"] and r["condition"] == condition]
            if match:
                picks.append(("Synthetic lighting", match[0]))
    take("Ignored poses", [r for r in originals if not r["expected"] and r["predicted"] in (NO_GESTURE, NOT_DETECTED)
                           and r["hands_detected"] != "0"])
    take("Known misses", [r for r in originals if r["expected"] and r["predicted"] not in (r["expected"], NOT_DETECTED)])
    take("Known misses", [r for r in originals if not r["expected"] and r["predicted"] not in (NO_GESTURE, NOT_DETECTED)])
    return picks


def render_frame(image: np.ndarray, section: str, row: dict) -> Image.Image:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(canvas)
    # Photo, letterboxed into the left area.
    area_w, area_h = WIDTH - PANEL - 36, HEIGHT - 70
    h, w = image.shape[:2]
    scale = min(area_w / w, area_h / h)
    photo = Image.fromarray(cv2.cvtColor(cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB))
    canvas.paste(photo, (18 + (area_w - photo.width) // 2, 18 + (area_h - photo.height) // 2))

    x = WIDTH - PANEL
    draw.rounded_rectangle((x, 18, WIDTH - 18, HEIGHT - 52), radius=14, fill=CARD)
    draw.text((x + 22, 34), "HANDWAVE  ·  HaGRID DEMO", font=_font(13, True), fill=ACCENT)
    draw.text((x + 22, 56), section, font=_font(24, True), fill=INK)

    expected = row["expected"]
    predicted = row["predicted"]
    shown = f"{predicted} {row['direction']}".strip() if predicted == "Pointing" else predicted
    if expected:
        ok = predicted == expected
    else:
        ok = predicted in (NO_GESTURE, NOT_DETECTED)
    fields = [
        ("Dataset label", f"{row['hagrid_label']}"),
        ("Expected", expected or "No action (not a HandWave pose)"),
        ("Lighting", row["condition"] if row["condition"] != "Original" else f"{row['lighting']} (natural)"),
        ("HandWave saw", shown),
        ("Action", _action_for(shown) if predicted not in (NO_GESTURE, NOT_DETECTED) else "None"),
    ]
    y = 110
    for label, value in fields:
        draw.text((x + 22, y), label.upper(), font=_font(11, True), fill=MUTED)
        draw.text((x + 22, y + 15), value, font=_font(18, True if label == "HandWave saw" else False), fill=INK)
        y += 52
    verdict = "CORRECT" if ok else "MISS"
    color = GOOD if ok else BAD
    draw.rounded_rectangle((x + 22, y + 6, x + 22 + 120, y + 38), radius=8, fill=color)
    draw.text((x + 34, y + 10), verdict, font=_font(16, True), fill="#06130f")
    draw.text((18, HEIGHT - 36), ATTRIBUTION, font=_font(12), fill=MUTED)
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, default=Path("benchmarks/results/hagrid/predictions.csv"))
    parser.add_argument("--out", type=Path, default=Path("docs/demo"))
    parser.add_argument("--seconds-per-example", type=float, default=2.2)
    parser.add_argument("--seed", type=int, default=3)
    args = parser.parse_args()

    rows = list(csv.DictReader(args.predictions.open(encoding="utf-8")))
    boxes, paths = _load_annotations(args.data_dir)
    examples = select_examples(rows, args.seed)
    blur, drawer = FaceBlur(), LandmarkDrawer()
    rng = np.random.default_rng(0)
    frames: list[Image.Image] = []
    faces_total = 0
    for section, row in examples:
        image = cv2.imread(str(paths[row["image_id"]]))
        bbox = boxes[(row["image_id"], row["hagrid_label"])]
        variant = apply_condition(image, row["condition"], rng)
        variant, faces = blur.apply(variant)
        faces_total += faces
        variant = drawer.apply(variant, bbox)
        frames.append(render_frame(variant, section, row))
        print(f"{section:20s} {row['hagrid_label']:16s} {row['condition']:18s} -> {row['predicted']} (faces blurred: {faces})")

    args.out.mkdir(parents=True, exist_ok=True)
    gif = args.out / "hagrid-demo.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=int(args.seconds_per_example * 1000), loop=0, optimize=True)
    fps = 10
    writer = cv2.VideoWriter(str(args.out / "hagrid-demo.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (WIDTH, HEIGHT))
    for frame in frames:
        bgr = cv2.cvtColor(np.asarray(frame), cv2.COLOR_RGB2BGR)
        for _ in range(int(fps * args.seconds_per_example)):
            writer.write(bgr)
    writer.release()
    print(f"{len(frames)} examples, {faces_total} faces blurred -> {gif}")


if __name__ == "__main__":
    main()
