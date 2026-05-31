# `robobench watch` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `robobench watch`, a long-running deterministic supervisor that continuously probes the robot and (only with `--auto-recover`) keeps it healthy by reusing the recovery engine, with cooldown + attempt-capped escalation and no nuclear reboot.

**Architecture:** A pure `run_supervisor` loop (all deps injected → 100% unit-testable, the never-die boundary for probe/recover errors) in `recovery/supervisor.py`, plus a thin `_cmd_watch` CLI that wires the lite probe + a recovery-engine `recover` closure + the real clock and runs until Ctrl+C. Monitoring uses the lite probe; remediation reuses `build_turtlebot4_recovery(...).run()` with `allow_reboot=False`.

**Tech Stack:** Python 3.11+ (threading not needed — single loop), argparse, pytest, ruff. Tests/lint: `.venv/Scripts/python.exe -m pytest -q` / `.venv/Scripts/python.exe -m ruff check src tests`. Baseline: 230 passed, version 0.13.0a0.

Spec: `docs/superpowers/specs/2026-05-30-robobench-watch-design.md`.

---

## File Structure

| File | Responsibility | Task |
|------|----------------|------|
| `src/robobench/recovery/supervisor.py` (new) | `run_supervisor` loop (monitor/cooldown/attempt-cap/escalate, injected deps) | 1 |
| `src/robobench/cli.py` | `watch` subparser + `_cmd_watch` + `_positive_int` validator | 2 |
| README + `docs/tutorials/recovering-a-stuck-robot.md` + `CHANGELOG.md` + version | release v0.14.0a0 | 3 |

Reused (existing): `RobotState` (`.is_healthy()`, `.failing_aspect()`),
`RecoveryResult` (`.outcome`, `.actions_taken`), `TurtleBot4Probe.read_connectivity()`,
`build_turtlebot4_recovery(..., allow_reboot=, deadline_s=, event_log=)`,
`EventLogger`.

---

## Task 1: `run_supervisor` loop

