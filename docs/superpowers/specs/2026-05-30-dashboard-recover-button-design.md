# Dashboard One-Click Recover Button — Design Spec

**Date:** 2026-05-30
**Status:** Approved (brainstorming) — pending implementation plan
**Topic:** Wire the existing CLI recovery engine into the dashboard so a user can preview and trigger recovery from the connectivity panel and watch live progress, with destructive actions gated.

## Problem

robobench's recovery engine (`RecoveryEngine` / `build_turtlebot4_recovery`) is **CLI-only** (`robobench recover`). The dashboard's connectivity panel (v0.10.0a0) now *diagnoses* which transport layer is broken (read-only) but cannot *act*. Users see "Discovery Server down" and then have to leave the browser and run the CLI. The natural next step is a one-click **Recover** button that runs the same engine from the dashboard.

The engine is **blocking and multi-minute** (each cycle: SSH probe + 8s settle; deadline 180s) and applies **destructive actions** (restart robot services; the nuclear Create3 reboot). A web button that mutates a robot needs the right execution model and safety gating.

## Design decisions (resolved during brainstorming)

1. **Execution model: background thread + status polling.** `POST /api/recover` starts a daemon thread running `engine.run()`; the engine streams `probe`/`action`/`outcome` events into an in-memory `RecoveryJob`; the frontend polls `GET /api/recover/status` every 1–2s. Matches the existing poll-based dashboard; no new dependencies (no WebSocket — deferred project-wide). A synchronous blocking request was rejected (minutes-long HTTP request would time out).

2. **Safety gating: Preview → Apply, nuclear web-excluded.** Two clicks: **Preview** runs an instant dry-run plan ("from the current diagnosis, will try X, Y, Z"); **Apply** actually runs the engine. The nuclear Create3 reboot is **never exposed to the web** — the controller always builds the engine with `allow_reboot=False`, and Preview filters nuclear out of the ladder. Rebooting the Create3 stays a deliberate CLI action (`robobench recover --allow-reboot`).

