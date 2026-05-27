# Connect a TurtleBot4 in 10 minutes

This tutorial walks you from "TurtleBot4 boots up" to "robobench tells you
the clock is in sync". It does **not** cover full navigation bring-up —
that's `examples/campus_guide/` and a later tutorial.

## What you need

- A TurtleBot4 (any variant). Powered on.
- A workstation on the same network as the robot.
- The robot's IP, SSH user, SSH password, and namespace. (TurtleBot4 defaults:
  user `ubuntu`, password `turtlebot4`. IP and namespace are set during
  initial robot setup — see iRobot's `turtlebot4_setup` docs.)
- Python 3.11+.
- `sshpass` installed locally (`sudo apt install sshpass` on Linux,
  `brew install hudochenkov/sshpass/sshpass` on macOS, or use WSL on Windows).

## Install robobench

```bash
git clone https://github.com/logisticPM/robobench
cd robobench
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Run the clock check

```bash
robobench check \
  --robot turtlebot4 \
  --ip 192.168.50.31 \
  --ssh-user ubuntu \
  --ssh-pass turtlebot4 \
  --namespace turtlebot468
```

Expected output (healthy):

```
Checking clock offset against 192.168.50.31 ...
  clock offset: +0.12s  [OK]
```

Expected output (drift problem):

```
Checking clock offset against 192.168.50.31 ...
  clock offset: +14.32s  [FAIL]
```

## What it told you

`OK` (< 2s offset): TF stamps will line up. You're safe to continue with
Nav2 bring-up.

`WARN` (2-10s): Subscribers using `tf2_ros.Buffer` with default
`cache_time` will sometimes miss transforms. Run `chrony` on both sides
and recheck.

`FAIL` (> 10s): Nothing using ROS time will work reliably. Stop and fix
this before going further. The upstream campus_guide deploy script
includes an automated chrony setup — see
`examples/campus_guide/code/scripts/deploy.sh` for reference until
robobench's Phase B adapter wraps it natively.

## What's next

- Phase B will add `robobench build`, `robobench launch`, `robobench
  activate`, `robobench health` — full bring-up parity with `deploy.sh`.
- Phase C will add the dashboard with live DDS / TF / sensor panels.

Track progress in [docs/superpowers/plans/](../superpowers/plans/).
