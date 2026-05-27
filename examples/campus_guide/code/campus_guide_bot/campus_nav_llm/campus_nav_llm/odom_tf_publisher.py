"""Odom → base_link TF publisher.

Subscribes to /odom and publishes the odom → base_link TF transform.
Needed when the Create3 republisher does not bridge the odometry TF.
"""
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from tf2_ros import TransformBroadcaster
from geometry_msgs.msg import TransformStamped


class OdomTfPublisher(Node):
    def __init__(self):
        super().__init__("odom_tf_publisher")

        self.declare_parameter("robot_namespace", "turtlebot468")
        ns = self.get_parameter("robot_namespace").value

        self.tf_broadcaster = TransformBroadcaster(self)

        odom_topic = f"/{ns}/odom" if ns else "/odom"
        self.create_subscription(Odometry, odom_topic, self._on_odom, 10)
        self.get_logger().info(f"Publishing odom→base_link TF from {odom_topic}")

    def _on_odom(self, msg: Odometry):
        t = TransformStamped()
        t.header = msg.header  # frame_id = "odom", stamp from odom msg
        t.child_frame_id = msg.child_frame_id  # "base_link"
        t.transform.translation.x = msg.pose.pose.position.x
        t.transform.translation.y = msg.pose.pose.position.y
        t.transform.translation.z = msg.pose.pose.position.z
        t.transform.rotation = msg.pose.pose.orientation
        self.tf_broadcaster.sendTransform(t)


def main():
    rclpy.init()
    node = OdomTfPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
