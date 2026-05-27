#!/bin/bash
source ~/CS5335TurtleBot/install/setup.bash

echo "Waiting 15s for nodes to be discoverable..."
sleep 15

NODES="map_server amcl controller_server smoother_server planner_server behavior_server bt_navigator waypoint_follower velocity_smoother"

for node in $NODES; do
  echo "=== $node ==="
  state=$(ros2 lifecycle get /turtlebot468/$node 2>/dev/null || echo "unknown")
  echo "  current: $state"
  if echo "$state" | grep -q "unconfigured"; then
    timeout 15 ros2 lifecycle set /turtlebot468/$node configure 2>&1 || echo "  configure timed out"
    sleep 2
  fi
  state=$(ros2 lifecycle get /turtlebot468/$node 2>/dev/null || echo "unknown")
  if echo "$state" | grep -q "inactive"; then
    timeout 15 ros2 lifecycle set /turtlebot468/$node activate 2>&1 || echo "  activate timed out"
    sleep 2
  fi
  state=$(ros2 lifecycle get /turtlebot468/$node 2>/dev/null || echo "unknown")
  echo "  final: $state"
done

echo ""
echo "=== Setting initial pose (near charging dock) ==="
ros2 topic pub --once /turtlebot468/initialpose geometry_msgs/msg/PoseWithCovarianceStamped '{header: {frame_id: "map"}, pose: {pose: {position: {x: 4.5, y: 1.5, z: 0.0}, orientation: {w: 1.0}}}}'

echo ""
echo "=== Checking amcl_pose ==="
timeout 10 ros2 topic hz /turtlebot468/amcl_pose 2>&1
