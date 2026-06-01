# Changelog

All notable changes to this project will be documented in this file.
Format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.15.0a0] — 2026-05-31

### Changed
- Promoted the hardcoded failure catalog into a robot-agnostic, versioned **case**
  format under `robobench/data/cases/*.yaml`, loaded via the new `robobench.cases`
  module. The dashboard panels are unchanged; fixes are now data — deduped and
  contributable as plain files.

### Added
- `robobench.cases`: `Case`, `load_cases`, `find_cases`, `validate_case`, and the
  six-value `SUBSYSTEMS` vocabulary (`networking`, `time_sync`, `transform`,
  `sensor`, `lifecycle`, `base`).
- A `base` case for the previously-uncatalogued `odom_publishing` failure.

## [0.14.0a0] — 2026-05-30

### Added

- **`robobench watch`** — a long-running deterministic supervisor. It probes the
  robot on an interval (lite SSH probe) and, **monitor-only by default**, prints a
  heartbeat + records to the flight recorder + alerts on unhealthy state. With
  `--auto-recover` it invokes the recovery engine, gated by a cooldown
  (`--recover-cooldown`) and an attempt cap (`--max-recover-attempts`) that
  escalates to monitor-only ("needs human") on repeated failure or `NEEDS_HUMAN`;
  a return to healthy resets the counter. The nuclear Create3 reboot is never
  reachable from `watch`. New pure, fully-injectable
  `robobench.recovery.supervisor.run_supervisor`.

### Notes

- `--auto-recover` auto-restarts robot services unattended based on logic that is
  unit-tested but not yet hardware-validated. Validate the recovery loop on a real
  robot before enabling it unattended; the monitor-only default reflects this.

## [0.13.0a0] — 2026-05-30

### Added

- **`robobench report`** — renders the flight-recorder `events_*.jsonl` session
  logs (written by `recover`/`preflight`) into a human-readable post-mortem:
  a timeline of each probe's failing layer, each recovery action, and the final
  outcome, plus a one-line summary. Defaults to the latest log in
  `~/.robobench/logs/`, or takes a path. New pure module `robobench.eventreport`
  (`latest_event_log`/`parse_events`/`format_report`). Closes the
  "we record diagnostics but never read them" gap.

## [0.12.1a0] — 2026-05-30

### Fixed

- **Clock sync reads drift before chrony converges.** `setup_clock_sync` now
  issues `sudo chronyc -a makestep` (over SSH) immediately after restarting
  chrony, then waits `settle_s` seconds (default 3.0, injectable for tests)
  before reading `date +%s`. Previously the drift figure reflected the
  pre-sync gap because the clock hadn't stepped yet.
- **Initial pose not passed to lifecycle activator.** `activate_lifecycle` now
  accepts a keyword-only `initial_pose: tuple[float, float, float] | None`
  parameter. When provided, `--initial-pose-x/y/yaw` flags are appended to the
  `robobench-lifecycle-activator` command so AMCL receives the correct starting
  pose during the activation sequence instead of defaulting to (0, 0, 0). The
  ABC and CLI `bringup` are updated in step.
