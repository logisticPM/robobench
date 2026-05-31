# Dashboard One-Click Recover Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a dashboard user Preview and Apply the existing recovery engine from the connectivity panel, watching live progress, with the nuclear Create3 reboot never reachable from the web.

**Architecture:** A thread-safe `RecoveryJob` doubles as the engine's `event_log` sink (live step stream). A `RecoveryController` owns the job, computes an instant Preview from the latest connectivity diagnosis, and runs the engine in a daemon thread (single-flight, `allow_reboot=False`). Two FastAPI endpoints (`POST /api/recover`, `GET /api/recover/status`) delegate to the controller; the CLI injects it in non-demo mode (None in demo → endpoints report unavailable). The connectivity card gains Preview/Apply buttons that poll status.

**Tech Stack:** Python 3.11+, FastAPI + pydantic, threading, pytest, ruff, vanilla-JS ES modules. Windows + Git Bash; rclpy NOT installed (irrelevant). Tests/lint: `.venv/Scripts/python.exe -m pytest -q` / `.venv/Scripts/python.exe -m ruff check src tests`. Baseline: **185 passed**, version 0.10.0a0.

Spec: `docs/superpowers/specs/2026-05-30-dashboard-recover-button-design.md`.

---

## File Structure

| File | Responsibility | Task |
|------|----------------|------|
| `src/robobench/panels/recovery_job.py` (new) | Thread-safe job status + `.log` event sink | 1 |
| `src/robobench/panels/recovery_controller.py` (new) | preview (pure) + single-flight start_apply + thread body | 2 |
| `src/robobench/panels/server.py` | `POST /api/recover`, `GET /api/recover/status`, `create_app(..., recovery=None)` | 3 |
| `src/robobench/cli.py` | `_cmd_dashboard` injects a `RecoveryController` (non-demo) | 4 |
| `src/robobench/panels/static/panels/connectivity.js` + `style.css` | Preview/Apply buttons + progress | 5 |
| tutorial + `CHANGELOG.md` + version | release v0.11.0a0 | 6 |

Key existing signatures this plan builds on (already in the codebase):
- `build_turtlebot4_recovery(ip, ssh_user, ssh_pass, namespace, *, allow_reboot, deadline_s, settle_s=8.0, event_log=None) -> RecoveryEngine`
- `RecoveryResult(outcome, actions_taken=[], trace=[], final_state=None)` (dataclass)
- `_LADDER: list[tuple[str, str, bool]]` = `(aspect, action_name, is_nuclear)` in `robobench.recovery.engine`
- `first_broken_layer(state) -> str | None` in `robobench.panels.connectivity`
- `create_app(state, namespace, expected_nodes=None) -> FastAPI` in `robobench.panels.server`

---

## Task 1: RecoveryJob (status + event sink)

**Files:**
- Create: `src/robobench/panels/recovery_job.py`
- Test: `tests/unit/panels/test_recovery_job.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/panels/test_recovery_job.py
from robobench.panels.recovery_job import RecoveryJob


def test_log_appends_steps():
    job = RecoveryJob()
    job.log("probe", {"healthy": False})
    job.log("action", {"name": "sync_clock"})
    assert job.snapshot()["steps"] == [
        {"event": "probe", "data": {"healthy": False}},
        {"event": "action", "data": {"name": "sync_clock"}},
    ]


def test_begin_resets_and_marks_running():
    job = RecoveryJob()
    job.log("old", {})
    job.begin()
    snap = job.snapshot()
    assert snap["status"] == "running"
    assert snap["steps"] == []
    assert snap["started_at"] is not None
    assert snap["finished_at"] is None


def test_finish_records_outcome_and_actions():
    job = RecoveryJob()
    job.begin()
    job.finish("CONVERGED", ["sync_clock", "restart_discovery_server"])
    snap = job.snapshot()
    assert snap["status"] == "done"
    assert snap["outcome"] == "CONVERGED"
    assert snap["actions"] == ["sync_clock", "restart_discovery_server"]
    assert snap["error"] is None
    assert snap["finished_at"] is not None


def test_finish_with_error():
    job = RecoveryJob()
    job.begin()
    job.finish("ERROR", [], error="ssh boom")
    snap = job.snapshot()
    assert snap["status"] == "done"
    assert snap["error"] == "ssh boom"


def test_status_property():
    job = RecoveryJob()
    assert job.status == "idle"
    job.begin()
    assert job.status == "running"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_recovery_job.py -v`
