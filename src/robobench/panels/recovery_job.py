"""Thread-safe status for a dashboard-initiated recovery run.

Doubles as the recovery engine's ``event_log`` sink: the engine calls
``.log(event, data)`` for each probe/action/outcome, which appends to ``steps``
so the polling frontend sees live progress. The authoritative top-level
``outcome`` is set by ``finish()`` from the RecoveryResult, not parsed from the
stream. threading only — no FastAPI/SSH imports.
"""

from __future__ import annotations

import threading
import time


class RecoveryJob:
    """Live status of one recovery run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = "idle"  # idle | running | done
        self._outcome: str | None = None
        self._actions: list[str] = []
        self._steps: list[dict] = []
        self._error: str | None = None
        self._started_at: float | None = None
        self._finished_at: float | None = None

    def log(self, event: str, data: dict) -> None:
        """EventLogger-compatible sink: append one engine event to the stream."""
        with self._lock:
            self._steps.append({"event": event, "data": data})

    def begin(self) -> None:
        with self._lock:
            self._status = "running"
            self._outcome = None
            self._actions = []
            self._steps = []
            self._error = None
            self._started_at = time.time()
            self._finished_at = None

    def finish(self, outcome: str, actions: list[str], error: str | None = None) -> None:
        with self._lock:
            self._status = "done"
            self._outcome = outcome
            self._actions = list(actions)
            self._error = error
            self._finished_at = time.time()

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": self._status,
                "outcome": self._outcome,
                "actions": list(self._actions),
                "steps": list(self._steps),
                "error": self._error,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
            }
