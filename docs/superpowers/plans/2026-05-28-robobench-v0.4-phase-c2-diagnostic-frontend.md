# Robobench v0.4 (Phase C-2) — Diagnostic Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Phase C diagnostic API a visual face — a no-build-step web dashboard (vendored cytoscape.js + uPlot, native ES modules) that renders the clock / sensor-rate / TF-tree / DDS-graph panels live, with catalog fix hints shown inline when a check is red. Plus a `--demo` mode that populates the backend with synthetic data so the whole thing is viewable without a robot.

**Architecture:**
- The frontend lives **inside the package** at `src/robobench/panels/static/` and is served by the existing FastAPI app via `StaticFiles` + a `/` route. `pip install 'robobench[dashboard]'` ships it.
- **No build step.** Native browser ES modules (`<script type="module">`) split the code into focused files; two third-party libraries are **vendored** (committed) so the dashboard works offline / on locked-down lab networks: `cytoscape.js` (TF tree + DDS graph) and `uPlot` (sensor sparkline).
- The frontend **polls** the v0.3 JSON endpoints (`/api/panels/*`) on an interval — no websocket yet (the backend is request/response; websocket is a later optimization).
- A `seed_demo_state()` pure function + `robobench dashboard --demo` flag populate `DiagnosticState` with realistic synthetic data (a TF tree with one stale edge, ~10 Hz scan, a node list missing `planner_server`). This is both the frontend's verification vehicle and the "try it without hardware" story.

**Tech Stack:** FastAPI `StaticFiles` (already a dashboard dep), vanilla JS ES modules, vendored `cytoscape.js` 3.30.x + `uPlot` 1.6.x (MIT, Apache-compatible). No npm, no bundler. Backend changes are TDD'd; frontend JS is verified via `--demo` + a real browser screenshot.

**Prerequisites:** v0.3.0a0 tagged. 92 tests passing. `robobench.panels.server.create_app`, `robobench.panels.state.DiagnosticState`, `robobench dashboard` CLI all exist.

