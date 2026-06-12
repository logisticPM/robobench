import builtins

import pytest

from robobench.relay.runner import _msg_class_path, run_dds_bridge


def test_msg_class_path_splits_type_string():
    assert _msg_class_path("nav_msgs/msg/Odometry") == ("nav_msgs.msg", "Odometry")
    assert _msg_class_path("tf2_msgs/msg/TFMessage") == ("tf2_msgs.msg", "TFMessage")


def test_run_dds_bridge_raises_clearly_without_ros2(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "rclpy":
            raise ImportError("no rclpy")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="requires ROS2"):
        run_dds_bridge(namespace="tb", discovery_server="1.2.3.4:11811")


def test_env_snapshot_covers_every_key_the_bridge_mutates():
    """The restore snapshot must include every env var the bridge pops or sets
    (regression: FASTRTPS_DEFAULT_PROFILES_FILE was popped via
    split_discovery_env but missing from the snapshot, so it was never restored)."""
    from robobench.relay.runner import _DS_ENV_KEYS  # noqa: PLC0415
    from robobench.relay.specs import _DISCOVERY_ENV_VARS  # noqa: PLC0415

    assert set(_DS_ENV_KEYS) >= set(_DISCOVERY_ENV_VARS)
    assert "RMW_IMPLEMENTATION" in _DS_ENV_KEYS
