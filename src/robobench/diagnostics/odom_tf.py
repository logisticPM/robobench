"""odom -> base_link TF republisher.

Some Create3 firmware does not bridge the odom TF, leaving Nav2 with a broken
odom->base_link edge (robobench's TF panel flags it). This republishes that
transform from the Odometry message. Pure field-mapping is testable; the rclpy
node is lazy-imported and smoke-tested.

Ports upstream campus_nav_llm/odom_tf_publisher.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from robobench._rosenv import require_rclpy


@dataclass(frozen=True)
class OdomTf:
    """Flat TF fields copied straight from an Odometry message."""

    frame_id: str
    child_frame_id: str
    stamp_sec: int
    stamp_nanosec: int
    tx: float
    ty: float
    tz: float
    qx: float
    qy: float
    qz: float
    qw: float


def odom_to_tf(
    frame_id: str,
    child_frame_id: str,
    stamp_sec: int,
    stamp_nanosec: int,
    position: tuple[float, float, float],
    orientation: tuple[float, float, float, float],
) -> OdomTf:
    """Map Odometry pose fields onto flat TF fields. Pure; no rclpy."""
    px, py, pz = position
    ox, oy, oz, ow = orientation
    return OdomTf(frame_id, child_frame_id, stamp_sec, stamp_nanosec, px, py, pz, ox, oy, oz, ow)


def odom_topic(namespace: str) -> str:
    """Return the odom topic for a namespace ('' -> '/odom')."""
    ns = namespace.strip("/")
    return f"/{ns}/odom" if ns else "/odom"


def run_odom_tf_publisher(namespace: str) -> None:  # pragma: no cover
    """Subscribe to odom, broadcast odom->base_link TF until interrupted."""
    require_rclpy()
    import rclpy  # noqa: PLC0415
    from geometry_msgs.msg import TransformStamped  # noqa: PLC0415
    from nav_msgs.msg import Odometry  # noqa: PLC0415
    from rclpy.node import Node  # noqa: PLC0415
    from tf2_ros import TransformBroadcaster  # noqa: PLC0415

    rclpy.init()
    node = Node("robobench_odom_tf")
    broadcaster = TransformBroadcaster(node)
    topic = odom_topic(namespace)

    def on_odom(msg: Odometry) -> None:
        t = TransformStamped()
        t.header = msg.header  # frame_id="odom", stamp from odom
        t.child_frame_id = msg.child_frame_id  # "base_link"
        t.transform.translation.x = msg.pose.pose.position.x
        t.transform.translation.y = msg.pose.pose.position.y
        t.transform.translation.z = msg.pose.pose.position.z
        t.transform.rotation = msg.pose.pose.orientation
        broadcaster.sendTransform(t)

    node.create_subscription(Odometry, topic, on_odom, 10)
    node.get_logger().info(f"Publishing odom->base_link TF from {topic}")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
