# `robobench report` — Design Spec

**Date:** 2026-05-30
**Status:** Approved (brainstorming) — pending implementation plan
**Topic:** A `robobench report` command that turns the flight-recorder JSONL session logs into a human-readable post-mortem (what was probed, which actions ran, the final outcome), closing the "we write logs but nothing reads them" gap.

## Problem

The flight recorder (`robobench.eventlog`, v0.8) writes JSONL session logs to
`~/.robobench/logs/events_*.jsonl` on every `recover` / `preflight` run (and the
lifecycle activator writes `lifecycle_*.jsonl`). Nothing reads them back —
robobench is "write-only" for diagnostics history. A user who wants to know *why
last night's recovery got STUCK*, or *what the preflight saw*, has to hand-read
raw JSON lines. The upstream had quality-report tooling over its event logs;
robobench has the recorder but no reader.

## Design decisions (resolved during brainstorming)

1. **Input selection: latest-by-default + optional path.** `robobench report`
   with no argument renders the most recent `events_*.jsonl` in
   `~/.robobench/logs/`; `robobench report <path>` renders a specific file.
2. **Schema scope: events only (recover/preflight) for v1.** The `events_*.jsonl`
   schema (`probe`/`action`/`outcome`/`preflight`) is the recovery post-mortem
   story. `lifecycle_*.jsonl` (a different Nav2-transition schema) is out of scope
   for v1; "latest" ignores it, and pointing `report` at one yields a clear
   "no recognizable events" message.
3. **Output: human-readable text** (timeline + summary). `--json` is deferred
   (the raw JSONL is already machine-readable; YAGNI).

## Event-log schema (input)

`events_*.jsonl` — one JSON object per line, written by `robobench.eventlog.EventLogger`:
```json
{"ts": "2026-05-31T02:55:53.123+00:00", "session_id": "6da3444c", "event": "probe", "data": {...}}
```
- `event: "probe"` → `data` is `dataclasses.asdict(RobotState)`:
  `{rpi_reachable, discovery_server_ok, clock_synced, create3_topics, tb4_nodes_present, odom_publishing}`.
- `event: "action"` → `data` is `{"aspect": str, "name": str}`.
- `event: "outcome"` → `data` is `{"outcome": str}` (CONVERGED/STUCK/TIMED_OUT/NEEDS_HUMAN/ERROR).
- `event: "preflight"` → `data` is `dataclasses.asdict(RobotState)` (single record).

## Architecture

A pure parse-and-format module plus a thin CLI command. The command resolves the
log path (latest `events_*.jsonl` by default), reads it, and prints the formatted
report. No network, SSH, or rclpy — fully unit-testable.

```
robobench report [PATH]
  └─ _cmd_report:
       PATH given       -> read PATH
       else             -> latest_event_log(~/.robobench/logs) -> None? "no logs" exit 1
       parse_events(text) -> records
       no recognizable events? -> "no recognizable recover/preflight events" exit 2
       else: print(format_report(records)) exit 0
```

## Components

### `src/robobench/eventreport.py` (new — pure)
- `latest_event_log(log_dir: Path | None = None) -> Path | None`: return the most
  recent `events_*.jsonl` in `log_dir` (default: `robobench.eventlog`'s
  `~/.robobench/logs`), by sorted filename (names embed a sortable
  `YYYYMMDD_HHMMSS` stamp). **Ignores `lifecycle_*.jsonl`.** `None` if the dir is
  absent or has no `events_*.jsonl`.
- `parse_events(text: str) -> list[dict]`: parse JSONL into a list of record
  dicts; **silently skip blank/malformed lines** (one bad line must not break the
  report).
