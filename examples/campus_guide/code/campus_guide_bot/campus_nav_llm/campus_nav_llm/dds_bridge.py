#!/usr/bin/env python3
"""DDS Bridge: subscribes to robot topics via Discovery Server,
republishes them on Simple Discovery for local Nav2 nodes.

Also bridges cmd_vel back from Simple Discovery to Discovery Server.

Runs two rclpy contexts in separate threads — one for each DDS domain.
The key trick: we init the Simple Discovery context FIRST (before DS env vars
are set), then set DS env vars, then init the Discovery Server context.
"""
import os
import sys
import signal
import threading
import time

# Must import rclpy AFTER manipulating env vars for each context
# So we delay imports


def main():
    ns = os.environ.get("ROBOT_NAMESPACE", "turtlebot468")

    # ── Step 1: Save and CLEAR Discovery Server vars ──
    ds_server = os.environ.pop("ROS_DISCOVERY_SERVER", "192.168.50.31:11811")
    ds_super = os.environ.pop("ROS_SUPER_CLIENT", "True")
    ds_profile = os.environ.pop("FASTRTPS_DEFAULT_PROFILES_FILE", "")

    # ── Step 2: Init Simple Discovery context (no DS env vars) ──
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import LaserScan, Imu
    from geometry_msgs.msg import Twist
    from tf2_msgs.msg import TFMessage

    SENSOR_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
    RELIABLE_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
    TF_STATIC_QOS = QoSProfile(
        depth=10,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )

    sd_context = rclpy.context.Context()
    sd_context.init()
    print("[Bridge] Simple Discovery context initialized")

    # ── Step 3: Set DS env vars and init Discovery Server context ──
    os.environ["ROS_DISCOVERY_SERVER"] = ds_server
    os.environ["ROS_SUPER_CLIENT"] = ds_super
    if ds_profile:
        os.environ["FASTRTPS_DEFAULT_PROFILES_FILE"] = ds_profile

    ds_context = rclpy.context.Context()
    ds_context.init()
    print(f"[Bridge] Discovery Server context initialized ({ds_server})")

    # ── Step 4: Create nodes ──
    # SD node: publishes robot data, subscribes to cmd_vel
    sd_node = Node("dds_bridge_sd", context=sd_context)
    # DS node: subscribes to robot data, publishes cmd_vel
    ds_node = Node("dds_bridge_ds", context=ds_context)

    count = [0]

    def make_forwarder(pub):
        def cb(msg):
            pub.publish(msg)
            count[0] += 1
        return cb

    # Robot -> Nav2 bridges
    bridges = [
        (f"/{ns}/odom", Odometry, SENSOR_QOS),
        (f"/{ns}/scan", LaserScan, SENSOR_QOS),
        (f"/{ns}/imu", Imu, SENSOR_QOS),
        (f"/{ns}/tf", TFMessage, RELIABLE_QOS),
        (f"/{ns}/tf_static", TFMessage, TF_STATIC_QOS),
    ]

    for topic, msg_type, qos in bridges:
        pub = sd_node.create_publisher(msg_type, topic, qos)
        ds_node.create_subscription(msg_type, topic, make_forwarder(pub), qos)
        print(f"[Bridge] {topic}: DS -> SD")

    # Nav2 -> Robot bridge (cmd_vel)
    cmd_vel_pub = ds_node.create_publisher(Twist, f"/{ns}/cmd_vel", RELIABLE_QOS)
    sd_node.create_subscription(
        Twist, f"/{ns}/cmd_vel", make_forwarder(cmd_vel_pub), RELIABLE_QOS
    )
    print(f"[Bridge] /{ns}/cmd_vel: SD -> DS")

    # ── Step 5: Spin both contexts ──
    sd_exec = SingleThreadedExecutor(context=sd_context)
    sd_exec.add_node(sd_node)
    ds_exec = SingleThreadedExecutor(context=ds_context)
    ds_exec.add_node(ds_node)

    def spin_sd():
        try:
            sd_exec.spin()
        except Exception as e:
            print(f"[Bridge] SD executor error: {e}")
            import traceback
            traceback.print_exc()

    def spin_ds():
        try:
            ds_exec.spin()
        except Exception as e:
            print(f"[Bridge] DS executor error: {e}")
            import traceback
            traceback.print_exc()

    sd_thread = threading.Thread(target=spin_sd, daemon=True)
    ds_thread = threading.Thread(target=spin_ds, daemon=True)
    sd_thread.start()
    ds_thread.start()

    print("[Bridge] Running. Ctrl+C to stop.")

    def status_loop():
        while True:
            time.sleep(30)
            print(f"[Bridge] Forwarded {count[0]} messages")

    status_thread = threading.Thread(target=status_loop, daemon=True)
    status_thread.start()

    # Wait for signal
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()

    print("[Bridge] Shutting down...")
    sd_exec.shutdown()
    ds_exec.shutdown()
    sd_node.destroy_node()
    ds_node.destroy_node()
    sd_context.try_shutdown()
    ds_context.try_shutdown()


if __name__ == "__main__":
    main()
