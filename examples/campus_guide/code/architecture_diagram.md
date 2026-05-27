# CS5335 TurtleBot Campus Guide — Architecture Diagram

*Updated: 2026-03-19 — For Technical Meeting*

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACES                                │
│                                                                             │
│  ┌──────────────────────────┐    ┌──────────────────────────────┐          │
│  │   Dashboard (port 8080)  │    │  Speech Web UI (port 8888)   │          │
│  │   FastAPI + WebSocket    │    │  FastAPI + WebSocket          │          │
│  │                          │    │                               │          │
│  │  • Interactive map       │    │  • Browser voice recognition  │          │
│  │  • Robot pose (live)     │    │    (Web Speech API)           │          │
│  │  • Deploy controls       │    │  • Quick destination cards    │          │
│  │  • AMCL covariance       │    │  • Command history            │          │
│  │  • Chat history          │    │  • Robot reply display        │          │
│  │  • Nav progress bar      │    │                               │          │
│  │  • API key management    │    │                               │          │
│  │  • Set Pose (click map)  │    │                               │          │
│  └────────────┬─────────────┘    └──────────────┬───────────────┘          │
│               │                                  │                          │
└───────────────┼──────────────────────────────────┼──────────────────────────┘
                │ WebSocket                        │ WebSocket
                ▼                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          ROS 2 TOPIC INTERFACE                              │
│                                                                             │
│   /user_input ──────────────────►  LLM Planner                             │
│   /robot_reply  ◄────────────────  LLM Planner                             │
│   /tool_cmd     ──────────────►  Task Executor                             │
│   /tool_result  ◄──────────────  Task Executor                             │
│   /system_status ◄──────────────  Task Executor (1 Hz)                     │
│   /nav_progress  ◄──────────────  Task Executor (every 3s during nav)      │
│   /{ns}/initialpose ────────────►  AMCL                                    │
│   /{ns}/amcl_pose   ◄──────────  AMCL                                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                    LAPTOP — ROS 2 Navigation Stack                          │
│                    (namespace: /turtlebot468)                                │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      LLM LAYER (Phase 1.2)                           │  │
│  │                                                                       │  │
│  │  ┌─────────────────────────┐    ┌──────────────────────────────┐     │  │
│  │  │     LLM Planner         │    │      Task Executor            │     │  │
│  │  │  (llm_planner_node.py)  │───►│  (task_executor_node.py)      │     │  │
│  │  │                         │    │                                │     │  │
│  │  │  • Claude via OpenRouter│    │  7 Tools:                     │     │  │
│  │  │  • 7 tool definitions   │    │  • navigate_to(location)      │     │  │
│  │  │  • Regex fast-path      │    │  • get_robot_position()       │     │  │
│  │  │  • Retry + backoff      │    │  • cancel_navigation()        │     │  │
│  │  │  • History trimming     │    │  • clear_costmap()            │     │  │
│  │  │                         │    │  • get_navigation_status()    │     │  │
│  │  │  Fast path patterns:    │    │  • speak(text)                │     │  │
│  │  │  "go to X" → navigate   │    │  • relocalize()              │     │  │
│  │  │  "stop"    → cancel     │    │                                │     │  │
│  │  │  "where"   → position   │    │  Safety:                      │     │  │
│  │  │                         │    │  • AMCL covariance monitor    │     │  │
│  │  │  /tool_cmd ────────────►│    │  • Goal pre-validation        │     │  │
│  │  │  /tool_result ◄─────────│    │  • Nav timeout (120s)         │     │  │
│  │  └─────────────────────────┘    └──────────────┬───────────────┘     │  │
│  │                                                 │                     │  │
│  └─────────────────────────────────────────────────┼─────────────────────┘  │
│                                                     │ Nav2 ActionClient     │
│  ┌──────────────────────────────────────────────────┼────────────────────┐  │
│  │                       NAV2 STACK                  │                    │  │
│  │                                                   ▼                    │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐     │  │
│  │  │ map_server   │  │    AMCL      │  │    bt_navigator          │     │  │
│  │  │ (static map) │  │ (particle    │  │  (navigate_to_pose       │     │  │
│  │  │              │─►│  filter)     │  │   action server)         │     │  │
│  │  │ 349x406 @    │  │              │  │                          │     │  │
│  │  │ 0.05 m/cell  │  │ 200-3000    │  └────────┬─────────────────┘     │  │
│  │  └──────────────┘  │ particles   │           │                       │  │
│  │                     └──────────────┘           ▼                       │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐     │  │
│  │  │ planner_     │  │ controller_  │  │   behavior_server        │     │  │
│  │  │ server       │  │ server       │  │                          │     │  │
│  │  │ (NavFn)      │  │ (DWB local)  │  │   spin, backup, wait,   │     │  │
│  │  │              │  │              │  │   drive_on_heading,      │     │  │
│  │  │ global_      │  │ local_       │  │   assisted_teleop       │     │  │
│  │  │ costmap      │  │ costmap      │  │                          │     │  │
│  │  └──────────────┘  └──────┬───────┘  └──────────────────────────┘     │  │
│  │                           │                                            │  │
│  │  ┌──────────────┐  ┌─────┴────────┐  ┌──────────────────────────┐     │  │
│  │  │ smoother_    │  │ velocity_    │  │   waypoint_follower      │     │  │
│  │  │ server       │  │ smoother     │  │                          │     │  │
│  │  └──────────────┘  └──────┬───────┘  └──────────────────────────┘     │  │
│  │                           │ /cmd_vel                                   │  │
│  └───────────────────────────┼───────────────────────────────────────────┘  │
│                               │                                             │
│  ┌────────────────────────────┼──────────────────────────────────────────┐  │
│  │  SUPPORT NODES             │                                          │  │
│  │                            │                                          │  │
│  │  odom_tf_publisher ─── publishes odom→base_link TF from /odom        │  │
│  │                                                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                               │                                             │
└───────────────────────────────┼─────────────────────────────────────────────┘
                                │
          FastDDS Discovery Server (UDP :11811 on RPi)
          RMW: rmw_fastrtps_cpp | Laptop = SUPER_CLIENT
                                │
