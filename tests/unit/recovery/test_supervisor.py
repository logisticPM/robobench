from robobench.recovery.engine import RecoveryResult
from robobench.recovery.state import RobotState
from robobench.recovery.supervisor import run_supervisor

_HEALTHY = RobotState(True, True, True, 5, True, True)
_BROKEN = RobotState(True, False, True, 5, True, True)  # discovery_server_ok fails


def test_monitor_only_never_recovers():
    states = iter([_BROKEN, _BROKEN])
    calls = {"sleep": 0}
    events = []
    run_supervisor(
        probe=lambda: next(states),
        recover=None,
        interval=1,
        cooldown_s=0,
        max_attempts=3,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: 0.0,
        should_stop=lambda: calls["sleep"] >= 2,  # noqa: PLR2004
        emit=lambda e, d: events.append((e, d)),
    )
    assert any(e == "unhealthy" for e, _ in events)
    assert not any(e in ("recover", "recover_error") for e, _ in events)


def test_auto_recover_attempts_and_resets_on_converged():
    states = iter([_BROKEN, _HEALTHY, _BROKEN])
    results = iter(
        [
            RecoveryResult(outcome="CONVERGED", actions_taken=["restart_discovery_server"]),
            RecoveryResult(outcome="CONVERGED", actions_taken=["restart_discovery_server"]),
        ]
    )
    calls = {"sleep": 0, "recover": 0}

    def recover():
        calls["recover"] += 1
        return next(results)

    run_supervisor(
        probe=lambda: next(states),
        recover=recover,
        interval=1,
        cooldown_s=0,
        max_attempts=3,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: float(calls["sleep"]),  # advances each cycle -> no cooldown
        should_stop=lambda: calls["sleep"] >= 3,  # noqa: PLR2004
        emit=lambda e, d: None,
    )
    assert calls["recover"] == 2  # noqa: PLR2004 — cycle1 broken->recover, cycle2 healthy, cycle3 broken->recover


def test_cooldown_skips_second_attempt():
    states = iter([_BROKEN, _BROKEN])
    results = iter([RecoveryResult(outcome="STUCK")])
    calls = {"sleep": 0, "recover": 0}

    def recover():
        calls["recover"] += 1
        return next(results)

    events = []
    run_supervisor(
        probe=lambda: next(states),
        recover=recover,
        interval=1,
        cooldown_s=100,
        max_attempts=3,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: 0.0,  # frozen -> 2nd cycle within cooldown
        should_stop=lambda: calls["sleep"] >= 2,  # noqa: PLR2004
        emit=lambda e, d: events.append((e, d)),
    )
    assert calls["recover"] == 1
    assert any(e == "cooldown" for e, _ in events)


def test_max_attempts_escalates():
    states = iter([_BROKEN] * 5)
    results = iter([RecoveryResult(outcome="STUCK")] * 5)
    calls = {"sleep": 0, "recover": 0}

    def recover():
        calls["recover"] += 1
        return next(results)

    events = []
    run_supervisor(
        probe=lambda: next(states),
        recover=recover,
        interval=1,
        cooldown_s=0,
        max_attempts=2,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: float(calls["sleep"]),
        should_stop=lambda: calls["sleep"] >= 5,  # noqa: PLR2004
        emit=lambda e, d: events.append((e, d)),
    )
    assert calls["recover"] == 2  # noqa: PLR2004 — 2 attempts then escalate; no more
    assert any(e == "escalate" and d.get("reason") == "max_attempts" for e, d in events)


def test_needs_human_escalates_immediately():
    states = iter([_BROKEN, _BROKEN, _BROKEN])
    results = iter([RecoveryResult(outcome="NEEDS_HUMAN")])
    calls = {"sleep": 0, "recover": 0}

    def recover():
        calls["recover"] += 1
        return next(results)

    events = []
    run_supervisor(
        probe=lambda: next(states),
        recover=recover,
        interval=1,
        cooldown_s=0,
        max_attempts=3,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: float(calls["sleep"]),
        should_stop=lambda: calls["sleep"] >= 3,  # noqa: PLR2004
        emit=lambda e, d: events.append((e, d)),
    )
    assert calls["recover"] == 1  # one attempt -> NEEDS_HUMAN -> escalated
    assert any(e == "escalate" and d.get("reason") == "needs_human" for e, d in events)


def test_recover_exception_counts_and_continues():
    states = iter([_BROKEN, _BROKEN, _BROKEN])
    calls = {"sleep": 0, "recover": 0}

    def boom():
        calls["recover"] += 1
        raise RuntimeError("ssh boom")

    events = []
    run_supervisor(
        probe=lambda: next(states),
        recover=boom,
        interval=1,
        cooldown_s=0,
        max_attempts=2,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: float(calls["sleep"]),
        should_stop=lambda: calls["sleep"] >= 3,  # noqa: PLR2004
        emit=lambda e, d: events.append((e, d)),
    )
    assert calls["recover"] == 2  # noqa: PLR2004 — each raise counts as an attempt, then escalate
    assert any(e == "recover_error" for e, _ in events)
    assert any(e == "escalate" for e, _ in events)


def test_healthy_after_escalation_allows_fresh_recovery():
    # unhealthy x2 (cap=2 -> escalate), then healthy (reset), then unhealthy -> recover again
    states = iter([_BROKEN, _BROKEN, _BROKEN, _HEALTHY, _BROKEN])
    results = iter(
        [
            RecoveryResult(outcome="STUCK"),
            RecoveryResult(outcome="STUCK"),
            RecoveryResult(outcome="CONVERGED", actions_taken=[]),
        ]
    )
    calls = {"sleep": 0, "recover": 0}

    def recover():
        calls["recover"] += 1
        return next(results)

    events = []
    run_supervisor(
        probe=lambda: next(states),
        recover=recover,
        interval=1,
        cooldown_s=0,
        max_attempts=2,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: float(calls["sleep"]),
        should_stop=lambda: calls["sleep"] >= 5,  # noqa: PLR2004
        emit=lambda e, d: events.append((e, d)),
    )
    # cycle1 recover, cycle2 recover, cycle3 escalate (no recover), cycle4 healthy (reset),
    # cycle5 unhealthy -> recover again
    assert calls["recover"] == 3  # noqa: PLR2004
    assert any(e == "escalate" for e, _ in events)


def test_probe_exception_continues():
    calls = {"sleep": 0, "probe": 0}
    events = []

    def probe():
        calls["probe"] += 1
        if calls["probe"] == 1:
            raise RuntimeError("probe boom")
        return _HEALTHY

    run_supervisor(
        probe=probe,
        recover=None,
        interval=1,
        cooldown_s=0,
        max_attempts=3,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: 0.0,
        should_stop=lambda: calls["sleep"] >= 2,  # noqa: PLR2004
        emit=lambda e, d: events.append((e, d)),
    )
    assert any(e == "probe_error" for e, _ in events)
    assert any(e == "healthy" for e, _ in events)
