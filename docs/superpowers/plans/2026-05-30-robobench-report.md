# `robobench report` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `robobench report`, which renders the flight-recorder `events_*.jsonl` session logs into a human-readable post-mortem (what was probed, which actions ran, the final outcome), closing the write-only-logs gap.

**Architecture:** A pure `eventreport.py` (find latest log / parse JSONL / format) plus a thin `_cmd_report` CLI command. Reuses `RobotState.failing_aspect()` for the per-probe diagnosis and `eventlog._DEFAULT_LOG_DIR` for the default location. No network/SSH/rclpy — fully unit-testable.

**Tech Stack:** Python 3.11+ (json, datetime), argparse, pytest, ruff. Tests/lint: `.venv/Scripts/python.exe -m pytest -q` / `.venv/Scripts/python.exe -m ruff check src tests`. Baseline: 219 passed, version 0.12.1a0. Output uses ASCII (`->`) to stay clean on Windows consoles.

Spec: `docs/superpowers/specs/2026-05-30-robobench-report-design.md`.

---

## File Structure

| File | Responsibility | Task |
|------|----------------|------|
| `src/robobench/eventreport.py` (new) | `latest_event_log` / `parse_events` / `format_report` (pure) | 1 |
| `src/robobench/cli.py` | `report` subparser + `_cmd_report` | 2 |
| README + `docs/tutorials/recovering-a-stuck-robot.md` + `CHANGELOG.md` + version | release v0.13.0a0 | 3 |

Input schema (`events_*.jsonl`, written by `robobench.eventlog.EventLogger`):
`{"ts": ISO8601, "session_id": str, "event": str, "data": dict}` — `event` is
`probe` (data = `RobotState` asdict), `action` (data = `{aspect, name}`),
`outcome` (data = `{outcome}`), or `preflight` (data = `RobotState` asdict).

---

## Task 1: `eventreport.py` — pure parse + format

**Files:**
- Create: `src/robobench/eventreport.py`
- Test: `tests/unit/test_eventreport.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_eventreport.py
from robobench.eventreport import format_report, latest_event_log, parse_events


def test_parse_events_skips_blank_and_malformed():
    text = (
        '{"event": "probe", "data": {}}\n'
        "\n"
        "not json\n"
        '{"event": "outcome", "data": {"outcome": "CONVERGED"}}\n'
    )
    records = parse_events(text)
    assert [r["event"] for r in records] == ["probe", "outcome"]


def test_latest_event_log_picks_newest_ignores_lifecycle(tmp_path):
    (tmp_path / "events_20260101_000000_a.jsonl").write_text("{}", encoding="utf-8")
    (tmp_path / "events_20260102_000000_b.jsonl").write_text("{}", encoding="utf-8")
    (tmp_path / "lifecycle_20260103_000000.jsonl").write_text("{}", encoding="utf-8")
    assert latest_event_log(tmp_path).name == "events_20260102_000000_b.jsonl"


def test_latest_event_log_none_when_empty(tmp_path):
    assert latest_event_log(tmp_path) is None


def _recover_records():
    healthy_but_discovery = {
        "rpi_reachable": True,
        "discovery_server_ok": False,
        "clock_synced": True,
        "create3_topics": 5,
        "tb4_nodes_present": True,
        "odom_publishing": True,
    }
    return [
        {"ts": "2026-05-31T02:55:53+00:00", "session_id": "6da3444c", "event": "probe",
         "data": healthy_but_discovery},
        {"ts": "2026-05-31T02:55:54+00:00", "session_id": "6da3444c", "event": "action",
         "data": {"aspect": "discovery_server_ok", "name": "restart_discovery_server"}},
        {"ts": "2026-05-31T02:56:34+00:00", "session_id": "6da3444c", "event": "outcome",
         "data": {"outcome": "CONVERGED"}},
    ]


def test_format_report_recover_session():
    out = format_report(_recover_records())
    assert "session 6da3444c" in out
    assert "failing: discovery_server_ok" in out
    assert "discovery_server_ok -> restart_discovery_server" in out
    assert "CONVERGED" in out
    assert "summary:" in out
    assert "1 action" in out


def test_format_report_preflight():
    out = format_report([
        {"ts": "2026-05-31T02:55:53+00:00", "session_id": "x", "event": "preflight",
         "data": {"rpi_reachable": False, "discovery_server_ok": False, "clock_synced": False,
                  "create3_topics": 0, "tb4_nodes_present": False, "odom_publishing": False}},
    ])
    assert "preflight" in out
    assert "rpi_reachable" in out


def test_format_report_no_recognized_events():
    assert format_report([{"ts": "t", "event": "init", "namespace": "tb"}]) == (
        "no recognizable recover/preflight events"
    )


def test_format_report_probe_bad_data_renders_unknown():
    out = format_report([{"ts": "t", "event": "probe", "data": {"wrong": "shape"}}])
    assert "unknown" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_eventreport.py -v`
