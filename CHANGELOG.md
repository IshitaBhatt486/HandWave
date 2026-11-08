# Changelog

HandWave follows [Semantic Versioning](https://semver.org/).

## 1.1.0 - 2026-11-08

### Added

- First-run setup (gestures, camera, double-clap, auto-pause, theme). Rerun it from the tray menu.
- Auto-pause while another app uses the camera, during calls, or while chosen programs run.
- Gesture macros: sequences of keys, shortcuts, media/mouse actions, text and waits.
- The camera starts when HandWave opens (can be turned off), and a Reduce motion option.
- Experimental macOS support: native media keys, ⌘/⌥ shortcuts, Spaces and
  Mission Control, AVFoundation camera, start at login. Untested on real Macs;
  see [docs/macos.md](docs/macos.md).
- Optional faster hand model and camera debug overlay (Settings → Camera).
- Release builds on GitHub Actions when a version tag is pushed, with optional
  optional code signing through the SignPath Foundation.
- A PowerShell installer (`scripts/install.ps1`) that downloads a release,
  verifies its checksum and adds a Start Menu shortcut.
- Licence compliance for the builds: every build ships `LICENSE` and a generated
  `THIRD_PARTY_LICENSES.txt`, the installer shows the licence, and the Help
  dialog shows the GPL notice. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### Changed

- New minimal interface with warm-black and ivory themes and subtle animations.
- A held pose now fires in about 0.35 s instead of 1.1 s; two-hand tracking
  costs 23 ms per frame instead of 44 ms.
- Gesture rules tuned on HaGRID: accuracy 58.8% → 81.2%, false triggers 13.3% → 4.9%.
- The portable exe is 164 MB instead of 292 MB.
- Profiles, templates and custom gestures are stored with your settings in
  `%APPDATA%\HandWave\config` (or `~/Library/Application Support/HandWave` on
  macOS), also when running from source. Existing files are copied over once.
- Repository layout: helper scripts live in `scripts/`, build specs in
  `packaging/`, and dependencies in `requirements.txt` / `requirements-dev.txt`.

### Fixed

- Diagnostics showed 0 MB of memory on 64-bit Windows.
- A camera read glitch could stop recognition; it now retries and reopens the camera.
- The camera preview grew with every frame and pushed controls off screen.
- Fingertip indicators were offset when the preview was cropped.
- An intermittent native crash at startup, caused by the order in which Qt and OpenCV loaded.
- The Windows build no longer bundles the developer's local `settings.json`.
- Gesture history and action log rows disappeared after switching to the light theme.
- The per-gesture Cooldown box was too narrow and showed "fault" instead of "Default".

## 1.0.0-rc.1 - 2026-09-06

First release candidate.

- Dark and light dashboard with live confidence, gesture history and diagnostics.
- Rebindable gestures with per-gesture sensitivity and enable switches.
- Separate capture, recognition and action threads with a latest-frame buffer.
- Portable exe and per-user NSIS installer.

Known limitations: Windows only, binaries are not code-signed, and recognition
quality depends on lighting and camera placement.
