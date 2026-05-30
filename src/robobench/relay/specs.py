"""Pure (rclpy-free) relay specs + DDS env helpers.

The relay needs one DDS context with NO Discovery-Server env vars (Simple
Discovery) and one WITH them. Everything here imports without ROS2 so it's
unit-testable; the rclpy wiring lives in runner.py.
"""

from __future__ import annotations

from dataclasses import dataclass

# Symbolic QoS names; runner.py maps these to real rclpy QoSProfile objects.
QOS_SENSOR = "sensor"  # depth 10, BEST_EFFORT
QOS_RELIABLE = "reliable"  # depth 10, RELIABLE
QOS_TF_STATIC = "tf_static"  # depth 10, RELIABLE, TRANSIENT_LOCAL

# DDS env vars that must be absent to build a Simple-Discovery context.
_DISCOVERY_ENV_VARS = (
    "ROS_DISCOVERY_SERVER",
    "ROS_SUPER_CLIENT",
    "FASTRTPS_DEFAULT_PROFILES_FILE",
)


@dataclass(frozen=True)
class BridgeSpec:
    """One topic to relay between the two DDS graphs.

    direction "ds_to_sd": robot (Discovery Server) -> local (Simple Discovery).
    direction "sd_to_ds": local (Simple) -> robot (Discovery Server).
    """

    topic: str
    msg_type: str  # "pkg/msg/Name" — runner imports the class
    qos: str  # one of QOS_*
    direction: str  # "ds_to_sd" | "sd_to_ds"


def bridge_specs(namespace: str) -> list[BridgeSpec]:
    """Standard TurtleBot4 relay set for a namespace."""
    ns = namespace.strip("/")
    return [
        BridgeSpec(f"/{ns}/odom", "nav_msgs/msg/Odometry", QOS_SENSOR, "ds_to_sd"),
        BridgeSpec(f"/{ns}/scan", "sensor_msgs/msg/LaserScan", QOS_SENSOR, "ds_to_sd"),
        BridgeSpec(f"/{ns}/imu", "sensor_msgs/msg/Imu", QOS_SENSOR, "ds_to_sd"),
        BridgeSpec(f"/{ns}/tf", "tf2_msgs/msg/TFMessage", QOS_RELIABLE, "ds_to_sd"),
        BridgeSpec(f"/{ns}/tf_static", "tf2_msgs/msg/TFMessage", QOS_TF_STATIC, "ds_to_sd"),
        BridgeSpec(f"/{ns}/cmd_vel", "geometry_msgs/msg/Twist", QOS_RELIABLE, "sd_to_ds"),
    ]


def split_discovery_env(environ: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Return (simple_discovery_env, saved_discovery_vars).

    ``simple_discovery_env`` is a copy of ``environ`` with the Discovery-Server
    vars removed; ``saved_discovery_vars`` holds what was removed so the caller
    can restore them when building the Discovery-Server context. Does not mutate
    the input.
    """
    simple = dict(environ)
    saved: dict[str, str] = {}
    for key in _DISCOVERY_ENV_VARS:
        if key in simple:
            saved[key] = simple.pop(key)
    return simple, saved
