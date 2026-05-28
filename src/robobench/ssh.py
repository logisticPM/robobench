"""Thin wrapper around paramiko for robot SSH operations.

Why a wrapper? Tests mock ``SSHClient`` instead of poking at paramiko's
internals. Real code uses the same boring interface — ``with SSHClient(...) as c:
result = c.run([...])`` — regardless of whether keys, passwords, or agents are
in play later.
"""

from __future__ import annotations

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
        except paramiko.SSHException as exc:
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
        _stdin, stdout, stderr = self._client.exec_command(joined, timeout=timeout)
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
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
