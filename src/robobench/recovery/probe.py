"""Probe interface: reads a robot's bring-up health into a RobotState.

Concrete probes (per robot) do the I/O; the engine only needs `read()`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from robobench.recovery.state import RobotState


class RobotProbe(ABC):
    """Reads the robot's current bring-up state."""

    @abstractmethod
    def read(self) -> RobotState:
        """Return a fresh RobotState snapshot."""
