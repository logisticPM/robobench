"""TurtleBot4 adapter — the reference implementation of ``RobotAdapter``.

v0.1 implements only ``check_clock_offset``. Remaining methods raise
``NotImplementedError`` and will be filled in across subsequent plans
(Phase B: extract from upstream ``deploy.sh``).
"""

from __future__ import annotations

import math
import shlex
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from robobench._process import run_local
from robobench.adapter_base import RobotAdapter
from robobench.ssh import SSHClient, check_workstation_chrony_config


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
    workspace_dir: str | None = None
    build_packages: list[str] = field(default_factory=lambda: ["campus_nav_llm"])
    launch_package: str = "campus_nav_llm"
    launch_file: str = "navigation_mode.launch.py"
    user_input_topic: str = "/user_input"

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

    def setup_clock_sync(
        self,
        workstation_ip: str,
        *,
        settle_s: float = 3.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> dict:
        """Configure chrony on the robot to follow the workstation; restart Create3 NTP.

        Returns a structured report dict. Mirrors upstream ``deploy.sh`` Step 1
        without the human-friendly logging.
        """
        report: dict = {
            "workstation_chrony": None,
            "chrony_installed": False,
            "chrony_configured": False,
            "create3_ntp_restarted": False,
            "drift_seconds": None,
        }
        report["workstation_chrony"] = check_workstation_chrony_config()

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

            # Force chrony to step the clock now and let it settle, so the drift
            # we read next reflects the synced time (chrony needs a few seconds to
            # contact the source and step — otherwise drift shows the pre-sync gap).
            ssh.run(["sudo", "chronyc", "-a", "makestep"], timeout=15)
            sleep(settle_s)

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
        if self.workspace_dir is None:
            raise ValueError(
                "workspace_dir is required for build(); set it in config.yaml "
                "under workspace.dir or pass workspace_dir=... to the adapter."
            )
        result = run_local(
            [
                "colcon",
                "build",
                "--packages-select",
                *self.build_packages,
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
                self.launch_package,
                self.launch_file,
                f"namespace:={self.namespace}",
            ]
        )
        target = pid_path if pid_path is not None else Path("/tmp/robobench_launch.pid")
        target.write_text(f"{proc.pid}\n")

    def activate_lifecycle(
        self, map_yaml: str | None = None, *, initial_pose: tuple[float, float, float] | None = None
    ) -> None:
        """Configure+activate all Nav2 nodes via the persistent activator.

        On activator failure, fall back to per-node ``ros2 lifecycle set``
        (configure then activate), mirroring upstream deploy.sh. Raises only if
        the fallback also fails to activate any node.
        """
        if map_yaml is None:
            raise ValueError("activate_lifecycle requires map_yaml path")
        cmd = [
            "robobench-lifecycle-activator",
            "--namespace",
            self.namespace,
            "--map-yaml",
            map_yaml,
        ]
        if initial_pose is not None:
            x, y, yaw = initial_pose
            cmd += ["--initial-pose-x", str(x), "--initial-pose-y", str(y), "--initial-pose-yaw", str(yaw)]
        result = run_local(cmd, timeout=180)
        if result.returncode == 0:
            return

        # Fallback: manual CLI activation, node by node.
        any_ok = False
        for node in self._LIFECYCLE_NODES:
            target = f"/{self.namespace}/{node}"
            configure = run_local(["ros2", "lifecycle", "set", target, "configure"], timeout=30)
            if configure.returncode != 0:
                continue
            activate = run_local(["ros2", "lifecycle", "set", target, "activate"], timeout=30)
            if activate.returncode == 0:
                any_ok = True
        if not any_ok:
            raise RuntimeError(
                f"lifecycle activation failed (activator rc={result.returncode}); "
                f"CLI fallback could not activate any node: {result.stderr.strip()}"
            )

    def set_initial_pose(self, x: float, y: float, theta: float) -> None:
        """Publish an AMCL initial pose at (x, y, theta) once."""
        qz = math.sin(theta / 2.0)
        qw = math.cos(theta / 2.0)
        msg = (
            "{header: {frame_id: 'map'}, "
            f"pose: {{pose: {{position: {{x: {x}, y: {y}, z: 0.0}}, "
            f"orientation: {{x: 0.0, y: 0.0, z: {qz}, w: {qw}}}}}, "
            "covariance: [0.25, 0, 0, 0, 0, 0,  0, 0.25, 0, 0, 0, 0,  "
            "0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0,  "
            "0, 0, 0, 0, 0, 0.06853892326654787]}}"
        )
        result = run_local(
            [
                "ros2",
                "topic",
                "pub",
                "--once",
                f"/{self.namespace}/initialpose",
                "geometry_msgs/msg/PoseWithCovarianceStamped",
                msg,
            ],
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(f"set_initial_pose publish failed: {result.stderr.strip()}")

    _CLOCK_OK = 2.0
    _CLOCK_WARN = 10.0

    def health_check(self) -> dict:
        """Return a structured health report.

        Schema::

            {
              "checks": {
                "clock_offset": {"status": "OK"|"WARN"|"FAIL", "value": float, "unit": "s"},
                "amcl_pose": {"status": "OK"|"FAIL", "detail": str},
                "navigate_to_pose_action": {"status": "OK"|"FAIL"},
                "nav_subscribers": {"status": "OK"|"FAIL", "count": int},
              },
              "overall": "HEALTHY"|"DEGRADED"|"UNHEALTHY",
            }
        """
        checks: dict[str, dict] = {}

        # 1. Clock offset
        try:
            offset = self.check_clock_offset()
            abs_offset = abs(offset)
            if abs_offset < self._CLOCK_OK:
                status = "OK"
            elif abs_offset < self._CLOCK_WARN:
                status = "WARN"
            else:
                status = "FAIL"
            checks["clock_offset"] = {"status": status, "value": offset, "unit": "s"}
        except RuntimeError as exc:
            checks["clock_offset"] = {"status": "FAIL", "detail": str(exc)}

        # 2. AMCL publishing
        amcl_topic = f"/{self.namespace}/amcl_pose"
        amcl = run_local(["ros2", "topic", "echo", "--once", amcl_topic], timeout=15)
        checks["amcl_pose"] = {
            "status": "OK" if amcl.returncode == 0 else "FAIL",
            "detail": "publishing" if amcl.returncode == 0 else "no pose in 15s",
        }

        # 3. navigate_to_pose action server visible
        actions = run_local(["ros2", "action", "list"], timeout=10)
        nav_action = f"/{self.namespace}/navigate_to_pose"
        action_ok = actions.returncode == 0 and nav_action in actions.stdout
        checks["navigate_to_pose_action"] = {
            "status": "OK" if action_ok else "FAIL",
        }

        # 4. /user_input has at least one subscriber
        info = run_local(["ros2", "topic", "info", self.user_input_topic], timeout=10)
        sub_count = 0
        for line in info.stdout.splitlines():
            if line.strip().startswith("Subscription count:"):
                try:
                    sub_count = int(line.split(":", 1)[1].strip())
                except ValueError:
                    sub_count = 0
                break
        checks["nav_subscribers"] = {
            "status": "OK" if sub_count > 0 else "FAIL",
            "count": sub_count,
        }

        # Overall
        if any(c["status"] == "FAIL" for c in checks.values()):
            overall = "UNHEALTHY"
        elif any(c["status"] == "WARN" for c in checks.values()):
            overall = "DEGRADED"
        else:
            overall = "HEALTHY"

        return {"checks": checks, "overall": overall}

    _LIFECYCLE_NODES = (
        "map_server",
        "amcl",
        "controller_server",
        "planner_server",
        "behavior_server",
        "bt_navigator",
        "velocity_smoother",
    )

    _PKILL_PATTERNS = (
        "navigation_mode.launch",
        "lifecycle_manager",
        "lifecycle_activator",
        "/map_server ",
        "/amcl ",
        "/controller_server ",
        "/planner_server ",
        "/behavior_server ",
        "/bt_navigator ",
        "/waypoint_follower ",
        "/velocity_smoother ",
        "task_executor",
        "llm_planner",
        "odom_tf_publisher",
    )

    def shutdown(
        self,
        pid_path: Path | None = None,
        *,
        settle_s: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Stop the navigation stack gracefully.

        SIGTERM first (lets on_shutdown handlers release FastDDS shared memory),
        wait ``settle_s``, then SIGKILL stragglers. Cleans /dev/shm FastDDS
        segments and restarts the ros2 daemon so the next bring-up starts clean.
        Refs: rclcpp#1704 (SIGTERM since Humble), FastDDS#2790 (SIGKILL leaks shm).
        """
        target = pid_path if pid_path is not None else Path("/tmp/robobench_launch.pid")

        # 1. Zero velocity, in case the robot is moving.
        run_local(
            [
                "ros2",
                "topic",
                "pub",
                "--once",
                f"/{self.namespace}/cmd_vel",
                "geometry_msgs/msg/Twist",
                "{linear: {x: 0.0}, angular: {z: 0.0}}",
            ],
            timeout=5.0,
        )

        # 2. Kill the recorded launcher PID, if present.
        if target.exists():
            try:
                pid = int(target.read_text().strip())
                run_local(["kill", str(pid)], timeout=2.0)
            except (ValueError, OSError):
                pass
            target.unlink(missing_ok=True)

        # 3. Graceful SIGTERM to all known nav-stack patterns.
        for pattern in self._PKILL_PATTERNS:
            run_local(["pkill", "-TERM", "-f", pattern], timeout=2.0)

        # 4. Wait, then SIGKILL anything still alive.
        sleep(settle_s)
        for pattern in self._PKILL_PATTERNS:
            run_local(["pkill", "-9", "-f", pattern], timeout=2.0)

        # 5. Release FastDDS shared memory (best-effort) and refresh the daemon.
        run_local(["fastdds", "shm", "clean"], timeout=10.0)
        run_local(["ros2", "daemon", "stop"], timeout=10.0)
        run_local(["ros2", "daemon", "start"], timeout=10.0)
