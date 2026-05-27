#!/bin/bash
# ============================================================
# CS5335 TurtleBot Auto Deployment Script (v3)
# ============================================================
# Usage:
#   ./deploy.sh                    # Full deploy
#   ./deploy.sh --skip-build       # Skip colcon build
#   ./deploy.sh --skip-clock       # Skip clock sync
#   ./deploy.sh --pose "x y theta" # Custom initial pose (default: front_door)
#
# v3 changes (evidence-based):
#   - Clock sync: only restart chrony, not turtlebot4 service (saves 60-90s)
#     Ref: chrony docs — restart chrony is sufficient; TurtleBot4 docs don't
#     require ROS restart for NTP changes
#   - Process cleanup: SIGTERM first, SIGKILL after 5s (graceful shutdown)
#     Ref: rclcpp#1704 — SIGTERM support since Humble; FastDDS#2790 — SIGKILL
#     leaks /dev/shm shared memory segments
#   - Removed Step 7 (set initial pose via CLI) — redundant with
#     lifecycle_activator Phase 4.5 which uses persistent node (more reliable)
#     Ref: Nav2 AMCL docs — set_initial_pose parameter
#   - Step 4 simplified: fixed 15s wait instead of unreliable ros2 node list
#     Ref: TurtleBot4 docs — "you may need to call ros2 topic list twice"
#   - Step 6 reduced to 15s sanity check (not 120s readiness gate)
#     Ref: nav2_bringup does not poll action servers after lifecycle activation
#
# References:
#   - Nav2 lifecycle: https://docs.nav2.org/configuration/packages/configuring-lifecycle.html
#   - Nav2 #3560: FastDDS Discovery Server filters lifecycle services
#   - rclcpp#1704: SIGTERM graceful shutdown
#   - FastDDS#2790: shared memory leak on SIGKILL
#   - rmw_fastrtps#392: service discovery race
# ============================================================

set -eo pipefail

# Colors & logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[DEPLOY]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; }
step() { echo -e "\n${CYAN}━━━ Step $1: $2 ━━━${NC}"; }

# ── Persist all output to log file ──
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_LOG_DIR="$SCRIPT_DIR/log/deploy"
mkdir -p "$DEPLOY_LOG_DIR"
DEPLOY_LOG="$DEPLOY_LOG_DIR/deploy_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$DEPLOY_LOG") 2>&1
log "Log file: $DEPLOY_LOG"

# ── Configuration ──
CONFIG_FILE="$SCRIPT_DIR/config.yaml"

