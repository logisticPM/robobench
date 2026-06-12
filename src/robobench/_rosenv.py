"""Shared ROS2-availability guard.

robobench's pure logic must import without ROS2. Modules that genuinely need
rclpy call require_rclpy() at runtime so the import-time surface stays clean
and the "you need ROS2" error is consistent and actionable.
"""

from __future__ import annotations


def require_rclpy() -> None:
    """Raise a clear RuntimeError if rclpy can't be imported."""
    try:
        import rclpy  # noqa: F401, PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "this command requires ROS2 (rclpy). source /opt/ros/<distro>/setup.bash, then retry."
        ) from exc