**Repo root:** `C:\Users\chntw\Documents\robotic\robobench\`

---

## File Structure

```
robobench/
├── pyproject.toml                              # +package-data so static/ ships in the wheel; version → 0.4.0a0
├── src/robobench/
│   ├── __init__.py                             # version → 0.4.0a0 (Task 12)
│   ├── cli.py                                  # `dashboard` gains --demo flag (Task 2)
│   └── panels/
│       ├── demo.py                             # NEW — seed_demo_state() pure fn (Task 1)
│       ├── server.py                           # +StaticFiles mount + `/` index route (Task 3)
│       └── static/                             # NEW — the frontend (Tasks 4-10)
│           ├── index.html                      # shell + module bootstrap
│           ├── style.css
│           ├── lib/
│           │   ├── cytoscape.min.js            # vendored (Task 4)
│           │   ├── uPlot.iife.min.js           # vendored (Task 4)
│           │   └── uPlot.min.css               # vendored (Task 4)
│           ├── core/
│           │   ├── api.js                       # fetch + poll helpers (Task 6)
│           │   └── status.js                    # status colors + fix rendering (Task 6)
│           └── panels/
│               ├── clock.js                     # (Task 7)
│               ├── sensor-rate.js               # uPlot (Task 8)
│               ├── tf-tree.js                   # cytoscape (Task 9)
│               └── dds-graph.js                 # cytoscape (Task 10)
├── tests/unit/panels/
│   ├── test_demo.py                            # NEW (Task 1)
│   ├── test_server.py                          # +static-serving tests (Task 3)
│   └── test_cli.py (tests/unit/)               # +--demo test (Task 2)
├── docs/tutorials/
│   └── diagnosing-with-dashboard.md            # +visual section (Task 11)
└── CHANGELOG.md                                # +0.4.0a0 (Task 12)
```

**Responsibility map:**
- `demo.py` — one pure function `seed_demo_state(state, now)`. No ROS, no HTTP. Testable.
- `server.py` — gains static mounting; unchanged otherwise. Still rclpy-free.
- `static/lib/` — third-party, vendored, never edited by us.
- `static/core/` — `api.js` (poll `/api/panels/*`), `status.js` (OK/WARN/FAIL/UNKNOWN → color, fix-list rendering). Reused by every panel.
- `static/panels/*.js` — one ES module per panel; each exports an `init<Panel>(rootEl)` that polls its endpoint and renders. cytoscape/uPlot are loaded as page globals (the vendored scripts are UMD/IIFE, not modules), so panel modules reference `cytoscape` / `uPlot` globals.

---

## Task 1: `seed_demo_state` synthetic data (TDD)

**Files:**
- Create: `src/robobench/panels/demo.py`
- Create: `tests/unit/panels/test_demo.py`

- [ ] **Step 1: Write failing test `tests/unit/panels/test_demo.py`**

```python
"""Tests for synthetic demo state seeding."""
from __future__ import annotations

from robobench.panels.analyzers import (
    build_dds_graph,
    build_tf_graph,
    classify_clock_offset,
    compute_topic_rate,
)
from robobench.panels.demo import DEMO_EXPECTED_NODES, seed_demo_state
from robobench.panels.state import DiagnosticState


def test_seed_demo_state_produces_a_mixed_health_picture():
    """The demo data should exercise OK, a healthy rate, and at least one FAIL
    so every panel has something interesting to render."""
    state = DiagnosticState()
    now = 1000.0
    seed_demo_state(state, now=now)

    snap = state.snapshot()

    # Clock: small offset => OK
    assert classify_clock_offset(snap["clock_offset"]) == "OK"

    # Scan: ~10 Hz => healthy
    assert compute_topic_rate(snap["scan_timestamps"]) > 8.0

    # TF: exactly one stale edge (broken)
    tf = build_tf_graph(snap["tf"], now=now, stale_after=1.0)
    assert len(tf["broken"]) == 1

    # DDS: at least one expected node missing
    dds = build_dds_graph(visible_nodes=snap["nodes"], expected_nodes=DEMO_EXPECTED_NODES)
    assert len(dds["missing"]) >= 1
```

- [ ] **Step 2: Run, confirm fail**

```bash
source .venv/Scripts/activate
pytest tests/unit/panels/test_demo.py -v
```
Expected: ImportError on `robobench.panels.demo`.

- [ ] **Step 3: Implement `src/robobench/panels/demo.py`**

```python
"""Synthetic demo data so the dashboard is viewable without a real robot.

`robobench dashboard --demo` calls seed_demo_state() instead of starting the
rclpy bridge. The data is chosen to exercise every panel: a healthy clock and
sensor rate, but a deliberately broken TF edge and a missing Nav2 node, so the
TF and DDS panels show their FAIL state + catalog fixes.
"""
from __future__ import annotations

from robobench.panels.state import DiagnosticState

# The Nav2 node set the demo pretends to expect. `planner_server` is absent
# from the seeded visible nodes so the DDS panel shows a FAIL.
DEMO_EXPECTED_NODES = [
    "/map_server",
    "/amcl",
    "/controller_server",
    "/planner_server",
    "/bt_navigator",
]


def seed_demo_state(state: DiagnosticState, now: float) -> None:
    """Fill ``state`` with a realistic mixed-health snapshot.

    - clock offset 0.12s (OK)
    - 20 scan stamps at ~10 Hz ending at ``now`` (healthy)
    - TF chain map->odom->base_link fresh, base_link->laser stale (broken)
    - visible nodes missing ``/planner_server`` (DDS FAIL)
    """
    state.set_clock_offset(0.12)

    # ~10 Hz: 20 samples spanning ~1.9s ending at `now`.
    for i in range(20):
        state.record_scan(now - 1.9 + i * 0.1)

    state.set_tf(
        [
            ("map", "odom", now),
            ("odom", "base_link", now),
            ("base_link", "laser", now - 100.0),  # stale -> broken
        ]
    )

    state.set_nodes(
        ["/map_server", "/amcl", "/controller_server", "/bt_navigator"]
    )  # /planner_server intentionally missing
```

- [ ] **Step 4: Run, confirm pass + ruff**

```bash
pytest tests/unit/panels/test_demo.py -v
pytest -q
ruff check src tests && ruff format --check src tests
```
Expected: 1 new test passes; 93 total.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/demo.py tests/unit/panels/test_demo.py
git commit -m "feat(panels): add seed_demo_state for hardware-free dashboard demo"
```

---

## Task 2: `robobench dashboard --demo` flag (TDD)

**Files:**
- Modify: `src/robobench/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Append failing test to `tests/unit/test_cli.py`**

```python
def test_dashboard_demo_flag_seeds_state_and_skips_bridge(mocker, tmp_path):
    """`robobench dashboard --demo` seeds demo state and does NOT start the bridge thread."""
    cfg = _write_config(tmp_path)

    fake_state = MagicMock()
    mocker.patch("robobench.cli.DiagnosticState", return_value=fake_state)
    mocker.patch("robobench.cli.create_app", return_value="APP")
    seed_mock = mocker.patch("robobench.cli.seed_demo_state")
    thread_mock = mocker.patch("robobench.cli.threading.Thread")
    mocker.patch("robobench.cli.uvicorn.run")

    rc = main(
        ["dashboard", "--robot", "turtlebot4", "--config", str(cfg), "--demo"]
    )

    assert rc == 0
    seed_mock.assert_called_once()           # demo data seeded
    thread_mock.assert_not_called()          # bridge thread NOT started in demo mode
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/test_cli.py -v -k demo_flag
```
Expected: fails — `--demo` not recognized, or `seed_demo_state` not patchable (not imported).

- [ ] **Step 3: Modify `src/robobench/cli.py`**

(a) In the guarded dashboard-imports block, add `seed_demo_state` so it's a module-level attribute (patchable). The block currently imports `uvicorn`, `create_app`, `DiagnosticState`. Update it to:

```python
try:
    import uvicorn

    from robobench.panels.demo import seed_demo_state
    from robobench.panels.server import create_app
    from robobench.panels.state import DiagnosticState

    _DASHBOARD_AVAILABLE = True
except ImportError:
    _DASHBOARD_AVAILABLE = False
```

(b) Add the `--demo` argument to the `dashboard` subparser in `_build_parser`:

```python
    dashboard.add_argument(
        "--demo",
        action="store_true",
        help="Seed synthetic data instead of connecting to a robot (no ROS2 needed).",
    )
```

(c) In `_cmd_dashboard`, replace the bridge-thread startup with a demo branch. The current body starts the thread unconditionally; change it to:

```python
    state = DiagnosticState()
    if args.demo:
        import time

        seed_demo_state(state, now=time.time())
        print("[dashboard] demo mode — serving synthetic data (no robot needed)")
    else:
        threading.Thread(
            target=_safe_run_bridge, args=(state, namespace), daemon=True
        ).start()

    app = create_app(
        state, namespace=namespace, expected_nodes=_DEFAULT_EXPECTED_NODES
    )
```

(Keep the rest of `_cmd_dashboard` — the `_DASHBOARD_AVAILABLE` guard, robot check, config load, `uvicorn.run` — unchanged.)

- [ ] **Step 4: Run, confirm pass + ruff + smoke**

```bash
pytest -q
ruff check src tests && ruff format --check src tests
robobench dashboard --help    # should now list --demo
```
Expected: 94 total tests pass. Note: the existing `test_dashboard_subcommand_starts_server` (non-demo) must still pass — it asserts `thread_mock.assert_called_once()`, which holds because that test doesn't pass `--demo`.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add dashboard --demo mode for hardware-free use"
```

---

## Task 3: Serve static files + `/` index route (TDD)

**Files:**
- Modify: `src/robobench/panels/server.py`
- Modify: `tests/unit/panels/test_server.py`
- Modify: `pyproject.toml`
- Create: `src/robobench/panels/static/index.html` (minimal placeholder so the route has something to serve during this task; real content lands in Task 5)

- [ ] **Step 1: Create a minimal placeholder index so tests have a file to serve**

Create `src/robobench/panels/static/index.html`:
```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>robobench diagnostics</title></head>
<body><h1>robobench diagnostics</h1></body>
</html>
```

- [ ] **Step 2: Append failing tests to `tests/unit/panels/test_server.py`**

```python
def test_index_route_serves_html():
    client = _client(DiagnosticState())
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "robobench diagnostics" in resp.text


def test_static_assets_are_mounted():
    """The /static mount serves files from the package static dir."""
    client = _client(DiagnosticState())
    resp = client.get("/static/index.html")
    assert resp.status_code == 200
```

- [ ] **Step 3: Run, confirm fail**

```bash
pytest tests/unit/panels/test_server.py -v -k "index_route or static_assets"
```
Expected: 404s.

- [ ] **Step 4: Add static serving to `create_app` in `server.py`**

Add imports at the top:
```python
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
```

Add a module-level constant (after imports):
```python
_STATIC_DIR = Path(__file__).parent / "static"
```

Inside `create_app`, before `return app`, add:
```python
    if _STATIC_DIR.exists():
        app.mount(
            "/static", StaticFiles(directory=str(_STATIC_DIR)), name="static"
        )

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "index.html"))
```

- [ ] **Step 5: Add package-data to `pyproject.toml` so static/ ships in the wheel**

After the `[tool.setuptools.packages.find]` block, add:
```toml
[tool.setuptools.package-data]
"robobench.panels" = ["static/**/*"]
```

- [ ] **Step 6: Run, confirm pass + ruff**

```bash
pip install -e ".[dev]"
pytest -q
ruff check src tests && ruff format --check src tests
```
Expected: 96 total tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/robobench/panels/server.py src/robobench/panels/static/index.html pyproject.toml tests/unit/panels/test_server.py
git commit -m "feat(panels): serve static frontend from FastAPI (StaticFiles + index route)"
```

