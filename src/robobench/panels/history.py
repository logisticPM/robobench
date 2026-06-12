"""Daemon-thread loop that samples diagnostic metrics into DiagnosticState's
bounded history, powering the dashboard's Trends panel. Importable without
ROS2 (no rclpy) — it only reads/writes DiagnosticState.

The instant panels answer "what is the clock offset now"; this history answers
"how has it drifted over the last two hours", which is the diagnosis the
instant view can't make.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from robobench.panels.analyzers import compute_topic_rate
from robobench.panels.state import DiagnosticState


def run_history_sampler(
    state: DiagnosticState,
    *,
    interval: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Every ``interval`` seconds, append (now, clock_offset, scan_hz) to history.

    Runs until ``should_stop()`` returns True (default: forever, for a daemon
    thread). All inputs are read from ``state`` snapshots, so one sampler works
    for both the live bridge and demo mode.
    """
    stop = should_stop or (lambda: False)
    while not stop():
        rate = compute_topic_rate(list(state.scan_timestamps()))
        state.append_history(now(), state.clock_offset(), rate)
        sleep(interval)