**Files:**
- Create: `src/robobench/recovery/supervisor.py`
- Test: `tests/unit/recovery/test_supervisor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/recovery/test_supervisor.py
from robobench.recovery.engine import RecoveryResult
from robobench.recovery.state import RobotState
from robobench.recovery.supervisor import run_supervisor

_HEALTHY = RobotState(True, True, True, 5, True, True)
_BROKEN = RobotState(True, False, True, 5, True, True)  # discovery_server_ok fails


def test_monitor_only_never_recovers():
    states = iter([_BROKEN, _BROKEN])
    calls = {"sleep": 0}
    events = []
    run_supervisor(
        probe=lambda: next(states),
        recover=None,
        interval=1, cooldown_s=0, max_attempts=3,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: 0.0,
        should_stop=lambda: calls["sleep"] >= 2,
        emit=lambda e, d: events.append((e, d)),
    )
    assert any(e == "unhealthy" for e, _ in events)
    assert not any(e in ("recover", "recover_error") for e, _ in events)


def test_auto_recover_attempts_and_resets_on_converged():
    states = iter([_BROKEN, _HEALTHY, _BROKEN])
    results = iter([
        RecoveryResult(outcome="CONVERGED", actions_taken=["restart_discovery_server"]),
        RecoveryResult(outcome="CONVERGED", actions_taken=["restart_discovery_server"]),
    ])
    calls = {"sleep": 0, "recover": 0}

    def recover():
        calls["recover"] += 1
        return next(results)

    run_supervisor(
        probe=lambda: next(states),
        recover=recover,
        interval=1, cooldown_s=0, max_attempts=3,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: float(calls["sleep"]),  # advances each cycle -> no cooldown
        should_stop=lambda: calls["sleep"] >= 3,
        emit=lambda e, d: None,
    )
    assert calls["recover"] == 2  # cycle1 broken->recover, cycle2 healthy, cycle3 broken->recover


def test_cooldown_skips_second_attempt():
    states = iter([_BROKEN, _BROKEN])
    results = iter([RecoveryResult(outcome="STUCK")])
    calls = {"sleep": 0, "recover": 0}

    def recover():
        calls["recover"] += 1
        return next(results)

    events = []
    run_supervisor(
        probe=lambda: next(states),
        recover=recover,
        interval=1, cooldown_s=100, max_attempts=3,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: 0.0,  # frozen -> 2nd cycle within cooldown
        should_stop=lambda: calls["sleep"] >= 2,
        emit=lambda e, d: events.append((e, d)),
    )
    assert calls["recover"] == 1
    assert any(e == "cooldown" for e, _ in events)


def test_max_attempts_escalates():
    states = iter([_BROKEN] * 5)
    results = iter([RecoveryResult(outcome="STUCK")] * 5)
    calls = {"sleep": 0, "recover": 0}

    def recover():
        calls["recover"] += 1
        return next(results)

    events = []
    run_supervisor(
        probe=lambda: next(states),
        recover=recover,
        interval=1, cooldown_s=0, max_attempts=2,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: float(calls["sleep"]),
        should_stop=lambda: calls["sleep"] >= 5,
        emit=lambda e, d: events.append((e, d)),
    )
    assert calls["recover"] == 2  # 2 attempts then escalate; no more
    assert any(e == "escalate" and d.get("reason") == "max_attempts" for e, d in events)


def test_needs_human_escalates_immediately():
    states = iter([_BROKEN, _BROKEN, _BROKEN])
    results = iter([RecoveryResult(outcome="NEEDS_HUMAN")])
    calls = {"sleep": 0, "recover": 0}

    def recover():
        calls["recover"] += 1
        return next(results)

    events = []
    run_supervisor(
        probe=lambda: next(states),
        recover=recover,
        interval=1, cooldown_s=0, max_attempts=3,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: float(calls["sleep"]),
        should_stop=lambda: calls["sleep"] >= 3,
        emit=lambda e, d: events.append((e, d)),
    )
    assert calls["recover"] == 1  # one attempt -> NEEDS_HUMAN -> escalated
    assert any(e == "escalate" and d.get("reason") == "needs_human" for e, d in events)


def test_recover_exception_counts_and_continues():
    states = iter([_BROKEN, _BROKEN, _BROKEN])
    calls = {"sleep": 0, "recover": 0}

    def boom():
        calls["recover"] += 1
        raise RuntimeError("ssh boom")

    events = []
    run_supervisor(
        probe=lambda: next(states),
        recover=boom,
        interval=1, cooldown_s=0, max_attempts=2,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: float(calls["sleep"]),
        should_stop=lambda: calls["sleep"] >= 3,
        emit=lambda e, d: events.append((e, d)),
    )
    assert calls["recover"] == 2  # each raise counts as an attempt, then escalate
    assert any(e == "recover_error" for e, _ in events)
    assert any(e == "escalate" for e, _ in events)


def test_probe_exception_continues():
    calls = {"sleep": 0, "probe": 0}
    events = []

    def probe():
        calls["probe"] += 1
        if calls["probe"] == 1:
            raise RuntimeError("probe boom")
        return _HEALTHY

    run_supervisor(
        probe=probe,
        recover=None,
        interval=1, cooldown_s=0, max_attempts=3,
        sleep=lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1),
        now=lambda: 0.0,
        should_stop=lambda: calls["sleep"] >= 2,
        emit=lambda e, d: events.append((e, d)),
    )
    assert any(e == "probe_error" for e, _ in events)
    assert any(e == "healthy" for e, _ in events)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/recovery/test_supervisor.py -v`
Expected: FAIL (`No module named 'robobench.recovery.supervisor'`)

- [ ] **Step 3: Write the implementation**