---

## Task 4: Vendor cytoscape.js + uPlot

**Files:**
- Create: `src/robobench/panels/static/lib/cytoscape.min.js`
- Create: `src/robobench/panels/static/lib/uPlot.iife.min.js`
- Create: `src/robobench/panels/static/lib/uPlot.min.css`

- [ ] **Step 1: Download the libraries**

```bash
cd C:/Users/chntw/Documents/robotic/robobench
mkdir -p src/robobench/panels/static/lib
curl -fsSL https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.2/cytoscape.min.js \
  -o src/robobench/panels/static/lib/cytoscape.min.js
curl -fsSL https://cdn.jsdelivr.net/npm/uplot@1.6.31/dist/uPlot.iife.min.js \
  -o src/robobench/panels/static/lib/uPlot.iife.min.js
curl -fsSL https://cdn.jsdelivr.net/npm/uplot@1.6.31/dist/uPlot.min.css \
  -o src/robobench/panels/static/lib/uPlot.min.css
```

- [ ] **Step 2: Sanity-check the downloads**

```bash
wc -c src/robobench/panels/static/lib/*
head -c 120 src/robobench/panels/static/lib/cytoscape.min.js
head -c 120 src/robobench/panels/static/lib/uPlot.iife.min.js
```
Expected: cytoscape.min.js is ~400KB+, uPlot.iife.min.js is ~50KB, uPlot.min.css is ~5KB. The `head` should show minified JS (starts with `/*!` license banner or `(function`), NOT an HTML error page. If any file is tiny (<1KB) or starts with `<!doctype` / `<html`, the download failed — re-fetch from the alternate CDN (`https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js`, `https://unpkg.com/uplot@1.6.31/dist/uPlot.iife.min.js`, `https://unpkg.com/uplot@1.6.31/dist/uPlot.min.css`).

