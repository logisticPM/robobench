# Changelog

All notable changes to this project will be documented in this file.
Format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
