# Robobench v0.3 (Phase C) — Diagnostic Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the headless diagnostic backend that powers robobench's "tell me what's wrong" wedge — a FastAPI server exposing live JSON panels (clock, sensor rates, TF tree, DDS graph), each enriched with actionable fix hints from a failure catalog, fed by a persistent rclpy bridge node. Demoable without any frontend: `robobench dashboard` then `curl localhost:8080/api/panels/tf`.

**Architecture:**
- A persistent `DiagnosticBridge` rclpy node (lazy-imported, same pattern as `lifecycle_activator`) subscribes to `/scan`, `/tf`, `/tf_static`, `/<ns>/amcl_pose` and writes into a thread-safe `DiagnosticState`. It spins in a daemon thread alongside FastAPI — the pattern the upstream `dashboard_server.py` already proved (`_ros_spin_thread`).
- **All diagnostic logic lives in pure functions** in `analyzers.py` (classify clock offset, compute topic Hz, build TF graph with broken-link detection, build DDS graph). These are 100% unit-testable with plain Python data — no ROS2, no hardware.
- A `FAILURE_CATALOG` maps each check + symptom to a `{cause, fix, link}`. FastAPI endpoints run analyzers over `DiagnosticState`, and when a check is WARN/FAIL they attach catalog hints. This is the "how to fix it" half of the positioning.
- The frontend (vendored cytoscape.js + uPlot) is **out of scope** — it's Phase C-2, a separate plan. This plan ships a JSON API that the frontend (and `curl`, and CI) consume.

**Tech Stack:** Python 3.11+, FastAPI + uvicorn (new optional dep group `dashboard`), httpx (dev, for `TestClient`), rclpy (lazy, runtime-only), pytest, ruff. No frontend, no new JS.

**Prerequisites:** v0.2.1a0 tagged. 53 unit tests passing. `robobench.diagnostics.lifecycle_activator` demonstrates the lazy-rclpy pattern this plan reuses.

**Repo root:** `C:\Users\chntw\Documents\robotic\robobench\`

---

## Scope note

Phase C was split during planning. This plan is **Phase C / diagnostic backend** only. Two sibling plans follow:
- **Phase C-2 — diagnostic frontend** (vendored cytoscape.js + uPlot, modular panels consuming this API). Not TDD-driven; separate doc.
- **Phase D — bring-up wizard + second adapter**.

This plan produces working, testable software on its own: a diagnostic JSON API.

---

## File Structure

```
robobench/
├── pyproject.toml                       # +[dashboard] optional deps, +dashboard CLI not needed (subcommand in cli.py)
├── src/robobench/
│   ├── __init__.py                      # version → 0.3.0a0 (Task 13)
│   ├── cli.py                           # +`dashboard` subcommand (Task 11)
│   └── panels/                          # NEW package — the diagnostic backend
│       ├── __init__.py
│       ├── state.py                     # DiagnosticState: thread-safe live-data container
│       ├── analyzers.py                 # PURE functions — the testable diagnostic core
│       ├── catalog.py                   # FAILURE_CATALOG + lookup_fixes()
│       ├── bridge.py                     # DiagnosticBridge rclpy node (lazy import)
│       └── server.py                    # FastAPI app + panel endpoints
├── tests/unit/panels/
│   ├── __init__.py
│   ├── test_state.py
│   ├── test_analyzers.py
│   ├── test_catalog.py
│   ├── test_bridge.py                   # smoke: importable without ROS2
│   └── test_server.py                   # FastAPI TestClient with injected state
├── docs/tutorials/
│   └── diagnosing-with-dashboard.md     # NEW (Task 12)
└── CHANGELOG.md                         # +0.3.0a0 entry (Task 13)
```

**Responsibility map:**
- `state.py` — `DiagnosticState`: holds the latest robot data the bridge collects (scan timestamps deque, tf transforms, node names, amcl pose, clock offset). Thread-safe (one lock). No ROS imports. Knows nothing about analysis or HTTP.
- `analyzers.py` — pure functions that turn raw `DiagnosticState` snapshots into panel verdicts. No ROS, no HTTP, no I/O. The unit-test core.
- `catalog.py` — static data + a lookup function. No deps.
- `bridge.py` — the only file that touches rclpy. Lazy-imported. Thin: callbacks just write to a `DiagnosticState`. Smoke-tested (importable without ROS2).
- `server.py` — FastAPI app. Reads a `DiagnosticState`, runs analyzers, attaches catalog hints, returns JSON. Tested with `TestClient` + an injected fake state. Does not import rclpy directly.
- `cli.py` — `robobench dashboard` starts the bridge thread + uvicorn.

---

## Task 1: Add `dashboard` optional dependency group

**Files:** `pyproject.toml`

- [ ] **Step 1: Add the optional dependency group + dev additions**

In `pyproject.toml`, find the `[project.optional-dependencies]` block. It currently has only `dev`. Replace the whole block with:

```toml
[project.optional-dependencies]
dashboard = [
  "fastapi>=0.110",
  "uvicorn>=0.29",
  "websockets>=12",
]
dev = [
  "pytest>=8.0",
  "pytest-mock>=3.12",
  "ruff>=0.4",
  "types-paramiko>=3.4",
  "fastapi>=0.110",
  "uvicorn>=0.29",
  "websockets>=12",
  "httpx>=0.27",
]
```

(`httpx` is required by FastAPI's `TestClient`; the dashboard deps are duplicated into `dev` so the test suite can import the server.)

- [ ] **Step 2: Install + verify existing tests still pass**

```bash
cd C:/Users/chntw/Documents/robotic/robobench
source .venv/Scripts/activate
pip install -e ".[dev]"
pytest -q
ruff check . && ruff format --check .
```
Expected: 53 tests pass, ruff clean. (fastapi/uvicorn/httpx now installed.)

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore(deps): add dashboard optional dependency group (fastapi, uvicorn, websockets)"
```

---

## Task 2: `DiagnosticState` thread-safe container (TDD)

**Files:**
- Create: `src/robobench/panels/__init__.py`
- Create: `src/robobench/panels/state.py`
- Create: `tests/unit/panels/__init__.py`
- Create: `tests/unit/panels/test_state.py`

- [ ] **Step 1: Create package markers**

Create `src/robobench/panels/__init__.py`:
```python
"""Robobench diagnostic backend — live state, analyzers, catalog, FastAPI server."""
```

Create `tests/unit/panels/__init__.py` as empty (0 bytes).

- [ ] **Step 2: Write failing test `tests/unit/panels/test_state.py`**

