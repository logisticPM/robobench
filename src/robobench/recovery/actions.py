"""Atomic recovery actions a robot adapter must provide, and their cost tier.

Each action is idempotent and targets one failing aspect. The engine picks
the cheapest action whose tier it's allowed to use. NUCLEAR actions (Create3
reboot) re-randomize DDS GUIDs and take minutes — gated behind explicit
opt-in so a debug tool never reboots hardware without consent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import IntEnum


class ActionTier(IntEnum):
    """Cost/disruption tier. Lower = cheaper, tried first."""

    CHEAP = 1  # local-only or a quick remote restart
    MEDIUM = 2  # restarts a robot-side service/app
    NUCLEAR = 3  # reboots Create3 hardware (minutes, GUID churn)


class RecoveryActions(ABC):
    """Vendor-agnostic atomic fixes. Each must be idempotent."""

    @abstractmethod
    def restart_local_daemon(self) -> None:
        """Restart the workstation ros2 daemon (clears stale topic cache)."""

    @abstractmethod
    def restart_discovery_server(self) -> None:
        """Restart the FastDDS Discovery Server on the robot (clears zombies)."""

    @abstractmethod
    def sync_clock(self) -> None:
        """Force a chrony makestep on the robot."""

    @abstractmethod
    def restart_tb4_service(self) -> None:
        """Restart the robot-side bring-up service."""

    @abstractmethod
    def restart_create3_app(self) -> None:
        """Restart the Create3 application (soft — no GUID change)."""

    @abstractmethod
    def reboot_create3(self) -> None:
        """Full Create3 reboot (NUCLEAR — minutes, re-randomizes DDS GUIDs)."""
