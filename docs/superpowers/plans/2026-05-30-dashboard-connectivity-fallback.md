# Dashboard DDS-blind Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the dashboard's in-process DDS bridge sees nothing, surface a layered SSH "connectivity" diagnosis (which transport layer is broken + how to fix it) in a new 5th dashboard panel.

**Architecture:** A second daemon thread runs a lite SSH probe (the five transport layers, skipping the slow odom echo) on a slow non-overlapping timer, writing a `RobotState` into `DiagnosticState`. A pure analyzer turns it into a panel payload; a new endpoint + frontend card render it. The existing DDS bridge and four panels are untouched.

**Tech Stack:** Python 3.11+, paramiko (SSH), FastAPI, pytest, ruff, vanilla-JS ES modules. Windows + Git Bash dev env; rclpy NOT installed (irrelevant here — this feature is SSH + pure analysis + FastAPI, no rclpy). Run tests/lint with `.venv/Scripts/python.exe -m pytest -q` and `.venv/Scripts/python.exe -m ruff check src tests`.

Spec: `docs/superpowers/specs/2026-05-30-dashboard-connectivity-fallback-design.md`.

---

## File Structure

| File | Responsibility | Task |
|------|----------------|------|
| `src/robobench/panels/catalog.py` | +5 per-aspect connectivity fix entries | 1 |
| `src/robobench/panels/connectivity.py` (new) | Pure: `CONNECTIVITY_ASPECTS`, `first_broken_layer`, `diagnose` | 2 |
| `src/robobench/panels/state.py` | `DiagnosticState.set_connectivity/connectivity` | 3 |
| `src/robobench/robots/turtlebot4_probe.py` | `read_connectivity()` lite read (refactor `read`) | 4 |
| `src/robobench/panels/connectivity_probe.py` (new) | `run_connectivity_probe` loop (thin, testable) | 5 |
| `src/robobench/panels/server.py` | `GET /api/panels/connectivity` | 6 |
| `src/robobench/cli.py` | `_cmd_dashboard` 2nd thread + `--no-ssh-probe`/`--ssh-probe-interval`; demo seed | 7 |
| `src/robobench/panels/static/panels/connectivity.js` (new) + `index.html` + `style.css` | 5th card | 8 |
| tutorial + `CHANGELOG.md` + version | release v0.10.0a0 | 9 |

---

## Task 1: Per-aspect connectivity fixes in the catalog

**Files:**
- Modify: `src/robobench/panels/catalog.py` (add 5 entries to `FAILURE_CATALOG`)
- Test: `tests/unit/panels/test_catalog.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/panels/test_catalog.py  (append)
def test_connectivity_aspect_fixes_present():
    from robobench.panels.catalog import lookup_fixes

    for aspect in (
        "rpi_reachable",
        "discovery_server_ok",
        "clock_synced",
        "create3_topics",
        "tb4_nodes_present",
    ):
        fixes = lookup_fixes(aspect, "FAIL")
        assert fixes, f"no catalog fixes for {aspect}"
        assert "fix" in fixes[0] and "cause" in fixes[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_catalog.py::test_connectivity_aspect_fixes_present -v`
Expected: FAIL (catalog has no `rpi_reachable` key, `lookup_fixes` returns `[]`)

- [ ] **Step 3: Add the five entries** — inside `FAILURE_CATALOG` in `catalog.py`, after the existing `"dds_graph"` list (before the closing `}` of the dict):

```python
    "rpi_reachable": [
        {
            "cause": "The robot's RPi is off, not on the network, or at a different IP.",
            "fix": "Check the robot is powered and on the same network; verify "
            "`robot.ip` in config.yaml; try `ping <ip>`.",
            "link": None,
        },
    ],
    "discovery_server_ok": [
        {
            "cause": "The FastDDS Discovery Server isn't listening on the robot.",
            "fix": "SSH in and `sudo systemctl restart discovery.service`; confirm "
            "port 11811 with `ss -ulnp | grep 11811`. (Nav2 #3560)",
            "link": "https://github.com/ros-navigation/navigation2/issues/3560",
        },
    ],
    "clock_synced": [
        {
            "cause": "Workstation and robot clocks have drifted apart.",
            "fix": "Run `robobench bringup` (configures chrony), or "
            "`ssh <robot> 'sudo chronyc -a makestep'`.",
            "link": None,
        },
    ],
    "create3_topics": [
        {
            "cause": "No /<namespace>/ topics — the Create3 base isn't publishing.",
            "fix": "Restart the Create3 app, or run `robobench recover`. "
            "Check the Create3 web UI at http://192.168.186.2.",
            "link": None,
        },
    ],
    "tb4_nodes_present": [
        {
            "cause": "The TurtleBot4 ROS nodes (Nav2 etc.) didn't come up.",
            "fix": "Re-run `robobench-lifecycle-activator`, or `robobench recover`; "
            "check the bring-up service: `systemctl status turtlebot4`.",
            "link": None,
        },
    ],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_catalog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/catalog.py tests/unit/panels/test_catalog.py
git commit -m "feat: per-aspect connectivity fixes in failure catalog"
```

