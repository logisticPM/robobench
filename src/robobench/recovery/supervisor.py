"""Continuous deterministic supervisor: probe -> (optionally) recover -> repeat.

Reuses the recovery engine via an injected zero-arg ``recover`` callable. Pure
orchestration — probe/recover/sleep/now/should_stop/emit are all injected, so the
whole policy (monitor-only, cooldown, attempt-cap, escalation, reset) is
unit-testable without hardware. ``run_supervisor`` is the never-die boundary: a
failing ``probe()`` or ``recover()`` is caught and the loop continues.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from robobench.recovery.engine import RecoveryResult
    from robobench.recovery.state import RobotState


def run_supervisor(
    probe: Callable[[], RobotState],
    recover: Callable[[], RecoveryResult] | None,
    *,
    interval: float,
    cooldown_s: float,
    max_attempts: int,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    should_stop: Callable[[], bool] | None = None,
    emit: Callable[[str, dict], None] | None = None,
) -> None:
    """Run the supervisor loop until ``should_stop()`` is true (default: forever).

    ``recover is None`` -> monitor-only (alert, never act). Otherwise an unhealthy
    cycle triggers ``recover()`` unless within ``cooldown_s`` of the last attempt
    or after ``max_attempts`` consecutive failures (then it escalates to
    monitor-only). A CONVERGED result resets the counter; NEEDS_HUMAN escalates
    immediately. Returning to healthy resets the counter.
    """
    stop = should_stop or (lambda: False)
    say = emit or (lambda _event, _data: None)

    attempts = 0
    escalated = False
    last_attempt: float | None = None

    while not stop():
        try:
            state = probe()
        except Exception as exc:  # noqa: BLE001 — a bad probe must not kill the loop
            say("probe_error", {"error": str(exc)})
            sleep(interval)
            continue

        if state.is_healthy():
            attempts = 0
            escalated = False
            say("healthy", {})
            sleep(interval)
            continue

        aspect = state.failing_aspect()
        say("unhealthy", {"aspect": aspect})

        if recover is None or escalated:
            pass  # monitor-only (by config or after escalation): alert, don't act
        elif last_attempt is not None and now() - last_attempt < cooldown_s:
            say("cooldown", {"aspect": aspect})
        elif attempts >= max_attempts:
            escalated = True
            say("escalate", {"reason": "max_attempts", "attempts": attempts})
        else:
            # stamp + count BEFORE recover() so a raised recover() still enforces
            # cooldown and the attempt cap
            last_attempt = now()
            attempts += 1
            try:
                result = recover()
            except Exception as exc:  # noqa: BLE001 — flapping remediation must not crash the loop
                say("recover_error", {"error": str(exc), "attempt": attempts})
            else:
                say("recover", {"outcome": result.outcome, "actions": list(result.actions_taken)})
                if result.outcome == "CONVERGED":
                    attempts = 0
                    escalated = False
                elif result.outcome == "NEEDS_HUMAN":
                    escalated = True
                    say("escalate", {"reason": "needs_human"})

        sleep(interval)
