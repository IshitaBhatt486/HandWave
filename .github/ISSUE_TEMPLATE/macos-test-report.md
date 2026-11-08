---
name: macOS test report
about: Report how HandWave behaves on a Mac (macOS support is experimental)
title: "[macOS] "
labels: macOS
---

**Mac:** <!-- e.g. MacBook Air M2 / Intel iMac 2019 -->
**macOS version:** <!-- e.g. 15.1 -->
**Python version:** <!-- python3 --version -->
**Run from:** <!-- source (`python -m handwave.main`) or HandWave.app -->

### Checklist
<!-- Tick what works, leave unticked what doesn't, and describe failures below. -->
- [ ] App starts; dashboard and themes look right
- [ ] First-run setup appears and choices are applied
- [ ] Camera permission prompt; preview shows the camera
- [ ] Open Palm toggles play/pause (Music / Spotify / browser video)
- [ ] Thumbs Up/Down change system volume
- [ ] Peace Sign / Pointing skip tracks
- [ ] Swipes switch Spaces; Hand Swipe Up opens Mission Control
- [ ] Macros type text and press ⌘ shortcuts
- [ ] Double-clap toggles recognition
- [ ] A FaceTime/Zoom call pauses HandWave; it resumes afterwards
- [ ] Opening Photo Booth pauses HandWave
- [ ] App profiles switch with the frontmost app
- [ ] Start at login works
- [ ] Menu-bar icon works
- [ ] `bash scripts/build_macos.sh` builds a working HandWave.app

### What went wrong
<!-- Steps, what you expected, what happened. -->

### Test output
```
<!-- QT_QPA_PLATFORM=offscreen python -m pytest -q --no-cov -->
```

### Log
<!-- Relevant lines from ~/.handwave/handwave.log -->
