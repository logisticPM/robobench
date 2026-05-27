#!/bin/bash
# Bridge robot topics from Discovery Server to local Simple Discovery.
# Runs topic_tools relay for each critical topic.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.yaml"

# Read config from config.yaml (single source of truth)
if [[ -f "$CONFIG_FILE" ]] && command -v python3 &>/dev/null; then
  _cfg() { python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG_FILE')); print($1)" 2>/dev/null; }
  ROBOT_IP=$(_cfg "c['robot']['ip']") || ROBOT_IP="192.168.50.31"
  DISCOVERY_PORT=$(_cfg "c['dds']['discovery_port']") || DISCOVERY_PORT="11811"
else
  ROBOT_IP="192.168.50.31"
  DISCOVERY_PORT="11811"
fi

source "$SCRIPT_DIR/install/setup.bash"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTRTPS_DEFAULT_PROFILES_FILE="$SCRIPT_DIR/fastdds_super_client.xml"
export ROS_DISCOVERY_SERVER="${ROBOT_IP}:${DISCOVERY_PORT}"
export ROS_SUPER_CLIENT=True

echo "Starting topic bridges from Discovery Server to local network..."

# Bridge odom, scan, tf, tf_static, cmd_vel (bidirectional for cmd_vel)
ros2 run topic_tools relay /turtlebot468/odom /turtlebot468/odom &
ros2 run topic_tools relay /turtlebot468/scan /turtlebot468/scan &
ros2 run topic_tools relay /turtlebot468/tf /turtlebot468/tf &
ros2 run topic_tools relay /turtlebot468/tf_static /turtlebot468/tf_static &
ros2 run topic_tools relay /turtlebot468/imu /turtlebot468/imu &

echo "Bridges started. Press Ctrl+C to stop."
wait