if [[ -f "$CONFIG_FILE" ]] && command -v python3 &>/dev/null; then
  _cfg() { python3 -c "import yaml; c=yaml.safe_load(open('$CONFIG_FILE')); print($1)" 2>/dev/null; }
  ROBOT_IP=$(_cfg "c['robot']['ip']") || ROBOT_IP="192.168.50.31"
  ROBOT_USER=$(_cfg "c['robot']['ssh_user']") || ROBOT_USER="ubuntu"
  ROBOT_PASS=$(_cfg "c['robot']['ssh_pass']") || ROBOT_PASS="turtlebot4"
  ROBOT_NS=$(_cfg "c['robot']['namespace']") || ROBOT_NS="turtlebot468"
  DISCOVERY_PORT=$(_cfg "c['dds']['discovery_port']") || DISCOVERY_PORT="11811"
  WS_DIR=$(_cfg "import os; print(os.path.expanduser(c['workspace']['dir']))") || WS_DIR="$HOME/CS5335TurtleBot"

  declare -A KNOWN_POSES
  while IFS='=' read -r name coords; do
    KNOWN_POSES["$name"]="$coords"
  done < <(python3 -c "
import yaml
c = yaml.safe_load(open('$CONFIG_FILE'))
for name, p in c.get('known_poses', {}).items():
    print(f\"{name}={p['x']} {p['y']} {p['theta']}\")
" 2>/dev/null)

  log "Loaded config from $CONFIG_FILE"
else
  ROBOT_IP="192.168.50.31"
  ROBOT_USER="ubuntu"
  ROBOT_PASS="turtlebot4"
  ROBOT_NS="turtlebot468"
  WS_DIR="$HOME/CS5335TurtleBot"
  DISCOVERY_PORT="11811"

  declare -A KNOWN_POSES=(
    ["front_door"]="5.19 2.56 0.0"
    ["back_door"]="-1.56 0.86 3.14"
    ["table_1"]="6.54 -0.38 -1.57"
    ["table_2"]="7.13 -2.24 -1.57"
    ["table_3"]="5.894 -4.693 0.0"
    ["table_4"]="4.22 -5.045 0.0"
    ["table_5"]="2.14 -5.486 0.0"
    ["table_6"]="0.184 -6.032 0.0"
    ["table_7"]="-2.018 -6.578 0.0"
    ["table_8"]="-3.128 -5.503 0.0"
    ["table_9"]="-3.71 -3.635 0.0"
    ["charging_station"]="-0.10 -0.24 0.0"
    ["stand_monitor"]="2.563 0.259 0.0"
  )
  warn "config.yaml not found or python3 unavailable, using defaults"
fi

# INIT_X, INIT_Y, INIT_THETA are set by --pose argument (default: front_door)

# ── Utility ──
wait_for() {
  local timeout=$1 poll=$2 desc=$3
  shift 3
  local elapsed=0
  while [[ $elapsed -lt $timeout ]]; do
    if eval "$@" 2>/dev/null; then
      return 0
    fi
    sleep "$poll"
    elapsed=$((elapsed + poll))
    echo -n "."
  done
  echo ""
  return 1
}

# Graceful process kill: SIGTERM → wait → SIGKILL
# Ref: rclcpp#1704 (Humble supports SIGTERM); FastDDS#2790 (SIGKILL leaks shm)
graceful_kill() {
  local pattern=$1
  # Phase 1: SIGTERM (allows on_shutdown cleanup, releases FastDDS shm)
  pkill -TERM -f "$pattern" 2>/dev/null || true
}

force_kill_remaining() {
  # Phase 2: SIGKILL only for processes that didn't exit after SIGTERM
  local patterns=(
    "navigation_mode.launch" "lifecycle_manager" "lifecycle_activator"
    "/map_server " "/amcl " "/controller_server " "/smoother_server "
    "/planner_server " "/behavior_server " "/bt_navigator "
    "/waypoint_follower " "/velocity_smoother "
    "task_executor" "llm_planner" "odom_tf_publisher"
  )
  for p in "${patterns[@]}"; do
    pkill -9 -f "$p" 2>/dev/null || true
  done
}

# ── Parse arguments ──
SKIP_BUILD=false
SKIP_CLOCK=false
POSE_NAME="front_door"

while [[ $# -gt 0 ]]; do
  case $1 in
    --skip-build) SKIP_BUILD=true; shift ;;
    --skip-clock) SKIP_CLOCK=true; shift ;;
    --pose)
      POSE_NAME="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: ./deploy.sh [--skip-build] [--skip-clock] [--pose LOCATION]"
      echo ""
      echo "Locations: ${!KNOWN_POSES[*]}"
      echo "  Or provide custom: --pose 'x y theta'"
      exit 0
      ;;
    *) err "Unknown option: $1"; exit 1 ;;
  esac
done

# Resolve pose
if [[ -n "${KNOWN_POSES[$POSE_NAME]+x}" ]]; then
  read -r INIT_X INIT_Y INIT_THETA <<< "${KNOWN_POSES[$POSE_NAME]}"
  log "Initial pose: $POSE_NAME ($INIT_X, $INIT_Y, $INIT_THETA)"
