"""Daemon-thread loop that periodically runs an SSH connectivity probe and
writes the result into DiagnosticState. Importable without ROS2 (no rclpy).

Single non-overlapping worker: probe() then sleep(interval), so a slow probe
never stacks. Each cycle is exception-guarded — one bad probe is logged and
skipped, never killing the thread.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from robobench.panels.state import DiagnosticState

if TYPE_CHECKING:
    from robobench.recovery.state import RobotState


class ConnectivityProbe(Protocol):
    def read_connectivity(self) -> RobotState: ...


def run_connectivity_probe(
    state: DiagnosticState,
    probe: ConnectivityProbe,
    *,
    interval: float,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Loop: ``state.set_connectivity(probe.read_connectivity())`` then sleep.

    ``probe`` is any object exposing ``read_connectivity() -> RobotState``.
    Runs until ``should_stop()`` returns True (default: forever, for a daemon
    thread). A probe exception is logged to stderr and the loop continues.
    """
    stop = should_stop or (lambda: False)
    while not stop():
        try:
            state.set_connectivity(probe.read_connectivity())
        except Exception as exc:  # noqa: BLE001 — one bad cycle must not kill the loop
            print(f"[connectivity] probe failed: {exc}", file=sys.stderr)
        sleep(interval)
