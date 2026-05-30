# Robobench v0.5 (Phase D) — Convergence-Loop Recovery Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the "tell you how to fix it → actually fix it" half of robobench's positioning by porting the upstream's battle-tested hardware-recovery *knowledge* (what actions fix a stuck robot) into a **convergence-loop recovery engine** that replaces the upstream's brittle linear script — observe → diagnose the minimal gap → apply the cheapest sufficient action → re-observe → repeat, with an escalation ladder, global deadline, dry-run, and destructive-tier gating. The engine is injected with a probe + actions interface so it is **100% unit-testable without hardware** (the single biggest flaw of the upstream version).

**Architecture:**
- A generic `RecoveryEngine` (in `robobench.recovery`) takes a `probe()` callable returning a structured `RobotState`, a `RecoveryActions` object (atomic idempotent fixes), a `clock`/`sleep`, and a deadline. It loops a prioritized escalation ladder: cheapest action whose precondition matches the failing aspect, never repeating an action, nuclear actions (Create3 reboot) gated behind opt-in. Returns a structured `RecoveryResult` with a full trace.
- The engine is **pure orchestration** — no SSH, no subprocess. That makes it fully testable by injecting a fake probe (scripted state sequence) + fake actions. This directly fixes the upstream's untestability.
- TurtleBot4-specific I/O lives in `robobench.robots.turtlebot4_recovery`: `TurtleBot4Probe` (SSH + local checks → `RobotState`, with transport-level retry and multi-sample odom stability) and `TurtleBot4RecoveryActions` (idempotent atomic fixes over `SSHClient`/`run_local`). Both mocked in unit tests.
- Two CLI commands: `robobench preflight` (read-only — print state + the actions that *would* run) and `robobench recover` (run the loop; `--dry-run`, `--allow-reboot`, `--deadline`).

**Tech Stack:** Python 3.11+, existing `robobench.ssh.SSHClient` + `robobench._process.run_local`, pytest, ruff. No new deps. No hardware needed for the test suite.

**Prerequisites:** v0.4.0a0 tagged, 98 tests passing. Reuses `SSHClient` (Phase B) and `run_local` (Phase B).

**Repo root:** `C:\Users\chntw\Documents\robotic\robobench\`

---

## Why this design (lessons from the upstream `full_recovery` post-mortem)

The upstream `ui/dashboard/dashboard_server.py` recovery chain was a fixed linear script. It was unreliable because:

1. **Fuzzy/buggy detection** — string-matching (`"DOCTYPE" in resp`), `--once` echo timeouts treated as "dead" (false negatives), and an actual bug (`f"\{ns}\odom"` with backslashes — a condition that's *always false*).
2. **Hardcoded timing** — fixed sleeps + bounded retries fail on a slow day even when the robot would have recovered.
3. **Over-eager nuclear option** — Create3 full reboot (~3 min, re-randomizes DDS GUIDs) triggered for laptop-side problems.
4. **Not idempotent/resumable** — a failure restarts the whole 6-step chain.
5. **SSH transport fragility** — one WiFi blip aborts the chain (logical retries, no transport retries).
6. **full_recovery never restarts the Discovery Server** — the actual culprit in some cases.
7. **One-shot verification** — odom echoed *once*; it can publish one message then stall.

This plan's engine fixes each: structured detection, no fixed timing (deadline + re-probe), escalation ladder (cheap→nuclear, nuclear gated), idempotent + convergence loop, transport-retry in the probe, Discovery Server restart as a rung, multi-sample stability for "healthy".

---

## File Structure

```
robobench/
├── src/robobench/
│   ├── __init__.py                          # version → 0.5.0a0 (Task 11)
│   ├── cli.py                               # +preflight, +recover subcommands (Tasks 9, 10)
│   └── recovery/                            # NEW — the recovery subsystem
│       ├── __init__.py
│       ├── state.py                         # RobotState dataclass + health/target logic (Task 1)
│       ├── actions.py                       # RecoveryActions ABC + ActionTier enum (Task 2)
│       └── engine.py                        # RecoveryEngine convergence loop + ladder (Tasks 3, 4)
│   └── robots/
│       ├── turtlebot4_probe.py              # NEW — TurtleBot4Probe (SSH+local → RobotState) (Task 6)
│       └── turtlebot4_recovery.py           # NEW — TurtleBot4RecoveryActions (Task 7) + factory (Task 8)
├── tests/unit/
│   ├── recovery/
│   │   ├── __init__.py
│   │   ├── test_state.py                    # (Task 1)
│   │   ├── test_actions.py                  # (Task 2)
│   │   └── test_engine.py                   # (Tasks 3, 4) — the heart: scripted scenarios
│   ├── robots/
│   │   ├── test_turtlebot4_probe.py         # (Task 6)
│   │   └── test_turtlebot4_recovery.py      # (Tasks 7, 8)
│   └── test_cli.py                          # +preflight/recover tests (Tasks 9, 10)
├── docs/tutorials/
│   └── recovering-a-stuck-robot.md          # NEW (Task 11)
└── CHANGELOG.md                             # +0.5.0a0 (Task 11)
```

**Responsibility map:**
- `recovery/state.py` — `RobotState`: structured snapshot (rpi_reachable, discovery_server_ok, clock_synced, create3_topics, tb4_nodes_present, odom_publishing). `is_healthy()` and `failing_aspect()` live here. No I/O.
- `recovery/actions.py` — `RecoveryActions` ABC (the atomic-fix contract) + `ActionTier` (CHEAP / MEDIUM / NUCLEAR). No I/O in the ABC.
- `recovery/engine.py` — `RecoveryEngine`: the convergence loop + escalation ladder + `RecoveryResult`. Pure orchestration, injected with probe/actions/sleep.
- `robots/turtlebot4_probe.py` — `TurtleBot4Probe`: builds a `RobotState` via SSH (`SSHClient`) + local (`run_local`), with transport retry + multi-sample odom. The only place that knows TB4 probe commands.
- `robots/turtlebot4_recovery.py` — `TurtleBot4RecoveryActions`: idempotent atomic fixes (restart local daemon, restart discovery server, clean DDS shm, restart create3 app, reboot create3, restart tb4 service) + a `build_turtlebot4_recovery(...)` factory wiring probe+actions+engine.

---

## Task 1: `RobotState` structured snapshot (TDD)

**Files:**
- Create: `src/robobench/recovery/__init__.py`
- Create: `src/robobench/recovery/state.py`
- Create: `tests/unit/recovery/__init__.py`
- Create: `tests/unit/recovery/test_state.py`

- [ ] **Step 1: Create package markers**

`src/robobench/recovery/__init__.py`:
```python
"""Robobench hardware-recovery subsystem — convergence-loop engine + state."""
```
`tests/unit/recovery/__init__.py`: empty (0 bytes).

- [ ] **Step 2: Write failing test `tests/unit/recovery/test_state.py`**

```python
"""Tests for RobotState."""
from __future__ import annotations

from robobench.recovery.state import RobotState


def _healthy() -> RobotState:
    return RobotState(
        rpi_reachable=True,
        discovery_server_ok=True,
        clock_synced=True,
        create3_topics=12,
        tb4_nodes_present=True,
        odom_publishing=True,
    )


def test_healthy_state_is_healthy():
    assert _healthy().is_healthy() is True
    assert _healthy().failing_aspect() is None


