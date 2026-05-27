"""Tests for TurtleBot4Adapter."""

from __future__ import annotations

import subprocess
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
    """SSHs to the robot, reads epoch seconds, subtracts from local time."""
    fake_local = datetime(2026, 5, 27, 12, 0, 10, tzinfo=UTC)
    mocker.patch(
        "robobench.robots.turtlebot4._now_utc",
        return_value=fake_local,
    )
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "1779883205\n"
    completed.stderr = ""
    run_mock = mocker.patch("robobench.robots.turtlebot4.subprocess.run", return_value=completed)

    offset = _adapter().check_clock_offset()

    assert offset == pytest.approx(5.0, abs=0.01)
    args, kwargs = run_mock.call_args
    assert args[0][0] == "sshpass"
    assert "ssh" in args[0]
    assert "ubuntu@192.168.50.31" in args[0]


def test_check_clock_offset_raises_on_ssh_failure(mocker):
    """A non-zero SSH exit becomes a RuntimeError with stderr in the message."""
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 255
    completed.stdout = ""
    completed.stderr = "ssh: connect to host 192.168.50.31 port 22: No route to host"
    mocker.patch("robobench.robots.turtlebot4.subprocess.run", return_value=completed)

    with pytest.raises(RuntimeError, match="No route to host"):
        _adapter().check_clock_offset()
