"""Tests for JSONL event logger."""
import json
import threading
import pytest


class TestEventLogger:
    def test_log_event_creates_file(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        logger = EventLogger(log_dir=str(tmp_path))
        logger.log("tool_exec", {"tool": "speak", "status": "ok"})
        logger.close()
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        assert "events" in files[0].name

    def test_log_event_writes_valid_jsonl(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        logger = EventLogger(log_dir=str(tmp_path))
        logger.log("tool_exec", {"tool": "navigate_to", "target": "desk_1"})
        logger.log("nav_result", {"status": "arrived", "elapsed_s": 12.5})
        logger.close()
        files = list(tmp_path.glob("*.jsonl"))
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 2
        event1 = json.loads(lines[0])
        assert event1["event"] == "tool_exec"
        assert event1["data"]["tool"] == "navigate_to"
        assert "ts" in event1
        assert "session_id" in event1
        event2 = json.loads(lines[1])
        assert event2["event"] == "nav_result"
        assert event2["data"]["elapsed_s"] == 12.5

    def test_log_is_thread_safe(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        logger = EventLogger(log_dir=str(tmp_path))
        def write_batch(prefix):
            for i in range(50):
                logger.log("test", {"i": f"{prefix}_{i}"})
        threads = [threading.Thread(target=write_batch, args=(f"t{t}",)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        logger.close()
        files = list(tmp_path.glob("*.jsonl"))
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 200
        for line in lines:
            json.loads(line)

    def test_session_id_is_consistent(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        logger = EventLogger(log_dir=str(tmp_path))
        logger.log("a", {})
        logger.log("b", {})
        logger.close()
        files = list(tmp_path.glob("*.jsonl"))
        lines = files[0].read_text().strip().split("\n")
        id1 = json.loads(lines[0])["session_id"]
        id2 = json.loads(lines[1])["session_id"]
        assert id1 == id2
        assert len(id1) == 8

    def test_close_flushes(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        logger = EventLogger(log_dir=str(tmp_path))
        logger.log("flush_test", {"x": 1})
        logger.close()
        files = list(tmp_path.glob("*.jsonl"))
        content = files[0].read_text()
        assert "flush_test" in content

    def test_log_after_close_does_not_crash(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        logger = EventLogger(log_dir=str(tmp_path))
        logger.close()
        logger.log("after_close", {})

class TestGetLogger:
    def test_get_logger_returns_different_instances(self, tmp_path):
        from campus_nav_llm.event_logger import EventLogger
        a = EventLogger(log_dir=str(tmp_path))
        b = EventLogger(log_dir=str(tmp_path))
        assert a.session_id != b.session_id
        a.close()
        b.close()
