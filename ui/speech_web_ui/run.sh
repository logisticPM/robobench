#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# TurtleBot468 Speech Web UI — Launch Script
#
# Usage:
#   ./run.sh            # Demo mode (no robot, for UI testing)
#   ./run.sh --ros      # Full mode (requires sourced ROS2 env)
# ─────────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Check Python venv / dependencies ─────────────────────────────
if [ ! -d ".venv" ]; then
  echo "[run.sh] Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate
echo "[run.sh] Installing / checking dependencies..."
pip install -q -r requirements.txt

# ── Optional: source ROS2 ─────────────────────────────────────────
ROS_FLAG=""
if [[ "$1" == "--ros" ]]; then
  if [ -f "/opt/ros/humble/setup.bash" ]; then
    source /opt/ros/humble/setup.bash
    echo "[run.sh] ROS2 Humble sourced"
  elif [ -f "/opt/ros/iron/setup.bash" ]; then
    source /opt/ros/iron/setup.bash
    echo "[run.sh] ROS2 Iron sourced"
  else
    echo "[run.sh] WARNING: Could not find ROS2 setup.bash — trying anyway"
  fi

  # Source workspace overlay if it exists
  WS_SETUP="$(dirname "$SCRIPT_DIR")/install/setup.bash"
  if [ -f "$WS_SETUP" ]; then
    source "$WS_SETUP"
    echo "[run.sh] Workspace overlay sourced: $WS_SETUP"
  fi

  ROS_FLAG="--ros"
fi

# ── DDS env vars (match what launch_nav.sh sets) ──────────────────
if [[ "$ROS_FLAG" == "--ros" ]]; then
  export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
  export ROS_DISCOVERY_SERVER="192.168.50.31:11811"
  export ROS_SUPER_CLIENT=True
  echo "[run.sh] DDS: FastRTPS Discovery Server @ ${ROS_DISCOVERY_SERVER}"
fi

# ── Launch ────────────────────────────────────────────────────────
PORT=${PORT:-8888}
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   TurtleBot468 Speech Commander                  ║"
echo "║   http://localhost:${PORT}                        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

python speech_server.py --port "$PORT" $ROS_FLAG