- `format_report(records: list[dict]) -> str`: render the human-readable report.
  - If no record has a recognized `event` in `{"probe","action","outcome","preflight"}`,
    return a single-line message: `"no recognizable recover/preflight events"`.
  - Otherwise emit:
    - a header: log session id (from the first record's `session_id`), start time
      (first `ts`), and duration (last `ts` − first `ts`, seconds);
    - a timeline: one line per record — `HH:MM:SS  <event>  <detail>`, where
      `probe`/`preflight` detail is `healthy` or `unhealthy (failing: <aspect>)`,
      `action` detail is `<aspect> → <name>`, `outcome` detail is the outcome string;
    - a `summary:` line — for a session ending in `outcome`:
      `"<OUTCOME> after <N> actions in <D>s"`; for a preflight-only log:
      `"preflight — healthy"` or `"preflight — unhealthy (<aspect>)"`.
  - The failing aspect for a probe/preflight record is computed by reconstructing
    `RobotState(**data).failing_aspect()` (reuses the canonical aspect-order logic
    from `robobench.recovery.state`), guarded by `try/except` → `"unknown"` if the
    data shape is unexpected.

### `src/robobench/cli.py` — `report` subcommand + `_cmd_report`
- Subparser `report` with one optional positional: `path` (nargs `?`, default
  `None`). No `--robot`.
- `_cmd_report(args)`:
  - If `args.path`: `target = Path(args.path)`; if not `target.exists()` →
    `print(f"error: {target} not found", file=sys.stderr)`, return 1.
  - Else: `target = latest_event_log()`; if `None` →
    `print("no session logs in ~/.robobench/logs/", file=sys.stderr)`, return 1.
  - `records = parse_events(target.read_text(encoding="utf-8"))`.
  - If no recognized events → `print(f"no recognizable recover/preflight events in {target}", file=sys.stderr)`, return 2.
  - Else `print(format_report(records))`, return 0.
  - (The header line should also show `log: <target>` so the user knows which file
    was rendered.)

## Data flow & lifecycle
1. `robobench recover` / `preflight` write `events_*.jsonl` (existing).
2. `robobench report` reads the latest (or a given) log → prints the post-mortem.
3. Closes the loop: live diagnosis (dashboard) + after-the-fact review (report).

## Error handling
- Missing path / no logs → clean message + exit 1 (no traceback).
- Unrecognized schema (lifecycle log, empty, garbage) → clean message + exit 2.
- Malformed JSONL lines are skipped individually.
- A probe record with an unexpected `data` shape → failing aspect renders as
  `"unknown"` rather than raising.

## Testing strategy
- **`parse_events`:** valid multi-line JSONL → all records; a blank line and a
  malformed (`not json`) line are skipped; valid lines around them still parse.
- **`latest_event_log`:** with two `events_*.jsonl` (different stamps) returns the
  newer; a `lifecycle_*.jsonl` present is ignored; empty/absent dir → `None`.
- **`format_report`:**
  - A synthetic recover session (probe[unhealthy:discovery_server_ok] → action →
    probe → outcome[CONVERGED]) → output contains `CONVERGED`, the action line
    `discovery_server_ok → restart_discovery_server`, `failing: discovery_server_ok`,
    and a `summary:` with the action count.
  - A preflight-only record (unhealthy, rpi_reachable) → `summary: preflight — unhealthy (rpi_reachable)`.
  - Records with no recognized events → the `"no recognizable ... events"` message.
  - A probe whose `data` is missing keys → renders `unknown`, no exception.
- **`_cmd_report` (CLI):** a temp events log → exit 0, output contains the outcome;
  missing path → exit 1; a lifecycle/garbage log → exit 2; no logs in an empty dir
  (point the default at a tmp dir via the `path` arg in tests, or test
  `latest_event_log` directly) → handled.
- All via `tmp_path`; no network/SSH/rclpy.

## Out of scope (YAGNI)
- `--json` structured output (raw JSONL already serves machines).
- Formatting `lifecycle_*.jsonl` (different schema; v1 is events-only).
- `--list` browse mode, log rotation/cleanup, multi-session aggregation.
- No change to the writer (`eventlog.py`) beyond importing its log-dir constant.

## Honest caveats
- Pure Python + file reads; fully unit-testable, no hardware. (Like `init`, this
  command has no hardware-only behavior — verifiable here end to end.)
