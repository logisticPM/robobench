# Robobench

> Open-source ROS2 platform for **robot hardware bring-up and debugging** —
> built for students and researchers who need to know *why their robot
> isn't doing what they told it to*.

## The problem

Half a robotics lab's calendar is spent fighting bring-up: DDS discovery
gone wrong, clock drift breaking TF, lifecycle nodes refusing to activate,
sensors silently dropping out. The actual research starts after that's
working. Robobench aims to compress that fight from days to minutes.

## What's here

Robobench is alpha (every release is tagged `…aN`). It is fully unit-tested but
**not yet validated on real hardware** — see *Status & roadmap* below.

**Adapter & bring-up.** A `RobotAdapter` interface, fully implemented by
`TurtleBot4Adapter`: clock sync (chrony + Create3 NTP), colcon build, Nav2
launch, lifecycle activation (with a per-node CLI fallback), named or raw
initial pose, a structured health check, and a graceful shutdown
(SIGTERM → SIGKILL, FastDDS shared-memory clean, ros2 daemon restart).

**Diagnostics dashboard** (`robobench dashboard`) — vanilla-JS, no build step:

- Five live panels: clock offset, LiDAR scan rate, TF tree, DDS node graph, and
  a **Connectivity** panel that SSH-probes the bring-up layers
  (RPi → Discovery Server → clock → Create3 topics → TB4 nodes) so you see
  *which layer* is broken even when DDS itself is blind.
- Each panel shows concrete failure-catalog fixes when it goes red.
- **One-click Recover**: *Preview* the plan, then *Apply* — runs the recovery
  engine in the background and streams progress. (The nuclear Create3 reboot is
  CLI-only, never reachable from the web.)
- `--demo` seeds synthetic data so the whole UI works with no robot and no ROS2.

**Recovery** (`robobench preflight` / `robobench recover`). A convergence-loop
engine: observe → fix the most-upstream failing aspect with the cheapest action
→ re-observe, with an escalation ladder, a global deadline, no action repeated,
and the Create3 reboot gated behind `--allow-reboot`. A JSONL flight recorder
logs every probe/action/outcome.

**Workarounds for flaky DDS.** `robobench bridge` relays robot topics from the
FastDDS Discovery Server onto local Simple Discovery (and `cmd_vel` back) when
discovery drops late joiners; `robobench odom-tf` republishes the
odom → base_link TF when the Create3 firmware doesn't.

## CLI

```bash
pip install -e '.[dashboard]'
robobench --help
```

| Command | What it does |
|---------|--------------|
| `robobench check` | Quick clock-offset diagnostic over SSH (no ROS2 needed) |
| `robobench bringup` | Full Nav2 bring-up: clock, build, launch, activate, pose, health |
| `robobench health` | JSON health report |
| `robobench preflight` | Read-only bring-up diagnosis (no fixes applied) |
| `robobench recover` | Drive a stuck robot back to health (`--dry-run` / `--allow-reboot` / `--deadline`) |
| `robobench dashboard` | Live diagnostic dashboard + one-click recover |
| `robobench bridge` | Relay topics across DDS discovery graphs |
| `robobench odom-tf` | Republish odom → base_link TF |
| `robobench shutdown` | Graceful stop of the navigation stack |

Plus the `robobench-lifecycle-activator` ROS2 node entry point.

## Quick start

- **First time?** `robobench init` writes a starter `config.yaml` (edit the
  `robot:` block, or pass `--ip/--ssh-user/--ssh-pass/--namespace`). Then run any
  command with `--config config.yaml`.
- [10-minute clock check](docs/tutorials/connect-turtlebot4.md)
- [Full bring-up walkthrough](docs/tutorials/bringup-walkthrough.md)
- [Diagnosing with the dashboard](docs/tutorials/diagnosing-with-dashboard.md)
- [Recovering a stuck robot](docs/tutorials/recovering-a-stuck-robot.md)
- [Bridging DDS topics](docs/tutorials/bridging-dds-topics.md)
- [Architecture notes](docs/architecture.md)

## Status & roadmap

Everything through **v0.11** is implemented and unit-tested (200+ tests), but the
SSH / DDS / recovery paths are **mocked in tests and not yet exercised on a real
TurtleBot4**. The next milestone is a real-hardware validation pass of the full
loop (check → bringup → dashboard → break something → preflight → recover).

| Next | Item |
|------|------|
| Validation | Real-hardware pass of bring-up + diagnostics + recovery |
| Phase E | Simulation support (Gazebo / a sim adapter) for hardware-free testing |
| Later | More robot adapters (TurtleBot3, Jackal, custom) to prove the interface generalizes |

Shipped since v0.2: the diagnostic dashboard (panels + connectivity), the
recovery engine and one-click recover, the DDS relay and odom-TF workarounds,
the JSONL flight recorder, named poses, and bring-up hardening.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Code of conduct: Contributor Covenant
v2.1 — see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Apache 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for attribution of
imported reference material.