---

## Task 2: Pure connectivity analyzer

**Files:**
- Create: `src/robobench/panels/connectivity.py`
- Test: `tests/unit/panels/test_connectivity.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/panels/test_connectivity.py
from robobench.panels.connectivity import CONNECTIVITY_ASPECTS, diagnose, first_broken_layer
from robobench.recovery.state import RobotState


def _state(**kw) -> RobotState:
    base = dict(
        rpi_reachable=True,
        discovery_server_ok=True,
        clock_synced=True,
        create3_topics=5,
        tb4_nodes_present=True,
        odom_publishing=True,
    )
    base.update(kw)
    return RobotState(**base)


def test_all_layers_ok_is_status_ok_even_if_odom_false():
    state = _state(odom_publishing=False)  # odom is downstream — ignored here
    result = diagnose(state)
    assert result["status"] == "OK"
    assert result["first_broken"] is None
    assert result["fixes"] == []
    assert [layer["name"] for layer in result["layers"]] == [a for a, _ in CONNECTIVITY_ASPECTS]


def test_first_broken_is_most_upstream():
    state = _state(discovery_server_ok=False, tb4_nodes_present=False)
    assert first_broken_layer(state) == "discovery_server_ok"
    result = diagnose(state)
    assert result["status"] == "FAIL"
    assert result["first_broken"] == "discovery_server_ok"
    assert result["fixes"], "FAIL should carry catalog fixes"


def test_create3_topics_zero_counts_as_broken():
    assert first_broken_layer(_state(create3_topics=0)) == "create3_topics"


def test_rpi_unreachable_is_first():
    state = _state(rpi_reachable=False, discovery_server_ok=False)
    assert first_broken_layer(state) == "rpi_reachable"


def test_none_is_unknown():
    result = diagnose(None)
    assert result["status"] == "UNKNOWN"
    assert result["layers"] == []
    assert result["first_broken"] is None
    assert result["fixes"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_connectivity.py -v`
Expected: FAIL (`No module named 'robobench.panels.connectivity'`)

- [ ] **Step 3: Write the implementation**

```python
# src/robobench/panels/connectivity.py
"""Pure connectivity diagnosis for the dashboard's SSH-probe fallback.

Turns a recovery RobotState into a layered "which transport layer is broken"
panel payload. Deliberately ignores ``odom_publishing`` (the sensor panel owns
liveness) — only the five upstream transport layers matter for "why is the
dashboard blind". No SSH, no rclpy: trivially unit-testable.
"""

from __future__ import annotations

from robobench.panels.catalog import lookup_fixes
from robobench.recovery.state import RobotState

# Upstream -> downstream: (aspect_name, human label). Excludes odom_publishing.
CONNECTIVITY_ASPECTS: tuple[tuple[str, str], ...] = (
    ("rpi_reachable", "RPi reachable"),
    ("discovery_server_ok", "Discovery Server up"),
    ("clock_synced", "Clock synced"),
    ("create3_topics", "Create3 topics present"),
    ("tb4_nodes_present", "TB4 nodes present"),
)


def _aspect_ok(state: RobotState, aspect: str) -> bool:
    if aspect == "create3_topics":
        return state.create3_topics > 0
    return bool(getattr(state, aspect))


def first_broken_layer(state: RobotState) -> str | None:
    """Most-upstream failing connectivity aspect (odom ignored), or None."""
    for aspect, _label in CONNECTIVITY_ASPECTS:
        if not _aspect_ok(state, aspect):
            return aspect
    return None


def diagnose(state: RobotState | None) -> dict:
    """Build the connectivity panel payload.

    ``None`` (probe hasn't run / disabled) -> UNKNOWN. Otherwise OK when all
    five layers pass, else FAIL with the first broken layer and its catalog fixes.
    """
    if state is None:
        return {"status": "UNKNOWN", "layers": [], "first_broken": None, "fixes": []}
    layers = [
        {"name": aspect, "label": label, "ok": _aspect_ok(state, aspect)}
        for aspect, label in CONNECTIVITY_ASPECTS
    ]
    broken = first_broken_layer(state)
    return {
        "status": "FAIL" if broken else "OK",
        "layers": layers,
        "first_broken": broken,
        "fixes": lookup_fixes(broken, "FAIL") if broken else [],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_connectivity.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/connectivity.py tests/unit/panels/test_connectivity.py
git commit -m "feat: pure connectivity analyzer (layered diagnosis, odom-agnostic)"
```

