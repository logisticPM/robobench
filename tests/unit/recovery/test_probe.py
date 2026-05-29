"""Tests for the RobotProbe ABC."""

from __future__ import annotations

import pytest

from robobench.recovery.probe import RobotProbe
from robobench.recovery.state import RobotState


def test_probe_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        RobotProbe()  # type: ignore[abstract]


def test_concrete_probe_returns_state():
    class FixedProbe(RobotProbe):
        def read(self) -> RobotState:
            return RobotState(
                rpi_reachable=True,
                discovery_server_ok=True,
                clock_synced=True,
                create3_topics=5,
                tb4_nodes_present=True,
                odom_publishing=True,
            )

    assert FixedProbe().read().is_healthy() is True
