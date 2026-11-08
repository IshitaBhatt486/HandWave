"""Replay a recorded landmark sequence through the real recognition pipeline.

Usage:
    python scripts/replay_gesture.py path/to/sequence.json
    python scripts/replay_gesture.py path/to/sequence.json --speed 2
    python scripts/replay_gesture.py path/to/sequence.json --step

This exercises no camera and no MediaPipe detection step (there is no frame
to detect from) — it feeds already-recorded, normalized hand landmarks into
``GestureEngine.recognize_hands``, the exact same recognition code the live
camera pipeline calls after MediaPipe extraction.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handwave.gestures.gesture_engine import GestureEngine
from handwave.gestures.landmark_replay import LandmarkReplayer
from handwave.gestures.landmark_sequence import LandmarkSequence


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sequence_path", help="Path to a recorded .json landmark sequence")
    parser.add_argument(
        "--speed", type=float, default=1.0, choices=(0.5, 1.0, 2.0), help="Playback speed multiplier"
    )
    parser.add_argument(
        "--step", action="store_true", help="Advance one frame at a time on Enter instead of real-time playback"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    sequence = LandmarkSequence.load(args.sequence_path)
    print(f"Loaded {len(sequence.frames)} frames. Metadata: {sequence.metadata}")

    engine = GestureEngine(overlay_enabled=False)
    try:
        replayer = LandmarkReplayer(sequence, engine, speed=args.speed)
        for step in replayer.steps():
            if args.step:
                input(f"[frame {step.frame_index}] press Enter to advance...")
            else:
                time.sleep(step.delay_seconds)
            hands = step.result.hands_detected
            print(
                f"frame {step.frame_index:4d}  hands={hands}  "
                f"gesture={step.result.name!r} confidence={step.result.confidence:.2f}  "
                f"two_hand={step.result.two_hand.name!r}"
            )
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