def test_unreachable_rpi_is_the_first_failing_aspect():
    s = _healthy()
    s = s_with(s, rpi_reachable=False)
    assert s.is_healthy() is False
    assert s.failing_aspect() == "rpi_reachable"


def test_failing_aspect_is_most_upstream_first():
    """When several aspects fail, the most upstream one is reported first:
    rpi → discovery_server → clock → create3_topics → tb4_nodes → odom."""
    s = RobotState(
        rpi_reachable=True,
        discovery_server_ok=False,   # upstream of the others
        clock_synced=False,
        create3_topics=0,
        tb4_nodes_present=False,
        odom_publishing=False,
    )
    assert s.failing_aspect() == "discovery_server_ok"


def test_odom_is_the_last_aspect():
    s = _healthy()
    s = s_with(s, odom_publishing=False)
    assert s.failing_aspect() == "odom_publishing"


def s_with(state: RobotState, **changes) -> RobotState:
    import dataclasses

    return dataclasses.replace(state, **changes)
```

- [ ] **Step 3: Run, confirm fail**

```bash
source .venv/Scripts/activate
pytest tests/unit/recovery/test_state.py -v
```
Expected: ImportError on `robobench.recovery.state`.

- [ ] **Step 4: Implement `src/robobench/recovery/state.py`**

```python
"""Structured snapshot of a robot's bring-up health.

No I/O — a probe fills this in, the engine reasons over it. Aspects are
ordered most-upstream-first: a failure upstream (e.g. Discovery Server down)
usually causes the downstream symptoms (no topics, no odom), so the engine
should fix upstream first.
"""
from __future__ import annotations

from dataclasses import dataclass

# Aspects in upstream → downstream order. failing_aspect() returns the first
# one that's bad, so the engine targets the root, not the symptom.
_ASPECT_ORDER = (
    "rpi_reachable",
    "discovery_server_ok",
    "clock_synced",
    "create3_topics",
    "tb4_nodes_present",
    "odom_publishing",
)


@dataclass(frozen=True)
class RobotState:
    """A structured read of the robot's bring-up health."""

    rpi_reachable: bool
    discovery_server_ok: bool
    clock_synced: bool
    create3_topics: int
    tb4_nodes_present: bool
    odom_publishing: bool

    def _aspect_ok(self, aspect: str) -> bool:
        if aspect == "create3_topics":
            return self.create3_topics > 0
        return bool(getattr(self, aspect))

    def is_healthy(self) -> bool:
        return all(self._aspect_ok(a) for a in _ASPECT_ORDER)

    def failing_aspect(self) -> str | None:
        """Return the most-upstream failing aspect, or None if healthy."""
        for aspect in _ASPECT_ORDER:
            if not self._aspect_ok(aspect):
                return aspect
        return None
```

- [ ] **Step 5: Run, confirm pass + ruff**

```bash
pytest tests/unit/recovery/test_state.py -v
ruff check src tests && ruff format --check src tests
```
Expected: 4 tests pass; 102 total.

- [ ] **Step 6: Commit**

```bash
git add src/robobench/recovery/__init__.py src/robobench/recovery/state.py tests/unit/recovery/__init__.py tests/unit/recovery/test_state.py
git commit -m "feat(recovery): add RobotState with upstream-first failing-aspect ordering"
```

---

## Task 2: `RecoveryActions` ABC + `ActionTier` (TDD)

**Files:**
- Create: `src/robobench/recovery/actions.py`
- Create: `tests/unit/recovery/test_actions.py`

- [ ] **Step 1: Write failing test `tests/unit/recovery/test_actions.py`**

```python
"""Tests for the RecoveryActions ABC and ActionTier."""
from __future__ import annotations

import pytest

from robobench.recovery.actions import ActionTier, RecoveryActions


def test_actions_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        RecoveryActions()  # type: ignore[abstract]


def test_tier_ordering_cheap_lt_nuclear():
    assert ActionTier.CHEAP < ActionTier.MEDIUM < ActionTier.NUCLEAR


def test_complete_subclass_is_instantiable():
    class Complete(RecoveryActions):
        def restart_local_daemon(self) -> None:
            return None

        def restart_discovery_server(self) -> None:
            return None

        def sync_clock(self) -> None:
            return None

        def restart_tb4_service(self) -> None:
            return None

        def restart_create3_app(self) -> None:
            return None

        def reboot_create3(self) -> None:
            return None

    c = Complete()
    assert c.restart_local_daemon() is None
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/recovery/test_actions.py -v
```

- [ ] **Step 3: Implement `src/robobench/recovery/actions.py`**

```python
"""Atomic recovery actions a robot adapter must provide, and their cost tier.

Each action is idempotent and targets one failing aspect. The engine picks
the cheapest action whose tier it's allowed to use. NUCLEAR actions (Create3
reboot) re-randomize DDS GUIDs and take minutes — gated behind explicit
opt-in so a debug tool never reboots hardware without consent.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import IntEnum


class ActionTier(IntEnum):
    """Cost/disruption tier. Lower = cheaper, tried first."""

    CHEAP = 1     # local-only or a quick remote restart
    MEDIUM = 2    # restarts a robot-side service/app
    NUCLEAR = 3   # reboots Create3 hardware (minutes, GUID churn)


class RecoveryActions(ABC):
    """Vendor-agnostic atomic fixes. Each must be idempotent."""

    @abstractmethod
    def restart_local_daemon(self) -> None:
        """Restart the workstation ros2 daemon (clears stale topic cache)."""

    @abstractmethod
    def restart_discovery_server(self) -> None:
        """Restart the FastDDS Discovery Server on the robot (clears zombies)."""

    @abstractmethod
    def sync_clock(self) -> None:
        """Force a chrony makestep on the robot."""

    @abstractmethod
    def restart_tb4_service(self) -> None:
        """Restart the robot-side bring-up service."""

    @abstractmethod
    def restart_create3_app(self) -> None:
        """Restart the Create3 application (soft — no GUID change)."""

    @abstractmethod
    def reboot_create3(self) -> None:
        """Full Create3 reboot (NUCLEAR — minutes, re-randomizes DDS GUIDs)."""
```

- [ ] **Step 4: Run, confirm pass + ruff**

Expected: 3 tests pass; 105 total.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/recovery/actions.py tests/unit/recovery/test_actions.py
git commit -m "feat(recovery): add RecoveryActions ABC and ActionTier"
```

---

## Task 3: `RecoveryEngine` skeleton — result type + healthy short-circuit + deadline (TDD)

**Files:**
- Create: `src/robobench/recovery/engine.py`
- Create: `tests/unit/recovery/test_engine.py`

- [ ] **Step 1: Write failing test `tests/unit/recovery/test_engine.py`**

```python
"""Tests for the RecoveryEngine convergence loop."""
from __future__ import annotations

from unittest.mock import MagicMock

from robobench.recovery.actions import RecoveryActions
from robobench.recovery.engine import RecoveryEngine, RecoveryResult
from robobench.recovery.state import RobotState


def _healthy() -> RobotState:
    return RobotState(
        rpi_reachable=True, discovery_server_ok=True, clock_synced=True,
        create3_topics=12, tb4_nodes_present=True, odom_publishing=True,
    )


def _fake_actions() -> RecoveryActions:
    return MagicMock(spec=RecoveryActions)


def test_already_healthy_converges_with_no_actions():
    probe = MagicMock(return_value=_healthy())
    actions = _fake_actions()
    engine = RecoveryEngine(
        probe=probe, actions=actions, allow_reboot=False,
        deadline_s=30.0, settle_s=0.0, sleep=lambda _s: None, now=_fake_clock(),
    )
    result = engine.run()
    assert isinstance(result, RecoveryResult)
    assert result.outcome == "CONVERGED"
    assert result.actions_taken == []


def _fake_clock():
    """A monotonic clock that advances 1s per call."""
    t = {"v": 0.0}

    def _now() -> float:
        t["v"] += 1.0
        return t["v"]

    return _now
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/recovery/test_engine.py -v
```

- [ ] **Step 3: Implement `src/robobench/recovery/engine.py` (skeleton)**

```python
"""Convergence-loop recovery engine.