- [ ] **Step 3: Add a NOTICE-style attribution line**

Append to the top-level `NOTICE` file (so the vendored libs' licenses are acknowledged — both are MIT):

```text

This product bundles the following third-party JavaScript libraries under
src/robobench/panels/static/lib/ (both MIT licensed):

- cytoscape.js (https://js.cytoscape.org/) — Copyright (c) The Cytoscape Consortium
- uPlot (https://github.com/leeoniya/uPlot) — Copyright (c) Leon Sorokin
```

- [ ] **Step 4: Commit**

```bash
git add src/robobench/panels/static/lib/ NOTICE
git commit -m "chore(ui): vendor cytoscape.js and uPlot (MIT) for offline dashboard"
```

---

## Task 5: `index.html` shell + `style.css`

**Files:**
- Modify: `src/robobench/panels/static/index.html` (replace placeholder)
- Create: `src/robobench/panels/static/style.css`

- [ ] **Step 1: Replace `src/robobench/panels/static/index.html` with the full shell**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>robobench diagnostics</title>
  <link rel="stylesheet" href="/static/lib/uPlot.min.css" />
  <link rel="stylesheet" href="/static/style.css" />
  <script src="/static/lib/cytoscape.min.js"></script>
  <script src="/static/lib/uPlot.iife.min.js"></script>
</head>
<body>
  <header>
    <h1>robobench diagnostics</h1>
    <span id="conn" class="conn">connecting…</span>
  </header>
  <main class="grid">
    <section id="clock-panel" class="panel"></section>
    <section id="sensor-panel" class="panel"></section>
    <section id="tf-panel" class="panel"></section>
    <section id="dds-panel" class="panel"></section>
  </main>
  <script type="module">
    import { initClockPanel } from "/static/panels/clock.js";
    import { initSensorPanel } from "/static/panels/sensor-rate.js";
    import { initTfPanel } from "/static/panels/tf-tree.js";
    import { initDdsPanel } from "/static/panels/dds-graph.js";

    initClockPanel(document.getElementById("clock-panel"));
    initSensorPanel(document.getElementById("sensor-panel"));
    initTfPanel(document.getElementById("tf-panel"));
    initDdsPanel(document.getElementById("dds-panel"));

    // Connection indicator: green once any panel fetch succeeds.
    window.addEventListener("robobench:ok", () => {
      const c = document.getElementById("conn");
      c.textContent = "connected";
      c.classList.add("ok");
    });
  </script>
</body>
</html>
```

- [ ] **Step 2: Create `src/robobench/panels/static/style.css`**

```css
:root {
  --ok: #2e7d32;
  --warn: #f9a825;
  --fail: #c62828;
  --unknown: #757575;
  --bg: #0f1419;
  --panel: #1a2129;
  --text: #e4e8eb;
  --muted: #8a939b;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
}

header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
  border-bottom: 1px solid #2a333d;
}

header h1 { font-size: 18px; margin: 0; font-weight: 600; }

.conn { font-size: 12px; color: var(--muted); }
.conn.ok { color: var(--ok); }

.grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  padding: 20px;
}

.panel {
  background: var(--panel);
  border: 1px solid #2a333d;
  border-radius: 8px;
  padding: 16px;
  min-height: 200px;
}

.panel h3 {
  margin: 0 0 12px;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  background: var(--unknown);
}

.fixes {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  font-size: 12px;
}

.fixes li {
  border-left: 3px solid var(--fail);
  padding: 6px 10px;
  margin-bottom: 6px;
  background: rgba(198, 40, 40, 0.08);
  border-radius: 0 4px 4px 0;
}

