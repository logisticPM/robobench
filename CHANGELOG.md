# Changelog

All notable changes to this project will be documented in this file.
Format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
