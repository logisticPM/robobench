"""rclpy wiring for the DDS topic relay. Imported lazily so the rest of
robobench works without ROS2 installed.

The dual-context trick (mirrors upstream dds_bridge.py): build a Simple-
Discovery context with the Discovery-Server env vars stripped, then restore
them and build the Discovery-Server context. Each topic spec wires a
subscription on the source graph to a publisher on the destination graph.
"""

from __future__ import annotations

import importlib
import os
import threading

from robobench._rosenv import require_rclpy
from robobench.relay.specs import (
    QOS_RELIABLE,
    QOS_SENSOR,
    QOS_TF_STATIC,
    bridge_specs,
    split_discovery_env,
)


def _msg_class_path(type_str: str) -> tuple[str, str]:
    """Map 'pkg/msg/Name' -> ('pkg.msg', 'Name')."""
    pkg, _msg, name = type_str.split("/")
    return f"{pkg}.msg", name


def _import_msg(type_str: str) -> type:
    module_name, class_name = _msg_class_path(type_str)
    return getattr(importlib.import_module(module_name), class_name)


_DS_ENV_KEYS = ("ROS_DISCOVERY_SERVER", "ROS_SUPER_CLIENT", "RMW_IMPLEMENTATION")


def _restore_env(snapshot: dict) -> None:  # pragma: no cover
    """Restore the DS env keys to the values captured in *snapshot*."""
    for k, v in snapshot.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _shutdown_resources(sd_exec, ds_exec, sd_node, ds_node, sd_context, ds_context) -> None:  # pragma: no cover  # noqa: E501
    """Shut down executor/node/context objects if they were ever created."""
    if sd_exec:
        sd_exec.shutdown()
    if ds_exec:
        ds_exec.shutdown()
    if sd_node:
        sd_node.destroy_node()
    if ds_node:
        ds_node.destroy_node()
    if sd_context:
        sd_context.try_shutdown()
    if ds_context:
        ds_context.try_shutdown()


def run_dds_bridge(namespace: str, discovery_server: str) -> None:  # pragma: no cover
    """Relay topics between the robot's Discovery-Server graph and the local
    Simple-Discovery graph until interrupted. Blocking."""
    require_rclpy()
    import rclpy  # noqa: PLC0415
    from rclpy.executors import SingleThreadedExecutor  # noqa: PLC0415
    from rclpy.node import Node  # noqa: PLC0415
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy  # noqa: PLC0415

    # Initialise all resources to None so the finally block is safe even if
    # setup raises before any/all of them are assigned.
    sd_exec = ds_exec = sd_node = ds_node = sd_context = ds_context = None

    # Snapshot the env keys we are about to mutate so we can restore them.
    env_snapshot = {k: os.environ.get(k) for k in _DS_ENV_KEYS}

    try:
        qos_map = {
            QOS_SENSOR: QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT),
            QOS_RELIABLE: QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE),
            QOS_TF_STATIC: QoSProfile(
                depth=10,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            ),
        }

        # Build the Simple-Discovery context first (DS env vars stripped)...
        _simple, saved = split_discovery_env(dict(os.environ))
        for key in saved:
            os.environ.pop(key, None)
        sd_context = rclpy.context.Context()
        sd_context.init()

        # ...then set DS env vars and build the Discovery-Server context.
        os.environ["ROS_DISCOVERY_SERVER"] = discovery_server
        os.environ["ROS_SUPER_CLIENT"] = saved.get("ROS_SUPER_CLIENT", "True")
        os.environ["RMW_IMPLEMENTATION"] = "rmw_fastrtps_cpp"
        ds_context = rclpy.context.Context()
        ds_context.init()

        sd_node = Node("robobench_relay_sd", context=sd_context)
        ds_node = Node("robobench_relay_ds", context=ds_context)

        def forwarder(pub):
            def cb(msg):
                pub.publish(msg)

            return cb

        for spec in bridge_specs(namespace):
            msg_cls = _import_msg(spec.msg_type)
            qos = qos_map[spec.qos]
            if spec.direction == "ds_to_sd":
                pub = sd_node.create_publisher(msg_cls, spec.topic, qos)
                ds_node.create_subscription(msg_cls, spec.topic, forwarder(pub), qos)
            else:  # sd_to_ds
                pub = ds_node.create_publisher(msg_cls, spec.topic, qos)
                sd_node.create_subscription(msg_cls, spec.topic, forwarder(pub), qos)

        sd_exec = SingleThreadedExecutor(context=sd_context)
        sd_exec.add_node(sd_node)
        ds_exec = SingleThreadedExecutor(context=ds_context)
        ds_exec.add_node(ds_node)
        threading.Thread(target=sd_exec.spin, daemon=True).start()
        threading.Thread(target=ds_exec.spin, daemon=True).start()

        # Block the main thread here; daemon executor threads run until we exit.
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        _restore_env(env_snapshot)
        _shutdown_resources(sd_exec, ds_exec, sd_node, ds_node, sd_context, ds_context)
