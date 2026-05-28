# Full bring-up walkthrough

You've already run `robobench check` from the [10-minute tutorial](connect-turtlebot4.md).
Now we bring the whole Nav2 stack up and verify it's healthy.

## Prerequisites

- A TurtleBot4 reachable on the network.
- ROS2 (Humble or Jazzy) installed on the workstation, with `colcon`, `ros2`,
  `rclpy`, `lifecycle_msgs`, `geometry_msgs`, and `nav2_*` packages.
- The `campus_guide` example workspace built locally (or your own ROS2 workspace
  containing the `campus_nav_llm` package).
- A `config.yaml` matching the upstream schema — copy from
  `examples/campus_guide/code/config.yaml`.
- A map YAML (e.g. `examples/campus_guide/code/campus_guide_bot/.../my_map.yaml`).

## Run it

```bash
robobench bringup \
  --robot turtlebot4 \
  --config ./config.yaml \
  --workstation-ip 192.168.50.10 \
  --map-yaml /abs/path/to/my_map.yaml \
  --initial-pose 5.19 2.56 0.0
```

Output is five labelled phases:

```
[1/5] clock sync (running) ...
[2/5] build (running) ...
[3/5] launch ...
[4/5] activate lifecycle ...
[5/5] health check ...
  overall: HEALTHY
    clock_offset: OK
    amcl_pose: OK
    navigate_to_pose_action: OK
    nav_subscribers: OK
```

If something is wrong, the phase that failed surfaces a `RuntimeError` with
actionable stderr. Each phase is independently runnable:

| Phase | Standalone command |
|-------|-------------------|
| 1 | (clock sync is not standalone in v0.2 — runs inside bringup; use `robobench check` to read the offset) |
| 2 | `colcon build --packages-select campus_nav_llm` (in your workspace) |
| 3 | `ros2 launch campus_nav_llm navigation_mode.launch.py` |
| 4 | `robobench-lifecycle-activator --namespace turtlebot468 --map-yaml /path/to/my_map.yaml` |
| 5 | `robobench health --robot turtlebot4 --config ./config.yaml` |

## When something fails

Run `robobench health --robot turtlebot4 --config ./config.yaml` again to get
the JSON report. Each entry has a `status` and, where applicable, a `detail`
field with the failure mode. Common patterns:

- `clock_offset: FAIL` — clock_sync didn't take. SSH manually, run
  `sudo chronyc -a makestep`.
- `amcl_pose: FAIL` — AMCL didn't activate, or initial pose is wrong. Re-run
  `robobench bringup` with a correct `--initial-pose`.
- `navigate_to_pose_action: FAIL` — Nav2 lifecycle didn't fully activate.
  Re-run `robobench-lifecycle-activator` and read its log under
  `~/.campus_nav_logs/`.

## Stopping

```bash
robobench shutdown --robot turtlebot4 --config ./config.yaml
```

Zeros `/cmd_vel`, kills the launcher PID, then `pkill -9`s the Nav2 nodes.

## Platform notes

- **Linux / macOS:** all commands work natively.
- **Windows:** the adapter shells out to `pkill` and writes `/tmp/robobench_launch.pid`.
  Use WSL on Windows for the full bring-up path. `robobench check` (no `pkill`,
  no `/tmp/`) works on native Windows + Git Bash since v0.2.

## Next

Phase C will replace `bringup` with a browser-driven wizard that runs the
same steps interactively, surfacing failures with one-click fixes.
