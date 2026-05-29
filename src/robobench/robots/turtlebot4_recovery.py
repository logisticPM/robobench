"""TurtleBot4 atomic recovery actions.

Each action is idempotent (safe to call when already healthy). Commands are
the ones the upstream proved work on real hardware — but here each is a
single small action the engine composes, NOT a fixed chain.

(A `build_turtlebot4_recovery` factory is added in Task D8.)
"""

from __future__ import annotations

from collections.abc import Callable

from robobench._process import run_local
from robobench.recovery.actions import RecoveryActions
from robobench.ssh import SSHClient

_CREATE3_IP = "192.168.186.2"


class TurtleBot4RecoveryActions(RecoveryActions):
    """Idempotent atomic fixes for a TurtleBot4 (Create3 + RPi)."""

    def __init__(
        self,
        ip: str,
        ssh_user: str,
        ssh_pass: str,
        namespace: str,
        *,
        ssh_factory: Callable[..., SSHClient] = SSHClient,
        run_local_func=None,
    ) -> None:
        self.ip = ip
        self.ssh_user = ssh_user
        self.ssh_pass = ssh_pass
        self.namespace = namespace
        self._ssh_factory = ssh_factory
        if run_local_func is None:
            run_local_func = run_local
        self._run_local = run_local_func

    def _ssh(self, cmd: list[str], timeout: float) -> None:
        with self._ssh_factory(self.ip, self.ssh_user, self.ssh_pass) as ssh:
            ssh.run(cmd, timeout=timeout)

    def restart_local_daemon(self) -> None:
        self._run_local(["ros2", "daemon", "stop"], timeout=10)
        self._run_local(["ros2", "daemon", "start"], timeout=10)

    def restart_discovery_server(self) -> None:
        # Kill zombies, clean DDS shared memory, restart the systemd unit.
        self._ssh(
            [
                "sh",
                "-c",
                "sudo systemctl stop discovery.service 2>/dev/null; "
                "sudo killall -9 fast-discovery-server fastdds 2>/dev/null; "
                "sudo rm -rf /dev/shm/fastrtps_* /dev/shm/fast_datasharing* 2>/dev/null; "
                "sudo systemctl start discovery.service",
            ],
            timeout=30,
        )

    def sync_clock(self) -> None:
        self._ssh(["sudo", "chronyc", "-a", "makestep"], timeout=15)

    def restart_tb4_service(self) -> None:
        self._ssh(["sudo", "systemctl", "restart", "turtlebot4.service"], timeout=20)

    def restart_create3_app(self) -> None:
        self._ssh(
            ["curl", "-s", "-m", "15", "-X", "POST", f"http://{_CREATE3_IP}/api/restart-app"],
            timeout=20,
        )

    def reboot_create3(self) -> None:
        self._ssh(
            ["curl", "-s", "-m", "15", "-X", "POST", f"http://{_CREATE3_IP}/api/reboot"],
            timeout=25,
        )
