from handwave.services.foreground_app import ForegroundAppInfo, get_foreground_app


def test_get_foreground_app_never_raises_and_returns_dataclass():
    result = get_foreground_app()
    assert isinstance(result, ForegroundAppInfo)
    # executable/window_title are best-effort: either a string or None, never a crash.
    assert result.executable is None or isinstance(result.executable, str)
    assert result.window_title is None or isinstance(result.window_title, str)
