# Performance: latency, reliability and footprint

*Measured on 2026-11-08 on a 12th-gen Intel laptop CPU (Windows 11, Python 3.11,
MediaPipe 0.10.14), using real HaGRID hand images at the app's 640×480 frame
size. Reproduce with the commands at the end.*

## Where the time goes

A gesture's journey from your hand to an action:

| Stage | Before | After | Change |
|---|---|---|---|
| Wait for the next camera frame | ~17 ms avg (+6–7 ms from a fixed 30 fps sleep, with normal camera jitter) | ~17 ms avg | sleep replaced by capture-time pacing |
| Hand tracking + recognition (p50 / p95) | 44.4 / 74.4 ms | **23.2 / 45.3 ms** | −48% / −39% |
| Stability filter (pose → stable gesture, median) | **~1,040 ms** | **~300 ms** | −70% |
| UI preview render (UI thread) | 2.7 ms | 1.7 ms, skipped when not visible | −37% |
| **Pose to action (typical)** | **~1.1 s** | **~0.35 s** | **~3× faster** |

The stability filter was by far the largest delay. The model and drawing
work came next.

## 1. Reducing latency without losing functionality

| Method | What it does | Effect |
|---|---|---|
| **Adaptive two-hand tracking** | MediaPipe re-runs palm detection on *every* frame while fewer than `max_num_hands` hands are tracked. HandWave now tracks one hand and probes for a second ~3×/s on a spare core (MediaPipe releases the GIL); two-hand tracking switches on only while two hands are visible. | 40.8 → 20.0 ms per frame for the model alone |
| **Short-window stability filter** | Replaces "1 s majority + 0.5 s hold" with "≥70% of a 0.4 s window, present ≥0.25 s". Same rule for leaving a gesture, so brief dropouts are ignored. | Onset ~1,040 → ~300 ms, with *fewer* spurious switches (simulated 15–30 fps, 10–25% per-frame error) |
| **Capture-time pacing** | Every frame is processed as soon as it arrives; frames are skipped only if a camera delivers faster than ~40 fps. | Removes 6–7 ms of avoidable wait; still caps 60 fps cameras near 30/s |
| **Debug text off by default** | Finger states/FPS/pinch text was drawn with outlines on every frame. Now opt-in (Settings → Camera); landmarks are still drawn. | ~0.5–1 ms per frame |
| **Single-pass preview render** | Wraps the BGR frame directly (no colour conversion or copy), one scaled draw, cached clip path; coalesces frames so only the newest is drawn. | 2.7 → 1.7 ms; 0 ms when hidden/minimised/on Diagnostics |
| **Throttled diagnostics** | Pipeline metrics went to the UI every frame; now 4×/s. | ~20 label updates/frame → 4/s |
| **Faster hand model (opt-in)** | MediaPipe's lite model. | 23.2 → 10.5 ms per frame, **but** 81.2% → 78.5% accuracy, so it is off by default |

Other standard techniques this pipeline already uses: a capacity-one
latest-frame buffer (no queue build-up), separate capture, recognition and
action threads, MediaPipe's tracking mode (no full detection on held poses),
and action execution off the recognition thread.

## 2. Improving reliability without adding latency

All of these cost zero extra time per frame:

| Change | Result |
|---|---|
| **Thumb test by reach, not joint angle** (thumb tip to middle knuckle ÷ palm length). A thumb folded across the palm is still *straight*, so the angle test called it extended. | Thumb classification 62.5% → 94.8% (balanced, HaGRID landmarks) |
| **Flat-palm rule**: a thumb resting alongside the index (not tucked toward the pinky) counts as part of an open palm. | `stop` palms 86% → 98% on cached landmarks (the thumb fix alone had dropped them to 64%) |
| **V-spread for Peace Sign** (≥10°) | `two_up` false triggers 23% → 0% |
| **Clearly-folded fingers for Pointing** | Keeps `rock` false triggers at ~1% (the thumb fix alone raised them to 20%) |
| **Thumbs up/down tilt up to 60°** | Real thumbs-down poses lean ~33° (median) |
| **Faster *and* stricter stability filter** (above) | Spurious switches 0.02–0.05 per run → 0 |
| **Camera glitch tolerance**: up to 15 failed reads are ridden out, then the device is reopened once before reporting an error. Driver buffer limited to 1 frame. | No more "camera stopped" errors from a single USB hiccup |
| **Working-set memory fixed**: undeclared `ctypes` signatures made the Diagnostics RAM figure always 0 MB on 64-bit Windows. | Real memory readings |
| **Shared C++ runtime**: PyQt6 6.7 ships a 2020 `msvcp140.dll`; whichever loads first serves the process. HandWave now loads the newer system runtime first, so OpenCV/MediaPipe (built with VS 14.40+) don't run against an incompatible one. | Removes a known class of native crashes |

