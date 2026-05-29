"""Tests for the RecoveryActions ABC and ActionTier."""

from __future__ import annotations

import pytest

from robobench.recovery.actions import ActionTier, RecoveryActions


def test_actions_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        RecoveryActions()  # type: ignore[abstract]


def test_tier_ordering_cheap_lt_nuclear():
    assert ActionTier.CHEAP < ActionTier.MEDIUM < ActionTier.NUCLEAR


def test_complete_subclass_is_instantiable():
    class Complete(RecoveryActions):
        def restart_local_daemon(self) -> None:
            return None

        def restart_discovery_server(self) -> None:
            return None

        def sync_clock(self) -> None:
            return None

        def restart_tb4_service(self) -> None:
            return None

        def restart_create3_app(self) -> None:
            return None

        def reboot_create3(self) -> None:
            return None

    c = Complete()
    assert c.restart_local_daemon() is None
