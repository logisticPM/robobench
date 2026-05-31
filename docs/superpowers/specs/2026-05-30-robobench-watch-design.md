# `robobench watch` — Design Spec

**Date:** 2026-05-30
**Status:** Approved (brainstorming) — pending implementation plan
**Topic:** A long-running deterministic supervisor that continuously probes the robot and (optionally) keeps it in a healthy bring-up state by reusing the recovery engine, with anti-thrash cooldown, attempt-capped escalation to a human, and safety gating.

## Problem

robobench has all the pieces of a real-time management agent — observe
(`TurtleBot4Probe`), decide+act (`RecoveryEngine`), record (`eventlog` /
`report`), surface (`dashboard`) — but they're one-shot. There's no
**continuous supervisor** that watches a robot over time and keeps it healthy.
`robobench watch` adds that loop, as a deterministic supervisor (no LLM), reusing
the existing engine.

## Design decisions (resolved during brainstorming)

1. **Default behavior: monitor-only; `--auto-recover` opts into acting.** By
   default `watch` probes + records + alerts on unhealthy state (and names what it
   *would* fix) but takes **no action**. Only `--auto-recover` lets it invoke the
   recovery engine. The nuclear Create3 reboot is **never** reachable from `watch`
   (`allow_reboot=False`, no flag). Rationale: `watch` is unattended and the
   recovery paths are not yet hardware-validated.
2. **Anti-thrash + escalation (when `--auto-recover`): cooldown + attempt-cap →
   escalate to monitor-only.** A cooldown enforces a minimum gap between recovery
   attempts; after `max_attempts` consecutive failed recoveries the supervisor
   **stops acting**, switches to monitor-only, and alerts "giving up — needs
   human." Returning to a healthy state resets the counter. A `NEEDS_HUMAN`
   outcome (RPi unreachable) escalates immediately without burning the remaining
   attempts.
3. **Reuse the engine.** Monitoring uses the **lite** probe
   (`read_connectivity`, ~seconds); remediation invokes
   `build_turtlebot4_recovery(...).run()` (which does its own full probe +
   convergence loop, `allow_reboot=False`). One `recover()` call == one bounded
   recovery attempt. `watch` does not re-implement decision logic.
4. **Fully injectable for testing.** The supervisor loop takes injected
   `probe`/`recover`/`sleep`/`now`/`should_stop`/`emit` so the entire policy
   (monitor-only, cooldown, attempt-cap, escalation, reset) is unit-tested with
   no hardware.

## Architecture

A pure supervisor loop in a new module, plus a thin CLI command that wires the
real lite probe + recovery-engine factory + clock and runs the loop until Ctrl+C.

```
robobench watch [--auto-recover] [--interval 20] [--recover-cooldown 60] [--max-recover-attempts 3]
  └─ _cmd_watch: build lite probe + (if --auto-recover) a recover() bound to the engine
                 run_supervisor(probe, recover_or_None, interval, cooldown_s, max_attempts,
                                sleep=time.sleep, now=time.monotonic, should_stop=..., emit=...)
```

## Components

