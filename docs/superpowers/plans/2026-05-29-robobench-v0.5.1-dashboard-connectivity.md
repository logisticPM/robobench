# Robobench v0.5.1 — Dashboard Connectivity Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the diagnostic dashboard honestly connectable on real hardware **from the same `config.yaml` everything else uses** — so the upcoming real-robot validation produces a true signal instead of setup confusion. Fixes three code-read gaps: (1) the dashboard ignores `config.yaml`'s robot IP and requires DDS env vars to be exported manually; (2) the clock panel always shows `UNKNOWN` against a real robot; (3) those facts aren't documented.

**Architecture:**
- The dashboard's rclpy bridge sets the DDS environment (`ROS_DISCOVERY_SERVER` from `config.yaml`'s `robot.ip` + `dds.discovery_port`, plus `RMW_IMPLEMENTATION` and `ROS_SUPER_CLIENT`) **before** `rclpy.init()`, so `robobench dashboard --config config.yaml` connects from config like `check`/`recover` do — no manual `export` needed.
- The clock panel gets data the rclpy-native way: the bridge computes a clock-offset proxy from each LiDAR scan's header stamp vs. local wall time (no SSH). Sign convention matches the rest of the codebase (positive = robot behind workstation). This conflates clock drift with sub-100ms transport latency — acceptable against the 2s/10s thresholds.
- All new logic lands as small **pure helpers** (`dds_env`, `clock_offset_from_stamp`) that are fully unit-tested; the rclpy wiring stays smoke-level (the bridge blocks on `spin`, so it can't be unit-run — consistent with how `bridge.py` was tested in Phase C).

**Tech Stack:** Python 3.11+, existing `robobench.panels.bridge` / `robobench.config` / `robobench.cli`, pytest, ruff. No new deps. No hardware needed for the test suite.

**Prerequisites:** v0.5.0a0 tagged, 137 tests passing.

**Repo root:** `C:\Users\chntw\Documents\robotic\robobench\`

---

## Scope note

This is a small patch release (5 tasks). It does **not** attempt the larger "dashboard ingests SSH probing / DDS-blind fallback" rework (deferred until real-hardware data confirms it's the actual pain) nor unify the three health representations. It only removes the friction that would corrupt the upcoming hardware test.

---

## File Structure (changes from v0.5.0)

```
robobench/
├── src/robobench/
│   ├── __init__.py                     # version → 0.5.1a0 (Task 5)
│   ├── config.py                       # +discovery_port in returned kwargs (Task 1)
│   ├── cli.py                          # dashboard passes discovery_server to bridge (Task 3)
│   └── panels/
│       └── bridge.py                   # +dds_env, +clock_offset_from_stamp; run_bridge sets
│                                       #  env + on_scan sets clock_offset (Task 2)
├── tests/unit/
│   ├── test_config.py                  # +discovery_port tests (Task 1)
│   └── panels/test_bridge.py           # +dds_env, +clock_offset_from_stamp tests (Task 2)
├── docs/tutorials/
│   └── diagnosing-with-dashboard.md    # drop manual-export note; clock works on hw (Task 4)
└── CHANGELOG.md                        # +0.5.1a0 (Task 5)
```

---

## Task 1: Config loader exposes `discovery_port` (TDD)

**Files:**
- Modify: `src/robobench/config.py`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: Append failing tests to `tests/unit/test_config.py`**

```python
def test_load_adapter_config_reads_dds_discovery_port(tmp_path: Path):
    """An explicit dds.discovery_port flows into the kwargs."""
    yaml_text = """
robot:
  ip: "192.168.50.31"
  ssh_user: "ubuntu"
  ssh_pass: "pw"
  namespace: "tb4"
dds:
  discovery_port: 11888
"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml_text)
    kwargs = load_adapter_config(cfg)
    assert kwargs["discovery_port"] == 11888


def test_load_adapter_config_discovery_port_defaults_to_11811(tmp_path: Path):
    """When dds.discovery_port is absent, default to the upstream default 11811."""
    yaml_text = """
robot:
  ip: "192.168.50.31"
  ssh_user: "ubuntu"
  ssh_pass: "pw"
  namespace: "tb4"
"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml_text)
    kwargs = load_adapter_config(cfg)
    assert kwargs["discovery_port"] == 11811
```

- [ ] **Step 2: Run, confirm fail**

```bash
source .venv/Scripts/activate
pytest tests/unit/test_config.py -v -k discovery_port
```
Expected: KeyError on `discovery_port`.

- [ ] **Step 3: Implement in `src/robobench/config.py`**

In `load_adapter_config`, find the line that reads the optional sections (`build = data.get("build") or {}` etc.) and add a `dds` read alongside them:

```python
    dds = data.get("dds") or {}
```

Then in the returned dict, add a `discovery_port` key (after `user_input_topic`):

```python
        "discovery_port": int(dds.get("discovery_port", 11811)),
```

Update the docstring schema block to mention the `dds` section:
```python
        dds:                                # optional
          discovery_port: 11811
```

- [ ] **Step 4: Run, confirm pass + ruff**

```bash
pytest tests/unit/test_config.py -v
pytest -q
ruff check src tests && ruff format --check src tests
```
Expected: 2 new tests pass; 139 total. If ruff format flags anything, run `ruff format src tests` then re-test.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/config.py tests/unit/test_config.py
git commit -m "feat(config): expose dds.discovery_port (default 11811)"
```

---

## Task 2: Bridge sets DDS env from config + computes clock offset from scan stamps (TDD)

**Files:**
- Modify: `src/robobench/panels/bridge.py`
- Modify: `tests/unit/panels/test_bridge.py`

- [ ] **Step 1: Append failing tests to `tests/unit/panels/test_bridge.py`**

(The file already has the no-ROS2 smoke tests + `from unittest.mock import patch`, `import pytest`.)

```python
def test_dds_env_builds_discovery_server_vars():
    from robobench.panels.bridge import dds_env

    env = dds_env("192.168.50.31:11811")
    assert env["ROS_DISCOVERY_SERVER"] == "192.168.50.31:11811"
    assert env["RMW_IMPLEMENTATION"] == "rmw_fastrtps_cpp"
    assert env["ROS_SUPER_CLIENT"] == "True"


def test_clock_offset_from_stamp_positive_when_robot_behind():
    """offset = now - stamp; robot stamp older than local now => positive
    (matches check_clock_offset's 'positive = robot behind' convention)."""
    from robobench.panels.bridge import clock_offset_from_stamp

    assert clock_offset_from_stamp(now_s=1000.0, stamp_s=995.0) == 5.0


def test_clock_offset_from_stamp_negative_when_robot_ahead():
    from robobench.panels.bridge import clock_offset_from_stamp

    assert clock_offset_from_stamp(now_s=1000.0, stamp_s=1003.0) == -3.0
```

- [ ] **Step 2: Run, confirm fail**

```bash
source .venv/Scripts/activate
pytest tests/unit/panels/test_bridge.py -v -k "dds_env or clock_offset"
```
Expected: ImportError on `dds_env` / `clock_offset_from_stamp`.

- [ ] **Step 3: Implement in `src/robobench/panels/bridge.py`**

(a) Add `import os` at the top of the module (after `from __future__ import annotations`):

```python
import os
```

(b) Add two module-level pure helpers (after the imports, before `_lazy_imports`):

```python
def dds_env(discovery_server: str) -> dict[str, str]:
    """Env vars that point rclpy at the robot's FastDDS Discovery Server.

    ``discovery_server`` is ``"ip:port"``. These mirror what the upstream
    deploy.sh exported; setting them before rclpy.init() lets the dashboard
    connect from config.yaml instead of relying on a hand-exported shell env.
    """
    return {
        "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
        "ROS_DISCOVERY_SERVER": discovery_server,
        "ROS_SUPER_CLIENT": "True",
    }


def clock_offset_from_stamp(now_s: float, stamp_s: float) -> float:
    """Clock-offset proxy in seconds: ``now - stamp`` (positive = robot behind).

    A sensor message's header stamp is the robot's time at publish; comparing
    it to local wall time gives clock drift (plus sub-100ms transport latency,
    negligible against the 2s/10s thresholds). Matches the sign convention of
    ``TurtleBot4Adapter.check_clock_offset`` (local - robot).
    """
    return now_s - stamp_s
```

(c) Change `run_bridge` to accept an optional `discovery_server` and apply the env before `rclpy.init()`. Update the signature and add the env application as the first thing inside the function (before `_lazy_imports()`):

```python
def run_bridge(
    state: DiagnosticState, namespace: str, discovery_server: str | None = None
) -> None:
    """Spin a node that fills ``state`` from robot topics. Blocks until shutdown.

    Intended to run in a daemon thread. Raises RuntimeError immediately if
    ROS2 isn't importable. If ``discovery_server`` ("ip:port") is given, the
    FastDDS Discovery Server env is set from it before rclpy initializes.
    """
    if discovery_server:
        os.environ.update(dds_env(discovery_server))
    ros = _lazy_imports()
    # ... rest unchanged ...
```

(d) In `run_bridge`, make `on_scan` also update the clock offset. Replace the existing `on_scan`:

```python
    def on_scan(msg) -> None:
        stamp = _stamp_to_float(msg.header.stamp)
        state.record_scan(stamp)
        import time as _time  # noqa: PLC0415

        state.set_clock_offset(clock_offset_from_stamp(_time.time(), stamp))
```

- [ ] **Step 4: Run, confirm pass + ruff**

```bash
pytest tests/unit/panels/test_bridge.py -v
pytest -q
ruff check src tests && ruff format --check src tests
```
Expected: 3 new tests pass (+ the 2 existing smoke tests still pass); 142 total. If ruff format flags anything, run `ruff format src tests` then re-test.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/bridge.py tests/unit/panels/test_bridge.py
git commit -m "feat(panels): bridge sets DDS env from config + clock offset from scan stamps"
```

---

## Task 3: Dashboard passes the config-derived discovery server to the bridge (TDD)

**Files:**
- Modify: `src/robobench/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Append failing test to `tests/unit/test_cli.py`**

```python
def test_dashboard_passes_discovery_server_from_config(mocker, tmp_path):
    """Non-demo dashboard derives discovery_server from config ip+port and
    hands it to the bridge thread."""
    cfg = _write_config(tmp_path)  # config has ip 192.168.50.31

    fake_state = MagicMock()
    mocker.patch("robobench.cli.DiagnosticState", return_value=fake_state)
    mocker.patch("robobench.cli.create_app", return_value="APP")
    thread_mock = mocker.patch("robobench.cli.threading.Thread")
    mocker.patch("robobench.cli.uvicorn.run")

    rc = main(["dashboard", "--robot", "turtlebot4", "--config", str(cfg)])

    assert rc == 0
    # bridge thread started with the discovery server string in its args
    args = thread_mock.call_args.kwargs.get("args")
    assert args is not None
    assert "192.168.50.31:11811" in args  # ip from _write_config + default port
```

Note: the existing `_write_config` helper writes `ip: '192.168.50.31'` and no `dds` section, so the default port 11811 applies → discovery server string `192.168.50.31:11811`.

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/test_cli.py -v -k discovery_server_from_config
```
Expected: fail — the bridge thread currently gets `args=(state, namespace)` with no discovery server.

- [ ] **Step 3: Implement in `src/robobench/cli.py`**

(a) Update `_safe_run_bridge` to accept and forward `discovery_server`:

```python
def _safe_run_bridge(state, namespace: str, discovery_server: str | None) -> None:
    """Run the bridge, swallowing the no-ROS2 RuntimeError so the web server
    stays up (panels degrade to UNKNOWN/empty instead of crashing)."""
    from robobench.panels.bridge import run_bridge  # noqa: PLC0415

    try:
        run_bridge(state, namespace=namespace, discovery_server=discovery_server)
    except RuntimeError as exc:
        print(f"[dashboard] bridge not started: {exc}", file=sys.stderr)
```

(b) In `_cmd_dashboard`, in the non-demo `else` branch, build the discovery server string from config and pass it to the thread. The current `else` branch is:

```python
    else:
        threading.Thread(target=_safe_run_bridge, args=(state, namespace), daemon=True).start()
        expected_nodes = _DEFAULT_EXPECTED_NODES
```

Replace with:

```python
    else:
        discovery_server = f"{kwargs['ip']}:{kwargs['discovery_port']}"
        threading.Thread(
            target=_safe_run_bridge,
            args=(state, namespace, discovery_server),
            daemon=True,
        ).start()
        print(f"[dashboard] connecting via Discovery Server {discovery_server}")
        expected_nodes = _DEFAULT_EXPECTED_NODES
```

- [ ] **Step 4: Run, confirm pass + ruff + smoke**

```bash
pytest -q
ruff check src tests && ruff format --check src tests
robobench dashboard --help
```
Expected: 143 total tests pass. The pre-existing `test_dashboard_subcommand_starts_server` still passes (it mocks Thread and only checks `assert_called_once` + `daemon` + uvicorn port — not the args tuple). If ruff format flags anything, run `ruff format src tests` then re-test.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): dashboard connects via Discovery Server from config"
```

---

## Task 4: Update the dashboard tutorial

**Files:** `docs/tutorials/diagnosing-with-dashboard.md`

- [ ] **Step 1: Update the "Start the dashboard" section**

Open `docs/tutorials/diagnosing-with-dashboard.md`. Find the paragraph under "Start the dashboard" that says the server starts a bridge and the note about ROS2 not being sourced. Replace that explanatory paragraph (the lines from "This:" through the "If ROS2 isn't sourced..." note, and the `> The dashboard requires the optional extra...` line) with:

```markdown
This:
1. Reads `config.yaml` and points rclpy at the robot's FastDDS Discovery
   Server (`robot.ip` + `dds.discovery_port`) — no manual `export` needed.
2. Starts a persistent ROS2 bridge node (daemon thread) subscribing to
   `/<ns>/scan`, `/tf`, and the live node list.
3. Serves the diagnostic API + web UI on `http://127.0.0.1:8080`.

> Requires the optional extra **and** ROS2 sourced in the shell:
> `pip install 'robobench[dashboard]'`, then `source /opt/ros/<distro>/setup.bash`.
> If ROS2 isn't available the server still starts; panels report `UNKNOWN`/empty
> and stderr shows `[dashboard] bridge not started: ... requires ROS2 ...`.

> **Clock panel:** the offset shown is derived from incoming LiDAR scan
> timestamps vs. local time (a clock-drift proxy that also includes negligible
> transport latency). For a pure SSH-measured offset, use `robobench check`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/tutorials/diagnosing-with-dashboard.md
git commit -m "docs(tutorials): dashboard connects from config; document clock-panel proxy"
```

---

## Task 5: CHANGELOG + bump v0.5.1a0 + tag + push

**Files:**
- Modify: `CHANGELOG.md`, `src/robobench/__init__.py`, `pyproject.toml`

- [ ] **Step 1: Update CHANGELOG.md** — replace `## [Unreleased]` with:

```markdown
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
```

- [ ] **Step 2: Bump version** — `0.5.0a0` → `0.5.1a0` in `src/robobench/__init__.py` and `pyproject.toml`.

- [ ] **Step 3: Final sweep**

```bash
source .venv/Scripts/activate
pip install -e ".[dev]"
pytest -q
ruff check . && ruff format --check .
robobench --version       # robobench 0.5.1a0
```
Expected: 143 tests pass, ruff clean, version correct.

- [ ] **Step 4: Commit + tag + push**

```bash
git add CHANGELOG.md src/robobench/__init__.py pyproject.toml
git commit -m "chore: bump version to 0.5.1a0 and update CHANGELOG"
git tag -a v0.5.1a0 -m "v0.5.1-alpha - dashboard connects from config + clock panel fix"
git push origin main
git push origin v0.5.1a0
```

- [ ] **Step 5: Verify**

```bash
git tag --list
```
Expected: through `v0.5.1a0`.

---

## Self-Review (Plan Author Notes)

**Spec coverage check:**
- Gap #1 (DDS env not set / config IP ignored) → Tasks 1 (discovery_port) + 2 (`dds_env` + run_bridge sets env) + 3 (dashboard passes it) ✅
- Gap #2 (clock panel always UNKNOWN) → Task 2 (`clock_offset_from_stamp` + on_scan wires `set_clock_offset`) ✅
- Gap #3 (undocumented) → Task 4 ✅
- Release → Task 5 ✅

**Placeholder scan:** No TBDs; every code step shows real code.

**Type consistency:**
- `discovery_port` is `int` (Task 1), formatted into `f"{ip}:{discovery_port}"` string in the dashboard (Task 3), consumed by `dds_env(discovery_server: str)` (Task 2). Consistent.
- `run_bridge(state, namespace, discovery_server=None)` signature (Task 2) matches the call in `_safe_run_bridge` (Task 3).
- `_safe_run_bridge(state, namespace, discovery_server)` (Task 3) matches the thread `args=(state, namespace, discovery_server)` tuple (Task 3).
- `clock_offset_from_stamp(now_s, stamp_s)` returns `now - stamp` (positive = robot behind), matching `classify_clock_offset`'s `abs()` handling and `check_clock_offset`'s convention.

**Known risks / honest notes:**
1. **Clock-offset proxy ≠ pure clock offset.** It folds in DDS transport latency (sub-100ms typically). Against the OK<2s / WARN<10s thresholds this is fine, but on a congested network the panel could read slightly worse than the true drift. Documented in Task 4; `robobench check` remains the SSH-measured ground truth.
2. **Still no real-hardware validation** — this plan's whole point is to *enable* a clean hardware test, not to be one. The env-setting + stamp-based offset are unit-tested via pure helpers, but the actual DDS connection + real scan stamps need a lab pass.
3. **`os.environ.update` in `run_bridge` mutates process env.** Fine for the dashboard (single-purpose process), and it runs in the bridge thread before rclpy.init(). Not thread-safe if something else reads env concurrently, but nothing else does at startup.
4. **`dds_env` hardcodes `RMW_IMPLEMENTATION=rmw_fastrtps_cpp` + `ROS_SUPER_CLIENT=True`** — correct for the TurtleBot4 Discovery Server setup, matching upstream. A non-Discovery-Server robot would need different values; out of scope (TB4-only today).

---

## Out of scope (deferred, unchanged from v0.5.0 roadmap)

- **Dashboard ingesting SSH probe / DDS-blind fallback** (show diagnosis when DDS itself is down) — the bigger rework; defer until hardware confirms it's the real pain.
- **Dashboard "Recover" button** — Phase D-2 / later.
- **Unifying the three health representations** (adapter.health_check vs dashboard panels vs recovery RobotState) — separate design effort.
- **Second adapter / simulation** — later phases.
