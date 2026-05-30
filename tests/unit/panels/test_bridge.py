"""Smoke tests for the diagnostic bridge.

The bridge is a ROS2 node — its substantive behavior is exercised only with a
real robot (``@pytest.mark.hardware``). The unit suite verifies the module
imports without ROS2 and that the rclpy-dependent entry point fails with a
clear message when ROS2 is missing.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_module_imports_without_ros2():
    """The bridge module imports successfully without ROS2 installed."""
    import robobench.panels.bridge  # noqa: F401, PLC0415


def test_run_bridge_raises_clear_error_without_ros2():
    """run_bridge raises RuntimeError mentioning ROS2 when rclpy is missing."""
    from robobench.panels.bridge import run_bridge  # noqa: PLC0415
    from robobench.panels.state import DiagnosticState  # noqa: PLC0415

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "rclpy" or name.startswith("rclpy."):
            raise ImportError("No module named 'rclpy'")
        return real_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=fake_import),
        pytest.raises(RuntimeError, match="ROS2"),
    ):
        run_bridge(DiagnosticState(), namespace="ns")


def test_dds_env_builds_discovery_server_vars():
    from robobench.panels.bridge import dds_env  # noqa: PLC0415

    env = dds_env("192.168.50.31:11811")
    assert env["ROS_DISCOVERY_SERVER"] == "192.168.50.31:11811"
    assert env["RMW_IMPLEMENTATION"] == "rmw_fastrtps_cpp"
    assert env["ROS_SUPER_CLIENT"] == "True"


def test_clock_offset_from_stamp_positive_when_robot_behind():
    """offset = now - stamp; robot stamp older than local now => positive
    (matches check_clock_offset's 'positive = robot behind' convention)."""
    from robobench.panels.bridge import clock_offset_from_stamp  # noqa: PLC0415

    assert clock_offset_from_stamp(now_s=1000.0, stamp_s=995.0) == 5.0  # noqa: PLR2004


def test_clock_offset_from_stamp_negative_when_robot_ahead():
    from robobench.panels.bridge import clock_offset_from_stamp  # noqa: PLC0415

    assert clock_offset_from_stamp(now_s=1000.0, stamp_s=1003.0) == -3.0  # noqa: PLR2004
