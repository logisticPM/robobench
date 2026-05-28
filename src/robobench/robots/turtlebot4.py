"""TurtleBot4 adapter — the reference implementation of ``RobotAdapter``.

v0.1 implements only ``check_clock_offset``. Remaining methods raise
``NotImplementedError`` and will be filled in across subsequent plans
(Phase B: extract from upstream ``deploy.sh``).
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from robobench._process import run_local
from robobench.adapter_base import RobotAdapter
from robobench.ssh import SSHClient


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
        with SSHClient(self.ip, self.ssh_user, self.ssh_pass) as ssh:
            result = ssh.run(["date", "+%s"], timeout=10)
        if result.returncode != 0:
            raise RuntimeError(
                f"SSH to {self.ip} failed (rc={result.returncode}): {result.stderr.strip()}"
            )
        robot_epoch = float(result.stdout.strip())
        local_epoch = _now_utc().timestamp()
        return local_epoch - robot_epoch

    def setup_clock_sync(self, workstation_ip: str) -> dict:
        """Configure chrony on the robot to follow the workstation; restart Create3 NTP.

        Returns a structured report dict. Mirrors upstream ``deploy.sh`` Step 1
        without the human-friendly logging.
        """
        report: dict = {
            "chrony_installed": False,
            "chrony_configured": False,
            "create3_ntp_restarted": False,
            "drift_seconds": None,
        }

        chrony_conf = (
            f"server {workstation_ip} prefer iburst minpoll 0 maxpoll 2\n"
            "pool ntp.ubuntu.com iburst maxsources 2\n"
            "local stratum 11\n"
            "allow 192.168.0.0/16\n"
            "makestep 0.1 -1\n"
            "rtcsync\n"
        )

        with SSHClient(self.ip, self.ssh_user, self.ssh_pass) as ssh:
            # 1. Check if chrony is installed; install if not.
            check = ssh.run(["dpkg", "-l", "chrony"], timeout=15)
            if check.returncode == 0 and "ii" in check.stdout:
                report["chrony_installed"] = True
            else:
                install = ssh.run(["sudo", "apt-get", "install", "-y", "chrony"], timeout=120)
                report["chrony_installed"] = install.returncode == 0
                if install.returncode != 0:
                    raise RuntimeError(f"chrony install failed: {install.stderr.strip()}")

            # 2. Write config + restart chrony. Use stdin-redirected tee.
            write_cmd = [
                "sh",
                "-c",
                (
                    f"echo {shlex.quote(chrony_conf)} "
                    "| sudo tee /etc/chrony/chrony.conf > /dev/null "
                    "&& sudo systemctl restart chrony"
                ),
            ]
            write = ssh.run(write_cmd, timeout=30)
            report["chrony_configured"] = write.returncode == 0
            if write.returncode != 0:
                raise RuntimeError(f"chrony config/restart failed: {write.stderr.strip()}")

            # 3. Verify drift with a fresh date +%s read.
            date_res = ssh.run(["date", "+%s"], timeout=10)
            if date_res.returncode == 0:
                robot_epoch = float(date_res.stdout.strip())
                local_epoch = _now_utc().timestamp()
                report["drift_seconds"] = local_epoch - robot_epoch

            # 4. Kick Create3 NTP restart (HTTP REST, runs from the robot).
            create3 = ssh.run(
                [
                    "curl",
                    "-s",
                    "-m",
                    "10",
                    "-X",
                    "POST",
                    "http://192.168.186.2/api/restart-ntpd",
                ],
                timeout=15,
            )
            failure_markers = ("fail", "error", "refused")
            report["create3_ntp_restarted"] = create3.returncode == 0 and not any(
                m in create3.stdout.lower() for m in failure_markers
            )

        return report

    def build(self) -> None:
        """Run ``colcon build --packages-select campus_nav_llm`` in the workspace."""
        result = run_local(
            [
                "colcon",
                "build",
                "--packages-select",
                "campus_nav_llm",
                "--symlink-install",
            ],
            timeout=600,
            cwd=self.workspace_dir,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"colcon build failed (rc={result.returncode}): {result.stderr.strip()}"
            )

    def launch(self, pid_path: Path | None = None) -> None:
        """Start ``ros2 launch campus_nav_llm navigation_mode.launch.py`` in the background.

        Writes the launcher PID to ``pid_path`` (defaults to
        ``/tmp/robobench_launch.pid``) so ``shutdown()`` can find it later.
        """
        proc = subprocess.Popen(  # noqa: S603 — controlled cmd list
            [
                "ros2",
                "launch",
                "campus_nav_llm",
                "navigation_mode.launch.py",
                f"namespace:={self.namespace}",
            ]
        )
        target = pid_path if pid_path is not None else Path("/tmp/robobench_launch.pid")
        target.write_text(f"{proc.pid}\n")

    def activate_lifecycle(self) -> None:
        raise NotImplementedError("Phase B: wraps lifecycle_activator")

    def set_initial_pose(self, x: float, y: float, theta: float) -> None:
        raise NotImplementedError("Phase B: extract from deploy.sh step 7")

    def health_check(self) -> dict:
        raise NotImplementedError("Phase B: extract from deploy.sh step 9")

    def shutdown(self) -> None:
        raise NotImplementedError("Phase B: wraps stop.sh")
