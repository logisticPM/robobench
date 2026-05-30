"""JSONL flight recorder for diagnostics/recovery runs.

Appends one JSON object per line: {ts, session_id, event, data}. Thread-safe,
stdlib-only, no ROS dependency. Ports upstream campus_nav_llm/event_logger.py;
default dir is ~/.robobench/logs.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

_DEFAULT_LOG_DIR = Path.home() / ".robobench" / "logs"


class NullEventLogger:
    """No-op logger — writes nothing, creates no files."""

    session_id = "null"
    path = ""

    def log(self, event: str, data: dict) -> None:
        pass

    def close(self) -> None:
        pass


class EventLogger:
    """Append-only JSONL event writer (thread-safe)."""

    def __init__(self, log_dir: str | None = None) -> None:
        directory = Path(log_dir) if log_dir else _DEFAULT_LOG_DIR
        directory.mkdir(parents=True, exist_ok=True)
        self.session_id = uuid.uuid4().hex[:8]
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        self._path = directory / f"events_{ts}_{self.session_id}.jsonl"
        self.path = str(self._path)
        self._lock = threading.Lock()
        self._file = open(self._path, "a", encoding="utf-8")  # noqa: SIM115
        self._closed = False

    def log(self, event: str, data: dict) -> None:
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "session_id": self.session_id,
            "event": event,
            "data": data,
        }
        line = json.dumps(record, default=str) + "\n"
        with self._lock:
            if not self._closed:
                self._file.write(line)
                self._file.flush()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._file.flush()
                self._file.close()
