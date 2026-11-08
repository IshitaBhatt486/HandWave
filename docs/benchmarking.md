# Benchmarking

## Frame buffering and action dispatch

```powershell
python -m benchmarks.benchmark_frame_latency
```

**Methodology**: synthetic producer/consumer workload isolating queue
behavior — it does not invoke MediaPipe or a real camera. Compare relative
results from the same run; absolute numbers vary by machine and load.

- **Frame-buffer comparison**: 120 frames from a producer sleeping 2ms
  between frames; the consumer simulates 10ms of processing per accepted
  frame. FIFO retains and processes every frame; latest-frame holds one frame
  and replaces it when a newer one arrives, discarding the stale one.
- **Action-dispatch comparison**: 40 actions each simulating a 5ms OS call.
  Synchronous executes each call on the recognition path directly; queued
  submits each callback to `ActionQueue`, drained independently by
  `ActionWorker`.

A representative run from this repository's test machine:

| Metric | FIFO | Latest frame | Effect |
|---|---:|---:|---:|
| Frames processed | 120 | 29 | freshness prioritized |
| Frames dropped | 0 | 91 | intentional stale-frame removal |
| Median latency | 495.2 ms | 11.8 ms | ~42x lower |
| P95 latency | 934.3 ms | 13.6 ms | ~69x lower |

| Metric | Synchronous | Queued | Effect |
|---|---:|---:|---:|
| Actions executed | 40 | 40 | no action loss |
| Recognition blocked | 216.0 ms | 0.18 ms | ~1,200x lower |

The queue does not make OS calls faster — it removes their cost from the
recognition critical path while preserving in-order execution.
`tests/test_pipeline_benchmark.py` gates this as a regression check (latest-frame
p95 must stay below 50% of FIFO p95; the action queue must execute every
action while keeping recognition-blocked time below 20% of synchronous).

Run only benchmark-marked tests:

```powershell
pytest -m benchmark --no-cov
```

## Startup

```powershell
python -m benchmarks.benchmark_startup
```

Measures, in a fresh subprocess, the cost of importing up to
`handwave.ui.main_window`, constructing `QApplication` + `SettingsManager` +
`MainWindow`, and calling `window.show()` — and explicitly reports whether
`mediapipe` was imported before the UI became visible (it shouldn't be; see
[development.md](development.md#things-that-are-easy-to-break)). Set
`HANDWAVE_STARTUP_PROFILE=1` when running the real application for a
checkpoint-by-checkpoint timing log.

## Interpretation and limitations

- Results depend on scheduler timing; treat them as directional, not absolute performance certification.
- Neither benchmark exercises MediaPipe or real camera/microphone hardware — recognition-loop FPS and latency on real hardware require manual, on-device measurement (see [troubleshooting.md](troubleshooting.md)).
- Dropped frames under the latest-frame strategy are a deliberate overload response, not a bug.

## Real-image accuracy benchmark (HaGRID)

`benchmarks/benchmark_hagrid.py` runs the real `GestureEngine` over annotated
HaGRID photos and reports per-gesture accuracy, false triggers, natural and
synthetic lighting robustness, and per-frame latency. The dataset is not in
the repository; see
[benchmarks/HAGRID_BENCHMARK_REPORT.md](benchmarks/HAGRID_BENCHMARK_REPORT.md)
for download steps, licence terms, results and analysis, and
[benchmarks/hagrid-results.md](benchmarks/hagrid-results.md) for the
generated tables.
