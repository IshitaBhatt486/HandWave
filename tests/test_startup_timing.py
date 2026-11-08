from handwave.diagnostics.startup_timing import StartupTimer, is_enabled


def test_disabled_by_default_marks_are_no_ops(monkeypatch):
    monkeypatch.delenv("HANDWAVE_STARTUP_PROFILE", raising=False)
    timer = StartupTimer()
    assert timer.enabled is False
    assert timer.mark("checkpoint") == 0.0
    assert timer.marks == []
    assert "disabled" in timer.report()


def test_enabled_records_increasing_elapsed_times():
    # The first tick is consumed by __init__ to record the reference start time.
    ticks = iter([0.0, 0.1, 0.35, 0.5])
    timer = StartupTimer(enabled=True, clock=lambda: next(ticks))
    timer.mark("start")
    timer.mark("middle")
    timer.mark("end")
    assert [label for label, _ in timer.marks] == ["start", "middle", "end"]
    assert [round(elapsed, 2) for _, elapsed in timer.marks] == [0.1, 0.35, 0.5]


def test_report_lists_deltas_between_checkpoints():
    ticks = iter([0.0, 0.0, 0.2])
    timer = StartupTimer(enabled=True, clock=lambda: next(ticks))
    timer.mark("a")
    timer.mark("b")
    report = timer.report()
    assert "a" in report and "b" in report
    assert "0.200" in report


def test_is_enabled_reflects_env_var(monkeypatch):
    monkeypatch.delenv("HANDWAVE_STARTUP_PROFILE", raising=False)
    assert is_enabled() is False
    monkeypatch.setenv("HANDWAVE_STARTUP_PROFILE", "1")
    assert is_enabled() is True
    monkeypatch.setenv("HANDWAVE_STARTUP_PROFILE", "0")
    assert is_enabled() is False
