"""Tests for TurtleBot4Adapter."""

from __future__ import annotations

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