┌───────────────────────────────┼─────────────────────────────────────────────┐
│                    RASPBERRY PI 4 (192.168.50.31)                           │
│                    (namespace: /turtlebot468)                                │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  turtlebot4 systemd service                                          │  │
│  │                                                                       │  │
│  │  • fast-discovery-server (UDP :11811)                                 │  │
│  │  • turtlebot4_node          (buttons, LEDs, display)                  │  │
│  │  • turtlebot4_base_node     (I2C bridge to Create3)                   │  │
│  │  • create3_republisher      (republishes Create3 topics)              │  │
│  │  • rplidar_composition      (LIDAR driver)                            │  │
│  │  • joy_linux_node           (joystick input)                          │  │
│  │  • teleop_twist_joy_node    (joystick → cmd_vel)                      │  │
│  │                                                                       │  │
│  │  Published topics:                                                    │  │
│  │    /{ns}/odom        ─── odometry (from Create3 via I2C)              │  │
│  │    /{ns}/scan        ─── laser scan (RPLIDAR A1M8)                    │  │
│  │    /{ns}/tf          ─── transform tree                               │  │
│  │    /{ns}/cmd_vel     ─── (receives) motor commands                    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                               │ I2C (/dev/i2c-3) + USB-C                    │
└───────────────────────────────┼─────────────────────────────────────────────┘
                                │
┌───────────────────────────────┼─────────────────────────────────────────────┐
│                    iROBOT CREATE3 BASE                                      │
│                                                                             │
│  • Differential drive motors                                                │
│  • Wheel encoders → odometry                                                │
│  • Bump/cliff sensors                                                       │
│  • Battery management                                                       │
│  • Docking station detection                                                │
│  • Internal clock (drifts — needs NTP sync)                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Deployment Flow (deploy.sh)

