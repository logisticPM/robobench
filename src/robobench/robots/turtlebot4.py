"""TurtleBot4 adapter — the reference implementation of ``RobotAdapter``.

v0.1 implements only ``check_clock_offset``. Remaining methods raise
``NotImplementedError`` and will be filled in across subsequent plans
(Phase B: extract from upstream ``deploy.sh``).
"""

from __future__ import annotations

from dataclasses import dataclass

from robobench.adapter_base import RobotAdapter


@dataclass
class TurtleBot4Adapter(RobotAdapter):
    """Adapter for iRobot TurtleBot4 platforms.

    Configuration mirrors the upstream ``config.yaml`` schema so that
    existing campus_guide setups can hand their config dict straight in.
    """

    ip: str
    ssh_user: str
    ssh_pass: str
    namespace: str
    workspace_dir: str

    def check_clock_offset(self) -> float:
        raise NotImplementedError("Filled in by Task 15")

    def build(self) -> None:
        raise NotImplementedError("Phase B: extract from deploy.sh step 2")

    def launch(self) -> None:
        raise NotImplementedError("Phase B: extract from deploy.sh step 3")

    def activate_lifecycle(self) -> None:
        raise NotImplementedError("Phase B: wraps lifecycle_activator")

    def set_initial_pose(self, x: float, y: float, theta: float) -> None:
        raise NotImplementedError("Phase B: extract from deploy.sh step 7")

    def health_check(self) -> dict:
        raise NotImplementedError("Phase B: extract from deploy.sh step 9")

    def shutdown(self) -> None:
        raise NotImplementedError("Phase B: wraps stop.sh")
