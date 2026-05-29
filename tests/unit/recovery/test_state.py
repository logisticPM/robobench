"""Tests for RobotState."""

from __future__ import annotations

import dataclasses

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


def s_with(state: RobotState, **changes) -> RobotState:
    return dataclasses.replace(state, **changes)


def test_healthy_state_is_healthy():
    assert _healthy().is_healthy() is True
    assert _healthy().failing_aspect() is None


def test_unreachable_rpi_is_the_first_failing_aspect():
    s = s_with(_healthy(), rpi_reachable=False)
    assert s.is_healthy() is False
    assert s.failing_aspect() == "rpi_reachable"


def test_failing_aspect_is_most_upstream_first():
    """When several aspects fail, the most upstream one is reported first:
    rpi → discovery_server → clock → create3_topics → tb4_nodes → odom."""
    s = RobotState(
        rpi_reachable=True,
        discovery_server_ok=False,
        clock_synced=False,
        create3_topics=0,
        tb4_nodes_present=False,
        odom_publishing=False,
    )
    assert s.failing_aspect() == "discovery_server_ok"


def test_odom_is_the_last_aspect():
    s = s_with(_healthy(), odom_publishing=False)
    assert s.failing_aspect() == "odom_publishing"


def test_create3_topics_zero_counts_as_failing():
    s = s_with(_healthy(), create3_topics=0)
    assert s.failing_aspect() == "create3_topics"
