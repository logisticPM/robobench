# Diagnosing a robot with the dashboard (API)

This walks through robobench's diagnostic backend. v0.3 ships the **JSON API**;
the visual frontend lands in a later release. You can drive everything with
`curl` today.

## Start the dashboard

```bash
robobench dashboard --robot turtlebot4 --config ./config.yaml --port 8080
```

This:
1. Reads `config.yaml` and points rclpy at the robot's FastDDS Discovery
   Server (`robot.ip` + `dds.discovery_port`) — no manual `export` needed.
2. Starts a persistent ROS2 bridge node (daemon thread) subscribing to
   `/<ns>/scan`, `/tf`, and the live node list.
3. Serves the diagnostic API + web UI on `http://127.0.0.1:8080`.

> Requires the optional extra **and** ROS2 sourced in the shell:
> `pip install 'robobench[dashboard]'`, then `source /opt/ros/<distro>/setup.bash`.
> If ROS2 isn't available the server still starts; panels report `UNKNOWN`/empty
> and stderr shows `[dashboard] bridge not started: ... requires ROS2 ...`.

> **Clock panel:** the offset shown is derived from incoming LiDAR scan
> timestamps vs. local time (a clock-drift proxy that also includes negligible
> transport latency). For a pure SSH-measured offset, use `robobench check`.

## Read the panels

Each panel is a GET endpoint returning JSON with a `status` and, when
something's wrong, a `fixes` array of `{cause, fix, link}` from the failure
catalog.

```bash
curl -s localhost:8080/api/panels/clock | jq
```
```json
{
  "status": "FAIL",
  "offset_seconds": 42.0,
  "fixes": [
    {"cause": "Workstation and robot clocks drifted apart.",
     "fix": "Run `robobench bringup` (configures chrony), or manually: ssh <robot> 'sudo chronyc -a makestep'.",
     "link": "https://docs.ros.org/en/rolling/Tutorials/Demos/Time.html"}
  ]
}
```

| Endpoint | What it tells you |
|----------|-------------------|
| `GET /api/panels/clock` | Workstation↔robot clock offset, OK/WARN/FAIL |
| `GET /api/panels/sensors` | LiDAR scan rate (Hz) and whether it's healthy |
| `GET /api/panels/tf` | TF frame graph + which edges are stale/broken |
| `GET /api/panels/dds` | Which expected Nav2 nodes are present vs missing |
| `GET /healthz` | Liveness check (always `{"status":"ok"}`) |

## A typical debug session

"My robot won't navigate." Start the dashboard, then:

```bash
curl -s localhost:8080/api/panels/dds | jq '.missing'
# ["planner_server"]   ← planner never came up

curl -s localhost:8080/api/panels/dds | jq -r '.fixes[0].fix'
# Re-run robobench-lifecycle-activator; check the node's log...
```

The `fixes` come from `robobench.panels.catalog` — concrete next steps, not
just a red light.

## Status thresholds

| Panel | OK | WARN | FAIL |
|-------|----|------|------|
| clock | offset < 2s | 2–10s | ≥ 10s (or UNKNOWN if no data) |
| sensors (scan Hz) | ≥ 5 Hz | 2–5 Hz | < 2 Hz |
| tf | no stale edges | — | any edge stamp older than 1s |
| dds | all expected nodes present | — | any expected node missing |

## The visual dashboard

As of v0.4, `robobench dashboard` serves a web UI at the root URL — open
`http://localhost:8080/` in a browser. Four live panels:

- **Clock offset** — OK/WARN/FAIL pill + current offset.
- **Sensor rate** — a live sparkline (uPlot) of LiDAR scan Hz.
- **TF tree** — the frame graph (cytoscape); stale/broken edges turn red.
- **DDS nodes** — expected Nav2 nodes; missing ones turn red.

Each panel shows the failure-catalog fixes inline when it's red.

### Try it without a robot

```bash
robobench dashboard --robot turtlebot4 --config ./config.yaml --demo
```

`--demo` seeds synthetic data (a healthy clock + sensor, a deliberately broken
TF edge, a missing Nav2 node) so you can see every panel — including its
red/fix states — with no hardware and no ROS2 installed. Great for trying
robobench before you have a robot on the bench.

## What's next

Phase D adds a browser-driven bring-up wizard (interactive, one-click fixes)
and a second robot adapter (TurtleBot3) to prove the `RobotAdapter` interface
generalizes.
