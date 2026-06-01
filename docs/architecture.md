# Robobench Architecture

This document covers the four design decisions a contributor needs to
understand before adding a new robot adapter, diagnostic panel, or CLI
subcommand.

## 1. Why an Abstract Base Class (not a Protocol)?

`RobotAdapter` is an `abc.ABC` with `@abstractmethod` decorators. We did NOT
use `typing.Protocol` even though Protocol would give us structural typing.

**Reason:** runtime enforcement. With ABC, instantiating an adapter that's
missing a method fails at construction time with a clear `TypeError`. With
Protocol, the same mistake fails much later — usually at the first method
call that uses the missing piece, often in the middle of a bring-up. For an
academic platform where students will write their own adapters, the
fail-fast behavior matters more than the duck-typing flexibility.

A second-order benefit: ABC subclasses *must* be explicit about their
parent (`class FooAdapter(RobotAdapter):`). This serves as in-code
documentation — anyone reading `robobench/robots/foo.py` immediately knows
what contract it fulfills.

## 2. Why paramiko (not sshpass or fabric)?

`robobench.ssh.SSHClient` wraps paramiko. Earlier drafts used
`sshpass + subprocess`; current code does not.

**Reasons:**
- **No external binary.** `pip install robobench` is enough — no
  `apt install sshpass` or Homebrew formula required. Works on native
  Windows + Git Bash for students who don't yet have WSL set up.
- **Tests mock at the right level.** Tests patch
  `robobench.ssh.paramiko.SSHClient`. With sshpass+subprocess, tests had
  to assert command list shape including auth-flag positioning — brittle.
- **Programmatic SFTP.** `put_text()` writes config files to the robot
  cleanly. With sshpass we needed `cat | ssh user@host 'sudo tee path'`
  which is error-prone around quoting.

We did NOT use `fabric` because (a) it's a heavy dep with strong opinions
about task scheduling that don't match robobench's per-method calls, and
(b) it would force a third abstraction layer (fabric → paramiko →
robobench). Paramiko directly gives us what we need.

## 3. Why lazy `rclpy` import in `robobench.diagnostics`?

`robobench.diagnostics.lifecycle_activator` is a ROS2 Python node — it
extends `rclpy.node.Node` and calls services via lifecycle_msgs and
geometry_msgs. Those are NOT pip packages; they only exist on a ROS2-sourced
system.

The naïve approach — `import rclpy` at module top — would break
`pip install robobench` for anyone without ROS2. Students on Windows
machines (where ROS2 native install is awkward) couldn't even install the
tool to read its help text.

**Solution:** all ROS-dependent imports live inside a `_lazy_imports()`
function that's called as the first statement of `main()`. The module
itself is importable in plain Python; failures only happen at execution
time, with a clear error message that says "source your ROS2 setup".

The `LifecycleActivator(Node)` class definition was also moved inside
`main()` because subclassing `Node` requires `Node` to be importable —
which it isn't at module top. This is the only invasive change required
by lazy imports.

**When you write a new diagnostic node:** put your ROS2 imports in a
`_lazy_imports()` helper, define your `Node` subclass inside `main()`,
and you're good.

## 4. Why shell out to the ROS2 CLI (instead of using rclpy directly)?

`build()`, `launch()`, `health_check()`, etc. all run `subprocess.Popen` /
`subprocess.run` against the `ros2` / `colcon` / `pkill` binaries.

**Reasons (v0.2-era):**
- **No rclpy at module top.** Same reason as decision #3 — keeps the
  adapter pip-installable without ROS2.
- **Matches deploy.sh's mental model.** Anyone who can read the upstream
  bash deploy can read the adapter. Easy onboarding.
- **Subprocess is the same on Linux and Mac.** rclpy-direct probes would
  require a DDS participant in robobench's own process, which adds
  startup cost and FastDDS Discovery Server complexity to every CLI call.

**The cost:** each `ros2 topic echo --once` takes 10-15 seconds with the
default timeout. `health_check` is currently ~45 seconds for four probes.

**Phase C will likely move the diagnostic-panel layer to rclpy direct.**
A persistent FastAPI server can hold one rclpy node alive across many
requests, paying the DDS-discovery cost once. Adapters stay subprocess-
based; only the panel layer switches.