---

## Task 3: DiagnosticState connectivity slot

**Files:**
- Modify: `src/robobench/panels/state.py`
- Test: `tests/unit/panels/test_state.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/panels/test_state.py  (append)
def test_connectivity_defaults_none_and_roundtrips():
    from robobench.panels.state import DiagnosticState
    from robobench.recovery.state import RobotState

    state = DiagnosticState()
    assert state.connectivity() is None
    assert state.snapshot()["connectivity"] is None

    rs = RobotState(True, False, True, 0, False, True)
    state.set_connectivity(rs)
    assert state.connectivity() == rs
    assert state.snapshot()["connectivity"] == rs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_state.py::test_connectivity_defaults_none_and_roundtrips -v`
Expected: FAIL (`AttributeError: 'DiagnosticState' object has no attribute 'connectivity'`)

- [ ] **Step 3: Implement** — in `state.py`:

Add a TYPE_CHECKING import near the top (after `from collections import deque`):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from robobench.recovery.state import RobotState
```

In `__init__`, after `self._clock_offset: float | None = None`:

```python
        self._connectivity: RobotState | None = None
```

Add two methods (after `clock_offset`):

```python
    def set_connectivity(self, state: RobotState | None) -> None:
        with self._lock:
            self._connectivity = state

    def connectivity(self) -> RobotState | None:
        with self._lock:
            return self._connectivity
```

In `snapshot()`, add the key to the returned dict:

```python
                "connectivity": self._connectivity,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/state.py tests/unit/panels/test_state.py
git commit -m "feat: DiagnosticState holds the latest connectivity RobotState"
```

---

## Task 4: Lite `read_connectivity()` on the probe

**Files:**
- Modify: `src/robobench/robots/turtlebot4_probe.py:53-95` (refactor `read` → `_read(check_odom)`, add `read_connectivity`)
- Test: `tests/unit/robots/test_turtlebot4_probe.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/robots/test_turtlebot4_probe.py  (append)
class _RecordingSSH:
    """Fake SSHClient context manager that records issued commands."""

    def __init__(self, commands: list):
        self._commands = commands

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cmd, timeout=None):
        import subprocess

        self._commands.append(cmd)
        text = " ".join(cmd)
        if "11811" in text:
            out = "1"
        elif cmd[:2] == ["date", "+%s"]:
            out = "0"  # ancient time -> clock NOT synced (drift huge)
        elif "topic list" in text:
            out = "12"
        elif "node list" in text:
            out = "/tb/node\n"
        else:
            out = ""
        return subprocess.CompletedProcess(cmd, 0, out, "")


def test_read_connectivity_skips_odom_echo():
    from robobench.robots.turtlebot4_probe import TurtleBot4Probe

    commands: list = []
    probe = TurtleBot4Probe(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="tb",
        ssh_factory=lambda *a, **k: _RecordingSSH(commands),
        ping=lambda _ip: True,
    )
    state = probe.read_connectivity()

    # odom echo must NOT have been issued
    assert not any("odom" in " ".join(c) for c in commands)
    # odom_publishing is the documented "not checked" sentinel
    assert state.odom_publishing is True
    # the five transport layers reflect the fake responses
    assert state.rpi_reachable is True
    assert state.discovery_server_ok is True
    assert state.create3_topics == 12
    assert state.tb4_nodes_present is True


