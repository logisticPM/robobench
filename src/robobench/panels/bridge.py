"""Persistent rclpy bridge node that feeds DiagnosticState.

Lazy rclpy import (same pattern as robobench.diagnostics.lifecycle_activator)
so the module is importable without ROS2. ``run_bridge`` is meant to run in a
daemon thread alongside the FastAPI server (the pattern the upstream
dashboard_server.py proved with its _ros_spin_thread).

Callbacks are intentionally thin: they only push raw data into DiagnosticState.
All analysis happens in robobench.panels.analyzers over snapshots.
"""

from __future__ import annotations

from robobench.panels.state import DiagnosticState


def _lazy_imports() -> dict:
    """Import rclpy + ROS message types; raise a clear error if ROS2 is absent."""
    try:
        import rclpy as _rclpy  # noqa: PLC0415, I001
        from rclpy.node import Node as _Node  # noqa: PLC0415
        from rclpy.qos import QoSProfile as _QoSProfile, ReliabilityPolicy as _ReliabilityPolicy  # noqa: PLC0415
        from sensor_msgs.msg import LaserScan as _LaserScan  # noqa: PLC0415
        from tf2_msgs.msg import TFMessage as _TFMessage  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "robobench diagnostic bridge requires ROS2 (rclpy, sensor_msgs, "
            "tf2_msgs). Source your ROS2 setup before running the dashboard."
        ) from exc
    return {
        "rclpy": _rclpy,
        "Node": _Node,
        "QoSProfile": _QoSProfile,
        "ReliabilityPolicy": _ReliabilityPolicy,
        "LaserScan": _LaserScan,
        "TFMessage": _TFMessage,
    }


def _stamp_to_float(stamp) -> float:
    """Convert a builtin_interfaces/Time to float seconds."""
    return stamp.sec + stamp.nanosec * 1e-9


def run_bridge(state: DiagnosticState, namespace: str) -> None:
    """Spin a node that fills ``state`` from robot topics. Blocks until shutdown.

    Intended to run in a daemon thread. Raises RuntimeError immediately if
    ROS2 isn't importable.
    """
    ros = _lazy_imports()
    rclpy = ros["rclpy"]
    Node = ros["Node"]
    QoSProfile = ros["QoSProfile"]
    ReliabilityPolicy = ros["ReliabilityPolicy"]
    LaserScan = ros["LaserScan"]
    TFMessage = ros["TFMessage"]

    rclpy.init()
    node = Node("robobench_diagnostic_bridge")

    sensor_qos = QoSProfile(depth=10)
    sensor_qos.reliability = ReliabilityPolicy.BEST_EFFORT

    scan_topic = f"/{namespace}/scan" if namespace else "/scan"

    def on_scan(msg) -> None:
        state.record_scan(_stamp_to_float(msg.header.stamp))

    def on_tf(msg) -> None:
        transforms = [
            (t.header.frame_id, t.child_frame_id, _stamp_to_float(t.header.stamp))
            for t in msg.transforms
        ]
        state.set_tf(transforms)

    node.create_subscription(LaserScan, scan_topic, on_scan, sensor_qos)
    node.create_subscription(TFMessage, "/tf", on_tf, 10)

    def refresh_nodes() -> None:
        names = [
            f"/{n}" if not n.startswith("/") else n
            for n, _ns in node.get_node_names_and_namespaces()
        ]
        state.set_nodes(names)

    node.create_timer(2.0, refresh_nodes)

    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
