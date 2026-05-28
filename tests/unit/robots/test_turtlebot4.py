"""Tests for TurtleBot4Adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from robobench.adapter_base import RobotAdapter
from robobench.robots.turtlebot4 import TurtleBot4Adapter


def test_turtlebot4_adapter_is_a_robot_adapter():
    """Sanity check: the concrete class extends the ABC."""
    assert issubclass(TurtleBot4Adapter, RobotAdapter)


def test_turtlebot4_adapter_instantiates_with_required_fields():
    """Constructor accepts ip, ssh user/pass, namespace, workspace_dir."""
    adapter = TurtleBot4Adapter(
        ip="192.168.50.31",
        ssh_user="ubuntu",
        ssh_pass="turtlebot4",
        namespace="turtlebot468",
        workspace_dir="~/CS5335TurtleBot",
    )
    assert adapter.ip == "192.168.50.31"
    assert adapter.namespace == "turtlebot468"


@pytest.mark.parametrize(
    "method,args",
    [
        ("build", ()),
        ("launch", ()),
        ("activate_lifecycle", ()),
        ("set_initial_pose", (1.0, 2.0, 0.0)),
        ("health_check", ()),
        ("shutdown", ()),
    ],
)
def test_unimplemented_methods_raise_not_implemented(method, args):
    """v0.1 only implements check_clock_offset; the rest signal not-yet-done."""
    adapter = TurtleBot4Adapter(
        ip="192.168.50.31",
        ssh_user="ubuntu",
        ssh_pass="turtlebot4",
        namespace="turtlebot468",
        workspace_dir="~/CS5335TurtleBot",
    )
    with pytest.raises(NotImplementedError):
        getattr(adapter, method)(*args)


def _adapter():
    return TurtleBot4Adapter(
        ip="192.168.50.31",
        ssh_user="ubuntu",
        ssh_pass="turtlebot4",
        namespace="turtlebot468",
        workspace_dir="~/CS5335TurtleBot",
    )


def test_check_clock_offset_returns_seconds(mocker):
    """Opens SSH to the robot, reads epoch via `date +%s`, subtracts from local time."""
    fake_local = datetime(2026, 5, 27, 12, 0, 10, tzinfo=UTC)
    mocker.patch("robobench.robots.turtlebot4._now_utc", return_value=fake_local)

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.run.return_value = MagicMock(returncode=0, stdout="1779883205\n", stderr="")
    sshclient_ctor = mocker.patch("robobench.robots.turtlebot4.SSHClient", return_value=fake_client)

    offset = _adapter().check_clock_offset()

    assert offset == pytest.approx(5.0, abs=0.01)
    sshclient_ctor.assert_called_once_with("192.168.50.31", "ubuntu", "turtlebot4")
    fake_client.run.assert_called_once_with(["date", "+%s"], timeout=10)


def test_check_clock_offset_raises_on_ssh_failure(mocker):
    """A non-zero remote exit becomes a RuntimeError with stderr in the message."""
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.run.return_value = MagicMock(
        returncode=127,
        stdout="",
        stderr="bash: date: command not found",
    )
    mocker.patch("robobench.robots.turtlebot4.SSHClient", return_value=fake_client)

    with pytest.raises(RuntimeError, match="date: command not found"):
        _adapter().check_clock_offset()
