#!/bin/bash
# activate_nav2.sh — Configure and activate Nav2 lifecycle nodes
#
# Uses --no-daemon to bypass the ROS2 daemon's broken Discovery Server cache.
# Run this AFTER launching navigation_mode.launch.py.
#
# Usage:
#   bash activate_nav2.sh
#   bash activate_nav2.sh turtlebot468   # explicit namespace

set -e

ROBOT_NS="${1:-turtlebot468}"

# DDS Discovery Server settings
export FASTRTPS_DEFAULT_PROFILES_FILE="${FASTRTPS_DEFAULT_PROFILES_FILE:-/home/khouryloaner/CS5335TurtleBot/fastdds_super_client.xml}"
export ROS_SUPER_CLIENT=TRUE

source /opt/ros/humble/setup.bash

echo "============================================"
echo " Nav2 Lifecycle Activator"
echo " Namespace: /${ROBOT_NS}"
echo " Using --no-daemon for Discovery Server"
echo "============================================"

# Localization nodes first, then navigation
LOCALIZATION_NODES=(
    "/${ROBOT_NS}/map_server"
    "/${ROBOT_NS}/amcl"
)

NAVIGATION_NODES=(
    "/${ROBOT_NS}/controller_server"
    "/${ROBOT_NS}/smoother_server"
    "/${ROBOT_NS}/planner_server"
    "/${ROBOT_NS}/behavior_server"
    "/${ROBOT_NS}/bt_navigator"
    "/${ROBOT_NS}/waypoint_follower"
    "/${ROBOT_NS}/velocity_smoother"
)

activate_node() {
    local node="$1"
    local short_name="${node##*/}"

    echo -n "  Configuring ${short_name}... "
    if ros2 lifecycle set "$node" configure --no-daemon 2>/dev/null; then
        echo "OK"
    else
        echo "FAILED (may already be configured)"
    fi

    sleep 1

    echo -n "  Activating  ${short_name}... "
    if ros2 lifecycle set "$node" activate --no-daemon 2>/dev/null; then
        echo "OK"
    else
        echo "FAILED (may already be active)"
    fi
}

echo ""
echo "--- Phase 1: Localization (map_server + AMCL) ---"
echo "Waiting 5s for nodes to start..."
sleep 5

for node in "${LOCALIZATION_NODES[@]}"; do
    activate_node "$node"
    sleep 1
done

echo ""
echo "--- Phase 2: Navigation ---"
echo "Waiting 5s for localization to settle..."
sleep 5

for node in "${NAVIGATION_NODES[@]}"; do
    activate_node "$node"
    sleep 1
done

echo ""
echo "============================================"
echo " Activation complete!"
echo " Check with: ros2 lifecycle nodes --no-daemon"
echo "============================================"
