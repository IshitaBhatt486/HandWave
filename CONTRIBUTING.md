# Contributing

Thanks for helping out. For anything bigger than a small fix, please open an
issue first so we can agree on the approach before you spend time on it.

## Getting set up

```powershell
git clone https://github.com/IshitaBhatt486/HandWave.git
cd HandWave
scripts\setup.cmd dev
scripts\run_tests.cmd -q
```

On macOS or Linux, create a Python 3.11 virtual environment and run
`pip install -r requirements-dev.txt`, then `python -m pytest -q`.
[docs/development.md](docs/development.md) explains the code layout and the
parts that are easy to break.

## Pull requests

- Keep each pull request to one change.
- Add or update tests for behaviour changes, and update the docs if users or
  contributors would notice the change.
- Make sure the test suite passes, including the 80% coverage gate.
- HandWave never sends data off the machine. Changes that add network access
  or store camera/audio data won't be accepted.

## Mac testing (help wanted)

macOS support has never been tested on a real Mac. You can help without
writing any code: follow [docs/macos.md](docs/macos.md#how-to-help), work
through the checklist, and file a
[macOS test report](https://github.com/IshitaBhatt486/HandWave/issues/new?template=macos-test-report.md).

## Licence

By contributing, you agree that your work is released under the
[MIT License](LICENSE).
