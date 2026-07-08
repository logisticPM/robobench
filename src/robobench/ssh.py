"""Thin wrapper around paramiko for robot SSH operations.

Why a wrapper? Tests mock ``SSHClient`` instead of poking at paramiko's
internals. Real code uses the same boring interface — ``with SSHClient(...) as c:
result = c.run([...])`` — regardless of whether keys, passwords, or agents are
in play later.
"""

from __future__ import annotations

import pathlib
import re
import shlex
from dataclasses import dataclass
from types import TracebackType

import paramiko


@dataclass(frozen=True)
class SSHResult:
    """Outcome of one remote command."""

    returncode: int
    stdout: str
    stderr: str


class SSHClient:
    """Single-connection SSH helper for one robot.

    Use as a context manager so the connection is closed deterministically::

        with SSHClient(host, user, password) as c:
            result = c.run(["date", "+%s"], timeout=5.0)
    """

    def __init__(self, host: str, user: str, password: str, port: int = 22) -> None:
        self.host = host
        self.user = user
        self._password = password
        self.port = port
        self._client: paramiko.SSHClient | None = None

    def __enter__(self) -> SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self._password,
                timeout=10,
                allow_agent=False,
                look_for_keys=False,
            )
        except (paramiko.SSHException, OSError) as exc:
            raise RuntimeError(f"SSH connect to {self.host}:{self.port} failed: {exc}") from exc
        self._client = client
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def run(self, cmd: list[str], timeout: float) -> SSHResult:
        """Run a command on the robot and return its outcome."""
        if self._client is None:
            raise RuntimeError("SSHClient not connected; use as a context manager")
        joined = shlex.join(cmd)
        try:
            _stdin, stdout, stderr = self._client.exec_command(joined, timeout=timeout)
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
        except (paramiko.SSHException, OSError) as exc:
            # Channel dropped/timed out mid-command. Surface a clean RuntimeError
            # (matching __enter__) instead of a raw paramiko/socket traceback.
            raise RuntimeError(f"SSH command on {self.host} failed: {exc}") from exc
        return SSHResult(returncode=rc, stdout=out, stderr=err)

    def put_text(self, remote_path: str, content: str) -> None:
        """Write a text file to the robot via SFTP."""
        if self._client is None:
            raise RuntimeError("SSHClient not connected; use as a context manager")
        sftp = self._client.open_sftp()
        try:
            with sftp.open(remote_path, "w") as f:
                f.write(content)
        finally:
            sftp.close()


def check_workstation_chrony_config(
    conf_path: pathlib.Path | str = "/etc/chrony/chrony.conf",
) -> dict:
    """Check the workstation's chrony.conf has the lines required to serve the robot.

    The robot's chrony follows the workstation as its NTP server. For that to
    work, the workstation must:
      1. Allow the robot's subnet (``allow 192.168.0.0/16`` or similar)
      2. Advertise a local stratum so chrony will serve time even without
         upstream sync (``local stratum 10``)

    Returns a structured dict::

        {
          "status": "OK" | "WARN" | "SKIPPED",
          "has_allow": bool,           # not present if SKIPPED
          "has_local_stratum": bool,   # not present if SKIPPED
          "hint": str,                 # present on WARN
          "reason": str,               # present on SKIPPED
        }

    SKIPPED indicates chrony.conf was not found — either the workstation has no
    chrony installed (Windows, or a minimal Linux), or the path is non-standard.
    Callers should treat SKIPPED as "user needs to verify manually".
    """
    path = pathlib.Path(conf_path)
    if not path.exists():
        return {
            "status": "SKIPPED",
            "reason": f"chrony.conf not found at {path}; install chrony or pass conf_path=",
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    has_allow = bool(re.search(r"^\s*allow\s+192\.168", text, re.MULTILINE))
    has_local_stratum = bool(re.search(r"^\s*local\s+stratum\s+\d+", text, re.MULTILINE))
    if has_allow and has_local_stratum:
        return {"status": "OK", "has_allow": True, "has_local_stratum": True}
    return {
        "status": "WARN",
        "has_allow": has_allow,
        "has_local_stratum": has_local_stratum,
        "hint": (
            "Add the following lines to /etc/chrony/chrony.conf and run "
            "'sudo systemctl restart chrony':\n"
            "    allow 192.168.0.0/16\n"
            "    local stratum 10"
        ),
    }
