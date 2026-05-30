# Robobench Upstream-Parity Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the remaining battle-tested bring-up/diagnostics capabilities from the upstream `CS5335TurtleBot` into robobench, in descending order of value, as independently shippable phases.

**Architecture:** Each phase follows robobench's established "pure core + lazy-rclpy shell" split: rclpy-free logic lives in testable modules; ROS2 I/O lives behind a `require_rclpy()` guard and is smoke-tested only. New long-running helpers (DDS relay, odom→TF) get their own CLI subcommands. Adapter resilience fixes (shutdown, lifecycle) modify `TurtleBot4Adapter` in place with injected `sleep` for testability. Each phase ends in a tagged release.

**Tech Stack:** Python 3.11+, paramiko (SSH), rclpy (lazy), FastAPI/uvicorn (existing dashboard), pytest + pytest-mock, ruff. Windows + Git Bash dev env (`.venv/Scripts/activate`); rclpy is NOT installed locally (lazy-import paths are smoke-tested via monkeypatched ImportError).

---

> ⚠️ **Hardware-validation caveat (Phase 1 only).** The DDS relay is the highest-*value* gap, but its value is conditional on the FastDDS Discovery Server actually being flaky on your hardware (dropping late joiners, GUID churn). The plan is ready to execute, but per the v0.5.1 recommendation, consider confirming the pain on a real TurtleBot4 before investing in Phase 1. Phases 3–5 are pure correctness/resilience and need no hardware to justify.

> **Git note.** Every release task commits + tags. The repo's local git author is already `logisticPM <chn.twu@gmail.com>` — do NOT run `git config`. LF→CRLF warnings on Windows are benign (repo stores LF).

## File Structure

| Phase | Files | Responsibility |
|-------|-------|----------------|
| (shared) | `src/robobench/_rosenv.py` | One `require_rclpy()` guard reused by all lazy-rclpy modules |
| 1 | `src/robobench/relay/specs.py` | Pure: topic relay specs + DDS env split |
| 1 | `src/robobench/relay/runner.py` | Lazy-rclpy dual-context relay loop |
| 1 | `src/robobench/cli.py` (+`bridge`) | `robobench bridge` subcommand |
| 2 | `src/robobench/diagnostics/odom_tf.py` | Pure odom→TF field map + lazy-rclpy republisher |
| 2 | `src/robobench/cli.py` (+`odom-tf`) | `robobench odom-tf` subcommand; catalog fix hint |
| 3 | `src/robobench/eventlog.py` | JSONL flight recorder (EventLogger/NullEventLogger) |
| 3 | `src/robobench/recovery/engine.py` | Engine logs probe/action/outcome |
| 4/5 | `src/robobench/robots/turtlebot4.py` | Graceful shutdown + lifecycle CLI fallback |
| 6 | `src/robobench/config.py` (+`load_known_poses`) | Named-pose registry loader + resolver |
| 6 | `src/robobench/cli.py` (`bringup --pose`) | Named-pose bring-up |

---

## Phase 1 — DDS topic relay (`robobench bridge`) → v0.6.0a0

**Why:** Highest value. When the Discovery Server drops a late joiner or churns GUIDs, plain local ROS2 tools / Nav2 nodes can't see robot topics. The relay republishes robot topics (odom/scan/imu/tf/tf_static) from the Discovery-Server graph onto the workstation's Simple-Discovery graph, and relays `cmd_vel` back. Ports `dds_bridge.py` + `bridge_topics.sh`.

### Task 1.1: Shared `require_rclpy()` guard

**Files:**
- Create: `src/robobench/_rosenv.py`
- Test: `tests/unit/test_rosenv.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_rosenv.py
import builtins

import pytest

from robobench._rosenv import require_rclpy


def test_require_rclpy_raises_when_rclpy_missing(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "rclpy":
            raise ImportError("no rclpy here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="requires ROS2"):
        require_rclpy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_rosenv.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'robobench._rosenv'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/robobench/_rosenv.py
"""Shared ROS2-availability guard.

robobench's pure logic must import without ROS2. Modules that genuinely need
rclpy call require_rclpy() at runtime so the import-time surface stays clean
and the "you need ROS2" error is consistent and actionable.
"""

from __future__ import annotations


def require_rclpy() -> None:
    """Raise a clear RuntimeError if rclpy can't be imported."""
    try:
        import rclpy  # noqa: F401, PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "this command requires ROS2 (rclpy). "
            "source /opt/ros/<distro>/setup.bash, then retry."
        ) from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_rosenv.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/robobench/_rosenv.py tests/unit/test_rosenv.py
git commit -m "feat: add shared require_rclpy() guard for lazy-rclpy modules"
```

### Task 1.2: Pure relay specs + DDS env split

**Files:**
- Create: `src/robobench/relay/__init__.py`
- Create: `src/robobench/relay/specs.py`
- Test: `tests/unit/relay/__init__.py`, `tests/unit/relay/test_specs.py`

- [ ] **Step 1: Create package markers**

```python
# src/robobench/relay/__init__.py
"""DDS topic-relay bridge: republish robot topics across DDS discovery graphs."""
```

```python
# tests/unit/relay/__init__.py
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/relay/test_specs.py
from robobench.relay.specs import bridge_specs, split_discovery_env


def test_bridge_specs_covers_core_topics():
    topics = {s.topic for s in bridge_specs("turtlebot468")}
    assert topics == {
        "/turtlebot468/odom",
        "/turtlebot468/scan",
        "/turtlebot468/imu",
        "/turtlebot468/tf",
        "/turtlebot468/tf_static",
        "/turtlebot468/cmd_vel",
    }


def test_bridge_specs_strips_slashes():
    specs = bridge_specs("/turtlebot468/")
    assert all(s.topic.startswith("/turtlebot468/") for s in specs)
    assert all("//" not in s.topic for s in specs)


def test_cmd_vel_relays_back_to_robot_others_inbound():
    by_topic = {s.topic: s for s in bridge_specs("tb")}
    assert by_topic["/tb/cmd_vel"].direction == "sd_to_ds"
    assert by_topic["/tb/odom"].direction == "ds_to_sd"


def test_split_discovery_env_removes_ds_vars():
    env = {
        "PATH": "/usr/bin",
        "ROS_DISCOVERY_SERVER": "1.2.3.4:11811",
        "ROS_SUPER_CLIENT": "True",
    }
    simple, saved = split_discovery_env(env)
    assert "ROS_DISCOVERY_SERVER" not in simple
    assert "ROS_SUPER_CLIENT" not in simple
    assert simple["PATH"] == "/usr/bin"
    assert saved == {"ROS_DISCOVERY_SERVER": "1.2.3.4:11811", "ROS_SUPER_CLIENT": "True"}


def test_split_discovery_env_does_not_mutate_input():
    env = {"ROS_DISCOVERY_SERVER": "x"}
    split_discovery_env(env)
    assert env == {"ROS_DISCOVERY_SERVER": "x"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/relay/test_specs.py -v`
Expected: FAIL (`No module named 'robobench.relay.specs'`)

- [ ] **Step 4: Write minimal implementation**

