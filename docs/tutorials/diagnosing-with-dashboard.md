# Diagnosing a robot with the dashboard (API)

This walks through robobench's diagnostic backend. v0.3 ships the **JSON API**;
the visual frontend lands in a later release. You can drive everything with
`curl` today.

## Start the dashboard

```bash
robobench dashboard --robot turtlebot4 --config ./config.yaml --port 8080
```

This:
1. Starts a persistent ROS2 bridge node (in a daemon thread) that subscribes
   to `/<ns>/scan`, `/tf`, and tracks the visible node list.
2. Serves a diagnostic API on `http://127.0.0.1:8080`.

If ROS2 isn't sourced, the server still starts — panels just report
`UNKNOWN` / empty until a bridge can connect. (You'll see
`[dashboard] bridge not started: ... requires ROS2 ...` on stderr.)

> The dashboard requires the optional extra: `pip install 'robobench[dashboard]'`.

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

## What's next

Phase C-2 adds the visual frontend: a TF tree you can see (cytoscape.js), a
DDS node graph, and live sensor sparklines (uPlot) — all consuming these same
endpoints.
