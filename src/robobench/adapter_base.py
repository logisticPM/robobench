"""Abstract base class for robot adapters.

A `RobotAdapter` is the contract every supported robot implements. The
robobench CLI and (later) the diagnostic panels only ever interact with
this interface; concrete vendor knowledge lives in subclasses under
``robobench.robots``.

Method contract:

- ``check_clock_offset``: return clock offset in seconds between
  workstation and robot. Negative = robot is behind workstation.
- ``build``: build the robot-side ROS2 workspace (typically over SSH).
- ``launch``: start the navigation stack on the robot.
- ``activate_lifecycle``: bring Nav2 lifecycle nodes through configure
  -> activate (works around DDS discovery quirks).
- ``set_initial_pose``: publish an AMCL initial pose.
- ``health_check``: return a structured dict describing all probed
  subsystems and whether each is OK.
- ``shutdown``: kill the navigation stack cleanly.

Adapters MAY raise ``NotImplementedError`` from any method in early
development; the CLI treats that as a "not yet wired up" diagnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class RobotAdapter(ABC):
    """Vendor-agnostic interface for ROS2 robot hardware."""

    @abstractmethod
    def check_clock_offset(self) -> float:
        """Return clock offset in seconds (workstation_time - robot_time)."""

    @abstractmethod
    def build(self) -> None:
        """Build the robot-side ROS2 workspace."""

    @abstractmethod
    def launch(self) -> None:
        """Start the navigation stack on the robot."""

    @abstractmethod
    def activate_lifecycle(self, map_yaml: str | None = None) -> None:
        """Bring lifecycle nodes through configure -> activate.

        Args:
            map_yaml: Absolute path to the static map YAML to load.
        """

    @abstractmethod
    def set_initial_pose(self, x: float, y: float, theta: float) -> None:
        """Publish an AMCL initial pose at (x, y, theta)."""

    @abstractmethod
    def health_check(self) -> dict:
        """Return a structured health report of all probed subsystems."""

    @abstractmethod
    def shutdown(self) -> None:
        """Cleanly stop the navigation stack."""
