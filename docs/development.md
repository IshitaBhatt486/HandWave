# Development

## Setup

You need Python 3.11. On Windows:

```powershell
scripts\setup.cmd dev     # .venv with requirements-dev.txt
scripts\run.cmd           # start HandWave
scripts\run_tests.cmd -q  # tests + 80% coverage gate
```

Anywhere else, the equivalent is `pip install -r requirements-dev.txt`,
`python -m handwave.main` and `python -m pytest -q`. macOS needs a few extra
steps; see [macos.md](macos.md).

Test results and coverage reports go to `test-results/`. Run one layer at a
time with `-m unit`, `-m integration`, `-m ui` or `-m benchmark` (add
`--no-cov` so the coverage gate doesn't fail a partial run).

## Layout

```text
handwave/
  actions/       action types, executor, cooldown/re-arm gate, action queue
  application/   glue between recognition results and actions
  config/        settings, profiles, templates, gesture names, safe file writes
  diagnostics/   pipeline metrics and startup timing
  gestures/      landmark model, built-in/custom/two-hand recognition, record/replay
  platforms/     Windows/macOS detection and macOS-specific code
  services/      double-clap, auto-pause, foreground app, startup, history
  ui/            dashboard, settings, onboarding, dialogs, theme
  vision/        capture and recognition threads
  main.py        entry point
benchmarks/      latency, startup and HaGRID benchmarks
docs/            user and developer documentation
packaging/       PyInstaller specs, NSIS installer, Windows version info
scripts/         setup, run, test, build and install helpers; licence, replay and screenshot tools
tests/           pytest suite
```

## How it fits together

The Qt main thread owns every widget. Capture, recognition and actions each
run on their own `QThread`: the capture thread keeps only the newest frame,
and actions go through a queue so a slow key press can't stall recognition.
[architecture.md](architecture.md) has the full picture;
[gesture-recognition.md](gesture-recognition.md), [actions.md](actions.md)
and [profiles.md](profiles.md) cover the parts you're most likely to change.

## Things that are easy to break

- **Import order.** `handwave/__init__.py` loads OpenCV before PyQt6 and
  preloads a recent MSVC runtime. Changing that order brings back an
  intermittent native crash on Windows. See `handwave/_runtime.py`.
- **Startup time.** Anything imported at module level from
  `handwave/ui/main_window.py` slows startup. MediaPipe (~0.7 s) is only
  imported once the recognition thread starts, and
  `tests/test_startup_performance.py` checks that. Run
  `python -m benchmarks.benchmark_startup` before and after changing imports.
- **macOS code** goes in `handwave/platforms/macos.py`, with PyObjC imported
  inside functions so Windows never loads it.

## Common changes

**A new setting:** add a typed, validated field to `AppSettings` in
`handwave/config/settings_manager.py`, a control in the right
`SettingsDialog` tab, and tests in `tests/test_settings_manager.py` and
`tests/test_settings_dialog.py`. Unknown keys in `settings.json` are ignored
and missing ones get defaults, so old files keep working.

**A new built-in pose:** add it to `GESTURES` and the default bindings in
`handwave/config/gesture_config.py`, add its finger pattern to
`GestureEngine.GESTURE_PATTERNS`, and add recognition cases to
`tests/test_gesture_recognition.py`. If it looks like an existing pose, add
an orientation check the way thumbs up/down do.

**A new action type:** see [actions.md](actions.md#extending-the-action-abstraction).

## Debugging without a camera

`LandmarkRecorder` in `handwave/gestures/landmark_sequence.py` saves hand
landmarks (never video) to JSON. Replay a recording through the real
recogniser with:

```powershell
python scripts\replay_gesture.py path\to\recording.json --speed 2
```

## Screenshots

`python scripts\capture_docs_screenshots.py --hagrid-dir <HaGRID sample>`
retakes the screenshots from the real app. HaGRID photos (see the
[benchmark report](benchmarks/HAGRID_BENCHMARK_REPORT.md) for the download)
go through the real recogniser, faces are blurred, and the timings shown are
measured. Without `--hagrid-dir` only the screens with no photo are updated.
Look at every image before committing it.
