"""Tests for the RecoveryEngine convergence loop."""

from __future__ import annotations

from unittest.mock import MagicMock

from robobench.recovery.actions import RecoveryActions
from robobench.recovery.engine import RecoveryEngine, RecoveryResult
from robobench.recovery.state import RobotState


def _healthy() -> RobotState:
    return RobotState(
        rpi_reachable=True,
        discovery_server_ok=True,
        clock_synced=True,
        create3_topics=12,
        tb4_nodes_present=True,
        odom_publishing=True,
    )


def _fake_actions() -> RecoveryActions:
    return MagicMock(spec=RecoveryActions)


def _fake_clock():
    """A monotonic clock that advances 1s per call."""
    t = {"v": 0.0}

    def _now() -> float:
        t["v"] += 1.0
        return t["v"]

    return _now


def test_already_healthy_converges_with_no_actions():
    probe = MagicMock(return_value=_healthy())
    actions = _fake_actions()
    engine = RecoveryEngine(
        probe=probe,
        actions=actions,
        allow_reboot=False,
        deadline_s=30.0,
        settle_s=0.0,
        sleep=lambda _s: None,
        now=_fake_clock(),
    )
    result = engine.run()
    assert isinstance(result, RecoveryResult)
    assert result.outcome == "CONVERGED"
    assert result.actions_taken == []
    assert result.final_state is not None
