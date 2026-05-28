"""Tests for robobench.ssh."""

from __future__ import annotations

from unittest.mock import MagicMock

import paramiko
import pytest

from robobench.ssh import SSHClient, SSHResult

# Exit code constant for "command not found"
COMMAND_NOT_FOUND = 127


def test_sshclient_run_returns_stdout_and_returncode(mocker):
    """A successful run returns SSHResult with rc=0 and stdout."""
    fake_client = MagicMock()
    fake_stdout = MagicMock()
    fake_stdout.read.return_value = b"1748347205\n"
    fake_stdout.channel.recv_exit_status.return_value = 0
    fake_stderr = MagicMock()
    fake_stderr.read.return_value = b""
    fake_client.exec_command.return_value = (MagicMock(), fake_stdout, fake_stderr)

    mocker.patch("robobench.ssh.paramiko.SSHClient", return_value=fake_client)

    with SSHClient("192.168.50.31", "ubuntu", "turtlebot4") as client:
        result = client.run(["date", "+%s"], timeout=5.0)

    assert isinstance(result, SSHResult)
    assert result.returncode == 0
    assert result.stdout == "1748347205\n"
    assert result.stderr == ""


def test_sshclient_run_nonzero_returncode_is_preserved(mocker):
    """A nonzero exit is returned, not raised."""
    fake_client = MagicMock()
    fake_stdout = MagicMock()
    fake_stdout.read.return_value = b""
    fake_stdout.channel.recv_exit_status.return_value = COMMAND_NOT_FOUND
    fake_stderr = MagicMock()
    fake_stderr.read.return_value = b"command not found\n"
    fake_client.exec_command.return_value = (MagicMock(), fake_stdout, fake_stderr)
    mocker.patch("robobench.ssh.paramiko.SSHClient", return_value=fake_client)

    with SSHClient("192.168.50.31", "ubuntu", "turtlebot4") as client:
        result = client.run(["nope"], timeout=5.0)

    assert result.returncode == COMMAND_NOT_FOUND
    assert "command not found" in result.stderr


def test_sshclient_connect_failure_raises_runtime_error(mocker):
    """A paramiko connect error becomes a RuntimeError with the host in the message."""
    fake_client = MagicMock()
    fake_client.connect.side_effect = paramiko.SSHException("auth failed")
    mocker.patch("robobench.ssh.paramiko.SSHClient", return_value=fake_client)

    with pytest.raises(RuntimeError, match="192.168.50.31"):  # noqa: SIM117
        with SSHClient("192.168.50.31", "ubuntu", "wrong-pass"):
            pass


def test_sshclient_put_text_writes_via_sftp(mocker):
    """put_text opens an SFTP channel and writes the bytes."""
    fake_client = MagicMock()
    fake_sftp = MagicMock()
    fake_file = MagicMock()
    fake_sftp.open.return_value.__enter__.return_value = fake_file
    fake_client.open_sftp.return_value = fake_sftp
    mocker.patch("robobench.ssh.paramiko.SSHClient", return_value=fake_client)

    with SSHClient("192.168.50.31", "ubuntu", "turtlebot4") as client:
        client.put_text("/tmp/x.conf", "hello\n")

    fake_sftp.open.assert_called_once_with("/tmp/x.conf", "w")
    fake_file.write.assert_called_once_with("hello\n")