- **lifecycle_activator wrote logs to `~/.campus_nav_logs/`** (the upstream
  project's directory) instead of `~/.robobench/logs/`, inconsistent with the
  flight recorder. `_LOG_DIR` is now `Path.home() / ".robobench" / "logs"`.

## [0.12.0a0] — 2026-05-30

### Added

- **`robobench init`** — scaffolds a commented starter `config.yaml` (active
  `robot`/`dds` blocks, optional `workspace`/`build`/`launch`/`health`/`known_poses`
  sections shown commented as inline docs). `--ip`/`--ssh-user`/`--ssh-pass`/
  `--namespace` pre-fill the robot block; `--output` (default `./config.yaml`) and
  `--force` control the target. `robobench.config.render_config_template` is the
  pure renderer. Gives new users a quick on-ramp instead of copying the
  campus-specific example out of `examples/`.

## [0.11.2a0] — 2026-05-30

### Fixed

- `main()` now catches `FileNotFoundError` and `ValueError` raised during
  command dispatch and prints a clean `error: …` message to stderr (exit 2)
  instead of a raw traceback. Affects all config-loading subcommands:
  `bringup`, `health`, `shutdown`, `preflight`, `recover`, `bridge`, `odom-tf`,
  `dashboard`.
- `recover --dry-run` now prints distinct messages for three cases:
  healthy robot (`robot is healthy; nothing to recover`), unreachable robot
  (`robot unreachable (ping failed) — check power/network; recovery cannot fix
  this remotely`), and a stuck robot with no non-nuclear ladder action available.
  Previously all three printed the misleading `healthy or nothing to try`.

## [0.11.1a0] — 2026-05-30

### Fixed

- `bringup`, `health`, and `shutdown` no longer crash with `TypeError` when
  `config.yaml` contains `dds.discovery_port`. A new `_adapter_from_config()`
  helper drops that config-only key before forwarding kwargs to
  `TurtleBot4Adapter`.
- `robobench check` (and any SSH-using command) now shows a clean error message
  instead of a raw paramiko traceback when the robot is unreachable: `SSHClient`
  now catches `OSError` subclasses (`TimeoutError`, `ConnectionRefusedError`,
  etc.) alongside `paramiko.SSHException` and wraps them into `RuntimeError`.
- `run_local` no longer raises an uncaught `FileNotFoundError` when the
  requested binary is missing (e.g. `ros2` not sourced). It now returns a
  `ProcessResult` with `returncode=127` and a `command not found` message in
  `stderr`, matching POSIX shell convention.

### Changed

- README rewritten to reflect the current feature set (was stuck at "What v0.2
  ships"): all nine CLI subcommands, the diagnostics dashboard + connectivity
  panel + one-click recover, the DDS relay / odom-TF workarounds, and a status
  note that nothing is hardware-validated yet.

## [0.11.0a0] — 2026-05-30

### Added

- **One-click Recover in the dashboard.** The connectivity card gains
  **Preview** (instant plan from the current diagnosis) and **Apply** (runs the
  recovery engine in a background thread, streaming progress to a polled status
  endpoint). `RecoveryJob` (thread-safe status + engine event sink),
  `RecoveryController` (single-flight, `allow_reboot=False`), `POST /api/recover`
  + `GET /api/recover/status`. The nuclear Create3 reboot is never reachable from
  the web (CLI-only); disabled in demo mode.

## [0.10.0a0] — 2026-05-30

### Added

- **Dashboard DDS-blind fallback.** A new **Connectivity** panel runs a lite SSH
  probe (`TurtleBot4Probe.read_connectivity()`) on a slow background thread and
  shows a layered ladder (RPi → Discovery Server → clock → Create3 topics → TB4
  nodes) with the first broken layer + its fix. When the DDS panels go blank,
  this one explains *why*. `robobench.panels.connectivity` (pure analyzer),
  `connectivity_probe.run_connectivity_probe` (non-overlapping loop),
  `GET /api/panels/connectivity`, per-aspect catalog fixes.
- `robobench dashboard --no-ssh-probe` / `--ssh-probe-interval` (default 20s).

## [0.9.1a0] — 2026-05-29

### Added

- **Named poses.** `robobench bringup --pose front_door` resolves from a
  `known_poses` map in config.yaml (or accepts a raw `'x y theta'`). New
  `robobench.config.load_known_poses` / `resolve_pose`. `--initial-pose` is now
  optional (one of the two is required). Ports upstream deploy.sh `--pose`.

## [0.9.0a0] — 2026-05-29

### Changed

- **Graceful shutdown.** `TurtleBot4Adapter.shutdown()` now SIGTERMs the nav
  stack, waits, then SIGKILLs stragglers, runs `fastdds shm clean` (no more
  leaked /dev/shm segments — FastDDS#2790), and restarts the ros2 daemon.
- **Lifecycle CLI fallback.** `activate_lifecycle()` falls back to per-node
  `ros2 lifecycle set configure/activate` if the persistent activator fails,
  instead of giving up (mirrors upstream deploy.sh).

## [0.8.0a0] — 2026-05-29

### Added

- **Flight recorder** (`robobench.eventlog`): JSONL session logs of every
  diagnostics/recovery run. `recover` and `preflight` now write
  `~/.robobench/logs/events_*.jsonl` and print the path; the recovery engine
  emits `probe`/`action`/`outcome` events. Ports upstream `event_logger.py`.

## [0.7.0a0] — 2026-05-29

### Added

- **`robobench odom-tf`** — republishes the odom->base_link TF when the Create3
  firmware doesn't bridge it (ports upstream `odom_tf_publisher.py`). Closes the
  "TF panel detects a broken odom edge but can't fix it" gap.
- TF failure-catalog entry now points at `robobench odom-tf`.

## [0.6.0a0] — 2026-05-29

### Added

- **`robobench bridge`** — DDS topic relay. Republishes robot topics
  (odom/scan/imu/tf/tf_static) from the FastDDS Discovery-Server graph onto the
  workstation's Simple-Discovery graph, and relays `cmd_vel` back. Survives
  Discovery-Server late-joiner drops (Nav2 #3560). Ports upstream `dds_bridge.py`
  + `bridge_topics.sh` as a testable pure-core (`robobench.relay.specs`) + lazy
  rclpy runner.
- `robobench._rosenv.require_rclpy()` — shared, consistent "you need ROS2" guard.
- Tutorial: `docs/tutorials/bridging-dds-topics.md`.

## [0.5.1a0] — 2026-05-29

### Fixed

- **Dashboard now connects from `config.yaml`.** `robobench dashboard` sets the
  FastDDS Discovery Server env (`ROS_DISCOVERY_SERVER` from `robot.ip` +
  `dds.discovery_port`, plus `RMW_IMPLEMENTATION`/`ROS_SUPER_CLIENT`) before
  rclpy initializes — no manual `export` needed, matching the SSH commands.
- **Clock panel works against a real robot.** The bridge computes a clock-offset
  proxy from incoming LiDAR scan header stamps vs. local time (was always
  `UNKNOWN` in non-demo mode). Sign convention matches `check_clock_offset`.

### Added

- `robobench.config.load_adapter_config` now returns `discovery_port`
  (from `dds.discovery_port`, default 11811).
- `robobench.panels.bridge.dds_env` and `clock_offset_from_stamp` pure helpers.

## [0.5.0a0] — 2026-05-29

### Added

- **Convergence-loop recovery engine** (`robobench.recovery`): observe →
  fix the most-upstream failing aspect with the cheapest action → re-observe →
  repeat, with an escalation ladder, global deadline, no action repeated, and
  the Create3 reboot gated behind `--allow-reboot`. Fully unit-tested via an
  injected probe + actions (no hardware needed).
- `RobotState` / `RobotProbe` / `RecoveryActions` interfaces; `TurtleBot4Probe`
  (structured detection, 2-sample odom stability, defensive parsing) and
  `TurtleBot4RecoveryActions` (idempotent atomic fixes).
- CLI: `robobench preflight` (read-only diagnosis) and `robobench recover`
  (`--dry-run`, `--allow-reboot`, `--deadline`).
- Tutorial: `docs/tutorials/recovering-a-stuck-robot.md`.

### Notes

- Replaces the upstream's brittle linear `full_recovery` script. The atomic
  actions are the upstream's proven commands; the *orchestration* is rebuilt
  as a testable convergence loop. See the Phase D plan for the post-mortem of
  why the linear chain was unreliable (fuzzy detection incl. an always-false
  `\{ns}\odom` bug, hardcoded timing, over-eager Create3 reboot, no idempotency).

## [0.4.0a0] — 2026-05-29

### Added

- **Visual diagnostic dashboard** served at `/` by `robobench dashboard`:
  vanilla-JS, no build step, native ES modules. Four live panels (clock,
  sensor-rate sparkline, TF tree, DDS node graph) polling the v0.3 panel API,
  each showing failure-catalog fixes inline when red.
- Vendored `cytoscape.js` (TF tree + DDS graph) and `uPlot` (sensor sparkline)
  under `src/robobench/panels/static/lib/` — works offline / on locked-down
  lab networks. Both MIT (see NOTICE).
- `robobench dashboard --demo` + `robobench.panels.demo.seed_demo_state` —
  populates synthetic data so the whole dashboard is viewable with no robot
  and no ROS2. A refresh loop keeps the demo's "fresh" TF edges fresh.
- FastAPI now serves the packaged static frontend (`StaticFiles` + `/` route);
  `static/**/*` ships in the wheel.
- `DiagnosticState.clear_scans()`.

### Fixed

- `build_dds_graph` now normalizes node-name slash prefixes, so `/map_server`
  and `map_server` compare equal (avoids a silent all-missing false positive).
- Demo mode no longer inflates the sensor rate on re-seed, and renders the TF
  tree correctly (explicit `cy.fit`); cytoscape graphs only rebuild when their
  structure changes. (All four found via real-browser verification.)

### Notes

- WebSocket live-push is still deferred; the frontend polls every 1–2s.

## [0.3.0a0] — 2026-05-28

### Added

- `robobench.panels` package — the diagnostic backend:
  - `DiagnosticState`: thread-safe live-data container.
  - `analyzers`: pure functions — clock classifier, topic-rate, TF graph with
    stale-edge detection, DDS node-presence graph.
  - `catalog`: failure catalog mapping each check to cause/fix/link.
  - `bridge`: lazy-rclpy node that fills DiagnosticState from `/scan`, `/tf`,
    and the live node list.
  - `server`: FastAPI app exposing `/api/panels/{clock,sensors,tf,dds}` JSON
    endpoints, each enriched with catalog fix hints on WARN/FAIL.
- `robobench dashboard` CLI subcommand — starts the bridge thread + server.
- `dashboard` optional dependency group (`pip install 'robobench[dashboard]'`).
- Tutorial: `docs/tutorials/diagnosing-with-dashboard.md`.

### Notes

- The visual frontend (cytoscape.js TF/DDS graphs, uPlot sensor sparklines) is
  Phase C-2 — this release ships the JSON API the frontend will consume.

## [0.2.1a0] — 2026-05-28

### Added

- `robobench.ssh.check_workstation_chrony_config` — verifies the workstation's
  chrony.conf has the `allow` and `local stratum` lines required for the
  robot to follow it as an NTP source. Surfaces as `workstation_chrony` in
  `setup_clock_sync`'s report.
- `TurtleBot4Adapter` gained four optional config fields with v0.2-compatible
  defaults: `build_packages`, `launch_package`, `launch_file`,
  `user_input_topic`. Set them in `config.yaml` (`build.packages`,
  `launch.package`, `launch.file`, `health.user_input_topic`) to point
  robobench at any ROS2 workspace — not just campus_guide.
- `docs/architecture.md` — documents the ABC, paramiko, lazy rclpy, and
  subprocess design decisions for contributors.

### Changed

- `TurtleBot4Adapter.workspace_dir` is now `str | None` (was `str` with a
  misleading `~/CS5335TurtleBot` default). `build()` raises a clear
  `ValueError` if it's needed but not set.
- `build()` / `launch()` / `health_check()` no longer hard-code
  `campus_nav_llm`-specific names; they read from the new dataclass fields.
- `ui/README.md` now leads with a status banner clarifying the dashboard
  and speech UI are imported v0 baseline and not yet wired into robobench.

### Fixed

- `setup_clock_sync` no longer silently reports success when the workstation
  itself isn't configured to serve NTP. The report's new `workstation_chrony`
  field surfaces a `WARN` with an actionable fix when chrony.conf is missing
  the required lines.

## [0.2.0a0] — 2026-05-27

### Added

- `robobench.ssh.SSHClient` — paramiko-based SSH wrapper (replaces `sshpass`).
- `robobench._process.run_local` — single mock point for adapter subprocess calls.
- `robobench.config.load_adapter_config` — load adapter kwargs from `config.yaml`.
- `robobench.diagnostics.lifecycle_activator` — Nav2 lifecycle activator, moved
  from upstream. Lazy `rclpy` import so the module is importable without ROS2.
- `TurtleBot4Adapter.setup_clock_sync` — chrony + Create3 NTP automation.
- `TurtleBot4Adapter.build / launch / activate_lifecycle / set_initial_pose /
  health_check / shutdown` — full RobotAdapter contract implemented.
- CLI: `robobench bringup`, `robobench health`, `robobench shutdown`.
- Script entry point: `robobench-lifecycle-activator`.
- Tutorial: `docs/tutorials/bringup-walkthrough.md`.
- `@pytest.mark.hardware` marker for tests that need a real robot
  (skipped by default; opt in with `pytest -m hardware`).

### Changed

- `check_clock_offset` now uses paramiko instead of `sshpass`, making the
  command work on native Windows without external binaries.
- `RobotAdapter.activate_lifecycle` signature gained an optional `map_yaml`
  parameter (backwards-compatible default of `None`).

## [0.1.0a0] — 2026-05-27

Initial release: `RobotAdapter` ABC, `TurtleBot4Adapter` scaffold,
`check_clock_offset` over SSH, `robobench check` CLI, governance, CI.