```python
"""Tests for DiagnosticState."""
from __future__ import annotations

from robobench.panels.state import DiagnosticState


def test_record_scan_keeps_bounded_timestamps():
    """record_scan appends a timestamp; the deque is bounded to maxlen."""
    s = DiagnosticState(scan_window=3)
    for t in [1.0, 2.0, 3.0, 4.0]:
        s.record_scan(t)
    assert list(s.scan_timestamps()) == [2.0, 3.0, 4.0]


def test_set_and_get_tf_transforms_round_trips():
    """TF transforms are stored as (parent, child, stamp) tuples."""
    s = DiagnosticState()
    s.set_tf([("map", "odom", 100.0), ("odom", "base_link", 100.1)])
    assert s.tf_transforms() == [("map", "odom", 100.0), ("odom", "base_link", 100.1)]


def test_set_and_get_node_names():
    s = DiagnosticState()
    s.set_nodes(["/amcl", "/controller_server"])
    assert s.node_names() == ["/amcl", "/controller_server"]


def test_clock_offset_defaults_to_none_then_settable():
    s = DiagnosticState()
    assert s.clock_offset() is None
    s.set_clock_offset(0.42)
    assert s.clock_offset() == 0.42


def test_snapshot_returns_consistent_copy():
    """snapshot() returns a plain dict copy that won't mutate with later writes."""
    s = DiagnosticState()
    s.set_clock_offset(1.0)
    s.set_nodes(["/a"])
    snap = s.snapshot()
    s.set_clock_offset(2.0)
    s.set_nodes(["/a", "/b"])
    assert snap["clock_offset"] == 1.0
    assert snap["nodes"] == ["/a"]
```

- [ ] **Step 3: Run, confirm fail**

```bash
pytest tests/unit/panels/test_state.py -v
```
Expected: ImportError on `robobench.panels.state`.

- [ ] **Step 4: Implement `src/robobench/panels/state.py`**

```python
"""Thread-safe container for live diagnostic data collected by the bridge.

The rclpy bridge writes here from its spin thread; the FastAPI handlers read
from request threads. One lock guards everything. No ROS or HTTP imports —
this is a plain data holder so it stays trivially testable.
"""
from __future__ import annotations

import threading
from collections import deque


class DiagnosticState:
    """Holds the most recent robot data the diagnostic bridge has seen."""

    def __init__(self, scan_window: int = 100) -> None:
        self._lock = threading.Lock()
        self._scan_ts: deque[float] = deque(maxlen=scan_window)
        self._tf: list[tuple[str, str, float]] = []
        self._nodes: list[str] = []
        self._clock_offset: float | None = None

    def record_scan(self, stamp: float) -> None:
        with self._lock:
            self._scan_ts.append(stamp)

    def scan_timestamps(self) -> deque[float]:
        with self._lock:
            return deque(self._scan_ts)

    def set_tf(self, transforms: list[tuple[str, str, float]]) -> None:
        with self._lock:
            self._tf = list(transforms)

    def tf_transforms(self) -> list[tuple[str, str, float]]:
        with self._lock:
            return list(self._tf)

    def set_nodes(self, names: list[str]) -> None:
        with self._lock:
            self._nodes = list(names)

    def node_names(self) -> list[str]:
        with self._lock:
            return list(self._nodes)

    def set_clock_offset(self, offset: float | None) -> None:
        with self._lock:
            self._clock_offset = offset

    def clock_offset(self) -> float | None:
        with self._lock:
            return self._clock_offset

    def snapshot(self) -> dict:
        """Return a consistent plain-dict copy of all state under one lock."""
        with self._lock:
            return {
                "scan_timestamps": list(self._scan_ts),
                "tf": list(self._tf),
                "nodes": list(self._nodes),
                "clock_offset": self._clock_offset,
            }
```

- [ ] **Step 5: Run, confirm pass + ruff**

```bash
pytest tests/unit/panels/test_state.py -v
ruff check src tests && ruff format --check src tests
```
Expected: 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/robobench/panels/__init__.py src/robobench/panels/state.py tests/unit/panels/__init__.py tests/unit/panels/test_state.py
git commit -m "feat(panels): add thread-safe DiagnosticState container"
```

---

## Task 3: Analyzers — clock classifier + topic rate (TDD)

**Files:**
- Create: `src/robobench/panels/analyzers.py`
- Create: `tests/unit/panels/test_analyzers.py`

- [ ] **Step 1: Write failing tests `tests/unit/panels/test_analyzers.py`**

```python
"""Tests for the pure diagnostic analyzer functions."""
from __future__ import annotations

import pytest

from robobench.panels.analyzers import classify_clock_offset, compute_topic_rate


@pytest.mark.parametrize(
    "offset,expected",
    [
        (0.0, "OK"),
        (1.9, "OK"),
        (-1.9, "OK"),
        (2.0, "WARN"),
        (5.0, "WARN"),
        (-9.9, "WARN"),
        (10.0, "FAIL"),
        (-50.0, "FAIL"),
    ],
)
def test_classify_clock_offset(offset, expected):
    assert classify_clock_offset(offset) == expected


def test_classify_clock_offset_none_is_unknown():
    assert classify_clock_offset(None) == "UNKNOWN"


def test_compute_topic_rate_basic():
    """10 evenly spaced stamps over 1.0s window => ~10 Hz."""
    timestamps = [i * 0.1 for i in range(11)]  # 0.0 .. 1.0, 11 samples, 10 intervals
    rate = compute_topic_rate(timestamps)
    assert rate == pytest.approx(10.0, abs=0.1)


def test_compute_topic_rate_too_few_samples_returns_zero():
    assert compute_topic_rate([]) == 0.0
    assert compute_topic_rate([1.0]) == 0.0


def test_compute_topic_rate_zero_span_returns_zero():
    """All-identical timestamps => no measurable span => 0.0 (not a div-by-zero)."""
    assert compute_topic_rate([5.0, 5.0, 5.0]) == 0.0
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/panels/test_analyzers.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement clock + rate in `src/robobench/panels/analyzers.py`**

