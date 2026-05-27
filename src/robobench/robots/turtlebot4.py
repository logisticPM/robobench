"""TurtleBot4 adapter — the reference implementation of ``RobotAdapter``.

v0.1 implements only ``check_clock_offset``. Remaining methods raise
``NotImplementedError`` and will be filled in across subsequent plans
(Phase B: extract from upstream ``deploy.sh``).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime

from robobench.adapter_base import RobotAdapter


def _now_utc() -> datetime:
    """Wrapper so tests can stub local time."""
    return datetime.now(tz=UTC)


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
        """Return ``local_time - robot_time`` in seconds (positive = robot is behind)."""
        cmd = [
            "sshpass",
            "-p",
            self.ssh_pass,
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"{self.ssh_user}@{self.ip}",
            "date +%s",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"SSH to {self.ip} failed (rc={result.returncode}): {result.stderr.strip()}"
            )
        robot_epoch = float(result.stdout.strip())
        local_epoch = _now_utc().timestamp()
        return local_epoch - robot_epoch

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