else
  read -r INIT_X INIT_Y INIT_THETA <<< "$POSE_NAME" 2>/dev/null || {
    err "Unknown pose: $POSE_NAME"
    err "Available: ${!KNOWN_POSES[*]}"
    exit 1
  }
  log "Custom initial pose: ($INIT_X, $INIT_Y, $INIT_THETA)"
fi

# ── Environment setup ──
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
# Respect ROS_DISCOVERY_SERVER if already set (e.g. local server for testing)
export ROS_DISCOVERY_SERVER="${ROS_DISCOVERY_SERVER:-${ROBOT_IP}:${DISCOVERY_PORT}}"
export ROS_SUPER_CLIENT=True

# ── Step 1: Clock sync via chrony ──
# Ref: chrony docs — restart chrony sufficient for config changes
#      TurtleBot4 docs — no ROS restart needed for NTP
if [[ "$SKIP_CLOCK" == false ]]; then
  step 1 "Clock sync (chrony)"

  SSH_CMD="sshpass -p $ROBOT_PASS ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 $ROBOT_USER@$ROBOT_IP"

  if ! command -v sshpass &>/dev/null; then
    warn "sshpass not installed. Sync clock manually or install sshpass."
    [[ -t 0 ]] && read -p "Press Enter to continue..."
  else
    # 1a. Ensure chrony installed
    log "Checking chrony on RPi..."
    CHRONY_INSTALLED=$($SSH_CMD "dpkg -l chrony 2>/dev/null | grep -c '^ii'" 2>/dev/null || echo "0")
    if [[ "$CHRONY_INSTALLED" -lt 1 ]]; then
      log "Installing chrony on RPi..."
      $SSH_CMD "sudo apt-get install -y chrony" 2>/dev/null || warn "chrony install failed"
    fi

    # 1b. Get laptop IP
    LAPTOP_IP=$(ip -4 addr show 2>/dev/null | grep "192\.168\." | head -1 | awk '{print $2}' | cut -d/ -f1 || echo "")
    if [[ -z "$LAPTOP_IP" ]]; then
      LAPTOP_IP=$(ip route get "$ROBOT_IP" 2>/dev/null | grep -oP 'src \K\S+' || echo "")
    fi

    if [[ -n "$LAPTOP_IP" ]]; then
      log "Laptop IP: $LAPTOP_IP"

      # 1c. Configure RPi chrony
      CHRONY_CONF="server ${LAPTOP_IP} prefer iburst minpoll 0 maxpoll 2