```python
"""Pure diagnostic analyzers.

Every function here takes plain Python data and returns plain Python data —
no ROS, no HTTP, no I/O. This is the unit-testable core of the diagnostic
backend. The FastAPI layer feeds these functions snapshots from
DiagnosticState and serializes the results.
"""
from __future__ import annotations

# Clock offset severity thresholds (seconds). Single source of truth for the
# whole project; the adapter and CLI should eventually import these too.
CLOCK_OK_THRESHOLD = 2.0
CLOCK_WARN_THRESHOLD = 10.0


def classify_clock_offset(offset: float | None) -> str:
    """Map a clock offset (seconds) to OK / WARN / FAIL / UNKNOWN."""
    if offset is None:
        return "UNKNOWN"
    magnitude = abs(offset)
    if magnitude < CLOCK_OK_THRESHOLD:
        return "OK"
    if magnitude < CLOCK_WARN_THRESHOLD:
        return "WARN"
    return "FAIL"


def compute_topic_rate(timestamps: list[float]) -> float:
    """Compute the publish rate (Hz) from a list of message timestamps.

    Returns 0.0 if there are fewer than two samples or the time span is zero
    (avoids division by zero on identical stamps).
    """
    if len(timestamps) < 2:
        return 0.0
    span = max(timestamps) - min(timestamps)
    if span <= 0.0:
        return 0.0
    intervals = len(timestamps) - 1
    return intervals / span
```

- [ ] **Step 4: Run, confirm pass + ruff**

```bash
pytest tests/unit/panels/test_analyzers.py -v
ruff check src tests && ruff format --check src tests
```
Expected: all parametrized clock cases + rate tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/analyzers.py tests/unit/panels/test_analyzers.py
git commit -m "feat(panels): add clock classifier and topic-rate analyzers"
```

---

## Task 4: Analyzer — TF graph builder with broken-link detection (TDD)

**Files:**
- Modify: `src/robobench/panels/analyzers.py`
- Modify: `tests/unit/panels/test_analyzers.py`

- [ ] **Step 1: Append failing tests**

Add to `tests/unit/panels/test_analyzers.py`:

```python
from robobench.panels.analyzers import build_tf_graph


def test_build_tf_graph_nodes_and_edges():
    """A simple two-edge chain produces 3 nodes and 2 edges."""
    transforms = [("map", "odom", 100.0), ("odom", "base_link", 100.0)]
    graph = build_tf_graph(transforms, now=100.0, stale_after=1.0)
    assert set(graph["nodes"]) == {"map", "odom", "base_link"}
    assert {"parent": "map", "child": "odom", "stale": False} in graph["edges"]
    assert {"parent": "odom", "child": "base_link", "stale": False} in graph["edges"]
    assert graph["broken"] == []


def test_build_tf_graph_flags_stale_edges():
    """An edge whose stamp is older than stale_after is flagged stale and broken."""
    transforms = [("map", "odom", 100.0), ("odom", "base_link", 90.0)]
    graph = build_tf_graph(transforms, now=100.0, stale_after=1.0)
    stale_edges = [e for e in graph["edges"] if e["stale"]]
    assert stale_edges == [{"parent": "odom", "child": "base_link", "stale": True}]
    assert graph["broken"] == ["odom->base_link"]


def test_build_tf_graph_empty():
    graph = build_tf_graph([], now=0.0, stale_after=1.0)
    assert graph == {"nodes": [], "edges": [], "broken": []}
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Append `build_tf_graph` to `analyzers.py`**

```python
def build_tf_graph(
    transforms: list[tuple[str, str, float]],
    now: float,
    stale_after: float = 1.0,
) -> dict:
    """Build a TF frame graph from (parent, child, stamp) transforms.

    An edge is "stale" if ``now - stamp > stale_after`` — the #1 symptom of a
    broken TF tree (a publisher died, or clock skew makes stamps look old).

    Returns::

        {
          "nodes": ["map", "odom", "base_link"],
          "edges": [{"parent": "map", "child": "odom", "stale": False}, ...],
          "broken": ["odom->base_link"],   # parent->child of every stale edge
        }
    """
    nodes: list[str] = []
    edges: list[dict] = []
    broken: list[str] = []
    for parent, child, stamp in transforms:
        for frame in (parent, child):
            if frame not in nodes:
                nodes.append(frame)
        stale = (now - stamp) > stale_after
        edges.append({"parent": parent, "child": child, "stale": stale})
        if stale:
            broken.append(f"{parent}->{child}")
    return {"nodes": nodes, "edges": edges, "broken": broken}
```

- [ ] **Step 4: Run, confirm pass + ruff**

Expected: 3 new tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/analyzers.py tests/unit/panels/test_analyzers.py
git commit -m "feat(panels): add TF graph builder with stale-edge detection"
```

---

## Task 5: Analyzer — DDS node graph builder (TDD)

**Files:**
- Modify: `src/robobench/panels/analyzers.py`
- Modify: `tests/unit/panels/test_analyzers.py`

- [ ] **Step 1: Append failing tests**

```python
from robobench.panels.analyzers import build_dds_graph


def test_build_dds_graph_marks_expected_nodes_present_and_missing():
    """Given visible nodes and an expected set, mark each present/missing."""
    visible = ["/amcl", "/controller_server", "/bt_navigator"]
    expected = ["/amcl", "/controller_server", "/planner_server"]
    graph = build_dds_graph(visible_nodes=visible, expected_nodes=expected)

    present = {n["name"]: n for n in graph["nodes"]}
    assert present["/amcl"]["status"] == "present"
    assert present["/controller_server"]["status"] == "present"
    # expected-but-not-visible
    assert present["/planner_server"]["status"] == "missing"
    # visible-but-not-expected (extra) still listed
    assert present["/bt_navigator"]["status"] == "present"
    assert graph["missing"] == ["/planner_server"]


def test_build_dds_graph_no_expected_lists_all_present():
    graph = build_dds_graph(visible_nodes=["/a", "/b"], expected_nodes=[])
    assert {n["name"] for n in graph["nodes"]} == {"/a", "/b"}
    assert all(n["status"] == "present" for n in graph["nodes"])
    assert graph["missing"] == []
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Append `build_dds_graph` to `analyzers.py`**

```python
def build_dds_graph(visible_nodes: list[str], expected_nodes: list[str]) -> dict:
    """Build a DDS node-presence graph.

    Every node is classified ``present`` (currently discoverable) or
    ``missing`` (expected but not seen — the usual symptom of a node that
    crashed or never came up under FastDDS Discovery Server).

    Returns::

        {
          "nodes": [{"name": "/amcl", "status": "present"}, ...],
          "missing": ["/planner_server"],   # expected but not visible
        }
    """
    visible_set = set(visible_nodes)
    expected_set = set(expected_nodes)
    all_names = list(dict.fromkeys([*visible_nodes, *expected_nodes]))

    nodes: list[dict] = []
    missing: list[str] = []
    for name in all_names:
        if name in visible_set:
            nodes.append({"name": name, "status": "present"})
        else:
            nodes.append({"name": name, "status": "missing"})
            missing.append(name)
    # `missing` should only contain expected-but-absent names, in expected order
    missing = [n for n in expected_nodes if n not in visible_set]
    return {"nodes": nodes, "missing": missing}
```