Expected: FAIL (`No module named 'robobench.panels.recovery_job'`)

- [ ] **Step 3: Write the implementation**

```python
# src/robobench/panels/recovery_job.py
"""Thread-safe status for a dashboard-initiated recovery run.

Doubles as the recovery engine's ``event_log`` sink: the engine calls
``.log(event, data)`` for each probe/action/outcome, which appends to ``steps``
so the polling frontend sees live progress. The authoritative top-level
``outcome`` is set by ``finish()`` from the RecoveryResult, not parsed from the
stream. threading only — no FastAPI/SSH imports.
"""

from __future__ import annotations

import threading
import time


class RecoveryJob:
    """Live status of one recovery run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = "idle"  # idle | running | done
        self._outcome: str | None = None
        self._actions: list[str] = []
        self._steps: list[dict] = []
        self._error: str | None = None
        self._started_at: float | None = None
        self._finished_at: float | None = None

    def log(self, event: str, data: dict) -> None:
        """EventLogger-compatible sink: append one engine event to the stream."""
        with self._lock:
            self._steps.append({"event": event, "data": data})

    def begin(self) -> None:
        with self._lock:
            self._status = "running"
            self._outcome = None
            self._actions = []
            self._steps = []
            self._error = None
            self._started_at = time.time()
            self._finished_at = None

    def finish(self, outcome: str, actions: list[str], error: str | None = None) -> None:
        with self._lock:
            self._status = "done"
            self._outcome = outcome
            self._actions = list(actions)
            self._error = error
            self._finished_at = time.time()

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": self._status,
                "outcome": self._outcome,
                "actions": list(self._actions),
                "steps": list(self._steps),
                "error": self._error,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
            }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_recovery_job.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/recovery_job.py tests/unit/panels/test_recovery_job.py
git commit -m "feat: RecoveryJob (thread-safe status + engine event sink)"
```

---

## Task 2: RecoveryController (preview + single-flight apply)

**Files:**
- Create: `src/robobench/panels/recovery_controller.py`
- Test: `tests/unit/panels/test_recovery_controller.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/panels/test_recovery_controller.py
from robobench.panels.recovery_controller import RecoveryController
from robobench.recovery.engine import RecoveryResult
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


class _SyncThread:
    """thread_factory that runs target synchronously on .start()."""

    def __init__(self, target, daemon=False):
        self._target = target

    def start(self):
        self._target()


class _NoStartThread:
    """thread_factory whose .start() does nothing (job stays 'running')."""

    def __init__(self, target, daemon=False):
        pass

    def start(self):
        pass


def test_preview_lists_nonnuclear_actions_for_failing_layer():
    ctrl = RecoveryController(build_engine=lambda job: None)
    out = ctrl.preview(_state(discovery_server_ok=False))
    assert out["failing_layer"] == "discovery_server_ok"
    assert out["would_try"] == ["restart_discovery_server"]


def test_preview_create3_excludes_nuclear_reboot():
    ctrl = RecoveryController(build_engine=lambda job: None)
    out = ctrl.preview(_state(create3_topics=0))
    assert out["failing_layer"] == "create3_topics"
    assert "restart_local_daemon" in out["would_try"]
    assert "reboot_create3" not in out["would_try"]


def test_preview_none_and_healthy_are_empty():
    ctrl = RecoveryController(build_engine=lambda job: None)
    assert ctrl.preview(None)["would_try"] == []
    assert ctrl.preview(_state())["would_try"] == []  # healthy -> first_broken None


def test_start_apply_runs_engine_and_finishes_done():
    class FakeEngine:
        def __init__(self, job):
            self._job = job

        def run(self):
            self._job.log("action", {"aspect": "clock_synced", "name": "sync_clock"})
            return RecoveryResult(outcome="CONVERGED", actions_taken=["sync_clock"])

    ctrl = RecoveryController(build_engine=lambda job: FakeEngine(job), thread_factory=_SyncThread)
    assert ctrl.start_apply() is True
    snap = ctrl.job.snapshot()
    assert snap["status"] == "done"
    assert snap["outcome"] == "CONVERGED"
    assert snap["actions"] == ["sync_clock"]
    assert {"event": "action", "data": {"aspect": "clock_synced", "name": "sync_clock"}} in snap["steps"]


def test_start_apply_single_flight():
    ctrl = RecoveryController(build_engine=lambda job: None, thread_factory=_NoStartThread)
    assert ctrl.start_apply() is True  # job now 'running' (thread never ran)
    assert ctrl.start_apply() is False  # blocked


def test_start_apply_engine_exception_sets_error():
    class BoomEngine:
        def __init__(self, job):
            pass

        def run(self):
            raise RuntimeError("ssh boom")

    ctrl = RecoveryController(build_engine=lambda job: BoomEngine(job), thread_factory=_SyncThread)
    assert ctrl.start_apply() is True
    snap = ctrl.job.snapshot()
    assert snap["status"] == "done"
    assert snap["outcome"] == "ERROR"
    assert snap["error"] == "ssh boom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_recovery_controller.py -v`
