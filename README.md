# Robobench

> Open-source ROS2 platform for **robot hardware bring-up and debugging** —
> built for students and researchers who need to know *why their robot
> isn't doing what they told it to*.

## The problem

Half a robotics lab's calendar is spent fighting bring-up: DDS discovery
gone wrong, clock drift breaking TF, lifecycle nodes refusing to activate,
sensors silently dropping out. The actual research starts after that's
working. Robobench aims to compress that fight from days to minutes.

## What v0.1 ships

- A `RobotAdapter` interface that any ROS2 robot can implement.
- A first reference adapter: TurtleBot4.
- A `robobench` CLI that runs hardware diagnostics against a real robot.
- A runnable end-to-end example (`examples/campus_guide/`) imported from
  upstream as a reference integration to benchmark against.
- A baseline web dashboard + speech UI (`ui/`) to be extended in Phase C.

## What v0.1 does NOT ship (and where it's going)

| Coming in | Feature |
|-----------|---------|
| Phase B   | Full extraction of `deploy.sh` into adapter methods |
| Phase C   | Diagnostic panels (DDS visibility, TF tree, sensor health, clock) |
| Phase C   | Browser-based bring-up wizard replacing `deploy.sh` |
| Phase D   | MkDocs tutorial site + GitHub Pages |
| Phase E   | Simulation support (Gazebo / Ignition) |
| Phase E+  | Additional robot adapters (TurtleBot3, Jackal, custom) |

## Install (v0.1)

```bash
pip install -e .
robobench --help
```

## Quick start

See [docs/tutorials/connect-turtlebot4.md](docs/tutorials/connect-turtlebot4.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Code of conduct: Contributor Covenant
v2.1 — see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Apache 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for attribution of
imported reference material.
