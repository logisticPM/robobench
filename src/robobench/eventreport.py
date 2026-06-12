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
_MIN_STAMPS_FOR_DURATION = 2


def list_event_logs(log_dir: Path | None = None) -> list[Path]:
    """All ``events_*.jsonl`` in ``log_dir`` (default ~/.robobench/logs), newest first.

    Ignores ``lifecycle_*.jsonl``. Filenames embed a sortable ``YYYYMMDD_HHMMSS``
    stamp, so a lexical sort is chronological. Returns [] if the directory is
    absent or has no matching log.
    """
    directory = log_dir or _DEFAULT_LOG_DIR
    if not directory.exists():
        return []
    return sorted(directory.glob("events_*.jsonl"), reverse=True)


def latest_event_log(log_dir: Path | None = None) -> Path | None:
    """Most recent ``events_*.jsonl`` in ``log_dir``, or None (see list_event_logs)."""
    logs = list_event_logs(log_dir)
    return logs[0] if logs else None


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
    if len(stamps) < _MIN_STAMPS_FOR_DURATION:
        return None
    try:
        delta = datetime.fromisoformat(stamps[-1]) - datetime.fromisoformat(stamps[0])
        return delta.total_seconds()
    except (ValueError, TypeError):
        return None


def summarize_session(records: list[dict]) -> dict:
    """One-line metadata for a session's records (for the dashboard session list).

    ``kind`` is ``preflight`` / ``watch`` / ``recover`` / ``unknown``;
    ``outcome`` is the last recorded outcome (None if the session never reached
    one); ``duration_s`` spans all timestamped records.
    """
    if any(r.get("event") == "preflight" for r in records):
        kind = "preflight"
    elif any(str(r.get("event", "")).startswith("watch_") for r in records):
        kind = "watch"
    elif any(r.get("event") in _RECOGNIZED_EVENTS for r in records):
        kind = "recover"
    else:
        kind = "unknown"

    outcomes = [
        (r.get("data") or {}).get("outcome") for r in records if r.get("event") == "outcome"
    ]
    return {
        "session_id": next((r.get("session_id") for r in records if r.get("session_id")), None),
        "kind": kind,
        "started": next((r.get("ts") for r in records if r.get("ts")), None),
        "duration_s": _duration_s(records),
        "outcome": outcomes[-1] if outcomes else None,
        "actions": sum(1 for r in records if r.get("event") == "action"),
        "events": len(records),
    }


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
            aspect = data.get("aspect", "?")
            name = data.get("name", "?")
            lines.append(f"  {when}  action     {aspect} -> {name}")
        elif event == "outcome":
            last_outcome = data.get("outcome", "?")
            lines.append(f"  {when}  outcome    {last_outcome}")

    lines.append("")
    if last_outcome is not None:
        tail = f" in {duration:.1f}s" if duration is not None else ""
        noun = "action" if action_count == 1 else "actions"
        lines.append(f"summary: {last_outcome} after {action_count} {noun}{tail}")
    elif preflight_detail is not None:
        lines.append(f"summary: preflight - {preflight_detail}")
    else:
        lines.append(f"summary: {action_count} action(s), no outcome recorded")
    return "\n".join(lines)