Expected: FAIL (`No module named 'robobench.panels.recovery_controller'`)

- [ ] **Step 3: Write the implementation**

```python
# src/robobench/panels/recovery_controller.py
"""Owns a RecoveryJob and runs the recovery engine in a background thread.

Single-flight (one recovery at a time). Preview is pure (computed from the
latest connectivity diagnosis — no SSH). The engine is built via an injected
``build_engine(job)`` callable that MUST wire ``event_log=job`` and
``allow_reboot=False`` — so the web path can never trigger the nuclear reboot.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from robobench.panels.connectivity import first_broken_layer
from robobench.panels.recovery_job import RecoveryJob
from robobench.recovery.engine import _LADDER, RecoveryEngine
from robobench.recovery.state import RobotState


class RecoveryController:
    """Drives dashboard-initiated recovery, gated and single-flight."""

    def __init__(
        self,
        build_engine: Callable[[RecoveryJob], RecoveryEngine],
        *,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        self.build_engine = build_engine
        self.job = RecoveryJob()
        self._thread_factory = thread_factory

    def preview(self, connectivity_state: RobotState | None) -> dict:
        """Non-nuclear ladder actions for the current failing layer. No SSH."""
        if connectivity_state is None:
            return {"available": True, "failing_layer": None, "would_try": []}
        failing = first_broken_layer(connectivity_state)
        would_try = [
            action for aspect, action, is_nuclear in _LADDER if aspect == failing and not is_nuclear
        ]
        return {"available": True, "failing_layer": failing, "would_try": would_try}

    def start_apply(self) -> bool:
        """Start a recovery in a daemon thread. Single-flight: returns False if
        one is already running."""
        if self.job.status == "running":
            return False
        self.job.begin()
        self._thread_factory(target=self._run, daemon=True).start()
        return True

    def _run(self) -> None:
        try:
            result = self.build_engine(self.job).run()
            self.job.finish(result.outcome, result.actions_taken)
        except Exception as exc:  # noqa: BLE001 — surface any failure to the UI, never crash the thread
            self.job.finish("ERROR", [], error=str(exc))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_recovery_controller.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/recovery_controller.py tests/unit/panels/test_recovery_controller.py
git commit -m "feat: RecoveryController (instant preview + single-flight apply, nuclear web-excluded)"
```

---

## Task 3: Recover endpoints