- [ ] **Step 4: Run, confirm pass + ruff**

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/analyzers.py tests/unit/panels/test_analyzers.py
git commit -m "feat(panels): add DDS node-presence graph builder"
```

---

## Task 6: Failure catalog + lookup (TDD)

**Files:**
- Create: `src/robobench/panels/catalog.py`
- Create: `tests/unit/panels/test_catalog.py`

- [ ] **Step 1: Write failing tests `tests/unit/panels/test_catalog.py`**

```python
"""Tests for the failure catalog."""
from __future__ import annotations

from robobench.panels.catalog import FAILURE_CATALOG, lookup_fixes


def test_catalog_has_entries_for_core_checks():
    """Every core diagnostic check has at least one catalog entry."""
    for check in ("clock_offset", "sensor_rate", "tf_tree", "dds_graph"):
        assert check in FAILURE_CATALOG
        assert len(FAILURE_CATALOG[check]) >= 1
        for entry in FAILURE_CATALOG[check]:
            assert {"cause", "fix"} <= entry.keys()


def test_lookup_fixes_returns_matching_entries():
    """A FAIL status returns the catalog entries for that check."""
    fixes = lookup_fixes("clock_offset", status="FAIL")
    assert isinstance(fixes, list)
    assert len(fixes) >= 1
    assert "fix" in fixes[0]


def test_lookup_fixes_ok_status_returns_empty():
    """An OK status has nothing to fix."""
    assert lookup_fixes("clock_offset", status="OK") == []


def test_lookup_fixes_unknown_check_returns_empty():
    assert lookup_fixes("nonexistent_check", status="FAIL") == []
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement `src/robobench/panels/catalog.py`**

```python
"""Failure catalog: maps each diagnostic check to candidate causes + fixes.

This is the "tell me how to fix it" half of robobench. When a panel reports
WARN or FAIL, the server attaches the matching catalog entries so the user
sees concrete next steps, not just a red light.

Each entry is ``{"cause": str, "fix": str, "link": str | None}``.
Keep entries terse and actionable — they render in a small panel.
"""
from __future__ import annotations

FAILURE_CATALOG: dict[str, list[dict]] = {
    "clock_offset": [
        {
            "cause": "Workstation and robot clocks drifted apart.",
            "fix": "Run `robobench bringup` (configures chrony), or manually: "
            "`ssh <robot> 'sudo chronyc -a makestep'`.",
            "link": "https://docs.ros.org/en/rolling/Tutorials/Demos/Time.html",
        },
        {
            "cause": "Workstation isn't serving NTP, so the robot can't follow it.",
            "fix": "Add `allow 192.168.0.0/16` and `local stratum 10` to "
            "/etc/chrony/chrony.conf, then `sudo systemctl restart chrony`.",
            "link": None,
        },
    ],
    "sensor_rate": [
        {
            "cause": "LiDAR/IMU not publishing, or QoS mismatch (BEST_EFFORT vs RELIABLE).",
            "fix": "Check the sensor is powered and the driver node is up "
            "(`ros2 node list`); confirm your subscriber QoS matches the publisher.",
            "link": None,
        },
        {
            "cause": "Network saturation dropping sensor packets.",
            "fix": "Check WiFi signal / switch to ethernet; inspect `ros2 topic hz` "
            "for the raw rate at the source.",
            "link": None,
        },
    ],
    "tf_tree": [
        {
            "cause": "A TF publisher died, leaving a stale/broken edge.",
            "fix": "Identify the broken parent->child edge, find which node should "
            "publish it (`ros2 topic info /tf`), and restart that node.",
            "link": "https://docs.ros.org/en/rolling/Concepts/About-Tf2.html",
        },
        {
            "cause": "Clock skew makes fresh transforms look stale.",
            "fix": "Fix clock sync first (see the clock panel) — TF staleness is "
            "often a symptom of clock drift, not a missing publisher.",
            "link": None,
        },
    ],
    "dds_graph": [
        {
            "cause": "Expected node never came up or crashed under Discovery Server.",
            "fix": "Re-run `robobench-lifecycle-activator`; check the node's log. "
            "FastDDS Discovery Server can silently drop late joiners (Nav2 #3560).",
            "link": "https://github.com/ros-navigation/navigation2/issues/3560",
        },
        {
            "cause": "Discovery Server not reachable from the workstation.",
            "fix": "Verify `ROS_DISCOVERY_SERVER` env var and that the server port "
            "(default 11811) is listening on the robot.",
            "link": None,
        },
    ],
}


def lookup_fixes(check_name: str, status: str) -> list[dict]:
    """Return catalog entries for a check when its status is WARN/FAIL.

    OK / UNKNOWN return an empty list (nothing to fix). Unknown check names
    return an empty list rather than raising — callers pass whatever check
    ran, and a missing catalog entry just means "no canned advice yet".
    """
    if status not in ("WARN", "FAIL"):
        return []
    return list(FAILURE_CATALOG.get(check_name, []))
```

- [ ] **Step 4: Run, confirm pass + ruff**

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/catalog.py tests/unit/panels/test_catalog.py
git commit -m "feat(panels): add failure catalog with cause/fix lookup"
```

---

## Task 7: `DiagnosticBridge` rclpy node (lazy import, smoke test)

**Files:**
- Create: `src/robobench/panels/bridge.py`
- Create: `tests/unit/panels/test_bridge.py`

- [ ] **Step 1: Write smoke tests `tests/unit/panels/test_bridge.py`**

```python
"""Smoke tests for the diagnostic bridge.

The bridge is a ROS2 node — its substantive behavior is exercised only with a
real robot (``@pytest.mark.hardware``). The unit suite verifies the module
imports without ROS2 and that the rclpy-dependent entry point fails with a
clear message when ROS2 is missing.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_module_imports_without_ros2():
    import robobench.panels.bridge  # noqa: F401


def test_run_bridge_raises_clear_error_without_ros2():
    from robobench.panels.bridge import run_bridge
    from robobench.panels.state import DiagnosticState

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "rclpy" or name.startswith("rclpy."):
            raise ImportError("No module named 'rclpy'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        with pytest.raises(RuntimeError, match="ROS2"):
            run_bridge(DiagnosticState(), namespace="ns")
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement `src/robobench/panels/bridge.py`**

```python
"""Persistent rclpy bridge node that feeds DiagnosticState.