Expected: FAIL (`No module named 'robobench.eventreport'`)

- [ ] **Step 3: Write the implementation**

```python
# src/robobench/eventreport.py
"""Read flight-recorder event logs back into a human-readable post-mortem.

The writer is robobench.eventlog (EventLogger); this is the reader. It parses
events_*.jsonl and renders what was probed, which actions ran, and the final
outcome. Pure (only reads files) — no network/SSH/rclpy.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from robobench.eventlog import _DEFAULT_LOG_DIR
from robobench.recovery.state import RobotState

_RECOGNIZED_EVENTS = ("probe", "action", "outcome", "preflight")


def latest_event_log(log_dir: Path | None = None) -> Path | None:
    """Most recent ``events_*.jsonl`` in ``log_dir`` (default ~/.robobench/logs).

    Ignores ``lifecycle_*.jsonl``. Filenames embed a sortable ``YYYYMMDD_HHMMSS``
    stamp, so a lexical sort is chronological. Returns None if the directory is
    absent or has no matching log.
    """
    directory = log_dir or _DEFAULT_LOG_DIR
    if not directory.exists():
        return None
    logs = sorted(directory.glob("events_*.jsonl"))
    return logs[-1] if logs else None


def parse_events(text: str) -> list[dict]:
    """Parse JSONL into a list of record dicts; skip blank/malformed lines."""
    records: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def _state_detail(data: dict) -> str:
    """'healthy' or 'unhealthy (failing: <aspect>)' from a RobotState dict."""
    try:
        aspect = RobotState(**data).failing_aspect()
    except (TypeError, ValueError):
        aspect = "unknown"
    return "healthy" if aspect is None else f"unhealthy (failing: {aspect})"


def _hhmmss(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return ts or "?"


def _duration_s(records: list[dict]) -> float | None:
    stamps = [r["ts"] for r in records if r.get("ts")]
    if len(stamps) < 2:
        return None
    try:
        return (datetime.fromisoformat(stamps[-1]) - datetime.fromisoformat(stamps[0])).total_seconds()
    except (ValueError, TypeError):
        return None


def format_report(records: list[dict]) -> str:
    """Render a human-readable post-mortem from event records."""
    recognized = [r for r in records if r.get("event") in _RECOGNIZED_EVENTS]
    if not recognized:
        return "no recognizable recover/preflight events"

    duration = _duration_s(recognized)
    session = next((r.get("session_id") for r in recognized if r.get("session_id")), "?")
    started = recognized[0].get("ts", "?")
    dur_str = f"   duration {duration:.1f}s" if duration is not None else ""

    lines = [f"session {session}   started {started}{dur_str}", ""]
    action_count = 0
    last_outcome: str | None = None
    preflight_detail: str | None = None
    for r in recognized:
        when = _hhmmss(r.get("ts", ""))
        data = r.get("data") or {}
        event = r.get("event")
        if event == "probe":
            lines.append(f"  {when}  probe      {_state_detail(data)}")
        elif event == "preflight":
            preflight_detail = _state_detail(data)
            lines.append(f"  {when}  preflight  {preflight_detail}")
        elif event == "action":
            action_count += 1
            lines.append(f"  {when}  action     {data.get('aspect', '?')} -> {data.get('name', '?')}")
        elif event == "outcome":
            last_outcome = data.get("outcome", "?")
            lines.append(f"  {when}  outcome    {last_outcome}")

    lines.append("")
    if last_outcome is not None:
        tail = f" in {duration:.1f}s" if duration is not None else ""
        lines.append(f"summary: {last_outcome} after {action_count} action(s){tail}")
    elif preflight_detail is not None:
        lines.append(f"summary: preflight - {preflight_detail}")
    else:
        lines.append(f"summary: {action_count} action(s), no outcome recorded")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_eventreport.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/robobench/eventreport.py tests/unit/test_eventreport.py
git commit -m "feat: eventreport — parse + format flight-recorder logs"
```

