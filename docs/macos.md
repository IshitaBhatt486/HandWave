# HandWave on macOS (experimental)

> **⚠ The macOS version is unstable and requires further testing.**
> It was written against Apple's documented APIs and is covered by simulated
> tests, but the maintainers have **not yet verified it on a real Mac**.
> Expect rough edges, and please report what you find; see
> [How to help](#how-to-help). Windows remains the supported platform.

## Status

| Feature | macOS implementation | Status |
|---|---|---|
| Hand tracking and gestures | MediaPipe + OpenCV (AVFoundation camera backend) | Implemented, untested on a Mac |
| Media keys (play/pause, next/previous, volume, mute) | Native system media-key events (`NSEvent` → `CGEventPost`), the same path as the keyboard's media row | Implemented, untested |
| Keyboard shortcuts, typing, mouse | PyAutoGUI (Quartz events); Win/Alt in bindings become ⌘/⌥ | Implemented, untested |
| Default swipe shortcuts | Ctrl+←/→ switch Spaces, ⌘Tab last app, Ctrl+↑ Mission Control | Implemented, untested |
| Launch program | `.app` bundles and app names open via `open -a` | Implemented, untested |
| Double-clap | `sounddevice` (Core Audio) | Implemented, untested |
| Auto-pause: camera in use | `AVCaptureDevice.isInUseByAnotherApplication` | Implemented, untested |
| Auto-pause: during calls | Microphone busy in another app **and** a call app running | Implemented, untested |
| Auto-pause: listed apps | `NSWorkspace` running apps + `ps` | Implemented, untested |
| Application profiles | Frontmost app via `NSWorkspace`; window title via `CGWindowList` | Implemented, untested |
| Start at login | LaunchAgent `~/Library/LaunchAgents/com.handwave.app.plist` | Implemented, untested |
| Settings location | `~/Library/Application Support/HandWave` | Implemented |
| Packaging | `HandWave.app` via `packaging/HandWave-macos.spec` (not signed or notarised) | Untested |

The platform code lives in [`handwave/platforms/macos.py`](../handwave/platforms/macos.py).
Simulated tests are in [`tests/test_macos_support.py`](../tests/test_macos_support.py),
and CI runs the whole test suite on GitHub's macOS runners (`test-macos`
job, allowed to fail while macOS support is experimental).

## Install and run (from source)

Requirements: macOS 11 or newer (Apple silicon or Intel), Python 3.11, a webcam.

```bash
git clone https://github.com/IshitaBhatt486/HandWave.git
cd HandWave
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m handwave.main
```

`requirements.txt` installs the macOS-only PyObjC bridges (Cocoa, Quartz,
AVFoundation) automatically and skips the Windows-only `keyboard` package.

Each release also has an experimental `HandWave-macOS.zip` on the
[releases page](https://github.com/IshitaBhatt486/HandWave/releases). To build
the app yourself, run `bash scripts/build_macos.sh` (it runs the tests, then
creates `dist/HandWave.app`). The app isn't notarised, so the first time,
right-click it and choose **Open**.

## Permissions

macOS asks for these the first time each is needed. If you run from source,
the permission is granted to your **terminal app** (Terminal, iTerm, VS Code),
not to Python. Manage them in **System Settings → Privacy & Security**.

| Permission | Why | Without it |
|---|---|---|
| Camera | Gesture recognition | Nothing to recognise |
| Microphone | Double-clap and call detection | Double-clap off; calls not detected |
| Accessibility | Sending media keys, shortcuts, clicks and typed text | Gestures are recognised but nothing happens |
| Screen Recording (optional) | Reading window titles for application profiles | Profiles match by app name only |

## Known limitations

- **Untested on real hardware.** The behaviour may differ from Windows.
- **Auto-pause cannot name the app** using the camera ("another app is using
  the camera"); macOS only reports *whether* the device is busy.
- **Call detection is a heuristic:** the microphone is busy in another app
  while a call app (Zoom, Teams, FaceTime, Discord, Slack, a browser…) is
  running. Voice dictation in a browser may pause HandWave briefly.
- **Shortcut defaults** assume macOS's standard Mission Control shortcuts.
  If you changed them in System Settings → Keyboard → Shortcuts, rebind the
  swipe gestures.
- The `.app` is not code-signed, so macOS asks for permissions again after
  each rebuild.

## How to help

Testing on a Mac is the most valuable contribution right now.

### 1. Run the test checklist

With HandWave running from source, try each item and note what happens.
Copy the list into a
[macOS test report](https://github.com/IshitaBhatt486/HandWave/issues/new?template=macos-test-report.md):

- [ ] App starts; the dashboard and dark/light themes look right (fonts, spacing)
- [ ] First-run setup appears and its choices are applied
- [ ] Camera permission prompt appears; the preview shows the camera
- [ ] Open Palm toggles play/pause in Music, Spotify **and** a browser video
- [ ] Thumbs Up/Down change the system volume (the volume HUD appears)
- [ ] Peace Sign / Pointing skip tracks
- [ ] Swipe left/right switches Spaces; Hand Swipe Up opens Mission Control
- [ ] A macro (Settings → Gestures & Actions → Macro) types text and presses ⌘ shortcuts
- [ ] Double-clap toggles recognition (Microphone permission prompt appears)
- [ ] Joining a FaceTime/Zoom call pauses HandWave and it resumes afterwards
- [ ] Opening Photo Booth while HandWave runs pauses it ("another app is using the camera")
- [ ] A profile in `profiles.json` for Spotify activates when Spotify is in front (see [profiles.md](profiles.md))
- [ ] The tray menu's start-at-login option launches HandWave after logging out and in
- [ ] Menu-bar (tray) icon works: open, enable/disable, exit
- [ ] `bash scripts/build_macos.sh` builds `HandWave.app`, and it runs

Please include your macOS version, Mac model (Apple silicon or Intel), Python
version, the output of `python -m pytest -q --no-cov`, and the log file
`~/.handwave/handwave.log`.

### 2. Run the tests

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --no-cov
```

On a real Mac this also runs `test_resident_memory_is_measured_on_a_real_mac`,
which is skipped elsewhere. Failures are useful reports even without a fix.

### 3. Send a fix

1. Open or comment on an issue labelled **macOS** so work isn't duplicated.
2. Keep macOS code in `handwave/platforms/macos.py` and choose it at call time
   with `handwave.platforms.is_macos()`, so Windows behaviour is untouched
   and tests can simulate either OS.
3. Import PyObjC (`AppKit`, `Quartz`, `AVFoundation`) **inside functions**,
   never at module level, so Windows never loads it.
4. Add or extend a test in `tests/test_macos_support.py` (fake the PyObjC
   modules the way the existing tests do), and say in the pull request what
   you verified on a real Mac.
5. Update the status table above when a feature is confirmed working.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the general workflow.