```python
# src/robobench/recovery/supervisor.py
"""Continuous deterministic supervisor: probe -> (optionally) recover -> repeat.

Reuses the recovery engine via an injected zero-arg ``recover`` callable. Pure
orchestration — probe/recover/sleep/now/should_stop/emit are all injected, so the
whole policy (monitor-only, cooldown, attempt-cap, escalation, reset) is
unit-testable without hardware. ``run_supervisor`` is the never-die boundary: a
failing ``probe()`` or ``recover()`` is caught and the loop continues.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from robobench.recovery.engine import RecoveryResult
    from robobench.recovery.state import RobotState


def run_supervisor(
    probe: Callable[[], RobotState],
    recover: Callable[[], RecoveryResult] | None,
    *,
    interval: float,
    cooldown_s: float,
    max_attempts: int,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    should_stop: Callable[[], bool] | None = None,
    emit: Callable[[str, dict], None] | None = None,
) -> None:
    """Run the supervisor loop until ``should_stop()`` is true (default: forever).

    ``recover is None`` -> monitor-only (alert, never act). Otherwise an unhealthy
    cycle triggers ``recover()`` unless within ``cooldown_s`` of the last attempt
    or after ``max_attempts`` consecutive failures (then it escalates to
    monitor-only). A CONVERGED result resets the counter; NEEDS_HUMAN escalates
    immediately. Returning to healthy resets the counter.
    """
    stop = should_stop or (lambda: False)
    say = emit or (lambda _event, _data: None)

    attempts = 0
    escalated = False
    last_attempt: float | None = None

    while not stop():
        try:
            state = probe()
        except Exception as exc:  # noqa: BLE001 — a bad probe must not kill the loop
            say("probe_error", {"error": str(exc)})
            sleep(interval)
            continue

        if state.is_healthy():
            attempts = 0
            escalated = False
            say("healthy", {})
            sleep(interval)
            continue

        aspect = state.failing_aspect()
        say("unhealthy", {"aspect": aspect})

        if recover is None or escalated:
            pass  # monitor-only (by config or after escalation): alert, don't act
        elif last_attempt is not None and now() - last_attempt < cooldown_s:
            say("cooldown", {"aspect": aspect})
        elif attempts >= max_attempts:
            escalated = True
            say("escalate", {"reason": "max_attempts", "attempts": attempts})
        else:
            last_attempt = now()
            attempts += 1
            try:
                result = recover()
            except Exception as exc:  # noqa: BLE001 — flapping remediation must not crash the loop
                say("recover_error", {"error": str(exc), "attempt": attempts})
            else:
                say("recover", {"outcome": result.outcome, "actions": list(result.actions_taken)})
                if result.outcome == "CONVERGED":
                    attempts = 0
                    escalated = False
                elif result.outcome == "NEEDS_HUMAN":
                    escalated = True
                    say("escalate", {"reason": "needs_human"})

        sleep(interval)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/recovery/test_supervisor.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/robobench/recovery/supervisor.py tests/unit/recovery/test_supervisor.py
git commit -m "feat: run_supervisor — continuous monitor/cooldown/escalate loop"
```

---

## Task 2: `robobench watch` CLI subcommand

**Files:**
- Modify: `src/robobench/cli.py` (`_positive_int` validator, `watch` subparser, `_cmd_watch`)
- Test: `tests/unit/test_cli.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_cli.py  (append)
def test_watch_monitor_only_by_default(monkeypatch, tmp_path):
    cfg = _dashboard_config(tmp_path)
    captured = {}
    monkeypatch.setattr(
        "robobench.recovery.supervisor.run_supervisor",
        lambda probe, recover, **kw: captured.update(recover=recover, kw=kw),
    )
    rc = main(["watch", "--robot", "turtlebot4", "--config", str(cfg)])
    assert rc == 0
    assert captured["recover"] is None  # monitor-only default
    assert captured["kw"]["interval"] == 20.0
    assert captured["kw"]["cooldown_s"] == 60.0
    assert captured["kw"]["max_attempts"] == 3


def test_watch_auto_recover_builds_recover(monkeypatch, tmp_path):
    cfg = _dashboard_config(tmp_path)
    captured = {}
    monkeypatch.setattr(
        "robobench.recovery.supervisor.run_supervisor",
        lambda probe, recover, **kw: captured.update(recover=recover),
    )
    rc = main(["watch", "--robot", "turtlebot4", "--config", str(cfg), "--auto-recover"])
    assert rc == 0
    assert captured["recover"] is not None  # auto-recover -> a recover callable
```