---

## Task 2: `robobench report` CLI subcommand

**Files:**
- Modify: `src/robobench/cli.py` (top import, `report` subparser, `_cmd_report`)
- Test: `tests/unit/test_cli.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_cli.py  (append)
_EVENTS_LOG = (
    '{"ts":"2026-05-31T02:55:53+00:00","session_id":"x","event":"probe",'
    '"data":{"rpi_reachable":true,"discovery_server_ok":false,"clock_synced":true,'
    '"create3_topics":5,"tb4_nodes_present":true,"odom_publishing":true}}\n'
    '{"ts":"2026-05-31T02:56:00+00:00","session_id":"x","event":"outcome",'
    '"data":{"outcome":"CONVERGED"}}\n'
)


def test_report_renders_given_log(tmp_path, capsys):
    log = tmp_path / "events_20260101_000000_x.jsonl"
    log.write_text(_EVENTS_LOG, encoding="utf-8")
    rc = main(["report", str(log)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "log:" in out
    assert "CONVERGED" in out


def test_report_missing_path_exit_1(capsys):
    rc = main(["report", "C:/no/such/robobench-log.jsonl"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_report_unrecognized_schema_exit_2(tmp_path, capsys):
    log = tmp_path / "lifecycle_x.jsonl"
    log.write_text('{"ts":"t","event":"init","namespace":"tb"}\n', encoding="utf-8")
    rc = main(["report", str(log)])
    assert rc == 2
    assert "no recognizable" in capsys.readouterr().err


def test_report_no_logs_default_exit_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("robobench.eventreport._DEFAULT_LOG_DIR", tmp_path)
    rc = main(["report"])
    assert rc == 1
    assert "no session logs" in capsys.readouterr().err
```

(`main` is imported at the top of `test_cli.py`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli.py -k report -v`
Expected: FAIL (`invalid choice: 'report'`)

- [ ] **Step 3: Add the import** — at the top of `cli.py`, next to the other `from robobench...` imports:

```python
from robobench.eventreport import format_report, latest_event_log, parse_events
```

- [ ] **Step 4: Add the subparser** — in `_build_parser`, after the `init.set_defaults(...)` block and before `return parser`:

```python
    report = subparsers.add_parser(
        "report", help="Summarize a recovery/preflight session log (post-mortem)."
    )
    report.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Session log to read (default: latest events_*.jsonl in ~/.robobench/logs).",
    )
    report.set_defaults(func=_cmd_report)
```

- [ ] **Step 5: Add the handler** — after `_cmd_init` (or with the other `_cmd_*`):

```python
def _cmd_report(args: argparse.Namespace) -> int:
    if args.path is not None:
        target = Path(args.path)
        if not target.exists():
            print(f"error: {target} not found", file=sys.stderr)
            return 1
    else:
        target = latest_event_log()
        if target is None:
            print("no session logs in ~/.robobench/logs/", file=sys.stderr)
            return 1
    records = parse_events(target.read_text(encoding="utf-8"))
    if not any(r.get("event") in ("probe", "action", "outcome", "preflight") for r in records):
        print(f"no recognizable recover/preflight events in {target}", file=sys.stderr)
        return 2
    print(f"log: {target}")
    print(format_report(records))
    return 0
```

- [ ] **Step 6: Run tests + full suite + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli.py -k report -v && .venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests`
Expected: report tests PASS; full suite PASS (~230 passed); ruff clean

- [ ] **Step 7: Commit**

```bash
git add src/robobench/cli.py tests/unit/test_cli.py
git commit -m "feat: robobench report subcommand"
```

---

## Task 3: Docs + release v0.13.0a0

**Files:**
- Modify: `README.md` (CLI table), `docs/tutorials/recovering-a-stuck-robot.md`
- Modify: `CHANGELOG.md`, `pyproject.toml`, `src/robobench/__init__.py`

