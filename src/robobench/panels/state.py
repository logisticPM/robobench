"""Thread-safe container for live diagnostic data collected by the bridge.

The rclpy bridge writes here from its spin thread; the FastAPI handlers read
from request threads. One lock guards everything. No ROS or HTTP imports —
this is a plain data holder so it stays trivially testable.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from robobench.recovery.state import RobotState


class DiagnosticState:
    """Holds the most recent robot data the diagnostic bridge has seen."""

    def __init__(self, scan_window: int = 100) -> None:
        self._lock = threading.Lock()
        self._scan_ts: deque[float] = deque(maxlen=scan_window)
        self._tf: list[tuple[str, str, float]] = []
        self._nodes: list[str] = []
        self._clock_offset: float | None = None
        self._connectivity: RobotState | None = None

    def record_scan(self, stamp: float) -> None:
        with self._lock:
            self._scan_ts.append(stamp)

    def scan_timestamps(self) -> deque[float]:
        with self._lock:
            return deque(self._scan_ts)

    def clear_scans(self) -> None:
        """Drop all recorded scan timestamps (used by demo re-seeding)."""
        with self._lock:
            self._scan_ts.clear()

    def set_tf(self, transforms: list[tuple[str, str, float]]) -> None:
        with self._lock:
            self._tf = list(transforms)

    def tf_transforms(self) -> list[tuple[str, str, float]]:
        with self._lock:
            return list(self._tf)

    def set_nodes(self, names: list[str]) -> None:
        with self._lock:
            self._nodes = list(names)

    def node_names(self) -> list[str]:
        with self._lock:
            return list(self._nodes)

    def set_clock_offset(self, offset: float | None) -> None:
        with self._lock:
            self._clock_offset = offset

    def clock_offset(self) -> float | None:
        with self._lock:
            return self._clock_offset

    def set_connectivity(self, state: RobotState | None) -> None:
        with self._lock:
            self._connectivity = state

    def connectivity(self) -> RobotState | None:
        with self._lock:
            return self._connectivity

    def snapshot(self) -> dict:
        """Return a consistent plain-dict copy of all state under one lock."""
        with self._lock:
            return {
                "scan_timestamps": list(self._scan_ts),
                "tf": list(self._tf),
                "nodes": list(self._nodes),
                "clock_offset": self._clock_offset,
                "connectivity": self._connectivity,
            }
