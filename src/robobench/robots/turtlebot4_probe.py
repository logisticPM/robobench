"""TurtleBot4 probe: reads bring-up health into a RobotState.

Fixes the upstream's fragile detection:
- structured parsing (no string-match on HTML, no buggy backslash topic name)
- odom requires TWO consecutive good samples (one message then stall != healthy)
- ROS env (ROS_SUPER_CLIENT=True) is set for every remote ros2 call
"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable
from datetime import UTC, datetime

from robobench._process import ProcessResult
from robobench._process import run_local as _rl_default
from robobench.recovery.probe import RobotProbe
from robobench.recovery.state import RobotState
from robobench.ssh import SSHClient

_CLOCK_TOLERANCE_S = 2.0
_ROS_ENV = "source /etc/turtlebot4/setup.bash && export ROS_SUPER_CLIENT=True && "


def _ping_cmd(ip: str, platform: str) -> list[str]:
    """One-shot ping with ~2s wait: Windows takes -n/-w (ms), POSIX -c/-W (s)."""
    if platform.startswith("win"):
        return ["ping", "-n", "1", "-w", "2000", ip]
    return ["ping", "-c", "1", "-W", "2", ip]


def _ping_succeeded(result: ProcessResult, platform: str) -> bool:
    """Windows ping exits 0 even for 'Destination host unreachable' replies
    (the gateway answered), so success there also requires a TTL= in stdout.
    POSIX ping exit codes are trustworthy."""
    if result.returncode != 0:
        return False
    if platform.startswith("win"):
        return "ttl=" in result.stdout.lower()
    return True


def _default_ping(ip: str) -> bool:
    result = _rl_default(_ping_cmd(ip, sys.platform), timeout=5)
    return _ping_succeeded(result, sys.platform)


class TurtleBot4Probe(RobotProbe):
    """Builds a RobotState from SSH + local checks against a TurtleBot4."""

    def __init__(
        self,
        ip: str,
        ssh_user: str,
        ssh_pass: str,
        namespace: str,
        *,
        discovery_port: int = 11811,
        ssh_factory: Callable[..., SSHClient] = SSHClient,
        run_local=None,
        ping: Callable[[str], bool] | None = None,
    ) -> None:
        self.ip = ip
        self.ssh_user = ssh_user
        self.ssh_pass = ssh_pass
        self.namespace = namespace
        self.discovery_port = discovery_port
        self._ssh_factory = ssh_factory
        self._run_local = run_local if run_local is not None else _rl_default
        self._ping = ping or _default_ping

    def _now(self) -> float:
        return datetime.now(tz=UTC).timestamp()

    def read(self) -> RobotState:
        """Full bring-up read (includes the odom 2-sample stability check)."""
        return self._read(check_odom=True)

    def read_connectivity(self) -> RobotState:
        """Lite read for the dashboard: the five transport layers, no odom echo.

        ``odom_publishing`` is set ``True`` as a documented sentinel meaning "not
        checked here" — the connectivity panel never reads it (the sensor panel
        owns liveness). Each cycle finishes in a few seconds instead of ~30s.
        """
        return self._read(check_odom=False)

    def _read(self, *, check_odom: bool) -> RobotState:
        if not self._ping(self.ip):
            return RobotState(
                rpi_reachable=False,
                discovery_server_ok=False,
                clock_synced=False,
                create3_topics=0,
                tb4_nodes_present=False,
                odom_publishing=False,
            )

        with self._ssh_factory(self.ip, self.ssh_user, self.ssh_pass) as ssh:
            ds = ssh.run(
                ["sh", "-c", f"ss -ulnp | grep ':{self.discovery_port}' | wc -l"],
                timeout=10,
            )
            discovery_ok = ds.returncode == 0 and _parse_int(ds.stdout) > 0

            dt = ssh.run(["date", "+%s"], timeout=10)
            clock_synced = False
            if dt.returncode == 0:
                drift = abs(self._now() - _parse_float(dt.stdout))
                clock_synced = drift <= _CLOCK_TOLERANCE_S

            ns_pat = shlex.quote(f"/{self.namespace}/")
            tc = ssh.run(
                ["sh", "-c", f"{_ROS_ENV}ros2 topic list | grep -c {ns_pat}"],
                timeout=20,
            )
            create3_topics = _parse_int(tc.stdout) if tc.returncode == 0 else 0

            nodes = ssh.run(
                ["sh", "-c", f"{_ROS_ENV}ros2 node list | grep {ns_pat}"],
                timeout=20,
            )
            tb4_nodes_present = nodes.returncode == 0 and bool(nodes.stdout.strip())

            odom_publishing = self._odom_stable(ssh) if check_odom else True

        return RobotState(
            rpi_reachable=True,
            discovery_server_ok=discovery_ok,
            clock_synced=clock_synced,
            create3_topics=create3_topics,
            tb4_nodes_present=tb4_nodes_present,
            odom_publishing=odom_publishing,
        )

    def _odom_stable(self, ssh: SSHClient) -> bool:
        odom_topic = shlex.quote(f"/{self.namespace}/odom")
        cmd = [
            "sh",
            "-c",
            f"{_ROS_ENV}timeout 8 ros2 topic echo {odom_topic} --once",
        ]
        for _ in range(2):
            r = ssh.run(cmd, timeout=15)
            ok = r.returncode == 0 and any(
                tok in r.stdout for tok in ("position:", "pose:", "header:")
            )
            if not ok:
                return False
        return True


def _parse_int(text: str) -> int:
    """Parse the last non-empty line as an int; 0 on failure (defensive —
    the upstream crashed on a trailing warning line)."""
    for raw_line in reversed(text.strip().splitlines()):
        stripped_line = raw_line.strip()
        if stripped_line:
            try:
                return int(stripped_line)
            except ValueError:
                return 0
    return 0


def _parse_float(text: str) -> float:
    try:
        return float(text.strip().splitlines()[-1].strip())
    except (ValueError, IndexError):
        return 0.0