**Files:**
- Modify: `src/robobench/panels/server.py` (imports, `create_app` signature, two endpoints)
- Test: `tests/unit/panels/test_server.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/panels/test_server.py  (append)
def _fake_controller():
    class FakeJob:
        def snapshot(self):
            return {"status": "idle", "outcome": None, "actions": [], "steps": [], "error": None}

    class FakeController:
        def __init__(self):
            self.job = FakeJob()
            self.allow_start = True

        def preview(self, conn):
            return {
                "available": True,
                "failing_layer": "discovery_server_ok",
                "would_try": ["restart_discovery_server"],
            }

        def start_apply(self):
            return self.allow_start

    return FakeController()


def test_recover_preview_apply_and_conflict():
    from fastapi.testclient import TestClient

    from robobench.panels.server import create_app
    from robobench.panels.state import DiagnosticState

    ctrl = _fake_controller()
    client = TestClient(create_app(DiagnosticState(), namespace="tb", expected_nodes=[], recovery=ctrl))

    r = client.post("/api/recover", json={"mode": "preview"})
    assert r.status_code == 200
    assert r.json()["would_try"] == ["restart_discovery_server"]

    assert client.post("/api/recover", json={"mode": "apply"}).status_code == 202

    ctrl.allow_start = False
    assert client.post("/api/recover", json={"mode": "apply"}).status_code == 409

    assert client.post("/api/recover", json={"mode": "nope"}).status_code == 400

    body = client.get("/api/recover/status").json()
    assert body["available"] is True
    assert body["status"] == "idle"


def test_recover_unavailable_without_controller():
    from fastapi.testclient import TestClient

    from robobench.panels.server import create_app
    from robobench.panels.state import DiagnosticState

    client = TestClient(create_app(DiagnosticState(), namespace="tb", expected_nodes=[]))
    assert client.post("/api/recover", json={"mode": "apply"}).status_code == 403
    assert client.get("/api/recover/status").json() == {"available": False, "status": "idle"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_server.py::test_recover_unavailable_without_controller -v`
Expected: FAIL (`create_app() got an unexpected keyword argument 'recovery'`)

- [ ] **Step 3: Implement** — in `server.py`:

Update the imports (the FastAPI line + add pydantic):

```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
```

Add a request model at module level (after the imports, before `_STATIC_DIR`):

```python
class RecoverRequest(BaseModel):
    mode: str
```

Change the `create_app` signature and store the controller:

```python
def create_app(
    state: DiagnosticState,
    namespace: str,
    expected_nodes: list[str] | None = None,
    *,
    recovery: object | None = None,
) -> FastAPI:
    """Build the FastAPI app bound to a given DiagnosticState."""
    app = FastAPI(title="robobench diagnostics")
    app.state.diag = state
    app.state.namespace = namespace
    app.state.expected_nodes = expected_nodes or []
    app.state.recovery = recovery
```

Add the two endpoints inside `create_app` (after the `connectivity_panel` endpoint, before the `if _STATIC_DIR.exists():` block):

```python
    @app.post("/api/recover")
    def recover(req: RecoverRequest):
        rec = app.state.recovery
        if rec is None:
            raise HTTPException(status_code=403, detail="recovery unavailable (demo or no SSH config)")
        if req.mode == "preview":
            return rec.preview(app.state.diag.connectivity())
        if req.mode == "apply":
            if not rec.start_apply():
                raise HTTPException(status_code=409, detail="a recovery is already running")
            return JSONResponse(status_code=202, content=rec.job.snapshot())
        raise HTTPException(status_code=400, detail="mode must be 'preview' or 'apply'")

    @app.get("/api/recover/status")
    def recover_status() -> dict:
        rec = app.state.recovery
        if rec is None:
            return {"available": False, "status": "idle"}
        return {"available": True, **rec.job.snapshot()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/panels/test_server.py -v`
