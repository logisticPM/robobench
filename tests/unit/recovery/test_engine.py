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


def _state(**overrides) -> RobotState:
    base = dict(
        rpi_reachable=True,
        discovery_server_ok=True,
        clock_synced=True,
        create3_topics=12,
        tb4_nodes_present=True,
        odom_publishing=True,
    )
    base.update(overrides)
    return RobotState(**base)


def _engine(probe, actions, allow_reboot=False):
    return RecoveryEngine(
        probe=probe,
        actions=actions,
        allow_reboot=allow_reboot,
        deadline_s=1000.0,
        settle_s=0.0,
        sleep=lambda _s: None,
        now=_fake_clock(),
    )


def test_unreachable_rpi_needs_human_immediately():
    """Can't fix a powered-off / off-network robot remotely."""
    probe = MagicMock(return_value=_state(rpi_reachable=False))
    actions = _fake_actions()
    result = _engine(probe, actions).run()
    assert result.outcome == "NEEDS_HUMAN"
    assert actions.method_calls == []  # no remote action attempted


def test_stale_local_daemon_fixed_by_restart_local_daemon():
    """create3_topics==0 but discovery OK -> cheapest fix (local daemon) first;
    the second probe returns healthy -> CONVERGED."""
    probe = MagicMock(side_effect=[_state(create3_topics=0), _state()])
    actions = _fake_actions()
    result = _engine(probe, actions).run()
    assert result.outcome == "CONVERGED"
    assert result.actions_taken == ["restart_local_daemon"]
    actions.restart_local_daemon.assert_called_once()


def test_discovery_down_restarts_discovery_server():
    probe = MagicMock(side_effect=[_state(discovery_server_ok=False), _state()])
    actions = _fake_actions()
    result = _engine(probe, actions).run()
    assert result.outcome == "CONVERGED"
    assert "restart_discovery_server" in result.actions_taken


def test_clock_drift_triggers_sync_clock():
    probe = MagicMock(side_effect=[_state(clock_synced=False), _state()])
    actions = _fake_actions()
    result = _engine(probe, actions).run()
    assert result.outcome == "CONVERGED"
    assert result.actions_taken == ["sync_clock"]


def test_tb4_nodes_missing_restarts_tb4_service():
    probe = MagicMock(side_effect=[_state(tb4_nodes_present=False), _state()])
    actions = _fake_actions()
    result = _engine(probe, actions).run()
    assert result.outcome == "CONVERGED"
    assert result.actions_taken == ["restart_tb4_service"]


def test_odom_dead_restarts_create3_app():
    probe = MagicMock(side_effect=[_state(odom_publishing=False), _state()])
    actions = _fake_actions()
    result = _engine(probe, actions).run()
    assert result.outcome == "CONVERGED"
    assert result.actions_taken == ["restart_create3_app"]


def test_no_create3_topics_needs_reboot_but_gated():
    """create3_topics==0 that never recovers escalates through cheap+medium; if
    none work and reboot is NOT allowed, it stops as STUCK rather than rebooting."""
    probe = MagicMock(return_value=_state(create3_topics=0))  # never recovers
    actions = _fake_actions()
    result = _engine(probe, actions, allow_reboot=False).run()
    assert result.outcome == "STUCK"
    actions.reboot_create3.assert_not_called()
    assert "restart_local_daemon" in result.actions_taken  # tried cheap first


def test_reboot_used_only_when_allowed_and_cheaper_exhausted():
    """With allow_reboot=True and nothing else working, reboot_create3 is the
    last action tried; if a probe after it returns healthy -> CONVERGED."""
    states = [
        _state(create3_topics=0),  # initial: try restart_local_daemon
        _state(create3_topics=0),  # still bad: try restart_discovery_server
        _state(create3_topics=0),  # still bad: try restart_tb4_service
        _state(create3_topics=0),  # still bad: try restart_create3_app
        _state(create3_topics=0),  # still bad: reboot_create3 (nuclear)
        _state(),  # healthy after reboot
    ]
    probe = MagicMock(side_effect=states)
    actions = _fake_actions()
    result = _engine(probe, actions, allow_reboot=True).run()
    assert result.outcome == "CONVERGED"
    assert result.actions_taken[-1] == "reboot_create3"
    actions.reboot_create3.assert_called_once()


def test_no_action_repeated():
    """An action that doesn't fix the aspect is not retried forever; the engine
    moves on and eventually STUCKs."""
    probe = MagicMock(return_value=_state(odom_publishing=False))  # never recovers
    actions = _fake_actions()
    result = _engine(probe, actions, allow_reboot=False).run()
    assert result.outcome == "STUCK"
    # restart_create3_app tried once for odom; not called repeatedly
    assert result.actions_taken.count("restart_create3_app") == 1


def test_engine_logs_events_to_injected_logger():
    healthy = RobotState(True, True, True, 5, True, True)
    broken = RobotState(True, False, True, 5, True, True)
    states = iter([broken, healthy])

    class FakeActions:
        def __getattr__(self, _name):
            return lambda: None

    events: list[tuple[str, dict]] = []

    class FakeLog:
        def log(self, event, data):
            events.append((event, data))

    engine = RecoveryEngine(
        probe=lambda: next(states),
        actions=FakeActions(),
        allow_reboot=False,
        deadline_s=100.0,
        settle_s=0.0,
        sleep=lambda _s: None,
        now=lambda: 0.0,
        event_log=FakeLog(),
    )
    result = engine.run()
    assert result.outcome == "CONVERGED"
    kinds = [e[0] for e in events]
    assert "probe" in kinds
    assert "action" in kinds
    assert ("outcome", {"outcome": "CONVERGED"}) in events
    action_event = next(d for k, d in events if k == "action")
    assert action_event["name"] == "restart_discovery_server"
    assert action_event["aspect"] == "discovery_server_ok"