```python
# src/robobench/relay/specs.py
"""Pure (rclpy-free) relay specs + DDS env helpers.

The relay needs one DDS context with NO Discovery-Server env vars (Simple
Discovery) and one WITH them. Everything here imports without ROS2 so it's
unit-testable; the rclpy wiring lives in runner.py.
"""

from __future__ import annotations

from dataclasses import dataclass

# Symbolic QoS names; runner.py maps these to real rclpy QoSProfile objects.
QOS_SENSOR = "sensor"  # depth 10, BEST_EFFORT
QOS_RELIABLE = "reliable"  # depth 10, RELIABLE
QOS_TF_STATIC = "tf_static"  # depth 10, RELIABLE, TRANSIENT_LOCAL

# DDS env vars that must be absent to build a Simple-Discovery context.
_DISCOVERY_ENV_VARS = (
    "ROS_DISCOVERY_SERVER",
    "ROS_SUPER_CLIENT",
    "FASTRTPS_DEFAULT_PROFILES_FILE",
)


@dataclass(frozen=True)
class BridgeSpec:
    """One topic to relay between the two DDS graphs.

    direction "ds_to_sd": robot (Discovery Server) -> local (Simple Discovery).
    direction "sd_to_ds": local (Simple) -> robot (Discovery Server).
    """

    topic: str
    msg_type: str  # "pkg/msg/Name" — runner imports the class
    qos: str  # one of QOS_*
    direction: str  # "ds_to_sd" | "sd_to_ds"


def bridge_specs(namespace: str) -> list[BridgeSpec]:
    """Standard TurtleBot4 relay set for a namespace."""
    ns = namespace.strip("/")
    return [
        BridgeSpec(f"/{ns}/odom", "nav_msgs/msg/Odometry", QOS_SENSOR, "ds_to_sd"),
        BridgeSpec(f"/{ns}/scan", "sensor_msgs/msg/LaserScan", QOS_SENSOR, "ds_to_sd"),
        BridgeSpec(f"/{ns}/imu", "sensor_msgs/msg/Imu", QOS_SENSOR, "ds_to_sd"),
        BridgeSpec(f"/{ns}/tf", "tf2_msgs/msg/TFMessage", QOS_RELIABLE, "ds_to_sd"),
        BridgeSpec(f"/{ns}/tf_static", "tf2_msgs/msg/TFMessage", QOS_TF_STATIC, "ds_to_sd"),
        BridgeSpec(f"/{ns}/cmd_vel", "geometry_msgs/msg/Twist", QOS_RELIABLE, "sd_to_ds"),
    ]


def split_discovery_env(environ: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Return (simple_discovery_env, saved_discovery_vars).

    ``simple_discovery_env`` is a copy of ``environ`` with the Discovery-Server
    vars removed; ``saved_discovery_vars`` holds what was removed so the caller
    can restore them when building the Discovery-Server context. Does not mutate
    the input.
    """
    simple = dict(environ)
    saved: dict[str, str] = {}
    for key in _DISCOVERY_ENV_VARS:
        if key in simple:
            saved[key] = simple.pop(key)
    return simple, saved
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/relay/test_specs.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add src/robobench/relay/__init__.py src/robobench/relay/specs.py tests/unit/relay/
git commit -m "feat: pure DDS relay specs + discovery-env split helper"
```

### Task 1.3: Lazy-rclpy relay runner

**Files:**
- Create: `src/robobench/relay/runner.py`
- Test: `tests/unit/relay/test_runner.py`

- [ ] **Step 1: Write the failing test** (only the rclpy-free seam is tested)

```python
# tests/unit/relay/test_runner.py
import builtins

import pytest

from robobench.relay.runner import _msg_class_path, run_dds_bridge


def test_msg_class_path_splits_type_string():
    assert _msg_class_path("nav_msgs/msg/Odometry") == ("nav_msgs.msg", "Odometry")
    assert _msg_class_path("tf2_msgs/msg/TFMessage") == ("tf2_msgs.msg", "TFMessage")


def test_run_dds_bridge_raises_clearly_without_ros2(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "rclpy":
            raise ImportError("no rclpy")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="requires ROS2"):
        run_dds_bridge(namespace="tb", discovery_server="1.2.3.4:11811")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/relay/test_runner.py -v`
Expected: FAIL (`No module named 'robobench.relay.runner'`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/robobench/relay/runner.py
"""rclpy wiring for the DDS topic relay. Imported lazily so the rest of
robobench works without ROS2 installed.

The dual-context trick (mirrors upstream dds_bridge.py): build a Simple-
Discovery context with the Discovery-Server env vars stripped, then restore
them and build the Discovery-Server context. Each topic spec wires a
subscription on the source graph to a publisher on the destination graph.
"""

from __future__ import annotations

import importlib
import os
import threading

from robobench._rosenv import require_rclpy
from robobench.relay.specs import (
    QOS_RELIABLE,
    QOS_SENSOR,
    QOS_TF_STATIC,
    bridge_specs,
    split_discovery_env,
)


def _msg_class_path(type_str: str) -> tuple[str, str]:
    """Map 'pkg/msg/Name' -> ('pkg.msg', 'Name')."""
    pkg, _msg, name = type_str.split("/")
    return f"{pkg}.msg", name


def _import_msg(type_str: str):
    module_name, class_name = _msg_class_path(type_str)
    return getattr(importlib.import_module(module_name), class_name)


def run_dds_bridge(namespace: str, discovery_server: str) -> None:  # pragma: no cover
    """Relay topics between the robot's Discovery-Server graph and the local
    Simple-Discovery graph until interrupted. Blocking."""
    require_rclpy()
    import rclpy  # noqa: PLC0415
    from rclpy.executors import SingleThreadedExecutor  # noqa: PLC0415
    from rclpy.node import Node  # noqa: PLC0415
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy  # noqa: PLC0415

    qos_map = {
        QOS_SENSOR: QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT),
        QOS_RELIABLE: QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE),
        QOS_TF_STATIC: QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        ),
    }

    # Build the Simple-Discovery context first (DS env vars stripped)...
    _simple, saved = split_discovery_env(dict(os.environ))
    for key in saved:
        os.environ.pop(key, None)
    sd_context = rclpy.context.Context()
    sd_context.init()

    # ...then restore/set DS env vars and build the Discovery-Server context.
    os.environ["ROS_DISCOVERY_SERVER"] = discovery_server
    os.environ["ROS_SUPER_CLIENT"] = saved.get("ROS_SUPER_CLIENT", "True")
    os.environ["RMW_IMPLEMENTATION"] = "rmw_fastrtps_cpp"
    ds_context = rclpy.context.Context()
    ds_context.init()

    sd_node = Node("robobench_relay_sd", context=sd_context)
    ds_node = Node("robobench_relay_ds", context=ds_context)

    def forwarder(pub):
        def cb(msg):
            pub.publish(msg)

        return cb

    for spec in bridge_specs(namespace):
        msg_cls = _import_msg(spec.msg_type)
        qos = qos_map[spec.qos]
        if spec.direction == "ds_to_sd":
            pub = sd_node.create_publisher(msg_cls, spec.topic, qos)
            ds_node.create_subscription(msg_cls, spec.topic, forwarder(pub), qos)
        else:  # sd_to_ds
            pub = ds_node.create_publisher(msg_cls, spec.topic, qos)
            sd_node.create_subscription(msg_cls, spec.topic, forwarder(pub), qos)

    sd_exec = SingleThreadedExecutor(context=sd_context)
    sd_exec.add_node(sd_node)
    ds_exec = SingleThreadedExecutor(context=ds_context)
    ds_exec.add_node(ds_node)
    threading.Thread(target=sd_exec.spin, daemon=True).start()
    threading.Thread(target=ds_exec.spin, daemon=True).start()

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        sd_exec.shutdown()
        ds_exec.shutdown()
        sd_node.destroy_node()
        ds_node.destroy_node()
        sd_context.try_shutdown()
        ds_context.try_shutdown()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/relay/test_runner.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/robobench/relay/runner.py tests/unit/relay/test_runner.py