- [ ] **Step 1: README CLI table** — in `README.md`, add a row to the `## CLI` table (after the `robobench shutdown` row):

```markdown
| `robobench report` | Human-readable post-mortem of the latest recover/preflight session log |
```

- [ ] **Step 2: Tutorial note** — append to `docs/tutorials/recovering-a-stuck-robot.md`:

```markdown
## Reviewing afterward

Every `robobench recover` / `robobench preflight` run writes a JSONL session log
to `~/.robobench/logs/`. To see what happened without reading raw JSON:

```bash
robobench report          # the latest session
robobench report <path>   # a specific log
```

It prints a timeline (each probe's failing layer, each action tried, the final
outcome) and a one-line summary — handy for understanding *why* a recovery got
`STUCK` or `TIMED_OUT`.
```

- [ ] **Step 3: CHANGELOG** — turn `## [Unreleased]` into a fresh empty `## [Unreleased]` above:

```markdown
## [0.13.0a0] — 2026-05-30

### Added

- **`robobench report`** — renders the flight-recorder `events_*.jsonl` session
  logs (written by `recover`/`preflight`) into a human-readable post-mortem:
  a timeline of each probe's failing layer, each recovery action, and the final
  outcome, plus a one-line summary. Defaults to the latest log in
  `~/.robobench/logs/`, or takes a path. New pure module `robobench.eventreport`
  (`latest_event_log`/`parse_events`/`format_report`). Closes the
  "we record diagnostics but never read them" gap.
```

- [ ] **Step 4: Bump version** to `0.13.0a0` in `pyproject.toml` (`version = "0.13.0a0"`) and `src/robobench/__init__.py` (`__version__ = "0.13.0a0"`).

- [ ] **Step 5: Verify, commit, tag, push**

```bash
.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests && .venv/Scripts/python.exe -c "import robobench; print(robobench.__version__)"
git add README.md docs/tutorials/recovering-a-stuck-robot.md CHANGELOG.md pyproject.toml src/robobench/__init__.py
git commit -m "release: v0.13.0a0 — robobench report session post-mortem"
git tag v0.13.0a0
git push origin main && git push origin v0.13.0a0
```
Expected: all tests pass; prints `0.13.0a0`.

---

## Self-Review

**1. Spec coverage:**
- `latest_event_log` (latest, ignores lifecycle, None) → Task 1 + tests. ✓
- `parse_events` (skip blank/malformed) → Task 1 + test. ✓
- `format_report` (timeline + summary; failing aspect via `RobotState.failing_aspect()`; "no recognizable events" message; bad-data → unknown) → Task 1 + tests. ✓
- Input selection (latest default + optional path) → Task 2 `_cmd_report`. ✓
- Exit codes: 0 render / 1 missing-or-no-log / 2 unrecognized → Task 2 + tests. ✓
- Events-only scope; lifecycle ignored/rejected → `latest_event_log` glob + the recognized-events check. ✓
- Text output, ASCII `->` (Windows-console-safe) → Task 1 format. ✓
- Docs (README + tutorial) → Task 3. ✓
- Out of scope (no --json, no lifecycle formatting, no --list) — respected. ✓

**2. Placeholder scan:** No TBD/TODO/"add error handling"/"similar to". Every code step complete; every run step has an exact command + expected result.

**3. Type consistency:** `latest_event_log(log_dir=None) -> Path | None`, `parse_events(text) -> list[dict]`, `format_report(records) -> str` defined in Task 1 are imported and called with matching signatures in Task 2's `cli.py` import + `_cmd_report`. The recognized-event set `("probe","action","outcome","preflight")` is identical in `eventreport._RECOGNIZED_EVENTS` and the `_cmd_report` guard. `_DEFAULT_LOG_DIR` is imported from `eventlog` (where it is defined) and monkeypatched at `robobench.eventreport._DEFAULT_LOG_DIR` in the no-logs test (matches where `latest_event_log` reads it).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-30-robobench-report.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review. (REQUIRED SUB-SKILL: superpowers:subagent-driven-development)
2. **Inline Execution** — batch with checkpoints. (REQUIRED SUB-SKILL: superpowers:executing-plans) — reasonable here (small, pure feature).