def test_read_connectivity_short_circuits_on_unreachable():
    from robobench.robots.turtlebot4_probe import TurtleBot4Probe

    commands: list = []
    probe = TurtleBot4Probe(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="tb",
        ssh_factory=lambda *a, **k: _RecordingSSH(commands),
        ping=lambda _ip: False,
    )
    state = probe.read_connectivity()
    assert state.rpi_reachable is False
    assert commands == []  # no SSH attempted when ping fails
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/robots/test_turtlebot4_probe.py::test_read_connectivity_skips_odom_echo -v`
Expected: FAIL (`AttributeError: 'TurtleBot4Probe' object has no attribute 'read_connectivity'`)

- [ ] **Step 3: Refactor `read` and add `read_connectivity`** — replace the current `read` method (lines 53-95) with:

```python
    def read(self) -> RobotState:
        """Full bring-up read (includes the odom 2-sample stability check)."""
        return self._read(check_odom=True)

    def read_connectivity(self) -> RobotState:
        """Lite read for the dashboard: the five transport layers, no odom echo.

        ``odom_publishing`` is set ``True`` as a documented sentinel meaning "not
        checked here" — the connectivity panel never reads it (the sensor panel
        owns liveness). Each cycle finishes in a few seconds instead of ~30s.
        """
        return self._read(check_odom=False)

    def _read(self, *, check_odom: bool) -> RobotState:
        if not self._ping(self.ip):
            return RobotState(
                rpi_reachable=False,
                discovery_server_ok=False,
                clock_synced=False,
                create3_topics=0,
                tb4_nodes_present=False,
                odom_publishing=False,
            )

        with self._ssh_factory(self.ip, self.ssh_user, self.ssh_pass) as ssh:
            ds = ssh.run(["sh", "-c", "ss -ulnp | grep 11811 | wc -l"], timeout=10)
            discovery_ok = ds.returncode == 0 and _parse_int(ds.stdout) > 0

            dt = ssh.run(["date", "+%s"], timeout=10)
            clock_synced = False
            if dt.returncode == 0:
                drift = abs(self._now() - _parse_float(dt.stdout))
                clock_synced = drift <= _CLOCK_TOLERANCE_S

            tc = ssh.run(
                ["sh", "-c", f"{_ROS_ENV}ros2 topic list | grep -c '/{self.namespace}/'"],
                timeout=20,
            )
            create3_topics = _parse_int(tc.stdout) if tc.returncode == 0 else 0

            nodes = ssh.run(
                ["sh", "-c", f"{_ROS_ENV}ros2 node list | grep '/{self.namespace}/'"],
                timeout=20,
            )
            tb4_nodes_present = nodes.returncode == 0 and bool(nodes.stdout.strip())

            odom_publishing = self._odom_stable(ssh) if check_odom else True

        return RobotState(
            rpi_reachable=True,
            discovery_server_ok=discovery_ok,
            clock_synced=clock_synced,
            create3_topics=create3_topics,
            tb4_nodes_present=tb4_nodes_present,
            odom_publishing=odom_publishing,
        )