.fixes a { color: #64b5f6; }

.graph { height: 240px; border-radius: 4px; background: #11161c; }
.metric { font-size: 13px; color: var(--muted); margin-top: 4px; }

@media (max-width: 720px) { .grid { grid-template-columns: 1fr; } }
```

- [ ] **Step 3: Commit**

```bash
git add src/robobench/panels/static/index.html src/robobench/panels/static/style.css
git commit -m "feat(ui): add dashboard shell and stylesheet"
```

---

## Task 6: `core/api.js` + `core/status.js`

**Files:**
- Create: `src/robobench/panels/static/core/api.js`
- Create: `src/robobench/panels/static/core/status.js`

- [ ] **Step 1: Create `src/robobench/panels/static/core/api.js`**

```javascript
// Fetch + polling helpers for the diagnostic panels.

export async function fetchPanel(name) {
  const resp = await fetch(`/api/panels/${name}`);
  if (!resp.ok) {
    throw new Error(`panel ${name}: HTTP ${resp.status}`);
  }
  return resp.json();
}

// Poll a panel endpoint every intervalMs, calling onData(payload) each time.
// Fires a window "robobench:ok" event on the first successful fetch so the
// header can flip to "connected". Returns the interval id.
export function startPolling(name, intervalMs, onData) {
  let announced = false;
  async function tick() {
    try {
      const data = await fetchPanel(name);
      if (!announced) {
        announced = true;
        window.dispatchEvent(new CustomEvent("robobench:ok"));
      }
      onData(data);
    } catch (err) {
      console.error(err);
    }
  }
  tick();
  return setInterval(tick, intervalMs);
}
```

- [ ] **Step 2: Create `src/robobench/panels/static/core/status.js`**

```javascript
// Shared status-color + fix-rendering helpers.

const COLORS = {
  OK: "var(--ok)",
  WARN: "var(--warn)",
  FAIL: "var(--fail)",
  UNKNOWN: "var(--unknown)",
};

export function statusColor(status) {
  return COLORS[status] || COLORS.UNKNOWN;
}

// Render a status string into a .pill element (text + background color).
export function renderStatusPill(el, status) {
  el.textContent = status;
  el.style.background = statusColor(status);
}

// Render an array of {cause, fix, link} into a <ul class="fixes">.
export function renderFixes(el, fixes) {
  el.innerHTML = "";
  for (const f of fixes || []) {
    const li = document.createElement("li");
    const link = f.link
      ? ` <a href="${f.link}" target="_blank" rel="noopener">docs</a>`
      : "";
    li.innerHTML = `<strong>${f.cause}</strong><br>${f.fix}${link}`;
    el.appendChild(li);
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add src/robobench/panels/static/core/
git commit -m "feat(ui): add api polling and status/fix rendering helpers"
```

---

## Task 7: `panels/clock.js`

**Files:** Create `src/robobench/panels/static/panels/clock.js`

- [ ] **Step 1: Create the file**

```javascript
import { startPolling } from "/static/core/api.js";
import { renderFixes, renderStatusPill } from "/static/core/status.js";

export function initClockPanel(root) {
  root.innerHTML = `
    <h3>Clock offset <span class="pill" id="clock-pill">…</span></h3>
    <div class="metric" id="clock-offset">waiting…</div>
    <ul class="fixes" id="clock-fixes"></ul>`;

  const pill = root.querySelector("#clock-pill");
  const offset = root.querySelector("#clock-offset");
  const fixes = root.querySelector("#clock-fixes");

  startPolling("clock", 2000, (data) => {
    renderStatusPill(pill, data.status);
    offset.textContent =
      data.offset_seconds === null
        ? "no data (robot not reachable?)"
        : `offset: ${data.offset_seconds.toFixed(2)} s`;
    renderFixes(fixes, data.fixes);
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add src/robobench/panels/static/panels/clock.js
git commit -m "feat(ui): add clock panel"
```

---

## Task 8: `panels/sensor-rate.js` (uPlot sparkline)

**Files:** Create `src/robobench/panels/static/panels/sensor-rate.js`

- [ ] **Step 1: Create the file**

```javascript
import { startPolling } from "/static/core/api.js";
import { renderFixes, renderStatusPill } from "/static/core/status.js";

// uPlot is loaded as a global from /static/lib/uPlot.iife.min.js.

const MAX_POINTS = 60;

export function initSensorPanel(root) {
  root.innerHTML = `
    <h3>Sensor rate <span class="pill" id="sensor-pill">…</span></h3>
    <div id="sensor-plot" class="graph"></div>
    <div class="metric" id="sensor-metric">waiting…</div>
    <ul class="fixes" id="sensor-fixes"></ul>`;

  const pill = root.querySelector("#sensor-pill");
  const metric = root.querySelector("#sensor-metric");
  const fixes = root.querySelector("#sensor-fixes");
  const plotEl = root.querySelector("#sensor-plot");

  const xs = [];
  const ys = [];
  let t = 0;

  const opts = {
    width: plotEl.clientWidth || 320,
    height: 160,
    scales: { x: { time: false } },
    series: [
      {},
      { label: "scan Hz", stroke: "#64b5f6", width: 2, fill: "rgba(100,181,246,0.1)" },
    ],
    axes: [
      { stroke: "#8a939b", grid: { stroke: "#2a333d" } },
      { stroke: "#8a939b", grid: { stroke: "#2a333d" } },
    ],
  };
  // eslint-disable-next-line no-undef
  const plot = new uPlot(opts, [xs, ys], plotEl);

  startPolling("sensors", 1000, (data) => {
    const scan = data.scan;
    renderStatusPill(pill, scan.status);
    metric.textContent = `${scan.rate_hz.toFixed(1)} Hz`;
    xs.push(t++);
    ys.push(scan.rate_hz);
    if (xs.length > MAX_POINTS) {
      xs.shift();
      ys.shift();
    }
    plot.setData([xs, ys]);
    renderFixes(fixes, scan.fixes);
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add src/robobench/panels/static/panels/sensor-rate.js
git commit -m "feat(ui): add sensor-rate panel with uPlot sparkline"
```

---

## Task 9: `panels/tf-tree.js` (cytoscape)

**Files:** Create `src/robobench/panels/static/panels/tf-tree.js`

- [ ] **Step 1: Create the file**

```javascript
import { startPolling } from "/static/core/api.js";
import { renderFixes, renderStatusPill } from "/static/core/status.js";

// cytoscape is loaded as a global from /static/lib/cytoscape.min.js.

export function initTfPanel(root) {
  root.innerHTML = `
    <h3>TF tree <span class="pill" id="tf-pill">…</span></h3>
    <div id="tf-graph" class="graph"></div>
    <ul class="fixes" id="tf-fixes"></ul>`;

  const pill = root.querySelector("#tf-pill");
  const fixes = root.querySelector("#tf-fixes");

  // eslint-disable-next-line no-undef
  const cy = cytoscape({
    container: root.querySelector("#tf-graph"),
    style: [
      {
        selector: "node",
        style: {
          label: "data(id)",
          "background-color": "#1565c0",
          color: "#fff",
          "font-size": 10,
          "text-valign": "center",
          "text-halign": "center",
          width: 70,
          height: 26,
          shape: "round-rectangle",
        },
      },
      {
        selector: "edge",
        style: {
          width: 2,
          "line-color": "#90a4ae",
          "target-arrow-shape": "triangle",
          "target-arrow-color": "#90a4ae",
          "curve-style": "bezier",
        },
      },
      {
        selector: "edge.stale",
        style: { "line-color": "#c62828", "target-arrow-color": "#c62828", width: 3 },
      },
    ],
    layout: { name: "breadthfirst", directed: true },
  });

  startPolling("tf", 2000, (data) => {
    renderStatusPill(pill, data.status);
    const els = [];
    for (const n of data.nodes) {
      els.push({ data: { id: n } });
    }
    for (const e of data.edges) {
      els.push({
        data: { id: `${e.parent}->${e.child}`, source: e.parent, target: e.child },
        classes: e.stale ? "stale" : "",
      });
    }
    cy.elements().remove();
    cy.add(els);
    cy.layout({ name: "breadthfirst", directed: true }).run();
    renderFixes(fixes, data.fixes);
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add src/robobench/panels/static/panels/tf-tree.js
git commit -m "feat(ui): add TF tree panel with cytoscape (stale edges in red)"
```

---

## Task 10: `panels/dds-graph.js` (cytoscape)

**Files:** Create `src/robobench/panels/static/panels/dds-graph.js`

- [ ] **Step 1: Create the file**

```javascript
import { startPolling } from "/static/core/api.js";
import { renderFixes, renderStatusPill } from "/static/core/status.js";

// cytoscape is loaded as a global from /static/lib/cytoscape.min.js.

export function initDdsPanel(root) {
  root.innerHTML = `
    <h3>DDS nodes <span class="pill" id="dds-pill">…</span></h3>
    <div id="dds-graph" class="graph"></div>
    <ul class="fixes" id="dds-fixes"></ul>`;

  const pill = root.querySelector("#dds-pill");
  const fixes = root.querySelector("#dds-fixes");

  // eslint-disable-next-line no-undef
  const cy = cytoscape({
    container: root.querySelector("#dds-graph"),
    style: [
      {
        selector: "node",
        style: {
          label: "data(id)",
          color: "#fff",
          "font-size": 9,
          "text-valign": "center",
          "text-halign": "center",
          width: 90,
          height: 24,
          shape: "round-rectangle",
          "background-color": "#2e7d32",
        },
      },
      {
        selector: "node.missing",
        style: { "background-color": "#c62828", "border-width": 2, "border-color": "#ff8a80" },
      },
    ],
    layout: { name: "grid" },
  });

  startPolling("dds", 2000, (data) => {
    renderStatusPill(pill, data.status);
    const els = data.nodes.map((n) => ({
      data: { id: n.name },
      classes: n.status === "missing" ? "missing" : "",
    }));
    cy.elements().remove();
    cy.add(els);
    cy.layout({ name: "grid" }).run();
    renderFixes(fixes, data.fixes);
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add src/robobench/panels/static/panels/dds-graph.js
git commit -m "feat(ui): add DDS node graph panel with cytoscape (missing nodes in red)"
```

---

## Task 11: Verify the frontend in a real browser (demo mode)

This is the frontend's verification gate — there's no JS unit-test runner (no-build ethos), so we verify by running the server in `--demo` mode and inspecting the rendered page.

**Files:** none (verification only; may produce a screenshot artifact)

- [ ] **Step 1: Start the dashboard in demo mode (background)**

```bash
cd C:/Users/chntw/Documents/robotic/robobench
source .venv/Scripts/activate
robobench dashboard --robot turtlebot4 --config examples/campus_guide/code/config.yaml --demo --port 8080
```
(Run in the background. The `--demo` flag means no ROS2 is needed.)

If `examples/campus_guide/code/config.yaml` isn't a valid path, create a throwaway one:
```bash
printf 'robot:\n  ip: "127.0.0.1"\n  ssh_user: "u"\n  ssh_pass: "p"\n  namespace: "demo"\n' > /tmp/demo-config.yaml
```
and use `--config /tmp/demo-config.yaml`.

- [ ] **Step 2: Confirm the endpoints return populated demo data**

```bash
curl -s localhost:8080/api/panels/clock   | python -m json.tool
curl -s localhost:8080/api/panels/sensors | python -m json.tool
curl -s localhost:8080/api/panels/tf      | python -m json.tool
curl -s localhost:8080/api/panels/dds     | python -m json.tool
```
Expected: clock OK (~0.12s); sensors ~10 Hz OK; tf shows `"broken": ["base_link->laser"]` status FAIL + fixes; dds shows `"missing": ["/planner_server"]` status FAIL + fixes.

- [ ] **Step 3: Open the page in a browser and verify rendering**

Open `http://localhost:8080/` in a browser (use the `browse` / gstack skill, or the `mcp__Claude_Preview` / `mcp__Claude_in_Chrome` tools if available, otherwise open manually). Verify:
- Header flips to "connected" (green).
- Clock panel shows an `OK` pill + `offset: 0.12 s`.
- Sensor panel shows a uPlot line climbing/holding near 10 Hz, `OK` pill.
- TF panel shows a cytoscape graph map→odom→base_link→laser with the `base_link→laser` edge **red**, `FAIL` pill, and a fix entry.
- DDS panel shows node boxes with `/planner_server` **red**, `FAIL` pill, and a fix entry.

Take a screenshot for the PR / tutorial (`docs/img/dashboard-demo.png` if you want to commit it).

- [ ] **Step 4: Stop the server**

Stop the background `robobench dashboard` process (Ctrl-C / kill the PID).

- [ ] **Step 5: Record the verification outcome**

No code commit for this task unless a screenshot was saved. If you saved `docs/img/dashboard-demo.png`:
```bash
git add docs/img/dashboard-demo.png
git commit -m "docs: add dashboard demo screenshot"
```
Otherwise mark the task complete with a note describing what you observed (which panels rendered correctly, any rendering bugs found + fixed in the relevant panels/*.js file).

**If a panel doesn't render:** the bug is in that panel's `.js` file (or the vendored lib path). Fix it, re-load the page, re-verify. Commit the fix to the relevant `panels/*.js` with a `fix(ui):` message. Do NOT proceed to Task 12 with a broken panel.

---

## Task 12: Tutorial update + CHANGELOG + bump v0.4.0a0 + tag + push

**Files:**
- Modify: `docs/tutorials/diagnosing-with-dashboard.md`
- Modify: `CHANGELOG.md`
- Modify: `src/robobench/__init__.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add a "Visual dashboard" section to the tutorial**

In `docs/tutorials/diagnosing-with-dashboard.md`, find the final `## What's next` section and insert this BEFORE it:

```markdown
## The visual dashboard

As of v0.4, `robobench dashboard` serves a web UI at the root URL — open
`http://localhost:8080/` in a browser. Four live panels:

- **Clock offset** — OK/WARN/FAIL pill + current offset.
- **Sensor rate** — a live sparkline (uPlot) of LiDAR scan Hz.
- **TF tree** — the frame graph (cytoscape); stale/broken edges turn red.
- **DDS nodes** — expected Nav2 nodes; missing ones turn red.

Each panel shows the failure-catalog fixes inline when it's red.

### Try it without a robot

```bash
robobench dashboard --robot turtlebot4 --config ./config.yaml --demo
```

`--demo` seeds synthetic data (a healthy clock + sensor, a deliberately broken
TF edge, a missing Nav2 node) so you can see every panel — including its
red/fix states — with no hardware and no ROS2 installed. Great for trying
robobench before you have a robot on the bench.
```

- [ ] **Step 2: Update CHANGELOG.md** — replace the `## [Unreleased]` line with:

```markdown
## [Unreleased]

## [0.4.0a0] — 2026-05-28

### Added

- **Visual diagnostic dashboard** served at `/` by `robobench dashboard`:
  vanilla-JS, no build step, native ES modules. Four live panels (clock,
  sensor-rate sparkline, TF tree, DDS node graph) polling the v0.3 panel API,
  each showing failure-catalog fixes inline when red.
- Vendored `cytoscape.js` (TF tree + DDS graph) and `uPlot` (sensor sparkline)
  under `src/robobench/panels/static/lib/` — works offline / on locked-down
  lab networks. Both MIT (see NOTICE).
- `robobench dashboard --demo` + `robobench.panels.demo.seed_demo_state` —
  populates synthetic data so the whole dashboard is viewable with no robot
  and no ROS2.
- FastAPI now serves the packaged static frontend (`StaticFiles` + `/` route);
  `static/**/*` ships in the wheel.

### Notes

- WebSocket live-push is still deferred; the frontend polls every 1–2s.
```

- [ ] **Step 3: Bump version**

`src/robobench/__init__.py`: `__version__ = "0.3.0a0"` → `"0.4.0a0"`.
`pyproject.toml`: `version = "0.3.0a0"` → `"0.4.0a0"`.

- [ ] **Step 4: Final sweep**

```bash
source .venv/Scripts/activate
pip install -e ".[dev]"
pytest -q
ruff check . && ruff format --check .
robobench --version       # robobench 0.4.0a0
```
Expected: all tests pass (~96), ruff clean, version correct.

- [ ] **Step 5: Commit + tag + push**

```bash
git add docs/tutorials/diagnosing-with-dashboard.md CHANGELOG.md src/robobench/__init__.py pyproject.toml
git commit -m "chore: bump version to 0.4.0a0 and update CHANGELOG"
git tag -a v0.4.0a0 -m "v0.4.0-alpha - Phase C-2: visual diagnostic dashboard + demo mode"
git push origin main
git push origin v0.4.0a0
```

- [ ] **Step 6: Verify**

```bash
git tag --list
```
Expected: `v0.1.0a0`, `v0.2.0a0`, `v0.2.1a0`, `v0.3.0a0`, `v0.4.0a0`.

---

## Self-Review (Plan Author Notes)

**Spec coverage check:**
- No-build vanilla JS + ES modules → Tasks 5-10 ✅
- Vendored cytoscape.js + uPlot → Task 4 ✅
- Reuse status-pill/fix-rendering plumbing → Task 6 (`status.js`) ✅
- 4 panels (clock/sensor/tf/dds) → Tasks 7-10 ✅
- Served from FastAPI → Task 3 ✅
- `--demo` mode (verification + hardware-free story) → Tasks 1, 2 ✅
- Visual verification → Task 11 ✅
- Tag v0.4.0a0 → Task 12 ✅

**Placeholder scan:** No TBDs. Every JS/Python/HTML/CSS file has complete content.

**Type consistency:**
- `seed_demo_state(state, now)` / `DEMO_EXPECTED_NODES` — defined Task 1, patched in CLI Task 2.
- Panel modules each export `init<Name>Panel(root)` — defined Tasks 7-10, imported by name in `index.html` Task 5. Names match: `initClockPanel`, `initSensorPanel`, `initTfPanel`, `initDdsPanel`.
- `core/api.js` exports `startPolling`, `fetchPanel`; `core/status.js` exports `renderStatusPill`, `renderFixes`, `statusColor` — all imported with those exact names in the panel modules.
- The JSON shapes the panels consume (`data.status`, `data.offset_seconds`, `data.scan.rate_hz`, `data.nodes`, `data.edges[].stale`, `data.broken`, `data.missing`, `data.fixes`) match exactly what the v0.3 endpoints return (verified against Phase C plan Tasks 9-10).

**Known risks / honest notes:**
1. **Frontend JS is not unit-tested.** Verification is Task 11 (browser + `--demo`). This is a deliberate trade for the no-build/no-npm academic-friendliness. The *served-ness* is tested (Task 3 TestClient); the *rendering* is human/agent-verified.
2. **cytoscape/uPlot are loaded as page globals**, not ES modules (their UMD/IIFE builds). The panel modules reference `cytoscape` / `uPlot` globals with an eslint-disable comment. This is correct for the vendored builds; if a future contributor swaps to the ESM builds, the imports change.
3. **Vendored lib size** (~450KB cytoscape) ships in the wheel. Acceptable for a dashboard tool; documented in NOTICE.
4. **Polling, not push.** 1–2s latency on panels. Fine for diagnostics; websocket is a later optimization.
5. **Demo data is static** (one snapshot). The sensor sparkline will show a flat ~10 Hz line in demo mode (each poll returns the same rate). That's enough to verify the plot renders; live variation needs a real robot.

---

## Out of scope (deferred)

- **WebSocket live push** — still polling; revisit if 1–2s latency proves too slow.
- **Bring-up wizard UI** (interactive, one-click fix-actions) — Phase D.
- **JS unit/E2E test harness** — would require adding a build/test toolchain, against the no-build ethos. Could add Playwright-based E2E in a future plan if the frontend grows.
- **Second robot adapter / sim** — Phase D / E.
