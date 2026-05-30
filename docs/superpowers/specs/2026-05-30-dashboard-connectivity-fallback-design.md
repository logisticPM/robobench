# Dashboard DDS-blind Fallback — Design Spec

**Date:** 2026-05-30
**Status:** Approved (brainstorming) — pending implementation plan
**Topic:** A connectivity-probe fallback so the dashboard explains *which layer is broken* when the in-process DDS bridge sees nothing.

## Problem

`robobench dashboard` connects to the robot as an in-process rclpy participant via
the FastDDS Discovery Server (env: `ROS_DISCOVERY_SERVER`, `ROS_SUPER_CLIENT`,
`RMW_IMPLEMENTATION`). It fills `DiagnosticState` from `/scan`, `/tf`, and the live
node list, and serves four panels (clock, sensors, tf, dds).

This path is **"DDS-blind"**: if the Discovery Server itself is down/unreachable, or
the RPi is off, or late joiners get dropped (Nav2 #3560), the dashboard sees *nothing*
— every panel reports `UNKNOWN`/empty and the user gets no explanation of *why*. The
SSH side of robobench already knows how to diagnose this (the recovery
`TurtleBot4Probe` reads a layered `RobotState`), but the dashboard never uses it.

**Goal:** when DDS yields nothing, the dashboard should still tell the user which
layer of the bring-up stack is broken (RPi unreachable? Discovery Server down? clock?
no topics? no Nav2 nodes?) and how to fix it — using the existing SSH probe as a
"ground truth" layer alongside DDS.

## Design decisions (resolved during brainstorming)

1. **Trigger model: always-parallel slow timer** (not lazy-on-blind, not on-demand).
   Rationale — *stability*: it's stateless with respect to DDS, so there's no
   "blind/not-blind" threshold to tune and no flapping (the Discovery Server's node
   list is intermittently visible by nature — that's the whole reason robobench
   exists). It has the fewest moving parts and mirrors the existing, proven pattern
   (the DDS bridge is itself a daemon thread with a 2s `refresh_nodes` timer). It
   degrades gracefully (SSH failure is itself a diagnostic signal) and the diagnosis
   is always available, independent of DDS state or user action.
   - **Non-overlapping single worker:** the loop is `probe(); sleep(interval)`, so the
     effective cadence is `max(interval, probe_duration)` — a slow probe never stacks.

2. **Surfacing: a new 5th "Connectivity" panel** (not a banner, not augmenting the DDS
   panel). It's consistent with the existing one-endpoint-per-panel architecture and
   naturally renders the layered ladder with the first broken layer highlighted.

3. **Probe scope: a connectivity-only lite probe** (not the full `TurtleBot4Probe.read()`).
   It checks `rpi_reachable → discovery_server_ok → clock_synced → create3_topics →
   tb4_nodes_present` and **skips the slow odom 2-sample echo** (~16–30s). Each cycle
   completes in a few seconds → tighter, predictable cadence. odom liveness is already
   covered by the sensor panel (scan rate), so the connectivity panel intentionally
   ignores it.

## Architecture

A second daemon thread in non-demo `robobench dashboard`: a connectivity-probe loop
that periodically runs the lite SSH probe and writes a layered result into
`DiagnosticState`. A new pure analyzer turns that result into a panel payload; a new
endpoint and frontend card render it. Existing code paths (DDS bridge, four panels)
are untouched.

```
config.yaml (ip, ssh_user, ssh_pass, namespace, dds.discovery_port)
        │
        ▼
_cmd_dashboard (non-demo)
        ├── thread 1: run_bridge(...)            [existing DDS path, unchanged]
        └── thread 2: run_connectivity_probe(...) [NEW]
                          │  every ~20s
                          ▼
                 TurtleBot4Probe.read_connectivity() → RobotState (odom ignored)
                          │
                          ▼
                 DiagnosticState.set_connectivity(state)
                          │
        GET /api/panels/connectivity → diagnose(state.connectivity()) → panel JSON
                          │
                          ▼
                 frontend panels/connectivity.js  (5th card: layer ladder + fixes)
```

## Components

### `src/robobench/panels/connectivity.py` (pure — no SSH, no rclpy)
- `CONNECTIVITY_ASPECTS`: ordered tuple of `(aspect_name, human_label)` for the five
  transport layers, upstream→downstream. **Excludes `odom_publishing`.**
- `first_broken_layer(state: RobotState) -> str | None`: the most-upstream failing
  aspect among `CONNECTIVITY_ASPECTS` only (odom is never consulted). `None` if all
  five are OK. `create3_topics` counts as failing when `== 0`.
- `diagnose(state: RobotState | None) -> dict`: returns
  `{"status": "OK"|"FAIL"|"UNKNOWN", "layers": [{"name", "label", "ok"}...],
  "first_broken": str|None, "fixes": [...]}`. `None` input → `UNKNOWN` (probe hasn't
  run / disabled). On `FAIL`, `fixes` come from the failure catalog for the broken layer.
- Imports `RobotState` from `robobench.recovery.state` (panels → recovery is a clean
  downward dependency, same as the rest of panels reusing lower-level types).

### `src/robobench/robots/turtlebot4_probe.py` (lite read)
- Refactor the existing `read()` so the SSH checks live in a private helper that takes
  a `check_odom: bool` flag (DRY — reuse all the existing `ss/date/topic/node` SSH
  commands and defensive parsing).
- `read()` keeps current behavior (`check_odom=True`).
- New `read_connectivity() -> RobotState`: runs the five connectivity checks,
  `check_odom=False`, and sets `odom_publishing=True` as a documented sentinel meaning
  "not checked here" — the connectivity analyzer never reads it. No `panels/` import
  (returns the existing `RobotState`).

### `src/robobench/panels/state.py` (DiagnosticState)
- Add `set_connectivity(state: RobotState | None)` and `connectivity() -> RobotState | None`,
  lock-guarded, included in `snapshot()`. Default `None`.

### `src/robobench/panels/connectivity_probe.py` (the loop — thin, testable)
- `run_connectivity_probe(state, probe, *, interval, sleep=time.sleep, should_stop=None) -> None`:
  loop `state.set_connectivity(probe.read_connectivity())`, each iteration wrapped in
  `try/except Exception` (log to stderr, continue — never kill the thread), then
  `sleep(interval)`; exit when `should_stop()` is true (default: run forever).
  `probe` is any object with `read_connectivity() -> RobotState` (duck-typed, so tests
  inject a fake). No rclpy; importable without ROS2.

### `src/robobench/panels/server.py` (new endpoint)
- `GET /api/panels/connectivity` → `diagnose(app.state.diag.connectivity())`. Pure;
  reads only `DiagnosticState`. No new imports beyond `connectivity.diagnose`.

### `src/robobench/panels/catalog.py` (per-layer fixes)
- Add five new entries to `FAILURE_CATALOG`, **keyed by the connectivity aspect name**
  (so the existing `lookup_fixes(check_name, status)` is reused unchanged):
  `"rpi_reachable"` (power/network/IP), `"discovery_server_ok"` (start
  `discovery.service`; check port 11811 — Nav2 #3560), `"clock_synced"` (chrony
  makestep / `robobench bringup`), `"create3_topics"` (Create3 app / `robobench
  recover`), `"tb4_nodes_present"` (re-run `robobench-lifecycle-activator`). Each is a
  `[{cause, fix, link}]` list. `diagnose()` calls `lookup_fixes(first_broken, "FAIL")`
  to populate the panel's `fixes`. These keys are distinct from the existing
  panel-name keys (`clock_offset`, `sensor_rate`, `tf_tree`, `dds_graph`), so no
  collision.

### `src/robobench/cli.py` (`_cmd_dashboard`)
- Non-demo: after starting the DDS bridge thread, build
  `TurtleBot4Probe(ip, ssh_user, ssh_pass, namespace)` from the already-loaded config
  kwargs and start a second daemon thread running `run_connectivity_probe(...)` with
  `interval = args.ssh_probe_interval` — unless `args.no_ssh_probe`.
- New args: `--no-ssh-probe` (store_true; disable the loop, revert to pure-DDS) and
  `--ssh-probe-interval` (float, default `20.0`).
- Demo: seed a synthetic connectivity `RobotState` (e.g. Discovery Server down) so the
  panel is viewable with no hardware, refreshed by the existing demo loop.

### Frontend `src/robobench/panels/static/`
- `panels/connectivity.js`: poll `/api/panels/connectivity`, render a 5-row ladder
  (each row label + ✓/✗, first-broken highlighted red), show `fixes` when `FAIL`,
  show a neutral "waiting for SSH probe…" when `UNKNOWN`. Mirror the existing panel JS.
- Register the card in `index.html` + style in `style.css` (match existing cards).

## Data flow & lifecycle
1. `robobench dashboard --robot turtlebot4 --config config.yaml` (non-demo).
2. Thread 1 (existing): DDS bridge fills scan/tf/nodes/clock.
3. Thread 2 (new): every ~20s, lite SSH probe → `DiagnosticState.connectivity`.
4. Browser polls all five panels; the connectivity card shows the layered diagnosis.
5. Ctrl+C: both daemon threads die with the process (daemon=True), same as today.

## Error handling & configuration
- **No new config.** Reuses `robot.ssh_user` / `robot.ssh_pass` already in `config.yaml`
  and already loaded by `_cmd_dashboard`.
- SSH failure → probe returns `rpi_reachable=False` (or the loop catches an exception
  and continues); the panel renders that as the diagnosis rather than crashing.
- `--no-ssh-probe` fully disables the thread (pure-DDS behavior, for users with no SSH
  access). When disabled, the panel stays `UNKNOWN`.
- The probe loop never raises out of its thread; one bad cycle is logged and skipped.

## Testing strategy
- **Pure analyzer** (`connectivity.py`): unit-test `first_broken_layer` and `diagnose`
  across each broken-layer combination, all-OK, `create3_topics == 0`, and `None →
  UNKNOWN`. Assert odom is never consulted (a state with `odom_publishing=False` but
  all five connectivity layers OK → `status OK`).
- **Lite probe** (`read_connectivity`): mock SSH (existing probe-test pattern); assert
  the odom echo command is NOT issued and the five checks are.
- **Probe loop** (`run_connectivity_probe`): inject a fake probe + fake sleep +
  `should_stop` returning true after N iterations; assert it writes connectivity each
  iteration and that a probe exception does not stop the loop.
- **Endpoint**: FastAPI TestClient with an injected `DiagnosticState` (connectivity set
  / unset) → assert payload + `UNKNOWN` when unset.
- **Frontend**: browser verification in demo mode (the seeded "Discovery Server down"
  report renders the ladder + fix).
- All existing tests must stay green; the DDS path and four panels are untouched.

## Out of scope (YAGNI)
- No auto-recovery from the dashboard (that's the separate "Recover button" idea).
- No change to the DDS bridge or the four existing panels.
- No generalization beyond TurtleBot4 (the probe is TB4-specific, like the rest).
- No persistence of connectivity history (the flight recorder is separate).

## Honest caveats
- Everything remains mocked/unit-tested; **zero real-hardware validation.**
- This is the **first time the dashboard runs real SSH** (it was pure DDS before). The
  lite probe reuses `TurtleBot4Probe`'s hardware-proven SSH commands, but the
  dashboard-side threading/cadence needs a real-robot pass.