Lazy rclpy import (same pattern as robobench.diagnostics.lifecycle_activator)
so the module is importable without ROS2. ``run_bridge`` is meant to run in a
daemon thread alongside the FastAPI server (the pattern the upstream
dashboard_server.py proved with its _ros_spin_thread).

Callbacks are intentionally thin: they only push raw data into DiagnosticState.
All analysis happens in robobench.panels.analyzers over snapshots.
"""
from __future__ import annotations

from robobench.panels.state import DiagnosticState


def _lazy_imports() -> dict:
    """Import rclpy + ROS message types; raise a clear error if ROS2 is absent."""
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import LaserScan
        from tf2_msgs.msg import TFMessage
    except ImportError as exc:
        raise RuntimeError(
            "robobench diagnostic bridge requires ROS2 (rclpy, sensor_msgs, "
            "tf2_msgs). Source your ROS2 setup before running the dashboard."
        ) from exc
    return {
        "rclpy": rclpy,
        "Node": Node,
        "QoSProfile": QoSProfile,
        "ReliabilityPolicy": ReliabilityPolicy,
        "LaserScan": LaserScan,
        "TFMessage": TFMessage,
    }


def _stamp_to_float(stamp) -> float:
    """Convert a builtin_interfaces/Time to float seconds."""
    return stamp.sec + stamp.nanosec * 1e-9


def run_bridge(state: DiagnosticState, namespace: str) -> None:
    """Spin a node that fills ``state`` from robot topics. Blocks until shutdown.

    Intended to run in a daemon thread. Raises RuntimeError immediately if
    ROS2 isn't importable.
    """
    ros = _lazy_imports()
    rclpy = ros["rclpy"]
    Node = ros["Node"]
    QoSProfile = ros["QoSProfile"]
    ReliabilityPolicy = ros["ReliabilityPolicy"]
    LaserScan = ros["LaserScan"]
    TFMessage = ros["TFMessage"]

    rclpy.init()
    node = Node("robobench_diagnostic_bridge")

    sensor_qos = QoSProfile(depth=10)
    sensor_qos.reliability = ReliabilityPolicy.BEST_EFFORT

    scan_topic = f"/{namespace}/scan" if namespace else "/scan"

    def on_scan(msg) -> None:
        state.record_scan(_stamp_to_float(msg.header.stamp))

    def on_tf(msg) -> None:
        transforms = [
            (t.header.frame_id, t.child_frame_id, _stamp_to_float(t.header.stamp))
            for t in msg.transforms
        ]
        state.set_tf(transforms)

    node.create_subscription(LaserScan, scan_topic, on_scan, sensor_qos)
    node.create_subscription(TFMessage, "/tf", on_tf, 10)

    # Periodically refresh the visible node list for the DDS panel.
    def refresh_nodes() -> None:
        names = [f"/{n}" if not n.startswith("/") else n for n, _ns in node.get_node_names_and_namespaces()]
        state.set_nodes(names)

    node.create_timer(2.0, refresh_nodes)

    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
```

- [ ] **Step 4: Run, confirm pass + ruff**

```bash
pytest tests/unit/panels/test_bridge.py -v
ruff check src tests && ruff format --check src tests
```
Expected: 2 smoke tests pass. The module imports without ROS2; `run_bridge` raises a clear RuntimeError when rclpy is mocked absent.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/bridge.py tests/unit/panels/test_bridge.py
git commit -m "feat(panels): add lazy-rclpy DiagnosticBridge node"
```

---

## Task 8: FastAPI app skeleton + `/healthz` + state injection (TDD)

**Files:**
- Create: `src/robobench/panels/server.py`
- Create: `tests/unit/panels/test_server.py`

- [ ] **Step 1: Write failing test `tests/unit/panels/test_server.py`**

```python
"""Tests for the diagnostic FastAPI server (TestClient + injected state)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from robobench.panels.server import create_app
from robobench.panels.state import DiagnosticState


def _client(state: DiagnosticState, expected_nodes=None) -> TestClient:
    app = create_app(state, namespace="ns", expected_nodes=expected_nodes or [])
    return TestClient(app)


def test_healthz_returns_ok():
    client = _client(DiagnosticState())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement `src/robobench/panels/server.py` (skeleton + healthz)**

```python
"""FastAPI app exposing diagnostic panels as JSON.

The app holds a reference to a DiagnosticState (filled by the bridge thread)
and a set of expected node names (for the DDS panel). Endpoints run pure
analyzers over state snapshots and attach failure-catalog hints on WARN/FAIL.

The app never imports rclpy — it only reads DiagnosticState. That keeps it
testable with a plain injected state object.
"""
from __future__ import annotations

from fastapi import FastAPI

from robobench.panels.state import DiagnosticState


def create_app(
    state: DiagnosticState,
    namespace: str,
    expected_nodes: list[str] | None = None,
) -> FastAPI:
    """Build the FastAPI app bound to a given DiagnosticState."""
    app = FastAPI(title="robobench diagnostics")
    app.state.diag = state
    app.state.namespace = namespace
    app.state.expected_nodes = expected_nodes or []

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app
```

- [ ] **Step 4: Run, confirm pass + ruff**

```bash
pytest tests/unit/panels/test_server.py -v
ruff check src tests && ruff format --check src tests
```
Expected: healthz test passes.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/server.py tests/unit/panels/test_server.py
git commit -m "feat(panels): add FastAPI app skeleton with healthz and state injection"
```

---

## Task 9: Panel endpoints — clock + sensors (TDD)

**Files:**
- Modify: `src/robobench/panels/server.py`
- Modify: `tests/unit/panels/test_server.py`

- [ ] **Step 1: Append failing tests**

```python
def test_clock_panel_ok():
    state = DiagnosticState()
    state.set_clock_offset(0.3)
    resp = _client(state).get("/api/panels/clock")
    body = resp.json()
    assert body["status"] == "OK"
    assert body["offset_seconds"] == 0.3
    assert body["fixes"] == []


def test_clock_panel_fail_attaches_catalog_fixes():
    state = DiagnosticState()
    state.set_clock_offset(42.0)
    body = _client(state).get("/api/panels/clock").json()
    assert body["status"] == "FAIL"
    assert len(body["fixes"]) >= 1
    assert "fix" in body["fixes"][0]


def test_clock_panel_unknown_when_no_offset():
    body = _client(DiagnosticState()).get("/api/panels/clock").json()
    assert body["status"] == "UNKNOWN"


