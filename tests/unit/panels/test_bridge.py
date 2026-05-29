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