```

- [ ] **Step 4: Run tests to verify they pass (incl. existing probe tests)**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/robots/test_turtlebot4_probe.py -v`
Expected: PASS (new + all existing — `read()` behavior is unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/robobench/robots/turtlebot4_probe.py tests/unit/robots/test_turtlebot4_probe.py
git commit -m "feat: TurtleBot4Probe.read_connectivity() (lite read, skips odom echo)"
```

---

## Task 5: Connectivity probe loop

**Files:**
- Create: `src/robobench/panels/connectivity_probe.py`
- Test: `tests/unit/panels/test_connectivity_probe.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/panels/test_connectivity_probe.py
from robobench.panels.connectivity_probe import run_connectivity_probe
from robobench.panels.state import DiagnosticState
from robobench.recovery.state import RobotState

_OK = RobotState(True, True, True, 5, True, True)
_BAD = RobotState(True, False, True, 0, False, True)


def test_loop_writes_connectivity_each_cycle_and_stops():
    state = DiagnosticState()
    reports = iter([_BAD, _OK])

    class Probe:
        def read_connectivity(self):
            return next(reports)

    counter = {"n": 0}

    def fake_sleep(_seconds):
        counter["n"] += 1

    run_connectivity_probe(
        state,
        Probe(),
        interval=1.0,
        sleep=fake_sleep,
        should_stop=lambda: counter["n"] >= 2,
    )
    assert state.connectivity() == _OK  # last write wins
    assert counter["n"] == 2  # exactly two cycles


def test_loop_survives_probe_exception():
    state = DiagnosticState()
    calls = {"probe": 0, "sleep": 0}

    class Probe:
        def read_connectivity(self):
            calls["probe"] += 1
            if calls["probe"] == 1:
                raise RuntimeError("ssh boom")
            return _OK

    def fake_sleep(_seconds):
        calls["sleep"] += 1

    run_connectivity_probe(
        state,
        Probe(),
        interval=0.0,
        sleep=fake_sleep,
        should_stop=lambda: calls["sleep"] >= 2,
    )
    # first cycle raised but was swallowed; second cycle wrote a result
    assert state.connectivity() == _OK
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_connectivity_probe.py -v`
Expected: FAIL (`No module named 'robobench.panels.connectivity_probe'`)

- [ ] **Step 3: Write the implementation**

```python
# src/robobench/panels/connectivity_probe.py
"""Daemon-thread loop that periodically runs an SSH connectivity probe and
writes the result into DiagnosticState. Importable without ROS2 (no rclpy).

Single non-overlapping worker: probe() then sleep(interval), so a slow probe
never stacks. Each cycle is exception-guarded — one bad probe is logged and
skipped, never killing the thread.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

from robobench.panels.state import DiagnosticState


def run_connectivity_probe(
    state: DiagnosticState,
    probe,
    *,
    interval: float,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Loop: ``state.set_connectivity(probe.read_connectivity())`` then sleep.

    ``probe`` is any object exposing ``read_connectivity() -> RobotState``.
    Runs until ``should_stop()`` returns True (default: forever, for a daemon
    thread). A probe exception is logged to stderr and the loop continues.
    """
    stop = should_stop or (lambda: False)
    while not stop():
        try:
            state.set_connectivity(probe.read_connectivity())
        except Exception as exc:  # noqa: BLE001 — one bad cycle must not kill the loop
            print(f"[connectivity] probe failed: {exc}", file=sys.stderr)
        sleep(interval)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_connectivity_probe.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/connectivity_probe.py tests/unit/panels/test_connectivity_probe.py
git commit -m "feat: non-overlapping connectivity probe loop (exception-guarded)"
```

---

## Task 6: `/api/panels/connectivity` endpoint

**Files:**
- Modify: `src/robobench/panels/server.py` (import + endpoint)
- Test: `tests/unit/panels/test_server.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/panels/test_server.py  (append)
def test_connectivity_panel_unknown_then_fail():
    from fastapi.testclient import TestClient

    from robobench.panels.server import create_app
    from robobench.panels.state import DiagnosticState
    from robobench.recovery.state import RobotState

    state = DiagnosticState()
    client = TestClient(create_app(state, namespace="tb", expected_nodes=[]))

    # No probe yet -> UNKNOWN
    body = client.get("/api/panels/connectivity").json()
    assert body["status"] == "UNKNOWN"

    # Discovery Server down -> FAIL at that layer, with fixes
    state.set_connectivity(RobotState(True, False, True, 0, False, True))
    body = client.get("/api/panels/connectivity").json()
    assert body["status"] == "FAIL"
    assert body["first_broken"] == "discovery_server_ok"
    assert body["fixes"]
    assert [layer["name"] for layer in body["layers"]][0] == "rpi_reachable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_server.py::test_connectivity_panel_unknown_then_fail -v`
Expected: FAIL (404 — endpoint doesn't exist)

- [ ] **Step 3: Implement** — in `server.py`, add to the imports block (after `from robobench.panels.catalog import lookup_fixes`):

```python
from robobench.panels.connectivity import diagnose as diagnose_connectivity
```

Add the endpoint inside `create_app` (after the `dds_panel` endpoint, before the `if _STATIC_DIR.exists():` block):

```python
    @app.get("/api/panels/connectivity")
    def connectivity_panel() -> dict:
        return diagnose_connectivity(app.state.diag.connectivity())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/server.py tests/unit/panels/test_server.py
git commit -m "feat: GET /api/panels/connectivity endpoint"
```

---

## Task 7: Wire the probe thread into `robobench dashboard`

**Files:**
- Modify: `src/robobench/cli.py` (dashboard subparser args + `_cmd_dashboard`)
- Test: `tests/unit/test_cli.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli.py  (append)
def _dashboard_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "robot:\n  ip: 1.2.3.4\n  ssh_user: u\n  ssh_pass: p\n  namespace: tb\n"
        "dds:\n  discovery_port: 11811\n",
        encoding="utf-8",
    )
    return cfg


def test_dashboard_starts_connectivity_probe_thread(monkeypatch, tmp_path):
    created = []

    class FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=False):
            created.append({"target": target, "kwargs": kwargs or {}})

        def start(self):
            pass

    monkeypatch.setattr("robobench.cli.threading.Thread", FakeThread)
    monkeypatch.setattr("robobench.cli.uvicorn.run", lambda *a, **k: None)

    from robobench.cli import main
    from robobench.panels.connectivity_probe import run_connectivity_probe

    rc = main(["dashboard", "--robot", "turtlebot4", "--config", str(_dashboard_config(tmp_path))])
    assert rc == 0
    probe_threads = [c for c in created if c["target"] is run_connectivity_probe]
    assert len(probe_threads) == 1
    assert probe_threads[0]["kwargs"]["interval"] == 20.0


def test_dashboard_no_ssh_probe_skips_thread(monkeypatch, tmp_path):
    created = []

    class FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=False):
            created.append(target)

        def start(self):
            pass

    monkeypatch.setattr("robobench.cli.threading.Thread", FakeThread)
    monkeypatch.setattr("robobench.cli.uvicorn.run", lambda *a, **k: None)

    from robobench.cli import main
    from robobench.panels.connectivity_probe import run_connectivity_probe

    rc = main(
        [
            "dashboard",
            "--robot",
            "turtlebot4",
            "--config",
            str(_dashboard_config(tmp_path)),
            "--no-ssh-probe",
        ]
    )
    assert rc == 0
    assert run_connectivity_probe not in created
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli.py::test_dashboard_starts_connectivity_probe_thread -v`
Expected: FAIL (`--no-ssh-probe`/probe thread don't exist; no probe thread created)

- [ ] **Step 3: Add dashboard args** — in `_build_parser`, in the `dashboard` subparser block (after the `--demo` argument, before `dashboard.set_defaults(...)`):

```python
    dashboard.add_argument(
        "--no-ssh-probe",
        action="store_true",
        help="Disable the SSH connectivity probe (pure-DDS dashboard).",
    )
    dashboard.add_argument(
        "--ssh-probe-interval",
        type=float,
        default=20.0,
        help="Seconds between SSH connectivity probes (default 20).",
    )
```

- [ ] **Step 4: Wire the thread + demo seed** — in `_cmd_dashboard`:

In the `if args.demo:` branch, after `seed_demo_state(state, now=time.time())`, add a synthetic connectivity report so the panel is viewable with no hardware:

```python
        from robobench.recovery.state import RobotState  # noqa: PLC0415

        state.set_connectivity(
            RobotState(
                rpi_reachable=True,
                discovery_server_ok=False,
                clock_synced=True,
                create3_topics=0,
                tb4_nodes_present=False,
                odom_publishing=True,
            )
        )
```

In the `else:` (non-demo) branch, after the bridge `threading.Thread(...).start()` block and its `print(...)`, add:

```python
        if not args.no_ssh_probe:
            from robobench.panels.connectivity_probe import run_connectivity_probe  # noqa: PLC0415

            probe = TurtleBot4Probe(
                ip=kwargs["ip"],
                ssh_user=kwargs["ssh_user"],
                ssh_pass=kwargs["ssh_pass"],
                namespace=namespace,
            )
            threading.Thread(
                target=run_connectivity_probe,
                args=(state, probe),
                kwargs={"interval": args.ssh_probe_interval},
                daemon=True,
            ).start()
            print(
                f"[dashboard] SSH connectivity probe every "
                f"{args.ssh_probe_interval:.0f}s"
            )
```

(`TurtleBot4Probe` is already imported at the top of `cli.py`.)

- [ ] **Step 5: Run tests + full suite + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli.py -v && .venv/Scripts/python.exe -m ruff check src tests`
Expected: PASS; ruff clean

- [ ] **Step 6: Commit**

```bash
git add src/robobench/cli.py tests/unit/test_cli.py
git commit -m "feat: dashboard runs SSH connectivity probe thread (--no-ssh-probe/--ssh-probe-interval)"
```

---

## Task 8: Connectivity frontend card

**Files:**
- Create: `src/robobench/panels/static/panels/connectivity.js`
- Modify: `src/robobench/panels/static/index.html`
- Modify: `src/robobench/panels/static/style.css`
- Verify: browser (demo mode)

- [ ] **Step 1: Write `connectivity.js`** (mirrors `clock.js`: `startPolling` + `renderStatusPill` + `renderFixes`)

```javascript
// src/robobench/panels/static/panels/connectivity.js
import { startPolling } from "/static/core/api.js";
import { renderFixes, renderStatusPill } from "/static/core/status.js";

export function initConnectivityPanel(root) {
  root.innerHTML = `
    <h3>Connectivity (SSH) <span class="pill" id="conn-pill">…</span></h3>
    <ul class="ladder" id="conn-ladder"></ul>
    <ul class="fixes" id="conn-fixes"></ul>`;

  const pill = root.querySelector("#conn-pill");
  const ladder = root.querySelector("#conn-ladder");
  const fixes = root.querySelector("#conn-fixes");

  startPolling("connectivity", 5000, (data) => {
    renderStatusPill(pill, data.status);
    if (data.status === "UNKNOWN" || data.layers.length === 0) {
      ladder.innerHTML = `<li class="muted">waiting for SSH probe…</li>`;
    } else {
      ladder.innerHTML = data.layers
        .map((layer) => {
          const broken = layer.name === data.first_broken;
          const mark = layer.ok ? "✓" : "✗";
          const cls = layer.ok ? "ok" : broken ? "broken" : "down";
          return `<li class="layer ${cls}"><span class="mark">${mark}</span>${layer.label}</li>`;
        })
        .join("");
    }
    renderFixes(fixes, data.fixes);
  });
}
```

- [ ] **Step 2: Register the card in `index.html`** — add the section in `<main class="grid">` after the dds panel:

```html
    <section id="connectivity-panel" class="panel"></section>
```

And in the `<script type="module">` block, add the import + init:

```javascript
    import { initConnectivityPanel } from "/static/panels/connectivity.js";
```

```javascript
    initConnectivityPanel(document.getElementById("connectivity-panel"));
```

- [ ] **Step 3: Style the ladder** — append to `style.css`:

```css
.ladder { list-style: none; padding: 0; margin: 0.5rem 0; }
.ladder .layer { display: flex; align-items: center; gap: 0.5rem; padding: 0.15rem 0; }
.ladder .mark { width: 1.2em; text-align: center; font-weight: bold; }
.ladder .ok { color: #2e7d32; }
.ladder .down { color: #9e9e9e; }
.ladder .broken { color: #c62828; font-weight: bold; }
.ladder .muted { color: #9e9e9e; font-style: italic; }
```

- [ ] **Step 4: Verify in the browser (demo mode)**

Run: `.venv/Scripts/python.exe -m robobench dashboard --robot turtlebot4 --config <any config.yaml> --demo --port 8080`
Open `http://localhost:8080/`. Expected: a 5th "Connectivity (SSH)" card showing the ladder with `RPi reachable ✓`, `Discovery Server up ✗` (red, the first broken), the rest greyed, and the Discovery Server fix listed below. (Use the browse skill or a manual check; capture a screenshot.) Stop the server when done.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/static/panels/connectivity.js src/robobench/panels/static/index.html src/robobench/panels/static/style.css
git commit -m "feat: connectivity panel frontend card (layer ladder)"
```

---

## Task 9: Tutorial + release v0.10.0a0

**Files:**
- Modify: `docs/tutorials/diagnosing-with-dashboard.md`
- Modify: `CHANGELOG.md`, `pyproject.toml`, `src/robobench/__init__.py`

- [ ] **Step 1: Document the connectivity panel** — add this section to `docs/tutorials/diagnosing-with-dashboard.md` (before "## What's next"):

````markdown
## The Connectivity panel (DDS-blind fallback)

The DDS-based panels go blank when the robot's Discovery Server is down or the
RPi is unreachable — DDS can't tell you *why*. The **Connectivity** panel fills
that gap: a second background thread runs an SSH probe (reusing your
`config.yaml` `ssh_user`/`ssh_pass`) every ~20s and shows a layered ladder:

```
✓ RPi reachable
✗ Discovery Server up        ← first broken layer, with a fix below
  Clock synced
  Create3 topics present
  TB4 nodes present
```

The first broken layer is highlighted with its failure-catalog fix. So when the
DDS panels are blank, this one still says e.g. "Discovery Server down — restart
`discovery.service`."

Flags: `--no-ssh-probe` disables it (pure-DDS dashboard); `--ssh-probe-interval`
sets the cadence (default 20s). The odom liveness check is intentionally skipped
here (the sensor panel's scan rate already covers it), keeping each probe fast.
````

- [ ] **Step 2: CHANGELOG** — add under `## [Unreleased]`:

```markdown
## [0.10.0a0] — 2026-05-30

### Added

- **Dashboard DDS-blind fallback.** A new **Connectivity** panel runs a lite SSH
  probe (`TurtleBot4Probe.read_connectivity()`) on a slow background thread and
  shows a layered ladder (RPi → Discovery Server → clock → Create3 topics → TB4
  nodes) with the first broken layer + its fix. When the DDS panels go blank,
  this one explains *why*. `robobench.panels.connectivity` (pure analyzer),
  `connectivity_probe.run_connectivity_probe` (non-overlapping loop),
  `GET /api/panels/connectivity`, per-aspect catalog fixes.
- `robobench dashboard --no-ssh-probe` / `--ssh-probe-interval` (default 20s).
```

- [ ] **Step 3: Bump version** to `0.10.0a0` in `pyproject.toml` (`version = "0.10.0a0"`) and `src/robobench/__init__.py` (`__version__ = "0.10.0a0"`).

- [ ] **Step 4: Verify, commit, tag, push**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests && .venv/Scripts/robobench --version
git add CHANGELOG.md pyproject.toml src/robobench/__init__.py docs/tutorials/diagnosing-with-dashboard.md
git commit -m "release: v0.10.0a0 — dashboard connectivity panel (DDS-blind fallback)"
git tag v0.10.0a0
git push origin main && git push origin v0.10.0a0
```
Expected: all tests pass; `robobench 0.10.0a0`.

---

## Self-Review

**1. Spec coverage:**
- Trigger model (always-parallel, non-overlapping single worker) → Task 5 + Task 7 thread. ✓
- Surfacing (new 5th Connectivity panel) → Task 6 endpoint + Task 8 card. ✓
- Lite probe (5 layers, skip odom) → Task 4. ✓
- Pure analyzer (`CONNECTIVITY_ASPECTS`/`first_broken_layer`/`diagnose`, odom ignored) → Task 2. ✓
- DiagnosticState slot → Task 3. ✓
- Per-aspect catalog fixes via `lookup_fixes` → Task 1 (+ consumed in Task 2). ✓
- No new config; reuse ssh creds → Task 7 (`kwargs`). ✓
- `--no-ssh-probe` / `--ssh-probe-interval` → Task 7. ✓
- Demo seed → Task 7. ✓
- Error handling (loop never dies; SSH fail → rpi_reachable False) → Task 5 + Task 4 ping short-circuit. ✓
- Out of scope (no recover button, no DDS-path changes) — respected. ✓

**2. Placeholder scan:** No TBD/TODO/"add error handling"/"similar to". Every code step has complete code; every run step has an exact command + expected result.

**3. Type consistency:** `read_connectivity() -> RobotState` (Task 4) consumed by `run_connectivity_probe` via duck-typed `probe.read_connectivity()` (Task 5) and by `DiagnosticState.set_connectivity(RobotState | None)` (Task 3); `diagnose(RobotState | None) -> dict` (Task 2) consumed by the endpoint (Task 6) and rendered by `connectivity.js` keys `status`/`layers[{name,label,ok}]`/`first_broken`/`fixes` (Task 8) — all consistent. `CONNECTIVITY_ASPECTS` aspect names match the catalog keys added in Task 1 (`rpi_reachable`, `discovery_server_ok`, `clock_synced`, `create3_topics`, `tb4_nodes_present`).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-30-dashboard-connectivity-fallback.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec then quality) between tasks. (REQUIRED SUB-SKILL: superpowers:subagent-driven-development)
2. **Inline Execution** — batch execution with checkpoints. (REQUIRED SUB-SKILL: superpowers:executing-plans)