Replaces the upstream's brittle linear recovery script. The loop:

    while not healthy and not past deadline:
        state = probe()
        if state.is_healthy(): -> CONVERGED
        action = pick the cheapest untried action for the failing aspect
        if none allowed/available: -> STUCK
        apply action; record it; settle; re-probe

Pure orchestration — `probe`, `actions`, `sleep`, `now` are all injected, so
the whole engine is unit-testable without a robot.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from robobench.recovery.actions import RecoveryActions
from robobench.recovery.state import RobotState


@dataclass
class RecoveryResult:
    """Outcome of a recovery run, with a full trace."""

    outcome: str  # CONVERGED | STUCK | TIMED_OUT | NEEDS_HUMAN
    actions_taken: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    final_state: RobotState | None = None


class RecoveryEngine:
    """Drives a robot back to a healthy bring-up state via small fixes."""

    def __init__(
        self,
        probe: Callable[[], RobotState],
        actions: RecoveryActions,
        *,
        allow_reboot: bool,
        deadline_s: float,
        settle_s: float,
        sleep: Callable[[float], None],
        now: Callable[[], float],
    ) -> None:
        self._probe = probe
        self._actions = actions
        self._allow_reboot = allow_reboot
        self._deadline_s = deadline_s
        self._settle_s = settle_s
        self._sleep = sleep
        self._now = now

    def run(self) -> RecoveryResult:
        result = RecoveryResult(outcome="TIMED_OUT")
        start = self._now()
        while True:
            state = self._probe()
            result.final_state = state
            if state.is_healthy():
                result.outcome = "CONVERGED"
                result.trace.append("healthy")
                return result
            if self._now() - start > self._deadline_s:
                result.outcome = "TIMED_OUT"
                result.trace.append("deadline exceeded")
                return result
            # Task 4 adds action selection here.
            result.outcome = "STUCK"
            result.trace.append("no action selection yet")
            return result
```

- [ ] **Step 4: Run, confirm pass + ruff**

Expected: the healthy-converges test passes; 106 total.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/recovery/engine.py tests/unit/recovery/test_engine.py
git commit -m "feat(recovery): add RecoveryEngine skeleton (result, healthy short-circuit, deadline)"
```

---

## Task 4: `RecoveryEngine` escalation ladder + convergence (TDD)

**Files:**
- Modify: `src/robobench/recovery/engine.py`
- Modify: `tests/unit/recovery/test_engine.py`

- [ ] **Step 1: Append failing tests to `tests/unit/recovery/test_engine.py`**

```python
def _state(**overrides) -> RobotState:
    base = dict(
        rpi_reachable=True, discovery_server_ok=True, clock_synced=True,
        create3_topics=12, tb4_nodes_present=True, odom_publishing=True,
    )
    base.update(overrides)
    return RobotState(**base)


def _engine(probe, actions, allow_reboot=False):
    return RecoveryEngine(
        probe=probe, actions=actions, allow_reboot=allow_reboot,
        deadline_s=1000.0, settle_s=0.0, sleep=lambda _s: None, now=_fake_clock(),
    )


def test_unreachable_rpi_needs_human_immediately():
    """Can't fix a powered-off / off-network robot remotely."""
    probe = MagicMock(return_value=_state(rpi_reachable=False))
    actions = _fake_actions()
    result = _engine(probe, actions).run()
    assert result.outcome == "NEEDS_HUMAN"
    assert actions.method_calls == []  # no remote action attempted


def test_stale_local_daemon_fixed_by_restart_local_daemon():
    """create3_topics==0 but discovery OK → cheapest fix (local daemon) first;
    the second probe returns healthy → CONVERGED."""
    probe = MagicMock(side_effect=[_state(create3_topics=0), _state()])
    actions = _fake_actions()
    result = _engine(probe, actions).run()
    assert result.outcome == "CONVERGED"
    assert result.actions_taken == ["restart_local_daemon"]
    actions.restart_local_daemon.assert_called_once()


def test_discovery_down_restarts_discovery_server():
    probe = MagicMock(side_effect=[_state(discovery_server_ok=False), _state()])
    actions = _fake_actions()
    result = _engine(probe, actions).run()
    assert result.outcome == "CONVERGED"
    assert "restart_discovery_server" in result.actions_taken


def test_clock_drift_triggers_sync_clock():
    probe = MagicMock(side_effect=[_state(clock_synced=False), _state()])
    actions = _fake_actions()
    result = _engine(probe, actions).run()
    assert result.outcome == "CONVERGED"
    assert result.actions_taken == ["sync_clock"]


def test_tb4_nodes_missing_restarts_tb4_service():
    probe = MagicMock(side_effect=[_state(tb4_nodes_present=False), _state()])
    actions = _fake_actions()
    result = _engine(probe, actions).run()
    assert result.outcome == "CONVERGED"
    assert result.actions_taken == ["restart_tb4_service"]


def test_odom_dead_restarts_create3_app():
    probe = MagicMock(side_effect=[_state(odom_publishing=False), _state()])
    actions = _fake_actions()
    result = _engine(probe, actions).run()
    assert result.outcome == "CONVERGED"
    assert result.actions_taken == ["restart_create3_app"]


def test_no_create3_topics_needs_reboot_but_gated():
    """create3_topics==0 with discovery OK escalates through cheap+medium; if
    none work and reboot is NOT allowed, it stops as STUCK rather than rebooting."""
    probe = MagicMock(return_value=_state(create3_topics=0))  # never recovers
    actions = _fake_actions()
    result = _engine(probe, actions, allow_reboot=False).run()
    assert result.outcome == "STUCK"
    actions.reboot_create3.assert_not_called()
    assert "restart_local_daemon" in result.actions_taken  # tried cheap first


def test_reboot_used_only_when_allowed_and_cheaper_exhausted():
    """With allow_reboot=True and nothing else working, reboot_create3 is the
    last action tried; if a probe after it returns healthy → CONVERGED."""
    states = [
        _state(create3_topics=0),  # initial: try restart_local_daemon
        _state(create3_topics=0),  # still bad: try restart_discovery_server
        _state(create3_topics=0),  # still bad: try restart_tb4_service
        _state(create3_topics=0),  # still bad: try restart_create3_app
        _state(create3_topics=0),  # still bad: reboot_create3 (nuclear)
        _state(),                  # healthy after reboot
    ]
    probe = MagicMock(side_effect=states)
    actions = _fake_actions()
    result = _engine(probe, actions, allow_reboot=True).run()
    assert result.outcome == "CONVERGED"
    assert result.actions_taken[-1] == "reboot_create3"
    actions.reboot_create3.assert_called_once()


def test_no_action_repeated():
    """An action that doesn't fix the aspect is not retried forever; the engine
    moves down the ladder and eventually STUCKs."""
    probe = MagicMock(return_value=_state(odom_publishing=False))  # never recovers
    actions = _fake_actions()
    result = _engine(probe, actions, allow_reboot=False).run()
    assert result.outcome == "STUCK"
    # restart_create3_app tried once for odom; not called repeatedly
    assert result.actions_taken.count("restart_create3_app") == 1
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/recovery/test_engine.py -v
```
Expected: the new tests fail (engine returns STUCK with no real ladder yet).