```
┌──────────────────────────────────────────────────────────────────────┐
│                         deploy.sh (9 steps)                          │
│                                                                      │
│  Step 1: Clock Sync                                                  │
│  ├─ Chrony NTP: Laptop (stratum 10) → RPi (stratum 11) → Create3   │
│  ├─ Auto-install chrony on RPi                                       │
│  ├─ Verify drift ≤ 2s                                                │
│  └─ Restart turtlebot4 service                                       │
│                                                                      │
│  Step 2: Build                                                       │
│  └─ colcon build --packages-select campus_nav_llm                    │
│                                                                      │
│  Step 3: Launch                                                      │
│  ├─ Restart ROS 2 daemon (SUPER_CLIENT)                              │
│  └─ ros2 launch navigation_mode.launch.py (background)               │
│      └─ Starts 10 nodes (NO lifecycle_managers)                      │
│                                                                      │
│  Step 4: Wait for Nodes                                              │
│  └─ Poll ros2 node list until ≥9 nodes (60s timeout)                │
│                                                                      │
│  Step 5: Lifecycle Activation (NEW — lifecycle_activator.py)         │
│  ├─ Single persistent DDS participant (vs 18 CLI calls before)       │
│  ├─ Phase 1: Configure all 9 nodes                                   │
│  ├─ Phase 2: Activate map_server                                     │
│  ├─ Phase 3: Activate AMCL (right after map_server)                  │
│  ├─ Phase 4: Reload map (transient_local fallback)                   │
│  ├─ Phase 5: Activate remaining 7 Nav2 nodes                        │
│  └─ Fallback: CLI activation if activator fails                      │
│                                                                      │
│  Step 6: Health Check                                                │
│  └─ Wait for navigate_to_pose action server (120s)                   │
│                                                                      │
│  Step 7: Set Initial Pose                                            │
│  └─ Publish to /{ns}/initialpose                                     │
│                                                                      │
│  Step 8: Wait for LLM Nodes                                         │
│  └─ task_executor + llm_planner (60s timeout)                        │
│                                                                      │
│  Step 9: Verification                                                │
│  └─ Check /user_input, /tool_cmd subscribers, action server          │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

## Lifecycle Activation Detail (Key Innovation)

```
PROBLEM: FastDDS Discovery Server + ros2 lifecycle CLI
  • Each CLI call = new DDS participant = full re-discovery (2-3s each)
  • 18 calls × 3s = 54s+ minimum (ros2cli #779)
  • FastDDS drops service responses from short-lived participants (rmw_fastrtps #392)
  • Discovery Server filters endpoints for non-matching participants (#499)

SOLUTION: lifecycle_activator.py — single persistent DDS participant

  ┌───────────────────────────────────────────────────┐
  │          lifecycle_activator node                  │
  │          (1 DDS participant, 18 service clients)   │
  │                                                    │
  │  Discovery: ~22s (one-time cost)                   │
  │                                                    │
  │  Phase 1: Configure all 9 nodes         (~12s)     │
  │  ├─ map_server     ──► inactive                    │
  │  ├─ amcl           ──► inactive                    │
  │  ├─ controller_server ► inactive                   │
  │  ├─ smoother_server  ──► inactive                  │
  │  ├─ planner_server   ──► inactive (loads costmap)  │
  │  ├─ behavior_server  ──► inactive (loads plugins)  │
  │  ├─ bt_navigator     ──► inactive                  │
  │  ├─ waypoint_follower ► inactive                   │
  │  └─ velocity_smoother ► inactive                   │
  │                                                    │
  │  Phase 2: Activate map_server           (~0.01s)   │
  │  └─ Publishes /map (transient_local)               │
  │                                                    │
  │  Phase 3: Activate AMCL                 (~0.01s)   │
  │  └─ Subscribes /map (receives map immediately)     │
  │                                                    │
  │  Phase 4: Reload map                    (~15s)     │
  │  └─ load_map service (fallback if AMCL missed it)  │
  │                                                    │
  │  Phase 5: Activate Nav2 stack           (~0.5s)    │
  │  └─ 7 remaining nodes activated                    │
  │                                                    │
  │  TOTAL: ~35s (vs 90-180s with CLI approach)        │
  └───────────────────────────────────────────────────┘

  Resilience:
  • _get_state() retries 3× on FastDDS response loss
  • _poll_state() waits up to 30s for nodes loading plugins
  • _transition() sends command even if response lost (idempotent)
```

## Network Topology

```
  ┌──────────────────┐          WiFi (ASUS_98)         ┌──────────────┐
  │   Laptop         │◄──────────────────────────────►  │  Router       │
  │  (Alienware m15) │    192.168.50.146                │  ASUS_98      │
  │                  │                                   │               │
  │  Nav2 Stack      │          Ethernet                 │               │──► Internet
  │  LLM Planner     │◄──────────────────────────────►  │               │    (OpenRouter
  │  Dashboard:8080  │    192.168.50.x                   │               │     API)
  │  Speech UI:8888  │                                   └───────────────┘
  │                  │                                          │
  │  DDS: SUPER_     │                                          │ WiFi
  │  CLIENT          │                                          │
  └──────────┬───────┘                                          │
             │                                                   │
             │ FastDDS Discovery Server                         │
             │ UDP :11811                                        │
             │                                                   │
  ┌──────────┴───────┐                                ┌─────────┴──────┐
  │  Raspberry Pi 4  │◄──────── WiFi ────────────────►│                │
  │  192.168.50.31   │    192.168.50.31                │                │
  │                  │                                  │                │
  │  Discovery Server│         I2C + USB-C             │                │
  │  TurtleBot4 Nodes│◄──────────────────────────────►│  Create3 Base  │
  │  RPLIDAR Driver  │    192.168.186.2                │  (motors,odom) │
  │                  │    (internal USB network)        │                │
  └──────────────────┘                                  └────────────────┘
```

## Semantic Map (6 Locations)

```
  Map: 349 × 406 pixels @ 0.05 m/cell (17.45m × 20.3m)
  Origin: (-8.1, -8.64)

  Locations:
  ┌─────────────────────┬─────────┬────────────┬─────────────────────────┐
  │ Name                │ (x, y)  │ Facing     │ Aliases                 │
  ├─────────────────────┼─────────┼────────────┼─────────────────────────┤
  │ front_door          │ 5.19,  2.76 │  0°   │ main entrance           │
  │ back_door           │-1.56,  1.06 │ 180°  │ rear exit               │
  │ table_1             │ 6.54, -0.38 │ 270°  │ desk 1, first table     │
  │ table_2             │ 7.13, -2.24 │ 270°  │ desk 2, second table    │
  │ table_3             │ 7.22, -4.33 │ 270°  │ desk 3, third table     │
  │ charging_station    │ 2.00,  1.00 │   0°  │ dock, charger           │
  └─────────────────────┴─────────┴────────────┴─────────────────────────┘
```

## Known Issues & Workarounds

| Issue | Root Cause | Workaround |
|-------|-----------|------------|
| Nav2 lifecycle_manager can't discover services | FastDDS Discovery Server filters endpoints (Nav2 #3560) | Removed lifecycle_managers; use lifecycle_activator.py |
| `ros2 lifecycle set` CLI is slow (2-3s/call) | New DDS participant per CLI call (ros2cli #779) | Persistent Python node with reusable service clients |
| Service responses silently dropped | FastDDS request/reply topic race (rmw_fastrtps #392) | Retry + poll state instead of trusting response |
| AMCL misses map (transient_local) | Late subscriber under Discovery Server | Ordered activation (map_server → AMCL) + load_map fallback |
| Create3 clock drift | No battery-backed RTC on RPi | Chrony NTP hierarchy (Laptop → RPi → Create3) |
| I2C bus errors | USB-C connection between RPi and Create3 | Physical unplug/replug USB-C cable |
| TF extrapolation warnings | Clock offset between RPi and laptop | transform_tolerance: 5.0s in Nav2 params |

## Test Coverage

```
99 tests across 5 files:
  test_llm_tools.py         — LLM tool call loop, fast path, retry
  test_tool_dispatch.py     — Task executor tool execution
  test_integration.py       — End-to-end: input → LLM → Nav2
  test_location_resolver.py — Semantic map lookup, aliases
  test_semantic_map.py      — JSON schema validation
```
