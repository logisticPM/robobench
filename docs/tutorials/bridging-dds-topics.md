# Bridging robot topics across DDS discovery (`robobench bridge`)

When the FastDDS Discovery Server drops a late joiner or churns GUIDs (Nav2
#3560), local ROS2 tools and Nav2 nodes stop seeing robot topics even though
the robot is publishing. `robobench bridge` republishes the robot's topics onto
your workstation's default (Simple Discovery) graph so plain `ros2 topic echo`
and a local Nav2 stack work again — and relays `cmd_vel` back to the robot.

```bash
robobench bridge --robot turtlebot4 --config ./config.yaml
```

It reads `robot.namespace`, `robot.ip`, and `dds.discovery_port` from
`config.yaml`, builds two DDS contexts (one Simple, one Discovery-Server), and
forwards `odom`, `scan`, `imu`, `tf`, `tf_static` inbound and `cmd_vel`
outbound. Leave it running in its own terminal; Ctrl+C stops it.

> Requires ROS2 sourced (`source /opt/ros/<distro>/setup.bash`) and the message
> packages (`nav_msgs`, `sensor_msgs`, `geometry_msgs`, `tf2_msgs`). Without
> ROS2 the command prints `[bridge] not started: ... requires ROS2 ...`.

> Advanced: to tune FastDDS buffers, point `FASTRTPS_DEFAULT_PROFILES_FILE` at
> your own super-client XML before launching; the relay preserves it.
