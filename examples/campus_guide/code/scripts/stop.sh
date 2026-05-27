#!/bin/bash
# Stop all TurtleBot navigation processes and send zero velocity
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.yaml"

# Read config from config.yaml (single source of truth)
if [[ -f "$CONFIG_FILE" ]] && command -v python3 &>/dev/null; then
  _cfg() { python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG_FILE')); print($1)" 2>/dev/null; }
  ROBOT_IP=$(_cfg "c['robot']['ip']") || ROBOT_IP="192.168.50.31"
  ROBOT_NS=$(_cfg "c['robot']['namespace']") || ROBOT_NS="turtlebot468"
  DISCOVERY_PORT=$(_cfg "c['dds']['discovery_port']") || DISCOVERY_PORT="11811"
else
  ROBOT_IP="192.168.50.31"
  ROBOT_NS="turtlebot468"
  DISCOVERY_PORT="11811"
fi

export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DISCOVERY_SERVER="${ROBOT_IP}:${DISCOVERY_PORT}"
export ROS_SUPER_CLIENT=True
source "$SCRIPT_DIR/install/setup.bash" 2>/dev/null || true

echo "Stopping robot..."

# Send zero velocity repeatedly
for i in $(seq 1 5); do
  ros2 topic pub --once "/$ROBOT_NS/cmd_vel" geometry_msgs/msg/Twist \
    '{linear: {x: 0.0}, angular: {z: 0.0}}' 2>/dev/null &
done
wait

# Kill launch process if saved
if [[ -f /tmp/turtlebot_launch.pid ]]; then
  PID=$(cat /tmp/turtlebot_launch.pid)
  if kill -0 "$PID" 2>/dev/null; then
    echo "Killing launch process ($PID)..."
    kill "$PID" 2>/dev/null
    sleep 2
    kill -9 "$PID" 2>/dev/null || true
  fi
  rm -f /tmp/turtlebot_launch.pid
fi

# Kill any remaining nav2/campus_nav processes
# Match full paths: /opt/ros/humble/lib/nav2_controller/controller_server etc.
pkill -9 -f "navigation_mode.launch" 2>/dev/null || true
pkill -9 -f "lifecycle_manager" 2>/dev/null || true
pkill -9 -f "lifecycle_activator" 2>/dev/null || true
pkill -9 -f "/map_server " 2>/dev/null || true
pkill -9 -f "/amcl " 2>/dev/null || true
pkill -9 -f "/controller_server " 2>/dev/null || true
pkill -9 -f "/smoother_server " 2>/dev/null || true
pkill -9 -f "/planner_server " 2>/dev/null || true
pkill -9 -f "/behavior_server " 2>/dev/null || true
pkill -9 -f "/bt_navigator " 2>/dev/null || true
pkill -9 -f "/waypoint_follower " 2>/dev/null || true
pkill -9 -f "/velocity_smoother " 2>/dev/null || true
pkill -9 -f "task_executor" 2>/dev/null || true
pkill -9 -f "llm_planner" 2>/dev/null || true
pkill -9 -f "odom_tf_publisher" 2>/dev/null || true

echo "Stopped."
