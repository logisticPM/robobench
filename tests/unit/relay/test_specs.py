from robobench.relay.specs import bridge_specs, split_discovery_env


def test_bridge_specs_covers_core_topics():
    topics = {s.topic for s in bridge_specs("turtlebot468")}
    assert topics == {
        "/turtlebot468/odom",
        "/turtlebot468/scan",
        "/turtlebot468/imu",
        "/turtlebot468/tf",
        "/turtlebot468/tf_static",
        "/turtlebot468/cmd_vel",
    }


def test_bridge_specs_strips_slashes():
    specs = bridge_specs("/turtlebot468/")
    assert all(s.topic.startswith("/turtlebot468/") for s in specs)
    assert all("//" not in s.topic for s in specs)


def test_cmd_vel_relays_back_to_robot_others_inbound():
    by_topic = {s.topic: s for s in bridge_specs("tb")}
    assert by_topic["/tb/cmd_vel"].direction == "sd_to_ds"
    assert by_topic["/tb/odom"].direction == "ds_to_sd"


def test_split_discovery_env_removes_ds_vars():
    env = {
        "PATH": "/usr/bin",
        "ROS_DISCOVERY_SERVER": "1.2.3.4:11811",
        "ROS_SUPER_CLIENT": "True",
    }
    simple, saved = split_discovery_env(env)
    assert "ROS_DISCOVERY_SERVER" not in simple
    assert "ROS_SUPER_CLIENT" not in simple
    assert simple["PATH"] == "/usr/bin"
    assert saved == {"ROS_DISCOVERY_SERVER": "1.2.3.4:11811", "ROS_SUPER_CLIENT": "True"}


def test_split_discovery_env_does_not_mutate_input():
    env = {"ROS_DISCOVERY_SERVER": "x"}
    split_discovery_env(env)
    assert env == {"ROS_DISCOVERY_SERVER": "x"}