def test_sensors_panel_reports_scan_rate():
    state = DiagnosticState()
    for t in [i * 0.1 for i in range(11)]:  # ~10 Hz
        state.record_scan(t)
    body = _client(state).get("/api/panels/sensors").json()
    assert body["scan"]["rate_hz"] > 8.0
    assert body["scan"]["status"] in ("OK", "WARN", "FAIL")


def test_sensors_panel_fail_when_no_data_attaches_fixes():
    body = _client(DiagnosticState()).get("/api/panels/sensors").json()
    assert body["scan"]["rate_hz"] == 0.0
    assert body["scan"]["status"] == "FAIL"
    assert len(body["scan"]["fixes"]) >= 1
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Add the endpoints to `create_app` in `server.py`**

Add these imports at the top of `server.py`:
```python
from robobench.panels.analyzers import (
    classify_clock_offset,
    compute_topic_rate,
)
from robobench.panels.catalog import lookup_fixes
```

Add inside `create_app`, before `return app`:
```python
    # Scan-rate thresholds (Hz). Below FAIL_HZ: effectively dead.
    SCAN_OK_HZ = 5.0
    SCAN_WARN_HZ = 2.0

    @app.get("/api/panels/clock")
    def clock_panel() -> dict:
        offset = app.state.diag.clock_offset()
        status = classify_clock_offset(offset)
        return {
            "status": status,
            "offset_seconds": offset,
            "fixes": lookup_fixes("clock_offset", status),
        }

    @app.get("/api/panels/sensors")
    def sensors_panel() -> dict:
        timestamps = list(app.state.diag.scan_timestamps())
        rate = compute_topic_rate(timestamps)
        if rate >= SCAN_OK_HZ:
            status = "OK"
        elif rate >= SCAN_WARN_HZ:
            status = "WARN"
        else:
            status = "FAIL"
        return {
            "scan": {
                "rate_hz": round(rate, 2),
                "status": status,
                "fixes": lookup_fixes("sensor_rate", status),
            }
        }
```

- [ ] **Step 4: Run, confirm pass + ruff**

Expected: 5 new server tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/server.py tests/unit/panels/test_server.py
git commit -m "feat(panels): add clock and sensors panel endpoints with catalog hints"
```

---

## Task 10: Panel endpoints — TF tree + DDS graph (TDD)

**Files:**
- Modify: `src/robobench/panels/server.py`
- Modify: `tests/unit/panels/test_server.py`

- [ ] **Step 1: Append failing tests**

```python
import time


def test_tf_panel_reports_graph_and_broken_edges():
    state = DiagnosticState()
    now = time.time()
    state.set_tf([("map", "odom", now), ("odom", "base_link", now - 100.0)])
    body = _client(state).get("/api/panels/tf").json()
    assert set(body["nodes"]) == {"map", "odom", "base_link"}
    assert body["broken"] == ["odom->base_link"]
    assert body["status"] == "FAIL"
    assert len(body["fixes"]) >= 1


def test_tf_panel_ok_when_all_fresh():
    state = DiagnosticState()
    now = time.time()
    state.set_tf([("map", "odom", now)])
    body = _client(state).get("/api/panels/tf").json()
    assert body["broken"] == []
    assert body["status"] == "OK"
    assert body["fixes"] == []


def test_dds_panel_marks_missing_expected_nodes():
    state = DiagnosticState()
    state.set_nodes(["/amcl"])
    body = _client(state, expected_nodes=["/amcl", "/planner_server"]).get(
        "/api/panels/dds"
    ).json()
    assert body["missing"] == ["/planner_server"]
    assert body["status"] == "FAIL"
    assert len(body["fixes"]) >= 1


def test_dds_panel_ok_when_all_present():
    state = DiagnosticState()
    state.set_nodes(["/amcl", "/planner_server"])
    body = _client(state, expected_nodes=["/amcl", "/planner_server"]).get(
        "/api/panels/dds"
    ).json()
    assert body["missing"] == []
    assert body["status"] == "OK"
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Add endpoints to `create_app`**

