"""Owns a RecoveryJob and runs the recovery engine in a background thread.

Single-flight (one recovery at a time). Preview is pure (computed from the
latest connectivity diagnosis — no SSH). The engine is built via an injected
``build_engine(job)`` callable that MUST wire ``event_log=job`` and
``allow_reboot=False`` — so the web path can never trigger the nuclear reboot.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from robobench.panels.connectivity import first_broken_layer
from robobench.panels.recovery_job import RecoveryJob
from robobench.recovery.engine import _LADDER, RecoveryEngine
from robobench.recovery.state import RobotState


class RecoveryController:
    """Drives dashboard-initiated recovery, gated and single-flight."""

    def __init__(
        self,
        build_engine: Callable[[RecoveryJob], RecoveryEngine],
        *,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        self.build_engine = build_engine
        self.job = RecoveryJob()
        self._thread_factory = thread_factory

    def preview(self, connectivity_state: RobotState | None) -> dict:
        """Non-nuclear ladder actions for the current failing layer. No SSH."""
        if connectivity_state is None:
            return {"available": True, "failing_layer": None, "would_try": []}
        failing = first_broken_layer(connectivity_state)
        would_try = [
            action for aspect, action, is_nuclear in _LADDER if aspect == failing and not is_nuclear
        ]
        return {"available": True, "failing_layer": failing, "would_try": would_try}

    def start_apply(self) -> bool:
        """Start a recovery in a daemon thread. Single-flight: returns False if
        one is already running."""
        if self.job.status == "running":
            return False
        self.job.begin()
        self._thread_factory(target=self._run, daemon=True).start()
        return True

    def _run(self) -> None:
        try:
            result = self.build_engine(self.job).run()
            self.job.finish(result.outcome, result.actions_taken)
        except Exception as exc:  # noqa: BLE001 — surface any failure to the UI, never crash the thread
            self.job.finish("ERROR", [], error=str(exc))
