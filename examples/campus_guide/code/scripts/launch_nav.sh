#!/bin/bash
# Launch Nav2 with FastDDS Discovery Server.
# Note: Nav2 lifecycle_manager cannot discover lifecycle services through
# Discovery Server (Nav2 #3560), so deploy.sh manually activates them.
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
export ROS_DISCOVERY_SERVER="${ROBOT_IP}:${DISCOVERY_PORT}"
export ROS_SUPER_CLIENT=True
ros2 launch campus_nav_llm navigation_mode.launch.py
