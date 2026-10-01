# HandWave V2 manual release checklist

Run this checklist on the intended Windows release device using the packaged
application. Record the device model, camera, display scale, and
observed camera/recognition FPS before approving a release.

## Installation and startup

- [ ] Install the NSIS package; confirm Start-menu and desktop shortcuts open HandWave.
- [ ] Enable Windows startup, sign out or restart, and confirm HandWave launches.
- [ ] Confirm the startup preference and local settings survive an upgrade/uninstall-reinstall cycle as intended.
- [ ] Pause/resume the computer; verify recognition can be enabled after resume.
- [ ] Disconnect/reconnect the camera while recognition is active; confirm an error is shown and retry succeeds.

## Camera, gestures, and interaction

- [ ] Test bright, normal, and dim lighting; record tracking quality and recognition FPS.
- [ ] Confirm the camera preview shows: “None of your video data leaves your device — it is processed on-device :)”.
- [ ] Confirm the fingerprint indicator follows one and two index fingertips, smooths jitter, fades after loss, and remains aligned after resizing at 100%, 150%, and 200% DPI.
- [ ] Verify open palm, fist, thumbs up/down, peace, and pointing actions, including cooldown and re-arm.
- [ ] Verify finger swipe up/down and open-hand swipe up/down separately. Verify left/right open-hand swipes change virtual desktops, then return to the original desktop.
- [ ] Verify two-hand open palms, fists, moving-apart, and moving-together gestures where configured.
- [ ] Record several custom static gestures under bright, normal, and dim lighting; test recognition, conflict warning, disable, rename, duplicate, and delete.
- [ ] Verify configured keyboard, hotkey, media, text, mouse-click, and local-program actions against harmless targets.

## Pinch and mouse scope

- [ ] Verify the implemented pinch-volume gesture: establish a thumb/index pinch, then move vertically for controlled volume steps.
- [ ] Do not mark pinch-to-zoom or hand-as-mouse complete: they are not implemented in HandWave V2 at this audit point.

## Profiles, templates, and audio

- [ ] Create, edit, save, duplicate, switch, export, import, and delete templates; verify edits do not change the source template.
- [ ] Confirm separate template mappings for the same gesture take effect after switching templates.
- [ ] Test foreground application profile detection, explicit-profile fallback, and no-match fallback to resolved global/template settings.
- [ ] When microphone support, double-clap activation, and cursor calibration
  are released, add their end-to-end checks to this checklist. They are not
  available for testing yet.

## Packaging

- [ ] Verify `SHA256SUMS.txt` against the portable executable and installer distributed for this exact build.
- [ ] Verify uninstall removes installed files and shortcuts without deleting user settings unless the installer explicitly offers that choice.
- [ ] Verify the final release binaries are built from the audited commit and are signed if distribution policy requires signing.
