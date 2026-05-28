"""Tests for robobench.ssh."""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import paramiko
import pytest

from robobench.ssh import SSHClient, SSHResult, check_workstation_chrony_config

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


def test_check_workstation_chrony_ok_when_required_lines_present(tmp_path: pathlib.Path):
    """When chrony.conf has both 'allow' for 192.168.* and 'local stratum N', returns OK."""
    conf = tmp_path / "chrony.conf"
    conf.write_text("server pool.ntp.org iburst\nallow 192.168.0.0/16\nlocal stratum 10\n")
    report = check_workstation_chrony_config(conf_path=conf)
    assert report["status"] == "OK"
    assert report["has_allow"] is True
    assert report["has_local_stratum"] is True


def test_check_workstation_chrony_warns_when_missing_lines(tmp_path: pathlib.Path):
    """Missing 'allow' or 'local stratum' yields WARN with actionable hint."""
    conf = tmp_path / "chrony.conf"
    conf.write_text("server pool.ntp.org iburst\n")
    report = check_workstation_chrony_config(conf_path=conf)
    assert report["status"] == "WARN"
    assert report["has_allow"] is False
    assert report["has_local_stratum"] is False
    assert "allow 192.168" in report["hint"]


def test_check_workstation_chrony_skips_when_no_chrony(tmp_path: pathlib.Path):
    """If the chrony.conf path doesn't exist (Windows or chrony not installed),
    return SKIPPED with a clear reason."""
    report = check_workstation_chrony_config(conf_path=tmp_path / "absent.conf")
    assert report["status"] == "SKIPPED"
    assert "chrony.conf" in report["reason"]