### `src/robobench/recovery/supervisor.py` (new — pure orchestration)
```python
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
) -> None: ...
```
- `probe` — lite monitoring read returning a `RobotState`.
- `recover` — `None` means monitor-only; otherwise a zero-arg callable running one
  bounded recovery (the engine's `run`) and returning a `RecoveryResult`.
- `emit(event, data)` — sink for status/heartbeat + structured events (the CLI
  wires it to both a console heartbeat and the flight recorder).
- Loop (each cycle), with internal state `attempts: int = 0`, `escalated: bool = False`,
  `last_attempt: float | None = None`:
  1. if `should_stop()` → return.
  2. `state = probe()`; `emit("observe", {...})`.
  3. if `state.is_healthy()`: reset `attempts = 0`, `escalated = False`;
     `emit("healthy", ...)`.
  4. else (unhealthy): `aspect = state.failing_aspect()`; `emit("unhealthy", {"aspect": aspect})`.
     - if `recover is None` or `escalated`: alert only (no action).
     - elif `last_attempt is not None and now() - last_attempt < cooldown_s`: skip (in cooldown).
     - elif `attempts >= max_attempts`: `escalated = True`; `emit("escalate", {"reason": "max_attempts"})` (needs human).
     - else: `result = recover()`; `last_attempt = now()`; `attempts += 1`;
       `emit("recover", {"outcome": result.outcome, "actions": result.actions_taken})`;
       if `result.outcome == "CONVERGED"`: reset `attempts = 0`, `escalated = False`;
       elif `result.outcome == "NEEDS_HUMAN"`: `escalated = True`; `emit("escalate", {"reason": "needs_human"})`.
  5. `sleep(interval)`.
- No rclpy/SSH/FastAPI imports — pure stdlib + `RobotState`/`RecoveryResult` types.

### `src/robobench/cli.py` — `watch` subcommand + `_cmd_watch`
- Subparser `watch`: `--robot` (required, `turtlebot4`), `--config` (required),
  `--auto-recover` (store_true), `--interval` (float, default 20.0),
  `--recover-cooldown` (float, default 60.0), `--max-recover-attempts` (int,
  default 3). **No `--allow-reboot`.** (`--interval`/`--recover-cooldown` use the
  existing `_positive_float` validator; `--max-recover-attempts` a positive-int
  validator.)
- `_cmd_watch(args)`:
  - load config; build a lite probe closure:
    `probe = lambda: TurtleBot4Probe(ip, ssh_user, ssh_pass, namespace).read_connectivity()`.
  - if `args.auto_recover`: build `recover = lambda: build_turtlebot4_recovery(
    ip, ssh_user, ssh_pass, namespace, allow_reboot=False, deadline_s=180.0,
    event_log=event_log).run()`; else `recover = None`.
  - `event_log = EventLogger()` (flight recorder for the session); print its path.
  - `emit` writes a concise console heartbeat line AND `event_log.log(event, data)`.
  - print a startup banner (mode: monitor-only vs auto-recover, interval).
  - `run_supervisor(probe, recover, interval=..., cooldown_s=..., max_attempts=...,
    sleep=time.sleep, now=time.monotonic, should_stop=None, emit=emit)`.
  - wrap in `try/except KeyboardInterrupt` → clean "stopped" message; `finally: event_log.close()`.
  - returns 0.

## Output & recording
- Console heartbeat per cycle, e.g.:
  - `[watch] 03:00:00  healthy`
  - `[watch] 03:00:20  UNHEALTHY (discovery_server_ok) - monitor-only` (ASCII `-`)
  - `[watch] 03:00:20  UNHEALTHY (discovery_server_ok) - recovering... CONVERGED`
  - `[watch] 03:02:00  giving up (max attempts) - needs human`
- Flight recorder: the supervisor's `emit` events + (during a recovery) the
  engine's own `probe`/`action`/`outcome` events (the engine gets `event_log`),
  so `robobench report` can summarize the recovery cycles in a watch session.
- Ctrl+C → clean stop, close the log.

## Error handling
`run_supervisor` is the never-die boundary — it guards the injected callables so
one bad cycle never crashes the loop:
- **`probe()` raises** → `emit("probe_error", {...})`, then `sleep(interval)` and
  continue to the next cycle. No recovery decision is made this cycle (you can't
  decide without a state). (The CLI's lite probe already short-circuits to
  `rpi_reachable=False` on ping failure; this guard covers an unexpected SSH/other
  error.)
- **`recover()` raises** (only reachable under `--auto-recover`) →
  `emit("recover_error", {...})`, count it as a failed attempt (`attempts += 1`,
  `last_attempt = now()`), and continue. So a flapping remediation still hits the
  attempt-cap and escalates rather than crashing.
- `--interval`/`--recover-cooldown` ≤ 0 rejected by `_positive_float`;
  `--max-recover-attempts` < 1 rejected by a positive-int validator.

## Testing strategy (no hardware)
- **`run_supervisor`** with injected scripted `probe` (a list/iterator of
  `RobotState`s), scripted `recover` (list of `RecoveryResult`s), `sleep=lambda _:None`,
  `now` = a fake monotonic clock, `should_stop` stopping after N cycles, and a
  recording `emit`:
  - monitor-only (`recover=None`): never calls recover; emits unhealthy alerts.
  - auto-recover: calls recover on an unhealthy cycle; a `CONVERGED` result resets
    the attempt counter (a later unhealthy cycle attempts again).
  - cooldown: two unhealthy cycles within `cooldown_s` → recover called once.
  - attempt-cap: `max_attempts` failed recoveries → `escalate` emitted, recover not
    called again even while still unhealthy; a subsequent healthy cycle resets,
    then a new unhealthy cycle can recover again.
  - `NEEDS_HUMAN` outcome → immediate escalate (no further recover attempts).
  - a `recover()` that raises → counts as a failed attempt, loop continues.
  - a `probe()` that raises → `probe_error` emitted, no recovery that cycle, loop
    continues to the next cycle.
- **`_cmd_watch`** (CLI): monkeypatch `run_supervisor` to capture that `recover`
  is `None` without `--auto-recover` and non-`None` with it; assert the engine
  factory is built with `allow_reboot=False`; assert `--interval`/cooldown/attempts
  flow through. (Don't run a real loop.)
- All via injected deps / monkeypatch; no network/SSH/rclpy.

## Out of scope (YAGNI)
- systemd unit / daemonization wrapper (run it under your own supervisor/`&`).
- Remote alerting (email/webhook) — `emit` is the extension point, but v1 emits to
  console + flight recorder only.
- LLM / any non-deterministic decision-making.
- Dashboard integration (the dashboard already has its own connectivity thread).
- The nuclear Create3 reboot from `watch` (never).

## Honest caveats
- **This is the feature that most needs real-hardware validation before you trust
  `--auto-recover` unattended.** It will, when enabled, repeatedly restart robot
  services based on logic that has only ever run against mocks — and two prior
  self-audits showed real-wiring is the bug-dense layer. The code is 100%
  unit-testable here (injected deps), but *trusting it to auto-act on a live robot
  overnight* requires a hardware pass of the recovery loop first. The spec
  default (monitor-only) reflects this: out of the box, `watch` only observes.
