#!/bin/bash
# Launch TurtleBot Dashboard
#
# Usage:
#   ./run.sh            # Demo mode (no ROS)
#   ./run.sh --ros      # Real mode with ROS 2

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Install deps if needed
pip install fastapi uvicorn python-multipart 2>/dev/null | grep -v "already satisfied"

if [[ "$1" == "--ros" ]]; then
  # Source ROS workspace
  source ~/CS5335TurtleBot/install/setup.bash 2>/dev/null || true
  export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
  export ROS_DISCOVERY_SERVER="192.168.50.31:11811"
  export ROS_SUPER_CLIENT=True
  echo "Starting dashboard with ROS 2 bridge..."
  python dashboard_server.py --ros --port 8080
else
  echo "Starting dashboard in DEMO mode..."
  echo "Open http://localhost:8080 in your browser"
  python dashboard_server.py --port 8080
fi
