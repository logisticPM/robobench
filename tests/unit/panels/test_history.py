"""Tests for the metric-history sampler loop."""

from __future__ import annotations

from robobench.panels.history import run_history_sampler
from robobench.panels.state import DiagnosticState


def test_sampler_appends_clock_and_scan_rate_each_cycle():
    state = DiagnosticState()
    state.set_clock_offset(0.25)
    for t in [i * 0.1 for i in range(11)]:  # ~10 Hz over 1s
        state.record_scan(t)

    cycles = iter([False, False, True])  # run two cycles, then stop
    clock = iter([100.0, 110.0])
    sleeps: list[float] = []

    run_history_sampler(
        state,
        interval=10.0,
        sleep=sleeps.append,
        now=lambda: next(clock),
        should_stop=lambda: next(cycles),
    )

    samples = state.history()
    assert [s[0] for s in samples] == [100.0, 110.0]
    assert all(s[1] == 0.25 for s in samples)  # noqa: PLR2004
    assert all(s[2] > 8.0 for s in samples)  # noqa: PLR2004
    assert sleeps == [10.0, 10.0]


def test_sampler_records_none_clock_and_zero_rate_when_no_data():
    state = DiagnosticState()
    stop_after_one = iter([False, True])

    run_history_sampler(
        state,
        interval=5.0,
        sleep=lambda _s: None,
        now=lambda: 42.0,
        should_stop=lambda: next(stop_after_one),
    )

    assert state.history() == [(42.0, None, 0.0)]
