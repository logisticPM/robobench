import json
from pathlib import Path

from robobench.eventlog import EventLogger, NullEventLogger


def test_default_log_dir_is_isolated_in_tests(_isolated_event_log_dir):
    """An EventLogger() with no log_dir must write into the per-test isolation
    dir, never the developer's real ~/.robobench/logs (the conftest autouse
    fixture redirects it — this pins that contract)."""
    logger = EventLogger()
    logger.log("probe", {"healthy": True})
    logger.close()

    assert Path(logger.path).parent == _isolated_event_log_dir
    assert list(_isolated_event_log_dir.glob("events_*.jsonl"))


def test_event_logger_writes_jsonl(tmp_path):
    logger = EventLogger(log_dir=str(tmp_path))
    logger.log("probe", {"healthy": False, "failing": "clock_synced"})
    logger.log("action", {"name": "sync_clock"})
    logger.close()

    files = list(tmp_path.glob("events_*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # noqa: PLR2004
    first = json.loads(lines[0])
    assert first["event"] == "probe"
    assert first["data"] == {"healthy": False, "failing": "clock_synced"}
    assert first["session_id"] == logger.session_id
    assert "ts" in first


def test_log_after_close_is_ignored(tmp_path):
    logger = EventLogger(log_dir=str(tmp_path))
    logger.close()
    logger.log("late", {})  # must not raise
    lines = next(tmp_path.glob("events_*.jsonl")).read_text(encoding="utf-8").splitlines()
    assert lines == []


def test_null_event_logger_writes_nothing(tmp_path):
    logger = NullEventLogger()
    logger.log("x", {"a": 1})
    logger.close()
    assert list(tmp_path.glob("*.jsonl")) == []
    assert logger.session_id == "null"


def test_log_path_is_readable(tmp_path):
    logger = EventLogger(log_dir=str(tmp_path))
    assert str(tmp_path) in logger.path
    logger.close()