## 5. How robobench connects: the FastDDS Discovery Server

robobench connects the way the upstream deploy did — **not** ROS2's default
Simple Discovery (UDP multicast), but a **FastDDS Discovery Server**. The robot's
onboard computer runs the server (UDP `11811` by default, configurable via
`dds.discovery_port`); the workstation joins it as a client.

Three environment settings must agree for a workstation participant to connect
**and** see the full graph:

| Setting | Value | Why |
|---------|-------|-----|
| `RMW_IMPLEMENTATION` | `rmw_fastrtps_cpp` | Discovery Server is a FastDDS feature; CycloneDDS can't join |
| `ROS_DISCOVERY_SERVER` | `<robot-ip>:<port>` | points the participant at the server (unicast, not multicast) |
| `ROS_SUPER_CLIENT` | `True` | a plain **CLIENT** connects but only sees what the server forwards; a **SUPER_CLIENT** gets the *whole* graph — required for `ros2 topic list` / `ros2 node list` |

The single most common, most confusing failure of this mode is omitting
`ROS_SUPER_CLIENT`: you connect fine but `ros2 topic list` is empty even though
the robot is healthy. (robobench ships a catalog case for exactly this:
`connected-as-client-not-super-client`.)

**Where robobench sets this up:**
- `panels/bridge.py::dds_env` sets all three before `rclpy.init()`, so the
  dashboard connects from `config.yaml` instead of a hand-exported shell env.
- `relay/runner.py` holds two contexts — one with the Discovery-Server vars and
  one with them stripped (Simple Discovery) — to bridge topics across the two
  graphs when discovery drops late joiners.
- `robots/turtlebot4_probe.py` runs `ros2` introspection **over SSH on the
  robot** with `ROS_SUPER_CLIENT=True`, side-stepping the workstation's client
  config entirely; its `discovery_server_ok` check greps the configured
  `dds.discovery_port` on the robot.

**Assumption — server id 0.** `ROS_DISCOVERY_SERVER="ip:port"` encodes the server
id by *list position*, so a single server is always id 0 (matching the upstream
`fastdds_super_client.xml`, whose GUID prefix `44.53.00.5f...` is the canonical
id-0 default). robobench does not support multi-server / non-zero-id setups.

## File-by-file map

| File | Owns |
|------|------|
| `src/robobench/adapter_base.py` | The `RobotAdapter` ABC. The single source of truth for the per-robot contract. |
| `src/robobench/ssh.py` | All paramiko interaction. `SSHClient` + free helpers like `check_workstation_chrony_config`. |
| `src/robobench/_process.py` | Local subprocess. `run_local` is the only function adapters use to invoke local binaries. |
| `src/robobench/config.py` | Reads `config.yaml`, returns adapter constructor kwargs. |
| `src/robobench/cli.py` | argparse + subcommand dispatch. Thin — does not contain robot logic. |
| `src/robobench/diagnostics/lifecycle_activator.py` | The Nav2 lifecycle activator, moved from upstream with lazy rclpy. |
| `src/robobench/robots/turtlebot4.py` | The reference robot adapter. Future adapters mirror this file's shape. |

## How to add a new robot adapter

1. Create `src/robobench/robots/<robot>.py`.
2. `@dataclass class <Robot>Adapter(RobotAdapter):` with the same field
   shape as `TurtleBot4Adapter` (ip, ssh_user, ssh_pass, namespace,
   workspace_dir, build_packages, launch_package, launch_file,
   user_input_topic). Vendor-specific fields go after these.
3. Implement all 7 abstract methods from `RobotAdapter`. Use
   `SSHClient` for anything that talks to the robot; `run_local` for
   anything that runs on the workstation.
4. Add the robot's name to the `--robot` choices in `cli.py` and
   teach `_cmd_check` / `_cmd_bringup` / `_cmd_health` / `_cmd_shutdown`
   how to construct your class. (We'll generalize this dispatch in a
   future plan.)
5. Write unit tests in `tests/unit/robots/test_<robot>.py`. Mock
   `SSHClient`, `run_local`, and `subprocess.Popen` at the module level
   of your adapter file — never call the real ROS2 or paramiko in unit
   tests.

For real-robot validation, add a `@pytest.mark.hardware` test alongside
the unit tests. Those are deselected by default; lab personnel run them
manually.
