# Troubleshooting

Start with the log at `%USERPROFILE%\.handwave\handwave.log` (`~/.handwave/handwave.log`
on macOS) and the **Diagnostics** tab. Together they usually show which stage
is failing: camera, hand tracking, gesture recognition or the action itself.

## HandWave doesn't start

- If Windows says the app was blocked (Smart App Control) or shows "Windows
  protected your PC", that's because releases aren't code-signed yet.
  SmartScreen offers **More info → Run anyway**; Smart App Control has no
  override, so run from source until signed builds are out.
- From source, run `scripts\setup.cmd` again, then `scripts\run.cmd` from a
  terminal so you can see any error.
- Set `HANDWAVE_STARTUP_PROFILE=1` before launching to log how long each
  startup step takes.
- If Smart App Control blocks a DLL when running from source, reinstall the
  pinned versions with `scripts\setup.cmd`.

## The camera doesn't turn on

- Allow camera access for desktop apps in **Windows Settings → Privacy &
  security → Camera**.
- Close other apps that might be holding the camera (video calls, OBS, browser tabs).
- If you have more than one camera, pick the right one in **Settings → Camera**.
- Check that the camera works in the Windows Camera app.

If auto-pause is on, HandWave also releases the camera on purpose while
another app uses it; the dashboard says why it paused.

## My hand isn't detected, or the wrong gesture shows up

- Keep your whole hand and wrist in the frame, roughly in the middle.
- Light your hand from the front. A bright window behind you is the most common problem.
- Hold static poses still for about half a second.
- For thumbs up/down, point the thumb clearly up or down with the other fingers folded.
- Lower the sensitivity in **Settings → General** if detection drops
  out, raise it if you get false triggers.
- Fist and thumbs down are the least reliable poses. If one keeps
  misfiring, disable it or record a custom gesture instead.

Two-hand gestures need both hands visible and making the *same* pose.

## The gesture shows up but nothing happens

The action log on the dashboard says why an action was skipped. The usual reasons:

- The gesture is disabled or bound to *No action*.
- It's in cooldown, or you haven't changed pose since it last fired. Held poses fire once.
- An app profile is active and has its own binding (the dashboard shows the active profile).
- The target app ignores the key. Try the same shortcut on the keyboard.

## Swipes or pinch don't work

- **Swipe:** move your whole hand across the frame in one quick, mostly
  horizontal motion (about 0.1–0.7 s). Slow drifts are ignored.
- **Pinch:** touch thumb and index tips first, then move up or down while
  keeping the same distance from the camera.

## Double-clap doesn't work

- Allow microphone access for desktop apps in Windows privacy settings.
- Clap twice, between 0.12 and 1 second apart.
- Open **Microphone** on the dashboard and run **Recalibrate** in a quiet room.
- If it triggers by mistake, raise *Clap minimum peak* in **Settings → Microphone**.
- If the wrong input is used, set the device index in **Settings → Microphone**.

## App profiles don't switch

- Turn on **Automatically switch application profiles** in **Settings → General**.
- The profile's program name has to match the process name, e.g. `spotify.exe`,
  not the window title.
- Apps running as administrator can't be detected from a normal HandWave; the
  global settings are used instead.

## It feels slow

Compare Camera FPS and Recognition FPS on the Diagnostics tab.

- **Low camera FPS:** usually lighting (cameras slow down in the dark), USB or the driver.
- **Recognition FPS lower than camera FPS:** the CPU can't keep up. Dropped
  frames are expected here and stop lag from building up. Try **Faster hand
  model** in **Settings → Camera** and close heavy apps.

## Settings don't save

Settings, profiles and custom gestures are in `%APPDATA%\HandWave\config\`.
Make sure that folder is writable. If a file is corrupted, HandWave falls back
to its `.bak` copy, then to defaults. Edit these files only while HandWave is closed.

## Start at login doesn't work

Toggle **Launch at Windows Startup** off and on in the tray menu, then check
that `HandWave.cmd` exists in
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`. Some security
software blocks scripts in that folder.

## Build problems

See [releasing.md](releasing.md). PyInstaller's optional-module warnings are in
`build\HandWave\warn-HandWave.txt`.

## Reporting a bug

Use the [bug report template](https://github.com/IshitaBhatt486/HandWave/issues/new?template=bug_report.md)
and include the HandWave version, Windows version, camera model, the relevant
part of the log, and a Diagnostics screenshot if it's a performance problem.