git commit -m "feat: lazy-rclpy dual-context DDS relay runner"
```

### Task 1.4: `robobench bridge` CLI subcommand

**Files:**
- Modify: `src/robobench/cli.py:105-123` (add subparser after `recover`), and add `_cmd_bridge`
- Test: `tests/unit/test_cli.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli.py  (append)
def test_bridge_invokes_runner(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "robot:\n"
        "  ip: 1.2.3.4\n"
        "  ssh_user: ubuntu\n"
        "  ssh_pass: pw\n"
        "  namespace: tb\n"
        "dds:\n"
        "  discovery_port: 11811\n",
        encoding="utf-8",
    )
    calls = {}

    def fake_run(namespace, discovery_server):
        calls["namespace"] = namespace
        calls["discovery_server"] = discovery_server

    monkeypatch.setattr("robobench.relay.runner.run_dds_bridge", fake_run)

    from robobench.cli import main

    rc = main(["bridge", "--robot", "turtlebot4", "--config", str(cfg)])
    assert rc == 0
    assert calls == {"namespace": "tb", "discovery_server": "1.2.3.4:11811"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cli.py::test_bridge_invokes_runner -v`
Expected: FAIL (`invalid choice: 'bridge'`)

- [ ] **Step 3: Add the subparser** — in `_build_parser`, immediately after the `recover.set_defaults(func=_cmd_recover)` block (cli.py:121) and before `return parser`:

```python
    bridge = subparsers.add_parser(
        "bridge",
        help="Relay robot topics from the Discovery Server to local Simple Discovery.",
    )
    bridge.add_argument("--robot", required=True, choices=["turtlebot4"])
    bridge.add_argument("--config", required=True)
    bridge.set_defaults(func=_cmd_bridge)
```

- [ ] **Step 4: Add the command handler** — after `_cmd_recover` (cli.py:345):

```python
def _cmd_bridge(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    kwargs = load_adapter_config(Path(args.config))
    namespace = kwargs["namespace"]
    discovery_server = f"{kwargs['ip']}:{kwargs['discovery_port']}"
    from robobench.relay.runner import run_dds_bridge  # noqa: PLC0415

    print(f"[bridge] relaying {namespace} topics via Discovery Server {discovery_server}")
    print("[bridge] Ctrl+C to stop.")
    try:
        run_dds_bridge(namespace=namespace, discovery_server=discovery_server)
    except RuntimeError as exc:
        print(f"[bridge] not started: {exc}", file=sys.stderr)
        return 2
    return 0
```

- [ ] **Step 5: Run test + full suite + lint**

Run: `pytest tests/unit/test_cli.py -v && ruff check src tests`
Expected: PASS; ruff clean

- [ ] **Step 6: Commit**

```bash
git add src/robobench/cli.py tests/unit/test_cli.py
git commit -m "feat: add robobench bridge subcommand (DDS topic relay)"
```

### Task 1.5: Tutorial + release v0.6.0a0

**Files:**
- Create: `docs/tutorials/bridging-dds-topics.md`
- Modify: `CHANGELOG.md`, `pyproject.toml:7`, `src/robobench/__init__.py:3`

- [ ] **Step 1: Write the tutorial**

````markdown
# Bridging robot topics across DDS discovery (`robobench bridge`)

When the FastDDS Discovery Server drops a late joiner or churns GUIDs (Nav2
#3560), local ROS2 tools and Nav2 nodes stop seeing robot topics even though
the robot is publishing. `robobench bridge` republishes the robot's topics onto
your workstation's default (Simple Discovery) graph so plain `ros2 topic echo`
and a local Nav2 stack work again — and relays `cmd_vel` back to the robot.

```bash
robobench bridge --robot turtlebot4 --config ./config.yaml
```

It reads `robot.namespace`, `robot.ip`, and `dds.discovery_port` from
`config.yaml`, builds two DDS contexts (one Simple, one Discovery-Server), and
forwards `odom`, `scan`, `imu`, `tf`, `tf_static` inbound and `cmd_vel`
outbound. Leave it running in its own terminal; Ctrl+C stops it.

> Requires ROS2 sourced (`source /opt/ros/<distro>/setup.bash`) and the message
> packages (`nav_msgs`, `sensor_msgs`, `geometry_msgs`, `tf2_msgs`). Without
> ROS2 the command prints `[bridge] not started: ... requires ROS2 ...`.

> Advanced: to tune FastDDS buffers, point `FASTRTPS_DEFAULT_PROFILES_FILE` at
> your own super-client XML before launching; the relay preserves it.
````

- [ ] **Step 2: Update CHANGELOG** — insert under `## [Unreleased]`:

```markdown
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
```

- [ ] **Step 3: Bump version** in `pyproject.toml` (`version = "0.6.0a0"`) and `src/robobench/__init__.py` (`__version__ = "0.6.0a0"`).

- [ ] **Step 4: Verify, commit, tag, push**

```bash
pytest && ruff check src tests && robobench --version
git add CHANGELOG.md pyproject.toml src/robobench/__init__.py docs/tutorials/bridging-dds-topics.md
git commit -m "release: v0.6.0a0 — robobench bridge (DDS topic relay)"
git tag v0.6.0a0
git push && git push --tags
```
Expected: all tests pass; `robobench 0.6.0a0`.

---

## Phase 2 — odom→base_link TF republisher (`robobench odom-tf`) → v0.7.0a0

**Why:** robobench's TF panel *detects* a broken/missing odom→base_link edge but has no way to *fix* it. The upstream `odom_tf_publisher.py` republishes that transform from `/odom` when the Create3 republisher doesn't bridge it. This is a standalone long-running helper (not a one-shot recovery action), so it gets its own CLI like the relay, plus a catalog fix hint.

### Task 2.1: Pure odom→TF field map

**Files:**
- Create: `src/robobench/diagnostics/odom_tf.py`
- Test: `tests/unit/diagnostics/test_odom_tf.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/diagnostics/test_odom_tf.py
from robobench.diagnostics.odom_tf import odom_to_tf


def test_odom_to_tf_copies_pose_and_frames():
    tf = odom_to_tf(
        frame_id="odom",
        child_frame_id="base_link",
        stamp_sec=10,
        stamp_nanosec=500,
        position=(1.0, 2.0, 0.0),
        orientation=(0.0, 0.0, 0.7071, 0.7071),
    )
    assert tf.frame_id == "odom"
    assert tf.child_frame_id == "base_link"
    assert (tf.stamp_sec, tf.stamp_nanosec) == (10, 500)
    assert (tf.tx, tf.ty, tf.tz) == (1.0, 2.0, 0.0)
    assert (tf.qx, tf.qy, tf.qz, tf.qw) == (0.0, 0.0, 0.7071, 0.7071)


def test_odom_topic_for_namespace():
    from robobench.diagnostics.odom_tf import odom_topic

    assert odom_topic("turtlebot468") == "/turtlebot468/odom"
    assert odom_topic("/turtlebot468/") == "/turtlebot468/odom"
    assert odom_topic("") == "/odom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/diagnostics/test_odom_tf.py -v`
Expected: FAIL (`No module named 'robobench.diagnostics.odom_tf'`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/robobench/diagnostics/odom_tf.py
"""odom -> base_link TF republisher.

Some Create3 firmware does not bridge the odom TF, leaving Nav2 with a broken
odom->base_link edge (robobench's TF panel flags it). This republishes that
transform from the Odometry message. Pure field-mapping is testable; the rclpy
node is lazy-imported and smoke-tested.

Ports upstream campus_nav_llm/odom_tf_publisher.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from robobench._rosenv import require_rclpy


@dataclass(frozen=True)
class OdomTf:
    """Flat TF fields copied straight from an Odometry message."""

    frame_id: str
    child_frame_id: str
    stamp_sec: int
    stamp_nanosec: int
    tx: float
    ty: float
    tz: float
    qx: float
    qy: float
    qz: float
    qw: float


def odom_to_tf(
    frame_id: str,
    child_frame_id: str,
    stamp_sec: int,
    stamp_nanosec: int,
    position: tuple[float, float, float],
    orientation: tuple[float, float, float, float],
) -> OdomTf:
    """Map Odometry pose fields onto flat TF fields. Pure; no rclpy."""
    px, py, pz = position
    ox, oy, oz, ow = orientation
    return OdomTf(frame_id, child_frame_id, stamp_sec, stamp_nanosec, px, py, pz, ox, oy, oz, ow)


def odom_topic(namespace: str) -> str:
    """Return the odom topic for a namespace ('' -> '/odom')."""
    ns = namespace.strip("/")
    return f"/{ns}/odom" if ns else "/odom"


def run_odom_tf_publisher(namespace: str) -> None:  # pragma: no cover
    """Subscribe to odom, broadcast odom->base_link TF until interrupted."""
    require_rclpy()
    import rclpy  # noqa: PLC0415
    from geometry_msgs.msg import TransformStamped  # noqa: PLC0415
    from nav_msgs.msg import Odometry  # noqa: PLC0415
    from rclpy.node import Node  # noqa: PLC0415
    from tf2_ros import TransformBroadcaster  # noqa: PLC0415

    rclpy.init()
    node = Node("robobench_odom_tf")
    broadcaster = TransformBroadcaster(node)
    topic = odom_topic(namespace)

    def on_odom(msg: Odometry) -> None:
        t = TransformStamped()
        t.header = msg.header  # frame_id="odom", stamp from odom
        t.child_frame_id = msg.child_frame_id  # "base_link"
        t.transform.translation.x = msg.pose.pose.position.x
        t.transform.translation.y = msg.pose.pose.position.y
        t.transform.translation.z = msg.pose.pose.position.z
        t.transform.rotation = msg.pose.pose.orientation
        broadcaster.sendTransform(t)

    node.create_subscription(Odometry, topic, on_odom, 10)
    node.get_logger().info(f"Publishing odom->base_link TF from {topic}")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/diagnostics/test_odom_tf.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/robobench/diagnostics/odom_tf.py tests/unit/diagnostics/test_odom_tf.py
git commit -m "feat: odom->base_link TF republisher (pure map + lazy rclpy node)"
```

### Task 2.2: `robobench odom-tf` CLI subcommand

**Files:**
- Modify: `src/robobench/cli.py` (add subparser + `_cmd_odom_tf`)
- Test: `tests/unit/test_cli.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli.py  (append)
def test_odom_tf_invokes_runner(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "robot:\n  ip: 1.2.3.4\n  ssh_user: u\n  ssh_pass: p\n  namespace: tb\n",
        encoding="utf-8",
    )
    seen = {}
    monkeypatch.setattr(
        "robobench.diagnostics.odom_tf.run_odom_tf_publisher",
        lambda namespace: seen.update(namespace=namespace),
    )
    from robobench.cli import main

    rc = main(["odom-tf", "--robot", "turtlebot4", "--config", str(cfg)])
    assert rc == 0
    assert seen == {"namespace": "tb"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cli.py::test_odom_tf_invokes_runner -v`
Expected: FAIL (`invalid choice: 'odom-tf'`)

- [ ] **Step 3: Add subparser** (after the `bridge` block from Task 1.4, before `return parser`):

```python
    odom_tf = subparsers.add_parser(
        "odom-tf",
        help="Republish odom->base_link TF when the Create3 doesn't bridge it.",
    )
    odom_tf.add_argument("--robot", required=True, choices=["turtlebot4"])
    odom_tf.add_argument("--config", required=True)
    odom_tf.set_defaults(func=_cmd_odom_tf)
```

- [ ] **Step 4: Add handler** (after `_cmd_bridge`):

```python
def _cmd_odom_tf(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    namespace = load_adapter_config(Path(args.config))["namespace"]
    from robobench.diagnostics.odom_tf import run_odom_tf_publisher  # noqa: PLC0415

    print(f"[odom-tf] publishing odom->base_link TF for {namespace}. Ctrl+C to stop.")
    try:
        run_odom_tf_publisher(namespace=namespace)
    except RuntimeError as exc:
        print(f"[odom-tf] not started: {exc}", file=sys.stderr)
        return 2
    return 0
```

- [ ] **Step 5: Run test + lint**

Run: `pytest tests/unit/test_cli.py -v && ruff check src tests`
Expected: PASS; ruff clean

- [ ] **Step 6: Commit**

```bash
git add src/robobench/cli.py tests/unit/test_cli.py
git commit -m "feat: add robobench odom-tf subcommand"
```

### Task 2.3: Catalog fix hint + release v0.7.0a0

**Files:**
- Modify: `src/robobench/panels/catalog.py:42-55` (append a `tf_tree` entry)
- Test: `tests/unit/panels/test_catalog.py` (append)
- Modify: `CHANGELOG.md`, `pyproject.toml`, `src/robobench/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/panels/test_catalog.py  (append)
def test_tf_tree_suggests_odom_tf_helper():
    from robobench.panels.catalog import lookup_fixes

    fixes = lookup_fixes("tf_tree", "FAIL")
    assert any("robobench odom-tf" in f["fix"] for f in fixes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/panels/test_catalog.py::test_tf_tree_suggests_odom_tf_helper -v`
Expected: FAIL (no entry mentions `robobench odom-tf`)

- [ ] **Step 3: Append the catalog entry** — inside the `"tf_tree"` list in `catalog.py` (after the clock-skew entry, before the closing `],`):

```python
        {
            "cause": "Create3 isn't bridging the odom->base_link TF.",
            "fix": "Run `robobench odom-tf --robot turtlebot4 --config config.yaml` "
            "to republish odom->base_link from /odom.",
            "link": None,
        },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/panels/test_catalog.py -v`
Expected: PASS

- [ ] **Step 5: Update CHANGELOG / bump / commit / tag / push**

CHANGELOG under `## [Unreleased]`:

```markdown
## [0.7.0a0] — 2026-05-29

### Added

- **`robobench odom-tf`** — republishes the odom->base_link TF when the Create3
  firmware doesn't bridge it (ports upstream `odom_tf_publisher.py`). Closes the
  "TF panel detects a broken odom edge but can't fix it" gap.
- TF failure-catalog entry now points at `robobench odom-tf`.
```

Bump `pyproject.toml` + `__init__.py` to `0.7.0a0`, then:

```bash
pytest && ruff check src tests && robobench --version
git add src/robobench/panels/catalog.py tests/unit/panels/test_catalog.py CHANGELOG.md pyproject.toml src/robobench/__init__.py
git commit -m "release: v0.7.0a0 — robobench odom-tf + TF catalog hint"
git tag v0.7.0a0
git push && git push --tags
```
Expected: all pass; `robobench 0.7.0a0`.

---

## Phase 3 — Event log / flight recorder → v0.8.0a0

**Why:** `recover` returns an in-memory trace that vanishes when the process exits. A diagnostics platform should persist what it saw and did, for post-mortems and "what changed". Ports upstream `event_logger.py` (JSONL, thread-safe, stdlib-only) and wires it into the recovery engine + CLI. Self-contained, fully unit-testable, strengthens the "tell you what's broken" story.

### Task 3.1: EventLogger + NullEventLogger

**Files:**
- Create: `src/robobench/eventlog.py`
- Test: `tests/unit/test_eventlog.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_eventlog.py
import json

from robobench.eventlog import EventLogger, NullEventLogger


def test_event_logger_writes_jsonl(tmp_path):
    logger = EventLogger(log_dir=str(tmp_path))
    logger.log("probe", {"healthy": False, "failing": "clock_synced"})
    logger.log("action", {"name": "sync_clock"})
    logger.close()

    files = list(tmp_path.glob("events_*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event"] == "probe"
    assert first["data"] == {"healthy": False, "failing": "clock_synced"}
    assert first["session_id"] == logger.session_id
    assert "ts" in first


def test_log_after_close_is_ignored(tmp_path):
    logger = EventLogger(log_dir=str(tmp_path))
    logger.close()
    logger.log("late", {})  # must not raise
    lines = next(tmp_path.glob("events_*.jsonl")).read_text(encoding="utf-8").splitlines()
    assert lines == []


def test_null_event_logger_writes_nothing(tmp_path):
    logger = NullEventLogger()
    logger.log("x", {"a": 1})
    logger.close()
    assert list(tmp_path.glob("*.jsonl")) == []
    assert logger.session_id == "null"


def test_log_path_is_readable(tmp_path):
    logger = EventLogger(log_dir=str(tmp_path))
    assert str(tmp_path) in logger.path
    logger.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_eventlog.py -v`
Expected: FAIL (`No module named 'robobench.eventlog'`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/robobench/eventlog.py
"""JSONL flight recorder for diagnostics/recovery runs.

Appends one JSON object per line: {ts, session_id, event, data}. Thread-safe,
stdlib-only, no ROS dependency. Ports upstream campus_nav_llm/event_logger.py;
default dir is ~/.robobench/logs.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_LOG_DIR = Path.home() / ".robobench" / "logs"


class NullEventLogger:
    """No-op logger — writes nothing, creates no files."""

    session_id = "null"
    path = ""

    def log(self, event: str, data: dict) -> None:
        pass

    def close(self) -> None:
        pass


class EventLogger:
    """Append-only JSONL event writer (thread-safe)."""

    def __init__(self, log_dir: str | None = None) -> None:
        directory = Path(log_dir) if log_dir else _DEFAULT_LOG_DIR
        directory.mkdir(parents=True, exist_ok=True)
        self.session_id = uuid.uuid4().hex[:8]
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._path = directory / f"events_{ts}_{self.session_id}.jsonl"
        self.path = str(self._path)
        self._lock = threading.Lock()
        self._file = open(self._path, "a", encoding="utf-8")  # noqa: SIM115
        self._closed = False

    def log(self, event: str, data: dict) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "session_id": self.session_id,
            "event": event,
            "data": data,
        }
        line = json.dumps(record, default=str) + "\n"
        with self._lock:
            if not self._closed:
                self._file.write(line)
                self._file.flush()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._file.flush()
                self._file.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_eventlog.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/robobench/eventlog.py tests/unit/test_eventlog.py
git commit -m "feat: JSONL event logger (flight recorder)"
```

### Task 3.2: RecoveryEngine logs probe/action/outcome

**Files:**
- Modify: `src/robobench/recovery/engine.py:54-107`
- Test: `tests/unit/recovery/test_engine.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/recovery/test_engine.py  (append)
def test_engine_logs_events_to_injected_logger():
    from robobench.recovery.engine import RecoveryEngine
    from robobench.recovery.state import RobotState

    healthy = RobotState(True, True, True, 5, True, True)
    broken = RobotState(True, False, True, 5, True, True)
    states = iter([broken, healthy])

    class FakeActions:
        def __getattr__(self, _name):
            return lambda: None

    events: list[tuple[str, dict]] = []

    class FakeLog:
        def log(self, event, data):
            events.append((event, data))

    engine = RecoveryEngine(
        probe=lambda: next(states),
        actions=FakeActions(),
        allow_reboot=False,
        deadline_s=100.0,
        settle_s=0.0,
        sleep=lambda _s: None,
        now=lambda: 0.0,
        event_log=FakeLog(),
    )
    result = engine.run()
    assert result.outcome == "CONVERGED"
    kinds = [e[0] for e in events]
    assert "probe" in kinds
    assert "action" in kinds
    assert ("outcome", {"outcome": "CONVERGED"}) in events
    action_event = next(d for k, d in events if k == "action")
    assert action_event["name"] == "restart_discovery_server"
    assert action_event["aspect"] == "discovery_server_ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/recovery/test_engine.py::test_engine_logs_events_to_injected_logger -v`
Expected: FAIL (`__init__() got an unexpected keyword argument 'event_log'`)

- [ ] **Step 3: Modify the engine** — add the import near the top of `engine.py` (after the existing imports, line 22):

```python
from robobench.eventlog import NullEventLogger
```

Extend `__init__` (add a keyword-only `event_log` param and store it). Change the signature block (engine.py:57-74) so the parameter list ends with:

```python
        sleep: Callable[[float], None],
        now: Callable[[], float],
        event_log: object | None = None,
    ) -> None:
        self._probe = probe
        self._actions = actions
        self._allow_reboot = allow_reboot
        self._deadline_s = deadline_s
        self._settle_s = settle_s
        self._sleep = sleep
        self._now = now
        self._log = event_log or NullEventLogger()
```

Then in `run()`, add `import dataclasses` at the top of the file and emit events. Replace the body of the `while True:` loop (engine.py:80-107) with:

```python
        while True:
            state = self._probe()
            result.final_state = state
            self._log.log("probe", dataclasses.asdict(state))
            if state.is_healthy():
                result.outcome = "CONVERGED"
                result.trace.append("healthy")
                self._log.log("outcome", {"outcome": result.outcome})
                return result
            if self._now() - start > self._deadline_s:
                result.outcome = "TIMED_OUT"
                result.trace.append("deadline exceeded")
                self._log.log("outcome", {"outcome": result.outcome})
                return result
            aspect = state.failing_aspect()
            if aspect == "rpi_reachable":
                result.outcome = "NEEDS_HUMAN"
                result.trace.append("rpi unreachable — power/network, cannot fix remotely")
                self._log.log("outcome", {"outcome": result.outcome})
                return result

            action_name = self._pick_action(aspect, tried)
            if action_name is None:
                result.outcome = "STUCK"
                result.trace.append(f"no untried action left for '{aspect}'")
                self._log.log("outcome", {"outcome": result.outcome})
                return result

            tried.add(action_name)
            result.actions_taken.append(action_name)
            result.trace.append(f"aspect '{aspect}' -> {action_name}")
            self._log.log("action", {"aspect": aspect, "name": action_name})
            getattr(self._actions, action_name)()
            self._sleep(self._settle_s)
```

Add `import dataclasses` at the top (after `from __future__ import annotations`, before `from collections.abc import Callable`).

- [ ] **Step 4: Run test to verify it passes (and existing engine tests still pass)**

Run: `pytest tests/unit/recovery/test_engine.py -v`
Expected: PASS (all existing + new)

- [ ] **Step 5: Commit**

```bash
git add src/robobench/recovery/engine.py tests/unit/recovery/test_engine.py
git commit -m "feat: recovery engine emits probe/action/outcome events"
```

### Task 3.3: Thread the logger through factory + CLI; print log path

**Files:**
- Modify: `src/robobench/robots/turtlebot4_recovery.py:87-110` (factory accepts `event_log`)
- Modify: `src/robobench/cli.py` (`_cmd_recover`, `_cmd_preflight`)
- Test: `tests/unit/test_cli.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli.py  (append)
def test_recover_writes_event_log(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "robot:\n  ip: 1.2.3.4\n  ssh_user: u\n  ssh_pass: p\n  namespace: tb\n",
        encoding="utf-8",
    )

    class FakeResult:
        outcome = "CONVERGED"
        actions_taken: list[str] = []

    class FakeEngine:
        def run(self):
            return FakeResult()

    captured = {}

    def fake_build(**kwargs):
        captured["event_log"] = kwargs.get("event_log")
        return FakeEngine()

    monkeypatch.setattr("robobench.cli.build_turtlebot4_recovery", fake_build)
    from robobench.cli import main

    rc = main(["recover", "--robot", "turtlebot4", "--config", str(cfg)])
    assert rc == 0
    assert captured["event_log"] is not None  # a real EventLogger was passed
    assert "event log:" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cli.py::test_recover_writes_event_log -v`
Expected: FAIL (`build_turtlebot4_recovery() got an unexpected keyword argument 'event_log'`)

- [ ] **Step 3: Extend the factory** — in `turtlebot4_recovery.py`, add an `event_log` param and forward it. Change the `build_turtlebot4_recovery` signature (line 87-96) to add `event_log: object | None = None,` after `settle_s: float = 8.0,`, and pass `event_log=event_log` into the `RecoveryEngine(...)` call (line 102-110).

- [ ] **Step 4: Wire the CLI** — at the top of `cli.py`, add `from robobench.eventlog import EventLogger`. In `_cmd_recover` (the non-dry-run branch, cli.py:331-345), replace with:

```python
    event_log = EventLogger()
    engine = build_turtlebot4_recovery(
        ip=kwargs["ip"],
        ssh_user=kwargs["ssh_user"],
        ssh_pass=kwargs["ssh_pass"],
        namespace=kwargs["namespace"],
        allow_reboot=args.allow_reboot,
        deadline_s=args.deadline,
        event_log=event_log,
    )
    try:
        result = engine.run()
    finally:
        event_log.close()
    print(f"recovery outcome: {result.outcome}")
    for a in result.actions_taken:
        print(f"  applied: {a}")
    print(f"event log: {event_log.path}")
    if result.outcome == "NEEDS_HUMAN":
        print("  robot unreachable — check power and network.", file=sys.stderr)
    return 0 if result.outcome == "CONVERGED" else 1
```

In `_cmd_preflight` (cli.py:277-303), after computing `state`, log it and print the path. After `state = probe.read()` add:

```python
    event_log = EventLogger()
    event_log.log("preflight", dataclasses.asdict(state))
    event_log.close()
```

and add `print(f"event log: {event_log.path}", file=sys.stderr)` just before the `return`.

- [ ] **Step 5: Run test + full suite + lint**

Run: `pytest && ruff check src tests`
Expected: PASS; ruff clean

- [ ] **Step 6: Release v0.8.0a0**

CHANGELOG under `## [Unreleased]`:

```markdown
## [0.8.0a0] — 2026-05-29

### Added

- **Flight recorder** (`robobench.eventlog`): JSONL session logs of every
  diagnostics/recovery run. `recover` and `preflight` now write
  `~/.robobench/logs/events_*.jsonl` and print the path; the recovery engine
  emits `probe`/`action`/`outcome` events. Ports upstream `event_logger.py`.
```

Bump to `0.8.0a0`, then:

```bash
git add -A
git commit -m "release: v0.8.0a0 — flight recorder wired into recover/preflight"
git tag v0.8.0a0
git push && git push --tags
```
Expected: all pass; `robobench 0.8.0a0`.

---

## Phase 4+5 — Bring-up hardening → v0.9.0a0

**Why:** Two pure-correctness/resilience fixes the upstream `deploy.sh` v3 proved on hardware, missing from robobench. Grouped into one release. (4) `shutdown()` currently `pkill -9`s immediately — it skips graceful SIGTERM, leaks `/dev/shm` FastDDS segments (FastDDS#2790), and leaves a stale ros2 daemon. (5) `activate_lifecycle()` raises on activator failure with no fallback; `deploy.sh` falls back to per-node `ros2 lifecycle set`.

### Task 4.1: Graceful shutdown (SIGTERM → settle → SIGKILL, shm clean, daemon restart)

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py:8-19` (imports), `:313-343` (`shutdown`)
- Test: `tests/unit/robots/test_turtlebot4.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/robots/test_turtlebot4.py  (append)
def test_shutdown_is_graceful_then_forceful(monkeypatch, tmp_path):
    from robobench.robots import turtlebot4

    calls: list[list[str]] = []
    monkeypatch.setattr(
        turtlebot4,
        "run_local",
        lambda cmd, timeout=None, **kw: calls.append(list(cmd)) or _ok(),
    )
    sleeps: list[float] = []

    adapter = turtlebot4.TurtleBot4Adapter(
        ip="1.2.3.4", ssh_user="u", ssh_pass="p", namespace="tb"
    )
    missing_pid = tmp_path / "nope.pid"
    adapter.shutdown(pid_path=missing_pid, settle_s=5.0, sleep=sleeps.append)

    flat = [" ".join(c) for c in calls]
    term_idx = next(i for i, c in enumerate(flat) if "pkill" in c and "-TERM" in c)
    kill_idx = next(i for i, c in enumerate(flat) if "pkill" in c and "-9" in c)
    assert term_idx < kill_idx, "SIGTERM must precede SIGKILL"
    assert sleeps == [5.0]
    assert any("fastdds" in c and "shm" in c for c in flat)
    assert any("daemon" in c and "stop" in c for c in flat)
    assert any("daemon" in c and "start" in c for c in flat)


def _ok():
    import subprocess

    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
```

> Note: if `test_turtlebot4.py` already defines an `_ok()`/CompletedProcess helper, reuse it instead of redefining.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/robots/test_turtlebot4.py::test_shutdown_is_graceful_then_forceful -v`
Expected: FAIL (`shutdown() got an unexpected keyword argument 'settle_s'`, plus missing SIGTERM/shm/daemon calls)

- [ ] **Step 3: Update imports** — in `turtlebot4.py`, change the import block to add `time` and `Callable`:

```python
import math
import shlex
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
```

- [ ] **Step 4: Rewrite `shutdown`** — replace the method (cli line numbers `turtlebot4.py:313-343`) with:

```python
    def shutdown(
        self,
        pid_path: Path | None = None,
        *,
        settle_s: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Stop the navigation stack gracefully.

        SIGTERM first (lets on_shutdown handlers release FastDDS shared memory),
        wait ``settle_s``, then SIGKILL stragglers. Cleans /dev/shm FastDDS
        segments and restarts the ros2 daemon so the next bring-up starts clean.
        Refs: rclcpp#1704 (SIGTERM since Humble), FastDDS#2790 (SIGKILL leaks shm).
        """
        target = pid_path if pid_path is not None else Path("/tmp/robobench_launch.pid")

        # 1. Zero velocity, in case the robot is moving.
        run_local(
            [
                "ros2",
                "topic",
                "pub",
                "--once",
                f"/{self.namespace}/cmd_vel",
                "geometry_msgs/msg/Twist",
                "{linear: {x: 0.0}, angular: {z: 0.0}}",
            ],
            timeout=5.0,
        )

        # 2. Kill the recorded launcher PID, if present.
        if target.exists():
            try:
                pid = int(target.read_text().strip())
                run_local(["kill", str(pid)], timeout=2.0)
            except (ValueError, OSError):
                pass
            target.unlink(missing_ok=True)

        # 3. Graceful SIGTERM to all known nav-stack patterns.
        for pattern in self._PKILL_PATTERNS:
            run_local(["pkill", "-TERM", "-f", pattern], timeout=2.0)

        # 4. Wait, then SIGKILL anything still alive.
        sleep(settle_s)
        for pattern in self._PKILL_PATTERNS:
            run_local(["pkill", "-9", "-f", pattern], timeout=2.0)

        # 5. Release FastDDS shared memory (best-effort) and refresh the daemon.
        run_local(["fastdds", "shm", "clean"], timeout=10.0)
        run_local(["ros2", "daemon", "stop"], timeout=10.0)
        run_local(["ros2", "daemon", "start"], timeout=10.0)
```

- [ ] **Step 5: Run test to verify it passes (and existing shutdown tests still pass)**

Run: `pytest tests/unit/robots/test_turtlebot4.py -v`
Expected: PASS

> If a pre-existing test asserted exactly the old `pkill -9`-only call sequence, update it to the new graceful sequence (the old assertion is now wrong, not a regression).

- [ ] **Step 6: Commit**

```bash
git add src/robobench/robots/turtlebot4.py tests/unit/robots/test_turtlebot4.py
git commit -m "feat: graceful shutdown (SIGTERM->SIGKILL, shm clean, daemon restart)"
```

### Task 5.1: Lifecycle CLI fallback

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py:175-192` (`activate_lifecycle`)
- Test: `tests/unit/robots/test_turtlebot4.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/robots/test_turtlebot4.py  (append)
def test_activate_lifecycle_falls_back_to_cli(monkeypatch):
    from robobench.robots import turtlebot4

    def fake_run(cmd, timeout=None, **kw):
        import subprocess

        rc = 1 if "robobench-lifecycle-activator" in cmd else 0
        return subprocess.CompletedProcess(cmd, rc, "", "boom" if rc else "")

    calls: list[list[str]] = []
    monkeypatch.setattr(
        turtlebot4,
        "run_local",
        lambda cmd, timeout=None, **kw: calls.append(list(cmd)) or fake_run(cmd, timeout),
    )
    adapter = turtlebot4.TurtleBot4Adapter(ip="i", ssh_user="u", ssh_pass="p", namespace="tb")
    adapter.activate_lifecycle(map_yaml="/m.yaml")  # must NOT raise — fallback succeeds

    flat = [" ".join(c) for c in calls]
    assert any("lifecycle" in c and "configure" in c for c in flat)
    assert any("lifecycle" in c and "activate" in c for c in flat)


def test_activate_lifecycle_raises_when_fallback_also_fails(monkeypatch):
    import pytest

    from robobench.robots import turtlebot4

    def fake_run(cmd, timeout=None, **kw):
        import subprocess

        return subprocess.CompletedProcess(cmd, 1, "", "fail")

    monkeypatch.setattr(turtlebot4, "run_local", fake_run)
    adapter = turtlebot4.TurtleBot4Adapter(ip="i", ssh_user="u", ssh_pass="p", namespace="tb")
    with pytest.raises(RuntimeError, match="lifecycle"):
        adapter.activate_lifecycle(map_yaml="/m.yaml")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/robots/test_turtlebot4.py::test_activate_lifecycle_falls_back_to_cli -v`
Expected: FAIL (current code raises on activator failure, no fallback)

- [ ] **Step 3: Add the node-list constant + rewrite `activate_lifecycle`** — add a class attribute near `_PKILL_PATTERNS`:

```python
    _LIFECYCLE_NODES = (
        "map_server",
        "amcl",
        "controller_server",
        "planner_server",
        "behavior_server",
        "bt_navigator",
        "velocity_smoother",
    )
```

Replace `activate_lifecycle` (turtlebot4.py:175-192) with:

```python
    def activate_lifecycle(self, map_yaml: str | None = None) -> None:
        """Configure+activate all Nav2 nodes via the persistent activator.

        On activator failure, fall back to per-node ``ros2 lifecycle set``
        (configure then activate), mirroring upstream deploy.sh. Raises only if
        the fallback also fails to activate any node.
        """
        if map_yaml is None:
            raise ValueError("activate_lifecycle requires map_yaml path")
        result = run_local(
            [
                "robobench-lifecycle-activator",
                "--namespace",
                self.namespace,
                "--map-yaml",
                map_yaml,
            ],
            timeout=180,
        )
        if result.returncode == 0:
            return

        # Fallback: manual CLI activation, node by node.
        any_ok = False
        for node in self._LIFECYCLE_NODES:
            target = f"/{self.namespace}/{node}"
            configure = run_local(["ros2", "lifecycle", "set", target, "configure"], timeout=30)
            activate = run_local(["ros2", "lifecycle", "set", target, "activate"], timeout=30)
            if configure.returncode == 0 and activate.returncode == 0:
                any_ok = True
        if not any_ok:
            raise RuntimeError(
                f"lifecycle activation failed (activator rc={result.returncode}); "
                f"CLI fallback could not activate any node: {result.stderr.strip()}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/robots/test_turtlebot4.py -v`
Expected: PASS (both new tests + existing)

- [ ] **Step 5: Release v0.9.0a0**

CHANGELOG under `## [Unreleased]`:

```markdown
## [0.9.0a0] — 2026-05-29

### Changed

- **Graceful shutdown.** `TurtleBot4Adapter.shutdown()` now SIGTERMs the nav
  stack, waits, then SIGKILLs stragglers, runs `fastdds shm clean` (no more
  leaked /dev/shm segments — FastDDS#2790), and restarts the ros2 daemon.
- **Lifecycle CLI fallback.** `activate_lifecycle()` falls back to per-node
  `ros2 lifecycle set configure/activate` if the persistent activator fails,
  instead of giving up (mirrors upstream deploy.sh).
```

Bump to `0.9.0a0`, run `pytest && ruff check src tests && robobench --version`, then:

```bash
git add -A
git commit -m "release: v0.9.0a0 — bring-up hardening (shutdown + lifecycle fallback)"
git tag v0.9.0a0
git push && git push --tags
```
Expected: all pass; `robobench 0.9.0a0`.

---

## Phase 6 — Named pose registry (`bringup --pose front_door`) → v0.9.1a0

**Why:** Lowest value (convenience, slightly app-flavored). Upstream `deploy.sh` resolves `--pose front_door` from a `known_poses` map in config.yaml; robobench's `bringup` only takes raw `--initial-pose X Y THETA`. Add a separate `load_known_poses()` loader (keeps adapter kwargs clean) + a pure `resolve_pose()` + a `--pose` flag.

### Task 6.1: `load_known_poses()` + `resolve_pose()`

**Files:**
- Modify: `src/robobench/config.py` (append two functions)
- Test: `tests/unit/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config.py  (append)
def test_load_known_poses(tmp_path):
    from robobench.config import load_known_poses

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "robot:\n  ip: i\n  ssh_user: u\n  ssh_pass: p\n  namespace: tb\n"
        "known_poses:\n"
        "  front_door: {x: 5.19, y: 2.56, theta: 0.0}\n",
        encoding="utf-8",
    )
    poses = load_known_poses(cfg)
    assert poses == {"front_door": {"x": 5.19, "y": 2.56, "theta": 0.0}}


def test_load_known_poses_empty_when_absent(tmp_path):
    from robobench.config import load_known_poses

    cfg = tmp_path / "config.yaml"
    cfg.write_text("robot:\n  ip: i\n  ssh_user: u\n  ssh_pass: p\n  namespace: tb\n", "utf-8")
    assert load_known_poses(cfg) == {}


def test_resolve_pose_named():
    from robobench.config import resolve_pose

    poses = {"front_door": {"x": 5.19, "y": 2.56, "theta": 0.0}}
    assert resolve_pose("front_door", poses) == (5.19, 2.56, 0.0)


def test_resolve_pose_raw_coords():
    from robobench.config import resolve_pose

    assert resolve_pose("1.0 -2.0 3.14", {}) == (1.0, -2.0, 3.14)


def test_resolve_pose_unknown_raises():
    import pytest

    from robobench.config import resolve_pose

    with pytest.raises(ValueError, match="unknown pose"):
        resolve_pose("garage", {"front_door": {"x": 0, "y": 0, "theta": 0}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config.py -k "pose" -v`
Expected: FAIL (`cannot import name 'load_known_poses'`)

- [ ] **Step 3: Append to `config.py`**

```python
def load_known_poses(path: Path) -> dict[str, dict]:
    """Return the optional ``known_poses`` map from config.yaml (or {})."""
    if not path.exists():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("known_poses") or {}


def resolve_pose(value: str, known_poses: dict[str, dict]) -> tuple[float, float, float]:
    """Resolve a pose name or a raw 'x y theta' string to (x, y, theta)."""
    if value in known_poses:
        p = known_poses[value]
        return (float(p["x"]), float(p["y"]), float(p["theta"]))
    parts = value.split()
    if len(parts) == 3:
        try:
            x, y, theta = (float(p) for p in parts)
            return (x, y, theta)
        except ValueError:
            pass
    known = ", ".join(sorted(known_poses)) or "(none configured)"
    raise ValueError(f"unknown pose '{value}'; known: {known}; or pass 'x y theta'")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_config.py -k "pose" -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/robobench/config.py tests/unit/test_config.py
git commit -m "feat: known_poses loader + resolve_pose helper"
```

### Task 6.2: `bringup --pose` wiring + release v0.9.1a0

**Files:**
- Modify: `src/robobench/cli.py:58-74` (bringup args), `:156-180` (`_cmd_bringup`)
- Test: `tests/unit/test_cli.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli.py  (append)
def test_bringup_resolves_named_pose(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "robot:\n  ip: i\n  ssh_user: u\n  ssh_pass: p\n  namespace: tb\n"
        "workspace:\n  dir: /ws\n"
        "known_poses:\n  front_door: {x: 5.19, y: 2.56, theta: 0.0}\n",
        encoding="utf-8",
    )
    poses_set: list[tuple] = []

    class FakeAdapter:
        def __init__(self, **kw):
            pass

        def setup_clock_sync(self, **kw):
            pass

        def build(self):
            pass

        def launch(self):
            pass

        def activate_lifecycle(self, map_yaml=None):
            pass

        def set_initial_pose(self, x, y, theta):
            poses_set.append((x, y, theta))

        def health_check(self):
            return {"overall": "HEALTHY", "checks": {}}

    monkeypatch.setattr("robobench.cli.TurtleBot4Adapter", FakeAdapter)
    from robobench.cli import main

    rc = main(
        [
            "bringup",
            "--robot",
            "turtlebot4",
            "--config",
            str(cfg),
            "--workstation-ip",
            "192.168.1.2",
            "--map-yaml",
            "/m.yaml",
            "--pose",
            "front_door",
            "--skip-clock",
            "--skip-build",
        ]
    )
    assert rc == 0
    assert poses_set == [(5.19, 2.56, 0.0)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cli.py::test_bringup_resolves_named_pose -v`
Expected: FAIL (`--pose` is not a recognized argument)

- [ ] **Step 3: Update bringup args** — in `_build_parser`, make `--initial-pose` optional (drop `required=True`) and add a `--pose` option:

```python
    bringup.add_argument(
        "--initial-pose",
        nargs=3,
        metavar=("X", "Y", "THETA"),
        type=float,
        default=None,
    )
    bringup.add_argument(
        "--pose",
        default=None,
        help="Named pose from config.yaml known_poses, or 'x y theta'.",
    )
```

- [ ] **Step 4: Update `_cmd_bringup`** — replace the pose resolution (cli.py:163, the `x, y, theta = args.initial_pose` line) with:

```python
    from robobench.config import load_known_poses, resolve_pose  # noqa: PLC0415

    if args.pose is not None:
        x, y, theta = resolve_pose(args.pose, load_known_poses(Path(args.config)))
    elif args.initial_pose is not None:
        x, y, theta = args.initial_pose
    else:
        print("bringup requires --pose or --initial-pose", file=sys.stderr)
        return 2
```

- [ ] **Step 5: Run test + full suite + lint**

Run: `pytest && ruff check src tests`
Expected: PASS; ruff clean

- [ ] **Step 6: Release v0.9.1a0**

CHANGELOG under `## [Unreleased]`:

```markdown
## [0.9.1a0] — 2026-05-29

### Added

- **Named poses.** `robobench bringup --pose front_door` resolves from a
  `known_poses` map in config.yaml (or accepts a raw `'x y theta'`). New
  `robobench.config.load_known_poses` / `resolve_pose`. `--initial-pose` is now
  optional (one of the two is required). Ports upstream deploy.sh `--pose`.
```

Bump to `0.9.1a0`, then:

```bash
git add -A
git commit -m "release: v0.9.1a0 — named pose registry for bringup"
git tag v0.9.1a0
git push && git push --tags
```
Expected: all pass; `robobench 0.9.1a0`.

---

## Self-Review

**1. Spec coverage** — every in-scope gap from the comparison maps to a phase:
gap ① DDS bridge → Phase 1; ⑦ FastDDS XML → noted in Phase 1 tutorial (env-var approach already covers the essential `ROS_SUPER_CLIENT`; shipping XML files is YAGNI); gap ② odom-TF → Phase 2; gap ③ event log → Phase 3; gap ④ graceful shutdown → Task 4.1; gap ⑤ lifecycle fallback → Task 5.1; gap ⑥ named poses → Phase 6. Out-of-scope LLM/speech features are intentionally excluded.

**2. Placeholder scan** — no TBD/"add error handling"/"similar to". Every code step shows full code; every run step shows exact command + expected result.

**3. Type/name consistency** — `require_rclpy()` (shared, Phase 1 Task 1.1) reused by relay runner + odom-tf; `BridgeSpec.direction` values `"ds_to_sd"/"sd_to_ds"` consistent across specs/runner/tests; `EventLogger.path`/`.session_id`/`.log()`/`.close()` consistent across eventlog/engine/CLI; engine `event_log` kwarg threaded factory→engine→CLI; `resolve_pose` returns `(x, y, theta)` consumed by `set_initial_pose(x, y, theta)`.

**Cross-phase dependency:** `_rosenv.require_rclpy()` (Phase 1 Task 1.1) is imported by Phase 2's `odom_tf.py`. If executing Phase 2 standalone before Phase 1, create `_rosenv.py` first (code in Task 1.1). Phases 3/4/5/6 are independent.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-05-29-robobench-upstream-parity-gaps.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec then quality) between tasks, fast iteration. (REQUIRED SUB-SKILL: superpowers:subagent-driven-development)

**2. Inline Execution** — execute in this session with batch checkpoints. (REQUIRED SUB-SKILL: superpowers:executing-plans)

Phases are independently shippable — you can also execute only Phases 3–5 (the no-hardware-needed correctness/resilience work) and defer Phases 1/2/6 until after real-hardware validation.