Add to the imports in `server.py`:
```python
import time

from robobench.panels.analyzers import (
    build_dds_graph,
    build_tf_graph,
    classify_clock_offset,
    compute_topic_rate,
)
```
(Merge the analyzer imports into the single existing import block — don't duplicate.)

Add inside `create_app`, before `return app`:
```python
    @app.get("/api/panels/tf")
    def tf_panel() -> dict:
        graph = build_tf_graph(
            app.state.diag.tf_transforms(), now=time.time(), stale_after=1.0
        )
        status = "FAIL" if graph["broken"] else "OK"
        return {**graph, "status": status, "fixes": lookup_fixes("tf_tree", status)}

    @app.get("/api/panels/dds")
    def dds_panel() -> dict:
        graph = build_dds_graph(
            visible_nodes=app.state.diag.node_names(),
            expected_nodes=app.state.expected_nodes,
        )
        status = "FAIL" if graph["missing"] else "OK"
        return {**graph, "status": status, "fixes": lookup_fixes("dds_graph", status)}
```

- [ ] **Step 4: Run, confirm pass + ruff**

Expected: 4 new tests pass; full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/server.py tests/unit/panels/test_server.py
git commit -m "feat(panels): add TF tree and DDS graph panel endpoints"
```

---

## Task 11: `robobench dashboard` CLI subcommand (TDD)

**Files:**
- Modify: `src/robobench/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Append failing test to `tests/unit/test_cli.py`**

```python
def test_dashboard_subcommand_starts_server(mocker, tmp_path):
    """`robobench dashboard` builds the app, starts the bridge thread, runs uvicorn."""
    cfg = _write_config(tmp_path)

    fake_state = MagicMock()
    mocker.patch("robobench.cli.DiagnosticState", return_value=fake_state)
    create_app_mock = mocker.patch("robobench.cli.create_app", return_value="APP")
    thread_mock = mocker.patch("robobench.cli.threading.Thread")
    run_mock = mocker.patch("robobench.cli.uvicorn.run")

    rc = main(
        ["dashboard", "--robot", "turtlebot4", "--config", str(cfg), "--port", "9090"]
    )

    assert rc == 0
    create_app_mock.assert_called_once()
    thread_mock.assert_called_once()        # bridge spins in a daemon thread
    assert thread_mock.call_args.kwargs.get("daemon") is True
    run_mock.assert_called_once()
    assert run_mock.call_args.kwargs.get("port") == 9090
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/test_cli.py -v -k dashboard
```
Expected: argparse "invalid choice: 'dashboard'".

- [ ] **Step 3: Implement in `src/robobench/cli.py`**

Add at the top of the file (merge with existing imports):
```python
import threading
```

Add inside `_build_parser`, after the `shutdown` subparser:
```python
    dashboard = subparsers.add_parser(
        "dashboard", help="Start the diagnostic dashboard server."
    )
    dashboard.add_argument("--robot", required=True, choices=["turtlebot4"])
    dashboard.add_argument("--config", required=True)
    dashboard.add_argument("--port", type=int, default=8080)
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.set_defaults(func=_cmd_dashboard)
```

Add the command function (after `_cmd_shutdown`):
```python
def _cmd_dashboard(args: argparse.Namespace) -> int:
    import uvicorn

    from robobench.panels.bridge import run_bridge
    from robobench.panels.server import create_app
    from robobench.panels.state import DiagnosticState

    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2

    kwargs = load_adapter_config(Path(args.config))
    namespace = kwargs["namespace"]

    state = DiagnosticState()
    # Bridge spins in a daemon thread; if ROS2 is missing it raises inside the
    # thread and the dashboard still serves (panels just show UNKNOWN/empty).
    threading.Thread(
        target=_safe_run_bridge, args=(state, namespace), daemon=True
    ).start()

    app = create_app(state, namespace=namespace, expected_nodes=_DEFAULT_EXPECTED_NODES)
    print(f"robobench dashboard on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _safe_run_bridge(state, namespace: str) -> None:
    """Run the bridge, swallowing the no-ROS2 RuntimeError so the web server
    stays up (panels degrade to UNKNOWN/empty instead of crashing)."""
    from robobench.panels.bridge import run_bridge

    try:
        run_bridge(state, namespace=namespace)
    except RuntimeError as exc:
        print(f"[dashboard] bridge not started: {exc}", file=sys.stderr)


_DEFAULT_EXPECTED_NODES = [
    "map_server",
    "amcl",
    "controller_server",
    "planner_server",
    "behavior_server",
    "bt_navigator",
    "waypoint_follower",
    "velocity_smoother",
]
```

Note: the test mocks `robobench.cli.DiagnosticState`, `robobench.cli.create_app`, `robobench.cli.threading.Thread`, and `robobench.cli.uvicorn.run`. For those patches to resolve, the symbols must be importable as attributes of the `robobench.cli` module. `threading` is imported at module top (done above). `uvicorn`, `DiagnosticState`, `create_app` are imported inside `_cmd_dashboard` — but `mocker.patch("robobench.cli.uvicorn.run")` needs `uvicorn` as a module attribute. **To make the patches work, also add module-level imports** at the top of `cli.py`:

```python
import uvicorn

from robobench.panels.server import create_app
from robobench.panels.state import DiagnosticState
```

Then remove the duplicate local imports of `uvicorn`, `create_app`, `DiagnosticState` from inside `_cmd_dashboard` (keep the local `run_bridge` import inside `_safe_run_bridge`). This makes `robobench.cli.uvicorn`, `robobench.cli.create_app`, `robobench.cli.DiagnosticState` patchable.

**Caveat:** module-level `import uvicorn` and `from robobench.panels.server import create_app` mean `robobench.cli` now imports FastAPI/uvicorn at load time. Since those are in the `dashboard` dep group (and in `dev`), importing `robobench.cli` without them installed would fail. To keep `robobench check` usable without the dashboard extra, guard the imports:

```python
try:
    import uvicorn
    from robobench.panels.server import create_app
    from robobench.panels.state import DiagnosticState
    _DASHBOARD_AVAILABLE = True
except ImportError:
    _DASHBOARD_AVAILABLE = False
```

And at the start of `_cmd_dashboard`:
```python
    if not _DASHBOARD_AVAILABLE:
        print(
            "dashboard requires the 'dashboard' extra: pip install 'robobench[dashboard]'",
            file=sys.stderr,
        )
        return 2
```

The test has the deps installed (they're in `dev`), so `_DASHBOARD_AVAILABLE` is True and the patches resolve.

- [ ] **Step 4: Run, confirm pass + ruff + smoke**

```bash
pytest -q
ruff check src tests && ruff format --check src tests
robobench dashboard --help
```
Expected: full suite green, `robobench dashboard --help` prints the new flags.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add robobench dashboard subcommand"
```

---

## Task 12: Tutorial — diagnosing with the dashboard (headless/API)

**Files:** `docs/tutorials/diagnosing-with-dashboard.md`

- [ ] **Step 1: Write the tutorial**

````markdown
# Diagnosing a robot with the dashboard (API)

This walks through robobench's diagnostic backend. v0.3 ships the **JSON API**;
the visual frontend lands in a later release. You can drive everything with
`curl` today.

## Start the dashboard

```bash
robobench dashboard --robot turtlebot4 --config ./config.yaml --port 8080
```

This:
1. Starts a persistent ROS2 bridge node (in a daemon thread) that subscribes
   to `/<ns>/scan`, `/tf`, and tracks the visible node list.
2. Serves a diagnostic API on `http://127.0.0.1:8080`.

If ROS2 isn't sourced, the server still starts — panels just report
`UNKNOWN` / empty until a bridge can connect.

## Read the panels

Each panel is a GET endpoint returning JSON with a `status` and, when
something's wrong, a `fixes` array of `{cause, fix, link}` from the failure
catalog.

```bash
curl -s localhost:8080/api/panels/clock | jq
```
```json
{
  "status": "FAIL",
  "offset_seconds": 42.0,
  "fixes": [
    {"cause": "Workstation and robot clocks drifted apart.",
     "fix": "Run `robobench bringup` (configures chrony), or manually: ssh <robot> 'sudo chronyc -a makestep'.",
     "link": "https://docs.ros.org/en/rolling/Tutorials/Demos/Time.html"}
  ]
}
```

| Endpoint | What it tells you |
|----------|-------------------|
| `GET /api/panels/clock` | Workstation↔robot clock offset, OK/WARN/FAIL |
| `GET /api/panels/sensors` | LiDAR scan rate (Hz) and whether it's healthy |
| `GET /api/panels/tf` | TF frame graph + which edges are stale/broken |
| `GET /api/panels/dds` | Which expected Nav2 nodes are present vs missing |
| `GET /healthz` | Liveness check (always `{"status":"ok"}`) |

## A typical debug session

"My robot won't navigate." Start the dashboard, then:

```bash
curl -s localhost:8080/api/panels/dds | jq '.missing'
# ["planner_server"]   ← planner never came up
curl -s localhost:8080/api/panels/dds | jq '.fixes[0].fix'
# "Re-run robobench-lifecycle-activator; check the node's log..."
```

The `fixes` come from `robobench.panels.catalog` — concrete next steps, not
just a red light.

## What's next

Phase C-2 adds the visual frontend: a TF tree you can see (cytoscape.js), a
DDS node graph, and live sensor sparklines (uPlot) — all consuming these same
endpoints.
````

- [ ] **Step 2: Commit**

```bash
git add docs/tutorials/diagnosing-with-dashboard.md
git commit -m "docs(tutorials): add diagnosing-with-dashboard API walkthrough"
```

---

## Task 13: CHANGELOG + version bump + tag v0.3.0a0 + push

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `src/robobench/__init__.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Update CHANGELOG.md**

Replace the `## [Unreleased]` line with:

```markdown
## [Unreleased]

## [0.3.0a0] — 2026-05-28

### Added

- `robobench.panels` package — the diagnostic backend:
  - `DiagnosticState`: thread-safe live-data container.
  - `analyzers`: pure functions — clock classifier, topic-rate, TF graph with
    stale-edge detection, DDS node-presence graph.
  - `catalog`: failure catalog mapping each check to cause/fix/link.
  - `bridge`: lazy-rclpy node that fills DiagnosticState from `/scan`, `/tf`,
    and the live node list.
  - `server`: FastAPI app exposing `/api/panels/{clock,sensors,tf,dds}` JSON
    endpoints, each enriched with catalog fix hints on WARN/FAIL.
- `robobench dashboard` CLI subcommand — starts the bridge thread + server.
- `dashboard` optional dependency group (`pip install 'robobench[dashboard]'`).
- Tutorial: `docs/tutorials/diagnosing-with-dashboard.md`.

### Notes

- The visual frontend (cytoscape.js TF/DDS graphs, uPlot sensor sparklines) is
  Phase C-2 — this release ships the JSON API the frontend will consume.
```

- [ ] **Step 2: Bump version**

In `src/robobench/__init__.py`: `__version__ = "0.2.1a0"` → `__version__ = "0.3.0a0"`.
In `pyproject.toml`: `version = "0.2.1a0"` → `version = "0.3.0a0"`.

- [ ] **Step 3: Final sweep**

```bash
source .venv/Scripts/activate
pip install -e ".[dev]"
pytest -q
ruff check . && ruff format --check .
robobench --version       # robobench 0.3.0a0
robobench dashboard --help
```
Expected: all tests pass (~75+), ruff clean, version correct, dashboard help works.

- [ ] **Step 4: Commit + tag + push**

```bash
git add CHANGELOG.md src/robobench/__init__.py pyproject.toml
git commit -m "chore: bump version to 0.3.0a0 and update CHANGELOG"
git tag -a v0.3.0a0 -m "v0.3.0-alpha - Phase C: diagnostic backend (panels API + failure catalog)"
git push origin main
git push origin v0.3.0a0
```

- [ ] **Step 5: Verify**

```bash
git tag --list
```
Expected: `v0.1.0a0`, `v0.2.0a0`, `v0.2.1a0`, `v0.3.0a0`.

---

## Self-Review (Plan Author Notes)

**Spec coverage check:**
- Persistent rclpy bridge → Task 7 ✅
- Pure analyzers (clock, rate, TF, DDS) → Tasks 3, 4, 5 ✅
- Failure catalog ("how to fix it") → Task 6, wired into endpoints in Tasks 9, 10 ✅
- FastAPI panel API → Tasks 8, 9, 10 ✅
- CLI `dashboard` → Task 11 ✅
- Headless-demoable (curl) → Task 12 tutorial proves it ✅
- v0.3.0a0 tag → Task 13 ✅

**Placeholder scan:** No TBDs. Every code step has the full code.

**Type consistency:**
- `DiagnosticState` methods (`record_scan`, `scan_timestamps`, `set_tf`, `tf_transforms`, `set_nodes`, `node_names`, `set_clock_offset`, `clock_offset`, `snapshot`) defined in Task 2 are used verbatim by the bridge (Task 7) and server (Tasks 8-10).
- Analyzer signatures: `classify_clock_offset(offset)`, `compute_topic_rate(timestamps)`, `build_tf_graph(transforms, now, stale_after)`, `build_dds_graph(visible_nodes, expected_nodes)` — defined in Tasks 3-5, called in Tasks 9-10 with matching args.
- `lookup_fixes(check_name, status)` — Task 6, called with check names `"clock_offset"`, `"sensor_rate"`, `"tf_tree"`, `"dds_graph"` which all exist as `FAILURE_CATALOG` keys.
- `create_app(state, namespace, expected_nodes)` — Task 8, reused identically in the test helper `_client` across Tasks 8-10, and in cli.py Task 11.

**Known risks / honest notes:**
1. **Bridge is unit-tested only for import safety.** Its actual subscription/callback behavior runs only against a real robot (`@pytest.mark.hardware` — to be added when lab personnel test). The analyzers it feeds ARE fully tested with synthetic data, so the risk is isolated to the thin glue in `bridge.py`.
2. **`get_node_names_and_namespaces` formatting.** The DDS panel compares node names; the bridge prefixes `/`. Real ROS2 node names may or may not include namespace — needs real-robot verification that the `expected_nodes` defaults match what `ros2 node list` actually shows under the namespace. Flagged for lab testing.
3. **Scan-rate thresholds (5/2 Hz)** are guesses for TurtleBot4 RPLIDAR (~10 Hz nominal). May need tuning per sensor — fine as defaults, configurable later.
4. **No websocket yet.** This plan is request/response (`curl`-friendly). Live streaming to the frontend is Phase C-2's concern; the frontend can poll these endpoints initially, or C-2 adds a `/ws` fanout then.
5. **Module-level FastAPI import in cli.py** is guarded with try/except so `robobench check` still works without the dashboard extra (Task 11 Step 3 caveat).

---

## Out of scope (deferred)

- **Visual frontend** (cytoscape.js, uPlot, modular panels) — Phase C-2.
- **WebSocket live streaming** — Phase C-2 (frontend polls the JSON endpoints until then).
- **Bring-up wizard** (browser-driven, replacing `robobench bringup`) — Phase D.
- **One-click fix actions** (the upstream dashboard's `/api/preflight/fix/*` pattern) — Phase D; v0.3 only *reports* fixes from the catalog, doesn't execute them.
- **Second robot adapter** — Phase D.
- **rclpy-direct migration of the adapter's `health_check`** (currently CLI shell-out, ~45s) — could reuse this bridge later; not in v0.3.