**End-to-end on HaGRID** (2,875 hands, full model):

| | Before | After |
|---|---|---|
| Gesture accuracy | 58.8% | **81.2%** |
| Accuracy when a hand is found | 67.3% | **92.9%** |
| False triggers on other poses | 13.3% | **4.9%** |

Per gesture: Open Palm 89%, Peace Sign 84% (was 6%), Pointing 80% (was 42%),
Thumbs Up 78% (was 55%), Thumbs Down 75% (was 59%), Fist 72%. Details:
[benchmarks/hagrid-results.md](benchmarks/hagrid-results.md).

## 3. Is it lightweight?

| | Before | After |
|---|---|---|
| Recognition-start import (memory) | +71 MB | **+57 MB** |
| Idle UI-thread CPU while recognition is live | 4.5% of a core | **1.8%** (incl. measurement overhead) |
| Two-hand probe while no hand is visible | n/a | idle (only runs while one hand is tracked) |
| Portable `HandWave.exe` | 292 MB | **164 MB (−44%)** |
| Time from launch to "HandWave started" (exe) | 54.0 s | **31.7 s** |

How:

- **matplotlib.pyplot is deferred.** MediaPipe imports it only for a 3-D
  plotting helper HandWave never calls; a placeholder loads it on first real
  use (`handwave/vision/lazy_imports.py`). The base `matplotlib` package is
  still imported: skipping it too exposed an intermittent native crash in the
  test suite that we could not root-cause, and importing it kept 10/10 full
  runs clean.
- **The status dot breathes only while starting or pausing**, not
  continuously: a looping animation repaints ~60 times a second forever.
- **A 2×/s timer that only fed an empty function was removed.**
- **The executable drops unused packages and models**: `jax`, `jaxlib`, `scipy`
  (~300 MB uncompressed, never imported at runtime; verified by listing
  `sys.modules` in a running app) and MediaPipe's face, pose, iris, holistic,
  selfie and objectron models (HandWave runs Hands only).

**Further option, not applied:** the portable build is a single file, which
unpacks over 500 MB to a temp folder on *every* launch, and Windows security then
scans those files. That is most of the remaining 30 s start time. A one-folder
build (installed once) would start in a few seconds, but it changes the
"single portable exe" deliverable that the release tests require, so it is
a product decision.

## 4. What was causing unnecessary latency

1. **The stability filter** (~1 s): a new pose had to outvote a full second of
   older frames, then wait another 0.5 s.
2. **Searching for a second hand on every frame** (~20 ms per frame), for
   two-hand gestures that cannot yet be bound to an action and only show in
   Diagnostics.
3. **A fixed 30 fps sleep** in the recognition loop (6–7 ms average extra
   frame age with a normal camera).
4. **Per-frame debug text**, drawn with outlines on the camera image even
   though the same data is on the Diagnostics page.
5. **Per-frame UI work**: colour conversion and two image copies for the
   preview, preview rendering while hidden, and 20 diagnostics labels
   updated 30 times a second.
6. **Start-up weight**: matplotlib.pyplot (0.2–0.5 s of import time and 14 MB,
   measured) and a bundle carrying ~300 MB of unused libraries.

## Reproduce

```powershell
# Gesture accuracy (needs the HaGRID sample, see docs/benchmarks/HAGRID_BENCHMARK_REPORT.md)
.venv\Scripts\python.exe -m benchmarks.benchmark_hagrid --data-dir <sample>
.venv\Scripts\python.exe -m benchmarks.benchmark_hagrid --data-dir <sample> --model-complexity 0
# Filter behaviour and regression guards
.venv\Scripts\python.exe -m pytest tests/test_gesture_filter.py tests/test_gesture_engine.py tests/test_camera_manager.py --no-cov
```
