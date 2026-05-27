"""JSONL event logger for quality reporting.

Appends structured JSON events (one per line) to a session log file.
Thread-safe, no ROS dependency, pure Python stdlib.

Usage:
    from campus_nav_llm.event_logger import EventLogger
    _evt = EventLogger()
    _evt.log("tool_exec", {"tool": "navigate_to", "target": "desk_1"})
"""
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_LOG_DIR = Path.home() / ".campus_nav_logs"


class NullEventLogger:
    """No-op logger for testing — writes nothing, creates no files."""

    session_id = "null"

    def log(self, event: str, data: dict) -> None:
        pass

    def close(self) -> None:
        pass


class EventLogger:
    """Append-only JSONL event writer.

    Each event line: {"ts": ISO8601, "session_id": str, "event": str, "data": dict}
    """

    def __init__(self, log_dir: str | None = None):
        self._dir = Path(log_dir) if log_dir else _DEFAULT_LOG_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self.session_id = uuid.uuid4().hex[:8]
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._path = self._dir / f"events_{ts}_{self.session_id}.jsonl"
        self._lock = threading.Lock()
        self._file = open(self._path, "a", encoding="utf-8")
        self._closed = False

    def log(self, event: str, data: dict) -> None:
        """Append one event to the JSONL file. Thread-safe."""
        if self._closed:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
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
        """Flush and close the log file."""
        with self._lock:
            if not self._closed:
                self._closed = True
                self._file.flush()
                self._file.close()
