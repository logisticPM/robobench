# Robobench

> Open-source ROS2 platform for **robot hardware bring-up and debugging** —
> built for students and researchers who need to know *why their robot
> isn't doing what they told it to*.

## The problem

Half a robotics lab's calendar is spent fighting bring-up: DDS discovery
gone wrong, clock drift breaking TF, lifecycle nodes refusing to activate,
sensors silently dropping out. The actual research starts after that's
working. Robobench aims to compress that fight from days to minutes.

## What v0.2 ships

- `RobotAdapter` interface — 7 methods, all implemented on TurtleBot4.
- `TurtleBot4Adapter` covers clock sync (chrony + Create3 NTP), build, launch,
  lifecycle activation, initial pose, structured health check, and graceful shutdown.
- CLI: `robobench check / bringup / health / shutdown`, plus the
  `robobench-lifecycle-activator` ROS2 node entry point.
- Two tutorials: 10-minute clock check, full bring-up walkthrough.
- Reference integration (`examples/campus_guide/`) + UI baseline (`ui/`).

## What v0.2 does NOT ship (and where it's going)

| Coming in | Feature |
|-----------|---------|
| Phase C   | Diagnostic panels (DDS visibility, TF tree, sensor health) |
| Phase C   | Browser-based bring-up wizard replacing `robobench bringup` |
| Phase D   | MkDocs tutorial site + GitHub Pages |
| Phase E   | Simulation support (Gazebo / Ignition) |
| Phase E+  | Additional robot adapters (TurtleBot3, Jackal, custom) |

## Install

```bash
pip install -e .
robobench --help
```

Sub-commands:

- `robobench check` — quick clock diagnostic (no ROS2 required)
- `robobench bringup` — full Nav2 bring-up (requires ROS2 workspace)
- `robobench health` — JSON health report
- `robobench shutdown` — graceful stop

## Quick start

- [10-minute clock check](docs/tutorials/connect-turtlebot4.md)
- [Full bring-up walkthrough](docs/tutorials/bringup-walkthrough.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Code of conduct: Contributor Covenant
v2.1 — see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Apache 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for attribution of
imported reference material.
