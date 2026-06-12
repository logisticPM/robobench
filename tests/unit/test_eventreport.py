from robobench.eventreport import (
    format_report,
    latest_event_log,
    list_event_logs,
    parse_events,
    summarize_session,
)


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
        {
            "ts": "2026-05-31T02:55:53+00:00",
            "session_id": "6da3444c",
            "event": "probe",
            "data": healthy_but_discovery,
        },
        {
            "ts": "2026-05-31T02:55:54+00:00",
            "session_id": "6da3444c",
            "event": "action",
            "data": {"aspect": "discovery_server_ok", "name": "restart_discovery_server"},
        },
        {
            "ts": "2026-05-31T02:56:34+00:00",
            "session_id": "6da3444c",
            "event": "outcome",
            "data": {"outcome": "CONVERGED"},
        },
    ]


def test_format_report_recover_session():
    out = format_report(_recover_records())
    assert "session 6da3444c" in out
    assert "failing: discovery_server_ok" in out
    assert "discovery_server_ok -> restart_discovery_server" in out
    assert "CONVERGED" in out
    assert "summary:" in out
    assert "1 action" in out
    assert "action(s)" not in out


def test_format_report_preflight():
    out = format_report(
        [
            {
                "ts": "2026-05-31T02:55:53+00:00",
                "session_id": "x",
                "event": "preflight",
                "data": {
                    "rpi_reachable": False,
                    "discovery_server_ok": False,
                    "clock_synced": False,
                    "create3_topics": 0,
                    "tb4_nodes_present": False,
                    "odom_publishing": False,
                },
            },
        ]
    )
    assert "preflight" in out
    assert "rpi_reachable" in out
    assert "summary: preflight" in out


def test_format_report_no_recognized_events():
    assert format_report([{"ts": "t", "event": "init", "namespace": "tb"}]) == (
        "no recognizable recover/preflight events"
    )


def test_format_report_probe_bad_data_renders_unknown():
    out = format_report([{"ts": "t", "event": "probe", "data": {"wrong": "shape"}}])
    assert "unknown" in out


def test_list_event_logs_newest_first_ignores_lifecycle(tmp_path):
    (tmp_path / "events_20260101_000000_a.jsonl").write_text("{}", encoding="utf-8")
    (tmp_path / "events_20260102_000000_b.jsonl").write_text("{}", encoding="utf-8")
    (tmp_path / "lifecycle_20260103_000000.jsonl").write_text("{}", encoding="utf-8")
    names = [p.name for p in list_event_logs(tmp_path)]
    assert names == ["events_20260102_000000_b.jsonl", "events_20260101_000000_a.jsonl"]


def test_list_event_logs_empty_or_missing_dir(tmp_path):
    assert list_event_logs(tmp_path) == []
    assert list_event_logs(tmp_path / "nope") == []


def test_summarize_session_recover():
    summary = summarize_session(_recover_records())
    assert summary["session_id"] == "6da3444c"
    assert summary["kind"] == "recover"
    assert summary["outcome"] == "CONVERGED"
    assert summary["actions"] == 1
    assert summary["started"] == "2026-05-31T02:55:53+00:00"
    assert summary["duration_s"] == 41.0  # noqa: PLR2004
    assert summary["events"] == 3  # noqa: PLR2004


def test_summarize_session_preflight_kind():
    records = [
        {"ts": "2026-05-31T02:55:53+00:00", "session_id": "x", "event": "preflight", "data": {}}
    ]
    summary = summarize_session(records)
    assert summary["kind"] == "preflight"
    assert summary["outcome"] is None
    assert summary["actions"] == 0


def test_summarize_session_watch_kind():
    records = [
        {"ts": "2026-05-31T02:55:53+00:00", "session_id": "w", "event": "watch_healthy"},
        {
            "ts": "2026-05-31T02:56:53+00:00",
            "session_id": "w",
            "event": "watch_unhealthy",
            "data": {"aspect": "clock_synced"},
        },
    ]
    summary = summarize_session(records)
    assert summary["kind"] == "watch"
    assert summary["duration_s"] == 60.0  # noqa: PLR2004


def test_summarize_session_empty_records():
    summary = summarize_session([])
    assert summary["session_id"] is None
    assert summary["kind"] == "unknown"
    assert summary["events"] == 0
    assert summary["duration_s"] is None
