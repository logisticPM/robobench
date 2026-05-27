#!/bin/bash
# Start the two-process DDS bridge: Discovery Server <-> Simple Discovery.
# Run this BEFORE launch_nav.sh.
source ~/CS5335TurtleBot/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
# Clear DS vars so the main process starts clean
unset ROS_DISCOVERY_SERVER
unset ROS_SUPER_CLIENT
unset FASTRTPS_DEFAULT_PROFILES_FILE
python3 ~/CS5335TurtleBot/dds_bridge_mp.py