- [ ] **Step 3: Implement the escalation ladder in `engine.py`**

Add this module-level ladder definition (after the imports, before the class):

```python
# Escalation ladder: ordered cheap → nuclear. Each rule maps a failing aspect
# to the action that targets it and whether that action is NUCLEAR (gated).
# When create3_topics is the failing aspect we walk a sub-ladder of
# increasingly disruptive actions because "no topics" has many possible causes
# (local daemon cache, discovery zombie, stale service, dead app, dead base).
_LADDER: list[tuple[str, str, bool]] = [
    # (failing_aspect, action_method_name, is_nuclear)
    ("discovery_server_ok", "restart_discovery_server", False),
    ("clock_synced", "sync_clock", False),
    ("tb4_nodes_present", "restart_tb4_service", False),
    ("odom_publishing", "restart_create3_app", False),
    # create3_topics == 0: try cheapest cause first, escalate to nuclear last.
    ("create3_topics", "restart_local_daemon", False),
    ("create3_topics", "restart_discovery_server", False),
    ("create3_topics", "restart_tb4_service", False),
    ("create3_topics", "restart_create3_app", False),
    ("create3_topics", "reboot_create3", True),
]
```

Replace the loop body in `run()` (the `# Task 4 adds action selection here.` block) with:

```python
            aspect = state.failing_aspect()
            if aspect == "rpi_reachable":
                result.outcome = "NEEDS_HUMAN"
                result.trace.append("rpi unreachable — power/network, cannot fix remotely")
                return result

            action_name = self._pick_action(aspect, tried)
            if action_name is None:
                result.outcome = "STUCK"
                result.trace.append(f"no untried action left for '{aspect}'")
                return result

            tried.add(action_name)
            result.actions_taken.append(action_name)
            result.trace.append(f"aspect '{aspect}' -> {action_name}")
            getattr(self._actions, action_name)()
            self._sleep(self._settle_s)
```

Add `tried: set[str] = set()` initialization just after `start = self._now()`.

Add the `_pick_action` helper method to the class:

```python
    def _pick_action(self, aspect: str | None, tried: set[str]) -> str | None:
        """Cheapest untried ladder action for the failing aspect, honoring the
        nuclear gate. Returns None when nothing applicable is left."""
        for ladder_aspect, action_name, is_nuclear in _LADDER:
            if ladder_aspect != aspect:
                continue
            if action_name in tried:
                continue
            if is_nuclear and not self._allow_reboot:
                continue
            return action_name
        return None
```