(`_dashboard_config` and `main` already exist at the top of `test_cli.py`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli.py -k watch -v`
Expected: FAIL (`invalid choice: 'watch'`)

- [ ] **Step 3: Add a positive-int validator** — near `_positive_float` in `cli.py`:

```python
def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed
```

- [ ] **Step 4: Add the subparser** — in `_build_parser`, after the `report.set_defaults(...)` block and before `return parser`:

```python
    watch = subparsers.add_parser(
        "watch",
        help="Continuously supervise a robot (monitor-only; --auto-recover to act).",
    )
    watch.add_argument("--robot", required=True, choices=["turtlebot4"])
    watch.add_argument("--config", required=True)
    watch.add_argument(
        "--auto-recover",
        action="store_true",
        help="Let the supervisor invoke recovery on unhealthy state (off by default).",
    )
    watch.add_argument("--interval", type=_positive_float, default=20.0,
                       help="Seconds between probes (default 20).")
    watch.add_argument("--recover-cooldown", type=_positive_float, default=60.0,
                       help="Min seconds between recovery attempts (default 60).")
    watch.add_argument("--max-recover-attempts", type=_positive_int, default=3,
                       help="Consecutive failed recoveries before escalating to monitor-only (default 3).")
    watch.set_defaults(func=_cmd_watch)
```

- [ ] **Step 5: Add the handler** — after `_cmd_report` (or with the other `_cmd_*`):

```python
def _cmd_watch(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    import time as _time  # noqa: PLC0415

    from robobench.recovery.supervisor import run_supervisor  # noqa: PLC0415

    kwargs = load_adapter_config(Path(args.config))
    probe_obj = TurtleBot4Probe(
        ip=kwargs["ip"],
        ssh_user=kwargs["ssh_user"],
        ssh_pass=kwargs["ssh_pass"],
        namespace=kwargs["namespace"],
    )
    event_log = EventLogger()

    recover = None
    if args.auto_recover:

        def recover():
            return build_turtlebot4_recovery(
                ip=kwargs["ip"],
                ssh_user=kwargs["ssh_user"],
                ssh_pass=kwargs["ssh_pass"],
                namespace=kwargs["namespace"],
                allow_reboot=False,
                deadline_s=180.0,
                event_log=event_log,
            ).run()

    def emit(event: str, data: dict) -> None:
        event_log.log(f"watch_{event}", data)
        detail = data.get("aspect") or data.get("reason") or data.get("outcome") or ""
        suffix = f" ({detail})" if detail else ""
        print(f"[watch] {event}{suffix}")

    mode = "auto-recover" if args.auto_recover else "monitor-only"
    print(
        f"[watch] supervising {kwargs['namespace']} "
        f"({mode}, every {args.interval:.0f}s) - Ctrl+C to stop"
    )
    print(f"[watch] event log: {event_log.path}")
    try:
        run_supervisor(
            probe_obj.read_connectivity,
            recover,
            interval=args.interval,
            cooldown_s=args.recover_cooldown,
            max_attempts=args.max_recover_attempts,
            sleep=_time.sleep,
            now=_time.monotonic,
            emit=emit,
        )
    except KeyboardInterrupt:
        print("\n[watch] stopped")
    finally:
        event_log.close()
    return 0
```

(`TurtleBot4Probe`, `build_turtlebot4_recovery`, `EventLogger`, `load_adapter_config`
are already imported at the top of `cli.py`. `probe_obj.read_connectivity` is passed
as the probe callable directly.)

- [ ] **Step 6: Run tests + full suite + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli.py -k watch -v && .venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests`
Expected: watch tests PASS; full suite PASS (~239 passed); ruff clean

- [ ] **Step 7: Commit**

```bash
git add src/robobench/cli.py tests/unit/test_cli.py
git commit -m "feat: robobench watch subcommand (deterministic supervisor)"
```

---

## Task 3: Docs + release v0.14.0a0

**Files:**
- Modify: `README.md` (CLI table), `docs/tutorials/recovering-a-stuck-robot.md`
- Modify: `CHANGELOG.md`, `pyproject.toml`, `src/robobench/__init__.py`

- [ ] **Step 1: README CLI table** — add a row to the `## CLI` table (after the `robobench report` row):

```markdown
| `robobench watch` | Continuously supervise a robot — monitor-only, or `--auto-recover` to auto-remediate |
```

- [ ] **Step 2: Tutorial note** — append to `docs/tutorials/recovering-a-stuck-robot.md`:

```markdown
## Continuous supervision (`robobench watch`)

`robobench recover` is one-shot. To keep a robot healthy over time, run the
supervisor:

```bash
robobench watch --robot turtlebot4 --config ./config.yaml             # monitor-only
robobench watch --robot turtlebot4 --config ./config.yaml --auto-recover
```

By default `watch` only **observes** — it prints a heartbeat, records to
`~/.robobench/logs/`, and alerts (naming the broken layer) without acting.
`--auto-recover` lets it invoke the recovery engine on unhealthy state, with a
cooldown between attempts (`--recover-cooldown`, default 60s) and an attempt cap
(`--max-recover-attempts`, default 3) after which it stops acting and escalates
("needs human"). The nuclear Create3 reboot is never used by `watch`.

> **Validate on real hardware before trusting `--auto-recover` unattended.** It
> will restart robot services automatically; run the recovery loop against a real
> robot first. Out of the box, `watch` is monitor-only for exactly this reason.
```

- [ ] **Step 3: CHANGELOG** — turn `## [Unreleased]` into a fresh empty `## [Unreleased]` above:

```markdown
## [0.14.0a0] — 2026-05-30

### Added

- **`robobench watch`** — a long-running deterministic supervisor. It probes the
  robot on an interval (lite SSH probe) and, **monitor-only by default**, prints a
  heartbeat + records to the flight recorder + alerts on unhealthy state. With
  `--auto-recover` it invokes the recovery engine, gated by a cooldown
  (`--recover-cooldown`) and an attempt cap (`--max-recover-attempts`) that
  escalates to monitor-only ("needs human") on repeated failure or `NEEDS_HUMAN`;
  a return to healthy resets the counter. The nuclear Create3 reboot is never
  reachable from `watch`. New pure, fully-injectable
  `robobench.recovery.supervisor.run_supervisor`.

### Notes

- `--auto-recover` auto-restarts robot services unattended based on logic that is
  unit-tested but not yet hardware-validated. Validate the recovery loop on a real
  robot before enabling it unattended; the monitor-only default reflects this.
```

- [ ] **Step 4: Bump version** to `0.14.0a0` in `pyproject.toml` (`version = "0.14.0a0"`) and `src/robobench/__init__.py` (`__version__ = "0.14.0a0"`).

- [ ] **Step 5: Verify, commit, tag, push**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests && .venv/Scripts/python.exe -c "import robobench; print(robobench.__version__)"
git add README.md docs/tutorials/recovering-a-stuck-robot.md CHANGELOG.md pyproject.toml src/robobench/__init__.py
git commit -m "release: v0.14.0a0 — robobench watch supervisor"
git tag v0.14.0a0
git push origin main && git push origin v0.14.0a0
```
Expected: all tests pass; prints `0.14.0a0`.

---

## Self-Review

**1. Spec coverage:**
- Monitor-only default + `--auto-recover` opt-in → Task 2 (`recover=None` unless `--auto-recover`). ✓
- Cooldown + attempt-cap → escalate to monitor-only → Task 1 loop (`cooldown_s`, `max_attempts`, `escalated`) + tests. ✓
- `NEEDS_HUMAN` immediate escalation; CONVERGED/healthy reset → Task 1 + tests. ✓
- Reuse engine via `recover` closure with `allow_reboot=False`, lite probe for monitoring → Task 2. ✓
- Never-die boundary (probe/recover exceptions caught) → Task 1 + 2 tests. ✓
- Flight recorder + engine events for `report` → Task 2 (`event_log` passed to both `emit` and the engine). ✓
- No nuclear, no `--allow-reboot` → Task 2 (none added; `allow_reboot=False`). ✓
- Cadence/cooldown/attempts flags + validators → Task 2 (`_positive_float`/`_positive_int`). ✓
- Docs (README + tutorial) + hardware caveat → Task 3. ✓
- Out of scope (no systemd, no remote alerting, no LLM, no dashboard integration) — respected. ✓

**2. Placeholder scan:** No TBD/TODO/"add error handling"/"similar to". Every code step complete; every run step has an exact command + expected result. Console output uses ASCII (`-`, no em-dash) — Windows-console-safe.

**3. Type consistency:** `run_supervisor(probe, recover, *, interval, cooldown_s, max_attempts, sleep, now, should_stop, emit)` defined in Task 1 is called with exactly those keyword names in Task 2's `_cmd_watch` and in every test. The emit event names (`probe_error`/`healthy`/`unhealthy`/`cooldown`/`escalate`/`recover`/`recover_error`) are consistent between the loop, the tests, and the CLI's `emit`. `recover` returns a `RecoveryResult` whose `.outcome`/`.actions_taken` are read in the loop and produced by `build_turtlebot4_recovery(...).run()`. `EventLogger.log`/`.path`/`.close` match existing usage.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-30-robobench-watch.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review. (REQUIRED SUB-SKILL: superpowers:subagent-driven-development)
2. **Inline Execution** — batch with checkpoints. (REQUIRED SUB-SKILL: superpowers:executing-plans)