3. **Concurrency: single-flight + probe coexists.** Only one recovery runs at a time; a second `POST {apply}` while running returns **409**. The connectivity probe loop keeps running during recovery (concurrent SSH sessions are harmless, and the panel's layers visibly turn green as recovery fixes them — good feedback).

4. **Demo mode: disabled with a note.** No real robot/SSH in demo, so the button is greyed out with "Recover needs a real robot (SSH)". No synthetic recovery (YAGNI; don't fake destructive ops). The connectivity panel already showcases the diagnosis in demo.

## Architecture

A Recover section under the connectivity panel. **Preview** is instant and read-only (computed from the latest connectivity diagnosis already in `DiagnosticState`). **Apply** spawns a daemon thread that runs the existing recovery engine, with the engine's `event_log` hook pointed at an in-memory `RecoveryJob` so progress streams live to the polling frontend. A `RecoveryController` (injected into the FastAPI app by the CLI, which holds the SSH creds) owns the job and enforces single-flight + the `allow_reboot=False` ceiling. In demo mode no controller is injected, so the endpoints report "unavailable".

```
Connectivity panel ── Preview ──> POST /api/recover {mode:"preview"}
                                     └─ controller.preview(state.connectivity())  [instant, no SSH]
                                        → {failing_layer, would_try:[...]}
                   ── Apply ─────> POST /api/recover {mode:"apply"}
                                     └─ controller.start_apply()  [single-flight]
                                        └─ daemon thread: engine.run()
                                              engine.event_log = RecoveryJob  (.log streams steps)
                   ── poll ──────> GET /api/recover/status → job.snapshot()
                                     {available, status, mode, outcome, actions, steps, error}
```

## Components

### `src/robobench/panels/recovery_job.py` — `RecoveryJob` (thread-safe, threading only)
- Fields (lock-guarded): `status` (`"idle"|"running"|"done"`), `mode` (`"apply"|None`), `outcome` (`str|None`), `actions` (`list[str]`), `steps` (`list[dict]` — appended live), `error` (`str|None`), `started_at`/`finished_at` (`float|None`).
- `log(event: str, data: dict) -> None`: append `{"event": event, "data": data}` to `steps`. **This is the EventLogger-compatible sink** the engine writes to — so passing the job as the engine's `event_log` streams probe/action/outcome events into `steps`. (The `steps` list is the live event stream; the authoritative top-level `outcome` field is set by `finish()` from the `RecoveryResult`, not parsed out of the stream.)
- `begin() -> None` / `finish(outcome, actions, error=None) -> None`: state transitions (idle→running, running→done) with timestamps.
- `snapshot() -> dict`: a consistent one-lock copy of all fields.

### `src/robobench/panels/recovery_controller.py` — `RecoveryController`
- `__init__(self, *, build_engine, sleep=time.sleep, now=time.monotonic)`: `build_engine` is a zero-arg callable returning a ready `RecoveryEngine` with `event_log=self.job` and `allow_reboot=False` (the CLI binds creds/namespace/deadline/settle into it). Injectable for tests.
- Holds one `RecoveryJob` (`self.job`).
- `preview(connectivity_state: RobotState | None) -> dict`: **pure** — compute the plan from the diagnosis. Uses `first_broken_layer` (from `panels.connectivity`) to find the failing layer, then `[action for aspect, action, is_nuclear in _LADDER if aspect == failing and not is_nuclear]` for the would-try list. Returns `{"failing_layer": str|None, "would_try": [...], "available": True}`. `None`/healthy → `would_try == []`.
- `start_apply() -> bool`: **single-flight.** If `job.status == "running"`, return `False` (caller → 409). Else `job.begin()`, spawn a daemon thread running `_run()`. Returns `True`.
- `_run(self)` (thread body): `try: engine = build_engine(); result = engine.run(); job.finish(result.outcome, result.actions_taken)` `except Exception as exc: job.finish("ERROR", [], error=str(exc))`. Never raises out of the thread.

### `src/robobench/panels/server.py` — endpoints (delegate to injected controller)
- `create_app(state, namespace, expected_nodes=None, *, recovery: RecoveryController | None = None)`. Store on `app.state.recovery`.
- `POST /api/recover` body `{"mode": "preview" | "apply"}`:
  - `recovery is None` → HTTP 403 `{"detail": "recovery unavailable (demo or no SSH config)"}`.
  - `mode == "preview"` → `recovery.preview(state.connectivity())` (200).
  - `mode == "apply"` → `recovery.start_apply()`; `True` → 202 + `recovery.job.snapshot()`; `False` → 409 `{"detail": "a recovery is already running"}`.
- `GET /api/recover/status` → `recovery.job.snapshot()` plus `"available": True`; when `recovery is None` → `{"available": False, "status": "idle"}` (so the UI greys the button in demo).

### `src/robobench/cli.py` — `_cmd_dashboard`
- Non-demo: construct the controller first, then give it a `build_engine` that closes over `controller.job` (so the engine streams events into that job), and inject the controller into the app:
  ```python
  controller = RecoveryController(build_engine=lambda: None)  # placeholder set next line
  controller.build_engine = lambda: build_turtlebot4_recovery(
      ip=kwargs["ip"], ssh_user=kwargs["ssh_user"], ssh_pass=kwargs["ssh_pass"],
      namespace=namespace, allow_reboot=False, deadline_s=180.0,
      event_log=controller.job,
  )
  # ... create_app(state, namespace=namespace, expected_nodes=..., recovery=controller)
  ```
  (`build_turtlebot4_recovery` already accepts `event_log` and `allow_reboot`. The implementation plan may instead make `RecoveryController.__init__` take the creds and build internally — either is fine as long as the engine's `event_log` is `controller.job` and `allow_reboot=False`.)
- Demo: `create_app(..., recovery=None)`.

### Frontend — `src/robobench/panels/static/`
- Extend the connectivity card (or add a sibling block in `connectivity.js`) with: a **Preview** button, an **Apply** button (disabled until a preview or always enabled — see below), and a `<div>` progress area.
- On load, poll `GET /api/recover/status`; if `available == false`, disable both buttons and show "Recover needs a real robot (SSH)".
- **Preview** → `POST /api/recover {mode:"preview"}`; render `would_try` ("Will try: restart_discovery_server → …"); enable **Apply**.
- **Apply** → `POST /api/recover {mode:"apply"}`; on 202 start polling `GET /api/recover/status` every 1.5s; render `steps` live (each action) and the final `outcome` pill; on 409 show "already running" and start polling. Stop polling when `status == "done"`.
- Register any new DOM in `index.html`/`style.css` as needed (the buttons live inside the existing `#connectivity-panel`, so likely no new `<section>`).

## Data flow & lifecycle
1. Connectivity probe loop keeps `DiagnosticState.connectivity()` fresh (existing).
2. User clicks **Preview** → instant plan from the current diagnosis (no SSH).
3. User clicks **Apply** → daemon thread runs `engine.run()`; events stream into `RecoveryJob.steps`; the connectivity panel keeps updating in parallel.
4. Frontend polls `status` until `done`; shows the outcome.
5. A second Apply while running → 409. Ctrl+C kills the daemon thread with the process.

## Error handling & safety
- `allow_reboot=False` is hard-wired in the controller's engine build — the web path can never trigger the nuclear Create3 reboot. Preview filters nuclear ladder rows.
- Single-flight: 409 on concurrent apply.
- Thread body is exception-guarded → a crashing engine sets `job.error` + `status="done"`, never kills the thread or the server.
- Demo / no-SSH → 403 + greyed UI.
- The `NEEDS_HUMAN` outcome (RPi unreachable) surfaces in the UI as a clear "robot unreachable — check power/network" message.

## Testing strategy
- **`RecoveryJob`**: `.log` appends steps; `begin`/`finish` transitions + timestamps; `snapshot` is a consistent copy; thread-safety (lock-guarded).
- **`RecoveryController.preview`**: given a connectivity `RobotState` with a broken layer → correct non-nuclear `would_try`; `None`/healthy → `[]`; confirm a nuclear-only aspect never appears.
- **`RecoveryController.start_apply`**: inject a fake `build_engine` returning a fake engine whose `run()` emits events to the job's `.log` and returns a `RecoveryResult`; assert the job ends `done` with the outcome + actions; assert **single-flight** (a second `start_apply()` while the first hasn't finished returns `False`); assert an engine exception → `job.error` set, `status == "done"`.
- **Endpoints** (FastAPI TestClient, injected fake controller): preview returns the plan; apply returns 202 + status; second apply while running → 409; `recovery=None` → 403 on POST and `available:false` on GET status.
- **Frontend**: browser/demo verification — in demo the buttons are greyed with the note; against a fake-controller app, the progress list renders steps and the outcome pill.
- All existing tests stay green; the DDS bridge, four panels, and the connectivity panel are untouched except the connectivity card gains the Recover controls.

## Out of scope (YAGNI)
- No WebSocket streaming (polling is the project pattern).
- No JSONL flight-recorder for dashboard-initiated recovery in v1 (the CLI path keeps that; dashboard progress lives in `RecoveryJob.steps`). Easy to add a tee later.
- No nuclear Create3 reboot from the web, ever.
- No simulated recovery in demo mode.
- No change to the recovery engine, the probe, or the CLI `recover`/`preflight` commands.

## Honest caveats
- Everything remains mocked/unit-tested; **zero real-hardware validation.**
- This is the **first time the dashboard triggers destructive actions** (restarting robot services) from the browser. The engine and atomic actions are unit-tested and the SSH commands are upstream-proven, but the full web → background-thread → real-SSH recovery loop needs a real-robot pass.