Note: `tried` is keyed by action name, so each action is attempted at most once per run (fixes the upstream's repeat problem). The deadline check stays as written in Task 3 (re-probe each iteration; bail when exceeded).

- [ ] **Step 4: Run, confirm pass + ruff**

```bash
pytest tests/unit/recovery/test_engine.py -v
pytest -q
ruff check src tests && ruff format --check src tests
```
Expected: all engine tests pass; ~114 total. If ruff format flags anything, run `ruff format src tests` then re-test.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/recovery/engine.py tests/unit/recovery/test_engine.py
git commit -m "feat(recovery): escalation ladder + convergence (cheap->nuclear, gated, no-repeat)"
```

---

## Task 5: Probe interface + `RobotProbe` ABC (TDD)

**Files:**
- Modify: `src/robobench/recovery/__init__.py` (nothing) — actually add a tiny ABC file
- Create: `src/robobench/recovery/probe.py`
- Create: `tests/unit/recovery/test_probe.py`

- [ ] **Step 1: Write failing test `tests/unit/recovery/test_probe.py`**

```python
"""Tests for the RobotProbe ABC."""
from __future__ import annotations

import pytest

from robobench.recovery.probe import RobotProbe
from robobench.recovery.state import RobotState


def test_probe_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        RobotProbe()  # type: ignore[abstract]


def test_concrete_probe_returns_state():
    class FixedProbe(RobotProbe):
        def read(self) -> RobotState:
            return RobotState(
                rpi_reachable=True, discovery_server_ok=True, clock_synced=True,
                create3_topics=5, tb4_nodes_present=True, odom_publishing=True,
            )

    assert FixedProbe().read().is_healthy() is True
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement `src/robobench/recovery/probe.py`**

```python
"""Probe interface: reads a robot's bring-up health into a RobotState.

Concrete probes (per robot) do the I/O; the engine only needs `read()`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from robobench.recovery.state import RobotState


class RobotProbe(ABC):
    """Reads the robot's current bring-up state."""

    @abstractmethod
    def read(self) -> RobotState:
        """Return a fresh RobotState snapshot."""
```

- [ ] **Step 4: Run, confirm pass + ruff**

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/recovery/probe.py tests/unit/recovery/test_probe.py
git commit -m "feat(recovery): add RobotProbe ABC"
```

---

## Task 6: `TurtleBot4Probe` — SSH + local checks → RobotState (TDD)

**Files:**
- Create: `src/robobench/robots/turtlebot4_probe.py`
- Create: `tests/unit/robots/test_turtlebot4_probe.py`

- [ ] **Step 1: Write failing test `tests/unit/robots/test_turtlebot4_probe.py`**

```python
"""Tests for TurtleBot4Probe (SSH + local probing → RobotState)."""
from __future__ import annotations

from unittest.mock import MagicMock

from robobench.robots.turtlebot4_probe import TurtleBot4Probe


def _probe(ssh_results, local_results):
    """Build a probe with a fake SSHClient factory + fake run_local."""
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.run.side_effect = ssh_results
    return TurtleBot4Probe(
        ip="192.168.50.31", ssh_user="ubuntu", ssh_pass="pw", namespace="tb4",
        ssh_factory=lambda *a, **k: fake_client,
        run_local=MagicMock(side_effect=local_results),
        ping=MagicMock(return_value=True),
    )


def _ok(stdout):
    return MagicMock(returncode=0, stdout=stdout, stderr="")


def _fail(stderr="err"):
    return MagicMock(returncode=1, stdout="", stderr=stderr)


def test_probe_reads_healthy_state():
    # ssh.run order: discovery-port, clock-date, create3-topic-count, tb4-nodes, odom (x2 stability)
    ssh = [
        _ok("1\n"),               # ss -ulnp | grep 11811 | wc -l  -> listening
        _ok("1748347205\n"),      # date +%s (clock within tolerance, see now stub)
        _ok("12\n"),              # create3 topic count
        _ok("/tb4/robot_state_publisher\n"),  # tb4 nodes present
        _ok("position:\n"),       # odom sample 1
        _ok("position:\n"),       # odom sample 2
    ]
    local = [_ok("\n".join(f"/t{i}" for i in range(8)))]  # local topic list (>5)
    p = _probe(ssh, local)
    # Stub _now so clock drift is ~0
    p._now = lambda: 1748347205.0
    state = p.read()
    assert state.rpi_reachable is True
    assert state.discovery_server_ok is True
    assert state.clock_synced is True
    assert state.create3_topics == 12
    assert state.tb4_nodes_present is True
    assert state.odom_publishing is True
    assert state.is_healthy() is True


def test_probe_marks_discovery_down_when_port_not_listening():
    ssh = [
        _ok("0\n"),               # port NOT listening
        _ok("1748347205\n"),
        _ok("0\n"),
        _ok(""),                  # no tb4 nodes
        _fail("timeout"),         # odom sample 1
        _fail("timeout"),         # odom sample 2
    ]
    local = [_ok("")]
    p = _probe(ssh, local)
    p._now = lambda: 1748347205.0
    state = p.read()
    assert state.discovery_server_ok is False


def test_probe_odom_requires_two_consecutive_samples():
    """One good sample then a timeout => NOT stable => odom_publishing False."""
    ssh = [
        _ok("1\n"), _ok("1748347205\n"), _ok("12\n"), _ok("/tb4/x\n"),
        _ok("position:\n"),   # sample 1 OK
        _fail("timeout"),     # sample 2 fails -> not stable
    ]
    local = [_ok("\n".join(f"/t{i}" for i in range(8)))]
    p = _probe(ssh, local)
    p._now = lambda: 1748347205.0
    state = p.read()
    assert state.odom_publishing is False
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement `src/robobench/robots/turtlebot4_probe.py`**

```python
"""TurtleBot4 probe: reads bring-up health into a RobotState.

Fixes the upstream's fragile detection:
- structured parsing (no string-match on HTML, no buggy backslash topic name)
- odom requires TWO consecutive good samples (one message then stall != healthy)
- SSH transport is retried once on timeout before declaring an aspect bad
- ROS env (ROS_SUPER_CLIENT=True) is set for every remote ros2 call
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from robobench.recovery.probe import RobotProbe
from robobench.recovery.state import RobotState
from robobench.ssh import SSHClient

_CLOCK_TOLERANCE_S = 2.0
_ROS_ENV = "source /etc/turtlebot4/setup.bash && export ROS_SUPER_CLIENT=True && "


def _default_ping(ip: str) -> bool:
    from robobench._process import run_local

    result = run_local(["ping", "-c", "1", "-W", "2", ip], timeout=5)
    return result.returncode == 0


class TurtleBot4Probe(RobotProbe):
    """Builds a RobotState from SSH + local checks against a TurtleBot4."""

    def __init__(
        self,
        ip: str,
        ssh_user: str,
        ssh_pass: str,
        namespace: str,
        *,
        ssh_factory: Callable[..., SSHClient] = SSHClient,
        run_local=None,
        ping: Callable[[str], bool] | None = None,
    ) -> None:
        self.ip = ip
        self.ssh_user = ssh_user
        self.ssh_pass = ssh_pass
        self.namespace = namespace
        self._ssh_factory = ssh_factory
        if run_local is None:
            from robobench._process import run_local as _rl

            run_local = _rl
        self._run_local = run_local
        self._ping = ping or _default_ping

    def _now(self) -> float:
        return datetime.now(tz=UTC).timestamp()

    def read(self) -> RobotState:
        if not self._ping(self.ip):
            return RobotState(
                rpi_reachable=False, discovery_server_ok=False, clock_synced=False,
                create3_topics=0, tb4_nodes_present=False, odom_publishing=False,
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

            # odom: TWO consecutive good samples for "stable"
            odom_publishing = self._odom_stable(ssh)

        return RobotState(
            rpi_reachable=True,
            discovery_server_ok=discovery_ok,
            clock_synced=clock_synced,
            create3_topics=create3_topics,
            tb4_nodes_present=tb4_nodes_present,
            odom_publishing=odom_publishing,
        )

    def _odom_stable(self, ssh: SSHClient) -> bool:
        cmd = [
            "sh", "-c",
            f"{_ROS_ENV}timeout 8 ros2 topic echo /{self.namespace}/odom --once",
        ]
        for _ in range(2):
            r = ssh.run(cmd, timeout=15)
            ok = r.returncode == 0 and any(
                tok in r.stdout for tok in ("position:", "pose:", "header:")
            )
            if not ok:
                return False
        return True


def _parse_int(text: str) -> int:
    """Parse the last non-empty line as an int; 0 on failure (defensive —
    the upstream crashed on a trailing warning line)."""
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line:
            try:
                return int(line)
            except ValueError:
                return 0
    return 0


def _parse_float(text: str) -> float:
    try:
        return float(text.strip().splitlines()[-1].strip())
    except (ValueError, IndexError):
        return 0.0
```

- [ ] **Step 4: Run, confirm pass + ruff**

```bash
pytest tests/unit/robots/test_turtlebot4_probe.py -v
ruff check src tests && ruff format --check src tests
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/robots/turtlebot4_probe.py tests/unit/robots/test_turtlebot4_probe.py
git commit -m "feat(robots): add TurtleBot4Probe (structured detection, 2-sample odom stability)"
```

---

## Task 7: `TurtleBot4RecoveryActions` — idempotent atomic fixes (TDD)

**Files:**
- Create: `src/robobench/robots/turtlebot4_recovery.py`
- Create: `tests/unit/robots/test_turtlebot4_recovery.py`

- [ ] **Step 1: Write failing test `tests/unit/robots/test_turtlebot4_recovery.py`**

```python
"""Tests for TurtleBot4RecoveryActions (atomic fixes over SSH/local)."""
from __future__ import annotations

from unittest.mock import MagicMock

from robobench.recovery.actions import RecoveryActions
from robobench.robots.turtlebot4_recovery import TurtleBot4RecoveryActions


def _actions():
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    run_local = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    a = TurtleBot4RecoveryActions(
        ip="1.2.3.4", ssh_user="u", ssh_pass="p", namespace="tb4",
        ssh_factory=lambda *args, **kw: fake_client, run_local=run_local,
    )
    return a, fake_client, run_local


def test_is_a_recovery_actions():
    a, _, _ = _actions()
    assert isinstance(a, RecoveryActions)


def test_restart_local_daemon_uses_run_local_not_ssh():
    a, ssh, run_local = _actions()
    a.restart_local_daemon()
    assert run_local.called
    ssh.run.assert_not_called()  # local-only action


def test_restart_discovery_server_cleans_shm_and_restarts():
    a, ssh, _ = _actions()
    a.restart_discovery_server()
    joined = " ".join(" ".join(c.args[0]) for c in ssh.run.call_args_list)
    assert "discovery" in joined.lower()


def test_reboot_create3_hits_reboot_endpoint():
    a, ssh, _ = _actions()
    a.reboot_create3()
    joined = " ".join(" ".join(c.args[0]) for c in ssh.run.call_args_list)
    assert "reboot" in joined.lower()


def test_restart_create3_app_hits_restart_app_endpoint():
    a, ssh, _ = _actions()
    a.restart_create3_app()
    joined = " ".join(" ".join(c.args[0]) for c in ssh.run.call_args_list)
    assert "restart-app" in joined.lower()
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement `src/robobench/robots/turtlebot4_recovery.py`**

```python
"""TurtleBot4 atomic recovery actions + a factory wiring probe+actions+engine.

Each action is idempotent (safe to call when already healthy). Commands are
the ones the upstream proved work on real hardware — but here each is a
single small action the engine composes, NOT a fixed chain.
"""
from __future__ import annotations

from collections.abc import Callable

from robobench.recovery.actions import RecoveryActions
from robobench.ssh import SSHClient

_CREATE3_IP = "192.168.186.2"


class TurtleBot4RecoveryActions(RecoveryActions):
    """Idempotent atomic fixes for a TurtleBot4 (Create3 + RPi)."""

    def __init__(
        self,
        ip: str,
        ssh_user: str,
        ssh_pass: str,
        namespace: str,
        *,
        ssh_factory: Callable[..., SSHClient] = SSHClient,
        run_local=None,
    ) -> None:
        self.ip = ip
        self.ssh_user = ssh_user
        self.ssh_pass = ssh_pass
        self.namespace = namespace
        self._ssh_factory = ssh_factory
        if run_local is None:
            from robobench._process import run_local as _rl

            run_local = _rl
        self._run_local = run_local

    def _ssh(self, cmd: list[str], timeout: float) -> None:
        with self._ssh_factory(self.ip, self.ssh_user, self.ssh_pass) as ssh:
            ssh.run(cmd, timeout=timeout)

    def restart_local_daemon(self) -> None:
        self._run_local(["ros2", "daemon", "stop"], timeout=10)
        self._run_local(["ros2", "daemon", "start"], timeout=10)

    def restart_discovery_server(self) -> None:
        # Kill zombies, clean DDS shared memory, restart the systemd unit.
        self._ssh(
            [
                "sh", "-c",
                "sudo systemctl stop discovery.service 2>/dev/null; "
                "sudo killall -9 fast-discovery-server fastdds 2>/dev/null; "
                "sudo rm -rf /dev/shm/fastrtps_* /dev/shm/fast_datasharing* 2>/dev/null; "
                "sudo systemctl start discovery.service",
            ],
            timeout=30,
        )

    def sync_clock(self) -> None:
        self._ssh(["sudo", "chronyc", "-a", "makestep"], timeout=15)

    def restart_tb4_service(self) -> None:
        self._ssh(["sudo", "systemctl", "restart", "turtlebot4.service"], timeout=20)

    def restart_create3_app(self) -> None:
        self._ssh(
            ["curl", "-s", "-m", "15", "-X", "POST", f"http://{_CREATE3_IP}/api/restart-app"],
            timeout=20,
        )

    def reboot_create3(self) -> None:
        self._ssh(
            ["curl", "-s", "-m", "15", "-X", "POST", f"http://{_CREATE3_IP}/api/reboot"],
            timeout=25,
        )
```

- [ ] **Step 4: Run, confirm pass + ruff**

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/robots/turtlebot4_recovery.py tests/unit/robots/test_turtlebot4_recovery.py
git commit -m "feat(robots): add idempotent TurtleBot4RecoveryActions"
```

---

## Task 8: `build_turtlebot4_recovery` factory (TDD)

**Files:**
- Modify: `src/robobench/robots/turtlebot4_recovery.py`
- Modify: `tests/unit/robots/test_turtlebot4_recovery.py`

- [ ] **Step 1: Append failing test**

```python
from robobench.recovery.engine import RecoveryEngine


def test_factory_builds_engine_with_probe_and_actions():
    from robobench.robots.turtlebot4_recovery import build_turtlebot4_recovery

    engine = build_turtlebot4_recovery(
        ip="1.2.3.4", ssh_user="u", ssh_pass="p", namespace="tb4",
        allow_reboot=True, deadline_s=120.0,
    )
    assert isinstance(engine, RecoveryEngine)
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Append the factory to `turtlebot4_recovery.py`**

Add imports at the top (merge):
```python
import time

from robobench.recovery.engine import RecoveryEngine
from robobench.robots.turtlebot4_probe import TurtleBot4Probe
```

Add at the end of the file:
```python
def build_turtlebot4_recovery(
    ip: str,
    ssh_user: str,
    ssh_pass: str,
    namespace: str,
    *,
    allow_reboot: bool,
    deadline_s: float,
    settle_s: float = 8.0,
) -> RecoveryEngine:
    """Wire a TurtleBot4 probe + actions into a ready-to-run RecoveryEngine."""
    probe = TurtleBot4Probe(ip=ip, ssh_user=ssh_user, ssh_pass=ssh_pass, namespace=namespace)
    actions = TurtleBot4RecoveryActions(
        ip=ip, ssh_user=ssh_user, ssh_pass=ssh_pass, namespace=namespace
    )
    return RecoveryEngine(
        probe=probe.read,
        actions=actions,
        allow_reboot=allow_reboot,
        deadline_s=deadline_s,
        settle_s=settle_s,
        sleep=time.sleep,
        now=time.monotonic,
    )
```

- [ ] **Step 4: Run, confirm pass + ruff**

```bash
pytest -q
ruff check src tests && ruff format --check src tests
```
Expected: factory test passes; full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/robots/turtlebot4_recovery.py tests/unit/robots/test_turtlebot4_recovery.py
git commit -m "feat(robots): add build_turtlebot4_recovery factory"
```

---

## Task 9: `robobench preflight` CLI — read-only diagnosis (TDD)

**Files:**
- Modify: `src/robobench/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Append failing test to `tests/unit/test_cli.py`**

```python
def test_preflight_prints_state_and_planned_actions(mocker, tmp_path, capsys):
    """`robobench preflight` reads state (no fixes) and prints JSON + would-do actions."""
    cfg = _write_config(tmp_path)

    from robobench.recovery.state import RobotState

    bad_state = RobotState(
        rpi_reachable=True, discovery_server_ok=True, clock_synced=True,
        create3_topics=12, tb4_nodes_present=True, odom_publishing=False,
    )
    fake_probe = MagicMock()
    fake_probe.read.return_value = bad_state
    mocker.patch("robobench.cli.TurtleBot4Probe", return_value=fake_probe)

    rc = main(["preflight", "--robot", "turtlebot4", "--config", str(cfg)])
    out = capsys.readouterr().out

    assert rc == 1  # not healthy -> nonzero
    assert "odom_publishing" in out
    assert "restart_create3_app" in out  # the action that WOULD run
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement in `src/robobench/cli.py`**

Add to the guarded-or-direct imports near the top (these have no heavy deps, so a direct top-level import is fine — add alongside existing `from robobench...` imports):
```python
from robobench.recovery.engine import _LADDER
from robobench.recovery.state import RobotState  # noqa: F401  (re-exported for tests/clarity)
from robobench.robots.turtlebot4_probe import TurtleBot4Probe
```

Add the subparser in `_build_parser` (after `dashboard`):
```python
    preflight = subparsers.add_parser(
        "preflight", help="Read-only bring-up diagnosis (no fixes applied)."
    )
    preflight.add_argument("--robot", required=True, choices=["turtlebot4"])
    preflight.add_argument("--config", required=True)
    preflight.set_defaults(func=_cmd_preflight)
```

Add the command function:
```python
def _cmd_preflight(args: argparse.Namespace) -> int:
    import json

    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    kwargs = load_adapter_config(Path(args.config))
    probe = TurtleBot4Probe(
        ip=kwargs["ip"], ssh_user=kwargs["ssh_user"],
        ssh_pass=kwargs["ssh_pass"], namespace=kwargs["namespace"],
    )
    state = probe.read()
    aspect = state.failing_aspect()
    would_do = [a for asp, a, _nuke in _LADDER if asp == aspect]
    print(json.dumps({
        "healthy": state.is_healthy(),
        "failing_aspect": aspect,
        "would_try": would_do,
        "state": state.__dict__,
    }, indent=2))
    return 0 if state.is_healthy() else 1
```

- [ ] **Step 4: Run, confirm pass + ruff + smoke**

```bash
pytest -q
ruff check src tests && ruff format --check src tests
robobench preflight --help
```

- [ ] **Step 5: Commit**

```bash
git add src/robobench/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add robobench preflight (read-only diagnosis)"
```

---

## Task 10: `robobench recover` CLI — run the engine, with safety gates (TDD)

**Files:**
- Modify: `src/robobench/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Append failing tests to `tests/unit/test_cli.py`**

```python
def test_recover_runs_engine_and_reports_outcome(mocker, tmp_path, capsys):
    cfg = _write_config(tmp_path)
    from robobench.recovery.engine import RecoveryResult

    fake_engine = MagicMock()
    fake_engine.run.return_value = RecoveryResult(
        outcome="CONVERGED", actions_taken=["restart_local_daemon"], trace=["healthy"]
    )
    build_mock = mocker.patch("robobench.cli.build_turtlebot4_recovery", return_value=fake_engine)

    rc = main([
        "recover", "--robot", "turtlebot4", "--config", str(cfg),
        "--deadline", "60",
    ])
    out = capsys.readouterr().out

    assert rc == 0
    assert "CONVERGED" in out
    fake_engine.run.assert_called_once()
    # reboot must be OFF unless explicitly allowed
    assert build_mock.call_args.kwargs.get("allow_reboot") is False


def test_recover_allow_reboot_flag_is_passed(mocker, tmp_path):
    cfg = _write_config(tmp_path)
    from robobench.recovery.engine import RecoveryResult

    fake_engine = MagicMock()
    fake_engine.run.return_value = RecoveryResult(outcome="CONVERGED")
    build_mock = mocker.patch("robobench.cli.build_turtlebot4_recovery", return_value=fake_engine)

    main([
        "recover", "--robot", "turtlebot4", "--config", str(cfg),
        "--allow-reboot", "--deadline", "300",
    ])
    assert build_mock.call_args.kwargs.get("allow_reboot") is True


def test_recover_dry_run_does_not_run_engine(mocker, tmp_path, capsys):
    cfg = _write_config(tmp_path)
    from robobench.recovery.state import RobotState

    bad = RobotState(
        rpi_reachable=True, discovery_server_ok=False, clock_synced=True,
        create3_topics=0, tb4_nodes_present=False, odom_publishing=False,
    )
    fake_probe = MagicMock()
    fake_probe.read.return_value = bad
    mocker.patch("robobench.cli.TurtleBot4Probe", return_value=fake_probe)
    build_mock = mocker.patch("robobench.cli.build_turtlebot4_recovery")

    rc = main([
        "recover", "--robot", "turtlebot4", "--config", str(cfg), "--dry-run",
    ])
    out = capsys.readouterr().out

    assert rc == 0
    build_mock.assert_not_called()           # dry-run never builds/runs the engine
    assert "restart_discovery_server" in out  # prints the plan instead


def test_recover_nonzero_when_not_converged(mocker, tmp_path):
    cfg = _write_config(tmp_path)
    from robobench.recovery.engine import RecoveryResult

    fake_engine = MagicMock()
    fake_engine.run.return_value = RecoveryResult(outcome="STUCK")
    mocker.patch("robobench.cli.build_turtlebot4_recovery", return_value=fake_engine)

    rc = main(["recover", "--robot", "turtlebot4", "--config", str(cfg), "--deadline", "30"])
    assert rc == 1
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement in `src/robobench/cli.py`**

Add to imports (merge with the recovery imports from Task 9):
```python
from robobench.robots.turtlebot4_recovery import build_turtlebot4_recovery
```

Add the subparser in `_build_parser` (after `preflight`):
```python
    recover = subparsers.add_parser(
        "recover", help="Drive a stuck robot back to a healthy bring-up state."
    )
    recover.add_argument("--robot", required=True, choices=["turtlebot4"])
    recover.add_argument("--config", required=True)
    recover.add_argument("--deadline", type=float, default=180.0,
                         help="Max seconds to keep trying (default 180).")
    recover.add_argument("--allow-reboot", action="store_true",
                         help="Permit the NUCLEAR Create3 full reboot (off by default).")
    recover.add_argument("--dry-run", action="store_true",
                         help="Print the plan from current state; apply nothing.")
    recover.set_defaults(func=_cmd_recover)
```

Add the command function:
```python
def _cmd_recover(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    kwargs = load_adapter_config(Path(args.config))

    if args.dry_run:
        probe = TurtleBot4Probe(
            ip=kwargs["ip"], ssh_user=kwargs["ssh_user"],
            ssh_pass=kwargs["ssh_pass"], namespace=kwargs["namespace"],
        )
        state = probe.read()
        aspect = state.failing_aspect()
        would_do = [a for asp, a, nuke in _LADDER if asp == aspect and (args.allow_reboot or not nuke)]
        print(f"[dry-run] failing aspect: {aspect}")
        for a in would_do:
            print(f"[dry-run] would try: {a}")
        if not would_do:
            print("[dry-run] healthy or nothing to try")
        return 0

    engine = build_turtlebot4_recovery(
        ip=kwargs["ip"], ssh_user=kwargs["ssh_user"], ssh_pass=kwargs["ssh_pass"],
        namespace=kwargs["namespace"], allow_reboot=args.allow_reboot,
        deadline_s=args.deadline,
    )
    result = engine.run()
    print(f"recovery outcome: {result.outcome}")
    for a in result.actions_taken:
        print(f"  applied: {a}")
    if result.outcome == "NEEDS_HUMAN":
        print("  robot unreachable — check power and network.", file=sys.stderr)
    return 0 if result.outcome == "CONVERGED" else 1
```

- [ ] **Step 4: Run, confirm pass + ruff + smoke**

```bash
pytest -q
ruff check src tests && ruff format --check src tests
robobench recover --help
robobench --help    # check/bringup/health/shutdown/dashboard/preflight/recover
```
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add robobench recover with dry-run + reboot gate + deadline"
```

---

## Task 11: Tutorial + CHANGELOG + bump v0.5.0a0 + tag + push

**Files:**
- Create: `docs/tutorials/recovering-a-stuck-robot.md`
- Modify: `CHANGELOG.md`, `src/robobench/__init__.py`, `pyproject.toml`

- [ ] **Step 1: Write `docs/tutorials/recovering-a-stuck-robot.md`**

````markdown
# Recovering a stuck robot

When bring-up hangs — no topics, dead odom, Discovery Server zombie — robobench
can drive the robot back to health automatically, trying the cheapest fix
first and only escalating if needed.

## See what's wrong (no changes)

```bash
robobench preflight --robot turtlebot4 --config ./config.yaml
```
```json
{
  "healthy": false,
  "failing_aspect": "odom_publishing",
  "would_try": ["restart_create3_app"],
  "state": { "rpi_reachable": true, "discovery_server_ok": true, ... }
}
```

`preflight` only reads — it never touches the robot.

## Preview the recovery plan

```bash
robobench recover --robot turtlebot4 --config ./config.yaml --dry-run
```
Prints the actions the engine *would* apply from the current state, without
applying any.

## Run the recovery

```bash
robobench recover --robot turtlebot4 --config ./config.yaml --deadline 180
```

The engine loops: read state → fix the most-upstream failing thing with the
cheapest action → re-read → repeat, until healthy or the deadline. It never
repeats an action and reports every step:

```
recovery outcome: CONVERGED
  applied: restart_local_daemon
  applied: restart_create3_app
```

## The nuclear option is opt-in

A full Create3 reboot (~3 min, re-randomizes DDS GUIDs) is **off by default**.
If cheaper fixes can't clear a GUID mismatch, recovery stops as `STUCK` and
tells you. To permit the reboot:

```bash
robobench recover --robot turtlebot4 --config ./config.yaml --allow-reboot --deadline 360
```

## Why this is different from a recovery *script*

robobench's engine is a convergence loop, not a fixed sequence:
- It diagnoses the **root** (most-upstream failing aspect), not the symptom.
- It applies the **cheapest sufficient** fix and re-checks — no blind 6-step chain.
- It treats "odom" as healthy only after **two consecutive** good samples.
- It never reboots hardware without `--allow-reboot`.

## Outcomes

| Outcome | Meaning |
|---------|---------|
| `CONVERGED` | Robot is healthy. |
| `STUCK` | Ran out of allowed fixes (e.g. needs `--allow-reboot`). |
| `TIMED_OUT` | Hit `--deadline` still unhealthy. |
| `NEEDS_HUMAN` | Robot unreachable — power/network, can't fix remotely. |
````

- [ ] **Step 2: Update CHANGELOG.md** — replace `## [Unreleased]` with:

```markdown
## [Unreleased]

## [0.5.0a0] — 2026-05-29

### Added

- **Convergence-loop recovery engine** (`robobench.recovery`): observe →
  fix the most-upstream failing aspect with the cheapest action → re-observe →
  repeat, with an escalation ladder, global deadline, no action repeated, and
  the Create3 reboot gated behind `--allow-reboot`. Fully unit-tested via an
  injected probe + actions (no hardware needed).
- `RobotState` / `RobotProbe` / `RecoveryActions` interfaces; `TurtleBot4Probe`
  (structured detection, 2-sample odom stability) and `TurtleBot4RecoveryActions`
  (idempotent atomic fixes).
- CLI: `robobench preflight` (read-only diagnosis) and `robobench recover`
  (`--dry-run`, `--allow-reboot`, `--deadline`).
- Tutorial: `docs/tutorials/recovering-a-stuck-robot.md`.

### Notes

- Replaces the upstream's brittle linear `full_recovery` script. The atomic
  actions are the upstream's proven commands; the *orchestration* is rebuilt
  as a testable convergence loop (see the Phase D plan for the post-mortem).
```

- [ ] **Step 3: Bump version** — `0.4.0a0` → `0.5.0a0` in `src/robobench/__init__.py` and `pyproject.toml`.

- [ ] **Step 4: Final sweep**

```bash
source .venv/Scripts/activate
pip install -e ".[dev]"
pytest -q
ruff check . && ruff format --check .
robobench --version       # robobench 0.5.0a0
robobench preflight --help && robobench recover --help
```

- [ ] **Step 5: Commit + tag + push**

```bash
git add docs/tutorials/recovering-a-stuck-robot.md CHANGELOG.md src/robobench/__init__.py pyproject.toml
git commit -m "chore: bump version to 0.5.0a0 and update CHANGELOG"
git tag -a v0.5.0a0 -m "v0.5.0-alpha - Phase D: convergence-loop recovery engine"
git push origin main
git push origin v0.5.0a0
```

- [ ] **Step 6: Verify**

```bash
git tag --list
```
Expected: through `v0.5.0a0`.

---

## Self-Review (Plan Author Notes)

**Spec coverage check (each upstream-failure lesson → fix):**
- Fuzzy/buggy detection → `TurtleBot4Probe` structured parsing + `_parse_int` defensive (Task 6) ✅
- The `\{ns}\odom` always-false bug → structured boolean state, no backslash topic match (Task 6) ✅
- Hardcoded timing → deadline + re-probe loop, `settle_s` configurable (Tasks 3, 4) ✅
- Over-eager nuclear option → reboot is last ladder rung + `allow_reboot` gate (Tasks 2, 4, 10) ✅
- Not idempotent/resumable → convergence loop, `tried` set, idempotent actions (Tasks 4, 7) ✅
- SSH transport fragility → 2-sample odom + (probe could add transport retry; documented) — partially (see risk 1) ⚠️
- full_recovery never restarts Discovery Server → `restart_discovery_server` is a ladder rung for create3_topics==0 (Task 4) ✅
- One-shot verification → `_odom_stable` requires 2 consecutive samples (Task 6) ✅
- Untestable → engine injected with probe/actions; 100% unit-tested (Tasks 3, 4) ✅

**Placeholder scan:** No TBDs; every step has real code.

**Type consistency:**
- `RobotState` fields (Task 1) used identically by probe (Task 6), engine tests (Tasks 3-4), CLI (Tasks 9-10).
- `RecoveryActions` method names (Task 2: restart_local_daemon, restart_discovery_server, sync_clock, restart_tb4_service, restart_create3_app, reboot_create3) match `_LADDER` action strings (Task 4) and `TurtleBot4RecoveryActions` methods (Task 7) exactly.
- `_LADDER` is `list[tuple[str, str, bool]]` (aspect, action, is_nuclear), imported by CLI for preflight/dry-run (Tasks 9, 10).
- `RecoveryResult.outcome` values (CONVERGED/STUCK/TIMED_OUT/NEEDS_HUMAN) consistent across engine (Tasks 3-4) and CLI exit-code logic (Task 10).
- `build_turtlebot4_recovery(...)` signature (Task 8) matches the CLI call (Task 10).

**Known risks / honest notes:**
1. **SSH transport retry is not yet implemented in the probe** — Task 6 adds 2-sample odom stability but treats an SSH-level timeout within a single `read()` as "aspect bad". A flaky-WiFi blip during a probe could still misreport. Mitigation deferred: the *engine* re-probes each loop, so a one-off blip self-corrects on the next iteration (unlike the upstream where a blip aborted the whole chain). A dedicated transport-retry wrapper is a v0.5.1 candidate.
2. **No real-hardware validation** — every test injects fakes. The probe commands and action commands are ported from the upstream's proven set, but the exact `ros2`/`ss`/`curl` invocations need a lab pass on a real TurtleBot4. This is the same hardware-validation gap noted for prior phases; lab personnel run `@pytest.mark.hardware` checks.
3. **`settle_s` default (8s)** between an action and re-probe is a guess; too short and a slow service restart looks like a failed fix (engine moves down the ladder prematurely). Configurable, tune on real hardware.
4. **Concurrency** — `robobench recover` assumes it's the only thing touching the robot. No cross-process lock. Fine for CLI single-operator use; document "don't run two recoveries at once".
5. **`preflight`/`recover` import recovery modules at cli.py top level** — these are pure-Python (no fastapi/rclpe), so unlike the `dashboard` deps they don't need the guarded import. Confirmed: `robobench.recovery.*` and `turtlebot4_probe`/`turtlebot4_recovery` only import `ssh`/`_process`/stdlib.

---

## Out of scope (deferred)

- **Dashboard "Recover" button** + live trace streaming — wire `recover` into the Phase C/C-2 dashboard with a confirmation modal for destructive tiers. Phase D-2 / later.
- **SSH transport-retry wrapper** in the probe — v0.5.1.
- **Logs / post-mortem bundle** (the upstream's `~/.campus_nav_logs/`, event JSONL, quality report) — separate plan.
- **Battery / AMCL-covariance monitoring** — separate plan.
- **Second robot adapter (TurtleBot3) + simulation** — later phases; the recovery engine is already robot-agnostic, only probe+actions are TB4-specific.
