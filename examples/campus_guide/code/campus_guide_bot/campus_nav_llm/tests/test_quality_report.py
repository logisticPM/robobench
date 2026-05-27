"""Tests for quality report generator."""
import json
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _write_events(tmp_path, events):
    f = tmp_path / "events_test.jsonl"
    lines = [json.dumps(e) for e in events]
    f.write_text("\n".join(lines) + "\n")
    return f


class TestReportGeneration:
    def test_empty_log_produces_report(self, tmp_path):
        from gen_quality_report import generate_report
        _write_events(tmp_path, [])
        report = generate_report(str(tmp_path))
        assert "# Quality Report" in report
        assert "No events" in report

    def test_tool_exec_summary(self, tmp_path):
        from gen_quality_report import generate_report
        events = [
            {"ts": "2026-04-07T10:00:00.000Z", "session_id": "abc", "event": "tool_exec",
             "data": {"tool": "navigate_to", "status": "arrived", "elapsed_s": 8.5, "request_id": "r1"}},
            {"ts": "2026-04-07T10:01:00.000Z", "session_id": "abc", "event": "tool_exec",
             "data": {"tool": "navigate_to", "status": "arrived", "elapsed_s": 12.0, "request_id": "r2"}},
            {"ts": "2026-04-07T10:02:00.000Z", "session_id": "abc", "event": "tool_exec",
             "data": {"tool": "speak", "status": "spoken", "elapsed_s": 0.01, "request_id": "r3"}},
        ]
        _write_events(tmp_path, events)
        report = generate_report(str(tmp_path))
        assert "navigate_to" in report
        assert "2/2" in report or "100%" in report
        assert "speak" in report

    def test_interaction_summary(self, tmp_path):
        from gen_quality_report import generate_report
        events = [
            {"ts": "2026-04-07T10:00:00.000Z", "session_id": "abc", "event": "interaction",
             "data": {"input": "go to desk", "reply": "Arrived at desk_1.", "path": "fast", "elapsed_s": 9.0}},
            {"ts": "2026-04-07T10:01:00.000Z", "session_id": "abc", "event": "interaction",
             "data": {"input": "where am I", "reply": "You are at desk_1.", "path": "llm", "elapsed_s": 2.5}},
        ]
        _write_events(tmp_path, events)
        report = generate_report(str(tmp_path))
        assert "fast" in report.lower() or "Fast" in report
        assert "llm" in report.lower() or "LLM" in report

    def test_error_section(self, tmp_path):
        from gen_quality_report import generate_report
        events = [
            {"ts": "2026-04-07T10:00:00.000Z", "session_id": "abc", "event": "tool_error",
             "data": {"tool": "navigate_to", "error": "Localization uncertain", "elapsed_s": 0.1, "request_id": "r1"}},
            {"ts": "2026-04-07T10:01:00.000Z", "session_id": "abc", "event": "handle_error",
             "data": {"input": "fly", "error": "Unknown tool"}},
        ]
        _write_events(tmp_path, events)
        report = generate_report(str(tmp_path))
        assert "Error" in report or "error" in report
        assert "Localization uncertain" in report

    def test_navigation_stats(self, tmp_path):
        from gen_quality_report import generate_report
        events = [
            {"ts": "2026-04-07T10:00:00.000Z", "session_id": "abc", "event": "tool_exec",
             "data": {"tool": "navigate_to", "status": "arrived", "elapsed_s": 15.0,
                      "input": {"location_name": "desk_1"}, "request_id": "r1"}},
            {"ts": "2026-04-07T10:02:00.000Z", "session_id": "abc", "event": "tool_exec",
             "data": {"tool": "navigate_to", "status": "rejected", "elapsed_s": 0.5,
                      "input": {"location_name": "nowhere"}, "request_id": "r2"}},
        ]
        _write_events(tmp_path, events)
        report = generate_report(str(tmp_path))
        assert "desk_1" in report or "arrived" in report

    def test_multiple_sessions(self, tmp_path):
        from gen_quality_report import generate_report
        f1 = tmp_path / "events_s1.jsonl"
        f2 = tmp_path / "events_s2.jsonl"
        f1.write_text(json.dumps({"ts": "2026-04-07T10:00:00.000Z", "session_id": "s1",
                                   "event": "tool_exec", "data": {"tool": "speak", "status": "ok", "elapsed_s": 0.01, "request_id": "r1"}}) + "\n")
        f2.write_text(json.dumps({"ts": "2026-04-07T11:00:00.000Z", "session_id": "s2",
                                   "event": "tool_exec", "data": {"tool": "speak", "status": "ok", "elapsed_s": 0.02, "request_id": "r2"}}) + "\n")
        report = generate_report(str(tmp_path))
        assert "s1" in report or "s2" in report or "2 session" in report.lower()