pool ntp.ubuntu.com iburst maxsources 2
local stratum 11
allow 192.168.186.0/24
makestep 0.1 -1
rtcsync"

      log "Configuring RPi chrony (server: $LAPTOP_IP)..."
      $SSH_CMD "echo '$CHRONY_CONF' | sudo tee /etc/chrony/chrony.conf > /dev/null && sudo systemctl restart chrony" 2>/dev/null \
        && log "RPi chrony configured" || warn "RPi chrony config failed"

      # 1d. Check laptop chrony
      if command -v chronyc &>/dev/null; then
        if ! grep -q "allow 192.168" /etc/chrony/chrony.conf 2>/dev/null; then
          log "Note: Add 'allow 192.168.0.0/16' and 'local stratum 10' to laptop /etc/chrony/chrony.conf"
          log "Then: sudo systemctl restart chrony"
        fi
      fi

      # 1e. Force sync
      $SSH_CMD "sudo chronyc -a makestep" 2>/dev/null || true
      sleep 3

      # 1f. Verify drift
      ROBOT_TIME=$($SSH_CMD "date +%s" 2>/dev/null || echo "0")
      LOCAL_TIME=$(date +%s)
      DRIFT=$(( LOCAL_TIME - ROBOT_TIME ))
      DRIFT=${DRIFT#-}
      if [[ "$DRIFT" -le 2 ]]; then
        log "Clock synced via chrony (drift: ${DRIFT}s)"
      elif [[ "$DRIFT" -le 10 ]]; then
        warn "Clock drift: ${DRIFT}s — chrony may need more time to converge"
      else
        warn "Clock drift: ${DRIFT}s — falling back to date -s"
        CURRENT_TIME=$(date +"%Y-%m-%d %H:%M:%S")
        $SSH_CMD "sudo date -s '$CURRENT_TIME'" 2>/dev/null || true
      fi
    else
      warn "Cannot determine laptop IP. Falling back to date -s"
      CURRENT_TIME=$(date +"%Y-%m-%d %H:%M:%S")
      $SSH_CMD "sudo date -s '$CURRENT_TIME'" 2>/dev/null || true
    fi

    # NOTE: We do NOT restart turtlebot4 service here.
    # Chrony restart is sufficient for clock changes. Restarting turtlebot4
    # would kill all RPi ROS nodes and require 60-90s for Create3 reconnection.
    # Ref: chrony docs, TurtleBot4 manual
  fi

  # Sync Create3 clock (NTP restart) — Create3 has its own MCU clock that drifts.
  # Without this, AMCL drops laser scans ("timestamp earlier than all data in cache").
  log "Syncing Create3 clock (restart-ntpd)..."
  CREATE3_RESULT=$($SSH_CMD "curl -s -X POST http://192.168.186.2/api/restart-ntpd" 2>/dev/null || echo "FAIL")
  if echo "$CREATE3_RESULT" | grep -qi "fail\|error\|refused"; then
    warn "Create3 NTP sync failed — AMCL may drop scans due to clock drift"
  else
    log "Create3 NTP restarted"
  fi

  # Verify robot is online (topics should already be visible if robot was running)
  log "Checking robot connectivity..."
  ros2 daemon stop 2>/dev/null || true
  sleep 1
  ros2 daemon start 2>/dev/null || true

  # Double topic list per TurtleBot4 docs recommendation
  ros2 topic list 2>/dev/null > /dev/null
  sleep 1
  TOPIC_COUNT=$(ros2 topic list 2>/dev/null | grep -c "$ROBOT_NS" || true)
  TOPIC_COUNT=${TOPIC_COUNT%%[^0-9]*}
  TOPIC_COUNT=${TOPIC_COUNT:-0}
  if [[ "$TOPIC_COUNT" -gt 0 ]]; then
    log "Robot online ($TOPIC_COUNT topics found)"
  else
    warn "No robot topics visible — robot may need time to start or a service restart"
    warn "If robot was just powered on, run: ssh ubuntu@$ROBOT_IP 'sudo systemctl restart turtlebot4'"
  fi
else
  log "Skipping clock sync"

  log "Checking robot connectivity..."
  if ping -c 1 -W 3 "$ROBOT_IP" &>/dev/null; then
    log "Robot reachable at $ROBOT_IP"
  else
    warn "Robot not reachable at $ROBOT_IP — deploy may fail"
  fi

  ros2 daemon stop 2>/dev/null || true
  sleep 1
  ros2 daemon start 2>/dev/null || true
  ros2 topic list 2>/dev/null > /dev/null
  sleep 1
  TOPIC_COUNT=$(ros2 topic list 2>/dev/null | grep -c "$ROBOT_NS" || true)
  TOPIC_COUNT=${TOPIC_COUNT%%[^0-9]*}
  TOPIC_COUNT=${TOPIC_COUNT:-0}
  if [[ "$TOPIC_COUNT" -gt 0 ]]; then
    log "Robot online ($TOPIC_COUNT topics found)"
  else
    warn "No robot topics visible — robot may need more time to start"
  fi
fi

# ── Step 2: Build ──
if [[ "$SKIP_BUILD" == false ]]; then
  step 2 "Building campus_nav_llm"
  cd "$WS_DIR"
  if ! colcon build --packages-select campus_nav_llm 2>&1 | tail -5; then
    err "Build failed!"
    exit 1
  fi
  log "Build complete"
else
  log "Skipping build"
fi

source "$WS_DIR/install/setup.bash"

# ── Step 3: Launch navigation stack ──
step 3 "Launching navigation stack"

# Graceful cleanup of stale processes
# Ref: rclcpp#1704 — SIGTERM triggers on_shutdown handlers since Humble
#      FastDDS#2790 — SIGKILL leaks /dev/shm shared memory segments
log "Stopping stale processes (SIGTERM)..."
if [[ -f /tmp/turtlebot_launch.pid ]]; then
  OLD_PID=$(cat /tmp/turtlebot_launch.pid 2>/dev/null)
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill -TERM "$OLD_PID" 2>/dev/null || true
  fi
fi
graceful_kill "navigation_mode.launch"
graceful_kill "lifecycle_manager"
graceful_kill "lifecycle_activator"
graceful_kill "task_executor"
graceful_kill "llm_planner"
graceful_kill "odom_tf_publisher"
graceful_kill "/map_server "
graceful_kill "/amcl "
graceful_kill "/controller_server "
graceful_kill "/planner_server "
graceful_kill "/bt_navigator "

# Wait for graceful shutdown
log "Waiting 5s for graceful shutdown..."
sleep 5

# SIGKILL anything still alive
force_kill_remaining
sleep 1

# Clean FastDDS shared memory if available
# Ref: FastDDS#2790, FastDDS Discussion#5146
if command -v fastdds &>/dev/null; then
  fastdds shm clean 2>/dev/null || true
fi

log "Stale processes cleaned"

# Fresh daemon
ros2 daemon stop 2>/dev/null || true
sleep 1
ros2 daemon start 2>/dev/null || true

log "Starting navigation_mode.launch.py in background..."
ros2 launch campus_nav_llm navigation_mode.launch.py &
LAUNCH_PID=$!
echo "$LAUNCH_PID" > /tmp/turtlebot_launch.pid
log "Launch PID: $LAUNCH_PID"

# ── Step 4: Wait for processes to start ──
# Ref: TurtleBot4 docs — ros2 node list unreliable under Discovery Server
#      ("you may need to call ros2 topic list twice")
# Instead of polling ros2 node list (daemon-cached, unreliable), we wait
# a fixed period for launch to spawn all processes. lifecycle_activator in
# Step 5 does the real service-level discovery.
step 4 "Waiting for launch processes (15s)"
sleep 15
log "Proceeding to lifecycle activation"

# ── Step 5: Activate lifecycle nodes ──
# Ref: ros2cli #779, rmw_fastrtps #392/#499, Nav2 #3560
step 5 "Activating lifecycle nodes (lifecycle_activator)"

MAP_YAML="$WS_DIR/install/campus_nav_llm/share/campus_nav_llm/maps/my_map.yaml"

log "Running lifecycle_activator (persistent DDS participant)..."
log "Initial pose: ($INIT_X, $INIT_Y, θ=$INIT_THETA)"
if timeout 180 ros2 run campus_nav_llm lifecycle_activator --ros-args \
    -p namespace:="$ROBOT_NS" \
    -p map_yaml:="$MAP_YAML" \
    -p service_timeout:=15.0 \
    -p discovery_timeout:=90.0 \
    -p initial_pose_x:="$INIT_X" \
    -p initial_pose_y:="$INIT_Y" \
    -p initial_pose_yaw:="$INIT_THETA"; then
  log "All lifecycle nodes activated successfully"
else
  err "lifecycle_activator failed (exit code $?)"
  warn "Falling back to manual CLI activation..."
  for node in map_server amcl controller_server planner_server behavior_server bt_navigator velocity_smoother; do
    log "  Trying $node..."
    timeout 30 ros2 lifecycle set "/$ROBOT_NS/$node" configure 2>/dev/null || true
    sleep 1
    timeout 30 ros2 lifecycle set "/$ROBOT_NS/$node" activate 2>/dev/null || true
    sleep 1
  done
fi

# ── Step 6: Quick sanity check ──
# Ref: nav2_bringup does not poll action servers after lifecycle activation.
#      BasicNavigator.waitUntilNav2Active() checks lifecycle state, not action
#      servers. Application-layer code handles its own readiness.
#      This is a quick sanity check, not a readiness gate.
step 6 "Sanity check"

if wait_for 15 3 "navigate_to_pose action" \
  "ros2 action list 2>/dev/null | grep -q '/$ROBOT_NS/navigate_to_pose'"; then
  echo ""
  log "navigate_to_pose action server confirmed"
else
  warn "Action server not visible via CLI (may still work — CLI is unreliable under Discovery Server)"
fi

# AMCL health check — verify AMCL is actually publishing pose
log "Checking AMCL health..."
if timeout 15 ros2 topic echo "/$ROBOT_NS/amcl_pose" --once &>/dev/null; then
  log "AMCL is publishing pose — localization active"
else
  warn "AMCL is NOT publishing pose after 15s!"
  warn "Possible causes: clock mismatch, TF issues, or bad initial pose"
  warn "Try: ros2 topic pub --once /$ROBOT_NS/initialpose ..."
fi

# (Step 7 removed — initial pose is handled by lifecycle_activator Phase 4.5
#  using a persistent ROS node, which is more reliable than CLI ros2 topic pub.
#  Ref: Nav2 AMCL set_initial_pose parameter; rmw_fastrtps#499)

# ── Step 7: Wait for LLM nodes ──
step 7 "Waiting for campus_nav_llm nodes"

if wait_for 60 3 "task_executor + llm_planner" \
  "ros2 node list 2>/dev/null | grep -q 'task_executor' && ros2 node list 2>/dev/null | grep -q 'llm_planner'"; then
  echo ""
  log "Both nodes running"
else
  warn "LLM nodes not all found (they have respawn — may still come up)."
fi

# ── Step 8: Final verification ──
step 8 "Verification"

echo ""
echo "Checking subscriptions..."
USER_INPUT_SUBS=$(ros2 topic info /user_input 2>/dev/null | grep "Subscription count" | awk '{print $3}' | tr -d '[:space:]' || echo "0")
TOOL_CMD_SUBS=$(ros2 topic info /tool_cmd 2>/dev/null | grep "Subscription count" | awk '{print $3}' | tr -d '[:space:]' || echo "0")
ACTION_OK=$(ros2 action list 2>/dev/null | grep -c "/$ROBOT_NS/navigate_to_pose" | tr -d '[:space:]' || echo "0")

if [[ "$USER_INPUT_SUBS" -gt 0 ]]; then
  echo -e "  /user_input:         ${GREEN}$USER_INPUT_SUBS subscriber(s)${NC}"
else
  echo -e "  /user_input:         ${RED}no subscribers${NC}"
fi

if [[ "$TOOL_CMD_SUBS" -gt 0 ]]; then
  echo -e "  /tool_cmd:           ${GREEN}$TOOL_CMD_SUBS subscriber(s)${NC}"
else
  echo -e "  /tool_cmd:           ${RED}no subscribers${NC}"
fi

if [[ "$ACTION_OK" -gt 0 ]]; then
  echo -e "  navigate_to_pose:    ${GREEN}available${NC}"
else
  echo -e "  navigate_to_pose:    ${RED}not found${NC}"
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN} Deployment complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Send commands:"
echo "  Open dashboard: http://127.0.0.1:8080"
echo "  Or from terminal:"
echo "    ros2 topic pub --once /user_input std_msgs/msg/String \"data: 'go to table 1'\""
echo ""
echo "To stop: kill $LAUNCH_PID  OR  ./stop.sh"
echo ""

wait $LAUNCH_PID 2>/dev/null
