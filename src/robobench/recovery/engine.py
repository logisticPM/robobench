"""Convergence-loop recovery engine.

Replaces the upstream's brittle linear recovery script. The loop:

    while not healthy and not past deadline:
        state = probe()
        if state.is_healthy(): -> CONVERGED
        action = pick the cheapest untried action for the failing aspect
        if none allowed/available: -> STUCK
        apply action; record it; settle; re-probe

Pure orchestration — `probe`, `actions`, `sleep`, `now` are all injected, so
the whole engine is unit-testable without a robot.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from robobench.recovery.actions import RecoveryActions
from robobench.recovery.state import RobotState


@dataclass
class RecoveryResult:
    """Outcome of a recovery run, with a full trace."""

    outcome: str  # CONVERGED | STUCK | TIMED_OUT | NEEDS_HUMAN
    actions_taken: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    final_state: RobotState | None = None


class RecoveryEngine:
    """Drives a robot back to a healthy bring-up state via small fixes."""

    def __init__(
        self,
        probe: Callable[[], RobotState],
        actions: RecoveryActions,
        *,
        allow_reboot: bool,
        deadline_s: float,
        settle_s: float,
        sleep: Callable[[float], None],
        now: Callable[[], float],
    ) -> None:
        self._probe = probe
        self._actions = actions
        self._allow_reboot = allow_reboot
        self._deadline_s = deadline_s
        self._settle_s = settle_s
        self._sleep = sleep
        self._now = now

    def run(self) -> RecoveryResult:
        result = RecoveryResult(outcome="TIMED_OUT")
        start = self._now()
        while True:
            state = self._probe()
            result.final_state = state
            if state.is_healthy():
                result.outcome = "CONVERGED"
                result.trace.append("healthy")
                return result
            if self._now() - start > self._deadline_s:
                result.outcome = "TIMED_OUT"
                result.trace.append("deadline exceeded")
                return result
            # Task D4 adds action selection here.
            result.outcome = "STUCK"
            result.trace.append("no action selection yet")
            return result
