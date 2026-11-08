# Third-party notices

HandWave's source code is under the [MIT License](LICENSE). The downloadable
builds (`HandWave.exe`, `HandWave.app`) also contain other open-source
software, and some of it is under licences with conditions of their own.

## What that means for the builds

- **PyQt6, MouseInfo and PyMsgBox are GPL v3.** A program that bundles them is
  covered by the GPL v3 as a whole, so the builds are distributed under the
  GPL v3. MIT code can be combined this way. In practice: the builds come
  with no warranty, anyone who gets a build can get the full source (this
  repository at the release tag), and anyone redistributing a build has to do
  the same. The source code itself stays MIT.
- **Qt (LGPL v3) and FFmpeg inside OpenCV (LGPL v2.1)** can be swapped for
  your own builds by running HandWave from source.
- **MediaPipe, OpenCV, absl-py and flatbuffers (Apache 2.0)** require their
  licence and NOTICE texts to travel with the program.

Every build includes `LICENSE` and `THIRD_PARTY_LICENSES.txt`, which lists
each bundled package with its version and full licence text. The file is
generated from the installed packages at build time by
[scripts/collect_licenses.py](scripts/collect_licenses.py), and it's attached
to every [GitHub release](https://github.com/IshitaBhatt486/HandWave/releases).
The installer also puts both files in the install folder, and the app's
Help dialog shows the licence notice.

## Main components

| Component | Licence | Used for |
|---|---|---|
| [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) | GPL v3 | User interface |
| [Qt 6](https://www.qt.io/) (PyQt6-Qt6) | LGPL v3 | User interface |
| [MediaPipe](https://github.com/google/mediapipe) | Apache 2.0 | Hand tracking and its models |
| [OpenCV](https://github.com/opencv/opencv-python) | Apache 2.0 (bundled FFmpeg: LGPL v2.1) | Camera capture and image processing |
| [NumPy](https://numpy.org) | BSD 3-Clause and others | Numerics |
| [PyAutoGUI](https://github.com/asweigart/pyautogui) | BSD 3-Clause | Keyboard and mouse input |
| [MouseInfo](https://github.com/asweigart/mouseinfo), [PyMsgBox](https://github.com/asweigart/pymsgbox) | GPL v3 | PyAutoGUI dependencies |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) (PortAudio) | MIT | Double-clap microphone input |
| [keyboard](https://github.com/boppreh/keyboard) | MIT | Media keys on Windows |
| [Matplotlib](https://matplotlib.org) | PSF-based | Imported by MediaPipe |
| [Python](https://www.python.org) | PSF License | Runtime |

Python and the Microsoft Visual C++ runtime DLLs are included under their
own redistribution terms.

## Demo media

The HaGRID images in `docs/demo/` are not MIT-licensed; see
[docs/demo/NOTICE.md](docs/demo/NOTICE.md).