Expected: PASS (existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add src/robobench/panels/server.py tests/unit/panels/test_server.py
git commit -m "feat: POST /api/recover + GET /api/recover/status (delegating to controller)"
```

---

## Task 4: CLI injects the controller

**Files:**
- Modify: `src/robobench/cli.py` (`_cmd_dashboard` + import)
- Test: `tests/unit/test_cli.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli.py  (append)
def _fake_thread_factory():
    class _T:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    return _T


def test_dashboard_injects_recovery_controller(monkeypatch, tmp_path):
    captured = {}

    def fake_create_app(state, namespace, expected_nodes=None, *, recovery=None):
        from fastapi import FastAPI

        captured["recovery"] = recovery
        return FastAPI()

    monkeypatch.setattr("robobench.cli.create_app", fake_create_app)
    monkeypatch.setattr("robobench.cli.uvicorn.run", lambda *a, **k: None)
    monkeypatch.setattr("robobench.cli.threading.Thread", _fake_thread_factory())

    from robobench.cli import main
    from robobench.panels.recovery_controller import RecoveryController

    rc = main(["dashboard", "--robot", "turtlebot4", "--config", str(_dashboard_config(tmp_path))])
    assert rc == 0
    assert isinstance(captured["recovery"], RecoveryController)


def test_dashboard_demo_has_no_recovery(monkeypatch, tmp_path):
    captured = {}

    def fake_create_app(state, namespace, expected_nodes=None, *, recovery=None):
        from fastapi import FastAPI

        captured["recovery"] = recovery
        return FastAPI()

    monkeypatch.setattr("robobench.cli.create_app", fake_create_app)
    monkeypatch.setattr("robobench.cli.uvicorn.run", lambda *a, **k: None)
    monkeypatch.setattr("robobench.cli.threading.Thread", _fake_thread_factory())

    from robobench.cli import main

    rc = main(
        ["dashboard", "--robot", "turtlebot4", "--config", str(_dashboard_config(tmp_path)), "--demo"]
    )
    assert rc == 0
    assert captured["recovery"] is None
```

> `_dashboard_config(tmp_path)` already exists in `test_cli.py` (added with the connectivity panel). Reuse it.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli.py::test_dashboard_injects_recovery_controller -v`
Expected: FAIL (`captured["recovery"]` is `None`, not a `RecoveryController`)

- [ ] **Step 3: Implement** — in `cli.py`:

Add the import near the other panels imports inside the `try:` block at the top (next to `from robobench.panels.server import create_app`):

```python
    from robobench.panels.recovery_controller import RecoveryController
```

In `_cmd_dashboard`, initialize `recovery = None` right after `state = DiagnosticState()`. In the non-demo `else:` branch (after the connectivity-probe thread block), build the controller:

```python
        recovery = RecoveryController(
            build_engine=lambda job: build_turtlebot4_recovery(
                ip=kwargs["ip"],
                ssh_user=kwargs["ssh_user"],
                ssh_pass=kwargs["ssh_pass"],
                namespace=namespace,
                allow_reboot=False,
                deadline_s=180.0,
                event_log=job,
            ),
        )
```

Change the `create_app(...)` call (near the end of `_cmd_dashboard`) to pass it:

```python
    app = create_app(state, namespace=namespace, expected_nodes=expected_nodes, recovery=recovery)
```

(`build_turtlebot4_recovery` is already imported at the top of `cli.py`.)

- [ ] **Step 4: Run tests + full suite + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli.py -v && .venv/Scripts/python.exe -m ruff check src tests`
Expected: PASS; ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/robobench/cli.py tests/unit/test_cli.py
git commit -m "feat: dashboard injects a RecoveryController (None in demo)"
```

---

## Task 5: Recover controls in the connectivity card

**Files:**
- Modify: `src/robobench/panels/static/panels/connectivity.js` (add Preview/Apply + status polling)
- Modify: `src/robobench/panels/static/style.css` (recover block styles)
- Verify: browser (demo mode)

- [ ] **Step 1: Replace `connectivity.js`** with the extended version (keeps the existing ladder/fixes, adds the recover block):

```javascript
// src/robobench/panels/static/panels/connectivity.js
import { startPolling } from "/static/core/api.js";
import { renderFixes, renderStatusPill } from "/static/core/status.js";

async function postRecover(mode) {
  const resp = await fetch("/api/recover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  return { status: resp.status, body: await resp.json().catch(() => ({})) };
}

function renderJob(out, job) {
  const lines = (job.steps || []).map((s) => {
    if (s.event === "action") return `→ ${s.data.name} (for ${s.data.aspect})`;
    if (s.event === "probe") return "· probed";
    if (s.event === "outcome") return `outcome: ${s.data.outcome}`;
    return `· ${s.event}`;
  });
  if (job.status === "done") {
    lines.push(job.error ? `ERROR: ${job.error}` : `done: ${job.outcome}`);
  }
  out.textContent = lines.join("\n");
}

export function initConnectivityPanel(root) {
  root.innerHTML = `
    <h3>Connectivity (SSH) <span class="pill" id="conn-pill">…</span></h3>
    <ul class="ladder" id="conn-ladder"></ul>
    <ul class="fixes" id="conn-fixes"></ul>
    <div class="recover">
      <button id="conn-preview" disabled>Preview recovery</button>
      <button id="conn-apply" disabled>Apply</button>
      <div class="recover-out" id="conn-recover-out"></div>
    </div>`;

  const pill = root.querySelector("#conn-pill");
  const ladder = root.querySelector("#conn-ladder");
  const fixes = root.querySelector("#conn-fixes");
  const previewBtn = root.querySelector("#conn-preview");
  const applyBtn = root.querySelector("#conn-apply");
  const out = root.querySelector("#conn-recover-out");

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

  let statusTimer = null;
  function pollStatus() {
    fetch("/api/recover/status")
      .then((r) => r.json())
      .then((job) => {
        renderJob(out, job);
        if (job.status === "done") {
          clearInterval(statusTimer);
          statusTimer = null;
          previewBtn.disabled = false;
        }
      })
      .catch((e) => console.error(e));
  }

  // Availability gate: disable the buttons in demo / no-SSH.
  fetch("/api/recover/status")
    .then((r) => r.json())
    .then((job) => {
      if (job.available === false) {
        out.textContent = "Recover needs a real robot (SSH).";
      } else {
        previewBtn.disabled = false;
      }
    })
    .catch((e) => console.error(e));

  previewBtn.addEventListener("click", async () => {
    const { body } = await postRecover("preview");
    if (!body.would_try || body.would_try.length === 0) {
      out.textContent = body.failing_layer
        ? `No web-safe fix for: ${body.failing_layer}`
        : "Nothing to recover (healthy or no diagnosis yet).";
      applyBtn.disabled = true;
    } else {
      out.textContent = `Will try: ${body.would_try.join(" → ")}`;
      applyBtn.disabled = false;
    }
  });

  applyBtn.addEventListener("click", async () => {
    applyBtn.disabled = true;
    previewBtn.disabled = true;
    const { status } = await postRecover("apply");
    if (status === 409) out.textContent = "A recovery is already running.";
    if (statusTimer === null) statusTimer = setInterval(pollStatus, 1500);
    pollStatus();
  });
}
```

- [ ] **Step 2: Append the recover styles** to `style.css`:

```css
.recover { margin-top: 0.6rem; }
.recover button { margin-right: 0.4rem; }
.recover button:disabled { opacity: 0.5; cursor: not-allowed; }
.recover-out { margin-top: 0.4rem; white-space: pre-line; font-family: monospace; font-size: 0.85em; color: #444; }
```

- [ ] **Step 3: Verify in the browser (demo mode)**

Run: `.venv/Scripts/python.exe -m robobench dashboard --robot turtlebot4 --config <any config.yaml> --demo --port 8090`
Open `http://localhost:8090/`. Expected: the Connectivity card shows the ladder AND a Recover block whose **Preview/Apply buttons are greyed out** with "Recover needs a real robot (SSH)." (demo injects no controller → `/api/recover/status` returns `available:false`). Stop the server when done.

- [ ] **Step 4: Commit**

```bash
git add src/robobench/panels/static/panels/connectivity.js src/robobench/panels/static/style.css
git commit -m "feat: Preview/Apply recover controls in the connectivity card"
```

---

## Task 6: Tutorial + release v0.11.0a0

**Files:**
- Modify: `docs/tutorials/diagnosing-with-dashboard.md`
- Modify: `CHANGELOG.md`, `pyproject.toml`, `src/robobench/__init__.py`

- [ ] **Step 1: Document the button** — add to `docs/tutorials/diagnosing-with-dashboard.md`, right after the "## The Connectivity panel (DDS-blind fallback)" section:

````markdown
### One-click Recover

Below the connectivity ladder, **Preview recovery** shows what robobench would
try for the current failing layer (e.g. "Will try: restart_discovery_server"),
computed instantly from the latest diagnosis. **Apply** then runs the recovery
engine in the background; the panel streams each action and the final outcome
(CONVERGED / STUCK / TIMED_OUT / NEEDS_HUMAN), and the ladder above turns green
as layers recover.

Safety: the nuclear Create3 reboot is **never** available from the web — Apply
only ever runs the cheap/medium fixes. To reboot the Create3, use the CLI:
`robobench recover --allow-reboot`. Only one recovery runs at a time. In demo
mode (no robot) the buttons are disabled.
````

- [ ] **Step 2: CHANGELOG** — add under `## [Unreleased]`:

```markdown
## [0.11.0a0] — 2026-05-30

### Added

- **One-click Recover in the dashboard.** The connectivity card gains
  **Preview** (instant plan from the current diagnosis) and **Apply** (runs the
  recovery engine in a background thread, streaming progress to a polled status
  endpoint). `RecoveryJob` (thread-safe status + engine event sink),
  `RecoveryController` (single-flight, `allow_reboot=False`), `POST /api/recover`
  + `GET /api/recover/status`. The nuclear Create3 reboot is never reachable from
  the web (CLI-only); disabled in demo mode.
```

- [ ] **Step 3: Bump version** to `0.11.0a0` in `pyproject.toml` (`version = "0.11.0a0"`) and `src/robobench/__init__.py` (`__version__ = "0.11.0a0"`).

- [ ] **Step 4: Verify, commit, tag, push**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests && .venv/Scripts/robobench --version
git add CHANGELOG.md pyproject.toml src/robobench/__init__.py docs/tutorials/diagnosing-with-dashboard.md
git commit -m "release: v0.11.0a0 — one-click Recover in the dashboard"
git tag v0.11.0a0
git push origin main && git push origin v0.11.0a0
```
Expected: all tests pass (~200 passed); `robobench 0.11.0a0`.

---

## Self-Review

**1. Spec coverage:**
- Background thread + status polling → Task 2 (`start_apply` daemon thread) + Task 3 (`GET /api/recover/status`) + Task 5 (poll). ✓
- Preview (instant, from connectivity, no SSH) → Task 2 `preview` + Task 3 POST `mode:preview` + Task 5 button. ✓
- Apply runs engine via `event_log=job`, `allow_reboot=False` → Task 2 `_run` + Task 4 `build_engine` lambda. ✓
- Single-flight 409 → Task 2 `start_apply` returns False + Task 3 409. ✓
- Nuclear web-excluded → Task 4 `allow_reboot=False` + Task 2 preview filters `is_nuclear`. ✓
- Demo disabled (403 / `available:false` / greyed UI) → Task 3 + Task 4 (recovery=None in demo) + Task 5 gate. ✓
- Probe coexists (no pause) → nothing added to pause it; the connectivity loop is untouched. ✓
- Thread exception-guarded → Task 2 `_run` try/except. ✓
- Out of scope respected (no WebSocket, no JSONL, no demo simulation, no engine/probe/CLI-recover changes). ✓

**2. Placeholder scan:** No TBD/TODO/"add error handling"/"similar to". Every code step is complete; every run step has an exact command + expected result. Task 5 Step 3 uses `<any config.yaml>` — that's a real user-supplied argument for a manual verification run, not a code placeholder.

**3. Type consistency:** `RecoveryJob` API (`log`/`begin`/`finish`/`status`/`snapshot`) used identically in Task 2 (`_run` calls `finish`; `start_apply` checks `status`/`begin`) and Task 3 (`rec.job.snapshot()`). `RecoveryController` API (`preview`/`start_apply`/`job`) used by Task 3 endpoints and Task 4 CLI. `build_engine: Callable[[RecoveryJob], RecoveryEngine]` — Task 4's lambda takes `job` and passes `event_log=job`, matching. `RecoveryResult.outcome`/`actions_taken` consumed in Task 2 `_run`. Endpoint JSON keys (`would_try`, `failing_layer`, `available`, `status`, `outcome`, `actions`, `steps`, `error`) match between Task 2/3 and the Task 5 frontend.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-30-dashboard-recover-button.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec then quality). (REQUIRED SUB-SKILL: superpowers:subagent-driven-development)
2. **Inline Execution** — batch with checkpoints. (REQUIRED SUB-SKILL: superpowers:executing-plans)
