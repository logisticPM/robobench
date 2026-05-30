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

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field

from robobench.eventlog import NullEventLogger
from robobench.recovery.actions import RecoveryActions
from robobench.recovery.state import RobotState

# Escalation ladder: ordered cheap -> nuclear. Each rule maps a failing aspect
# to the action that targets it and whether that action is NUCLEAR (gated).
# When create3_topics is the failing aspect we walk a sub-ladder of
# increasingly disruptive actions because "no topics" has many possible causes
# (local daemon cache, discovery zombie, stale service, dead app, dead base).
_LADDER: list[tuple[str, str, bool]] = [
    # (failing_aspect, action_method_name, is_nuclear)
    ("discovery_server_ok", "restart_discovery_server", False),
    ("clock_synced", "sync_clock", False),
    ("tb4_nodes_present", "restart_tb4_service", False),
    ("odom_publishing", "restart_create3_app", False),
    # create3_topics == 0: try cheapest cause first, escalate to nuclear last.
    ("create3_topics", "restart_local_daemon", False),
    ("create3_topics", "restart_discovery_server", False),
    ("create3_topics", "restart_tb4_service", False),
    ("create3_topics", "restart_create3_app", False),
    ("create3_topics", "reboot_create3", True),
]


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
        event_log: object | None = None,
    ) -> None:
        self._probe = probe
        self._actions = actions
        self._allow_reboot = allow_reboot
        self._deadline_s = deadline_s
        self._settle_s = settle_s
        self._sleep = sleep
        self._now = now
        self._log = event_log or NullEventLogger()

    def run(self) -> RecoveryResult:
        result = RecoveryResult(outcome="TIMED_OUT")
        start = self._now()
        tried: set[str] = set()
        while True:
            state = self._probe()
            result.final_state = state
            self._log.log("probe", dataclasses.asdict(state))
            if state.is_healthy():
                result.outcome = "CONVERGED"
                result.trace.append("healthy")
                self._log.log("outcome", {"outcome": result.outcome})
                return result
            if self._now() - start > self._deadline_s:
                result.outcome = "TIMED_OUT"
                result.trace.append("deadline exceeded")
                self._log.log("outcome", {"outcome": result.outcome})
                return result
            aspect = state.failing_aspect()
            if aspect == "rpi_reachable":
                result.outcome = "NEEDS_HUMAN"
                result.trace.append("rpi unreachable — power/network, cannot fix remotely")
                self._log.log("outcome", {"outcome": result.outcome})
                return result

            action_name = self._pick_action(aspect, tried)
            if action_name is None:
                result.outcome = "STUCK"
                result.trace.append(f"no untried action left for '{aspect}'")
                self._log.log("outcome", {"outcome": result.outcome})
                return result

            tried.add(action_name)
            result.actions_taken.append(action_name)
            result.trace.append(f"aspect '{aspect}' -> {action_name}")
            self._log.log("action", {"aspect": aspect, "name": action_name})
            getattr(self._actions, action_name)()
            self._sleep(self._settle_s)

    def _pick_action(self, aspect: str | None, tried: set[str]) -> str | None:
        """Cheapest untried ladder action for the failing aspect, honoring the
        nuclear gate. Returns None when nothing applicable is left."""
        for ladder_aspect, action_name, is_nuclear in _LADDER:
            if ladder_aspect != aspect:
                continue
            if action_name in tried:
                continue
            if is_nuclear and not self._allow_reboot:
                continue
            return action_name
        return None
