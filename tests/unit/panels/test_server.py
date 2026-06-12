"""Tests for the diagnostic FastAPI server (TestClient + injected state)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from robobench.panels.server import create_app
from robobench.panels.state import DiagnosticState
from robobench.recovery.state import RobotState

# Test constants for magic number suppression
SMALL_OFFSET = 0.3
TARGET_SCAN_RATE = 8.0
HTTP_OK = 200
HTTP_ACCEPTED = 202
HTTP_FORBIDDEN = 403
HTTP_CONFLICT = 409
HTTP_UNPROCESSABLE = 422


def _client(state: DiagnosticState, expected_nodes=None) -> TestClient:
    app = create_app(state, namespace="ns", expected_nodes=expected_nodes or [])
    return TestClient(app)


def test_healthz_returns_ok():
    client = _client(DiagnosticState())
    resp = client.get("/healthz")
    assert resp.status_code == 200  # noqa: PLR2004
    assert resp.json() == {"status": "ok"}


def test_clock_panel_ok():
    state = DiagnosticState()
    state.set_clock_offset(SMALL_OFFSET)
    resp = _client(state).get("/api/panels/clock")
    body = resp.json()
    assert body["status"] == "OK"
    assert body["offset_seconds"] == SMALL_OFFSET
    assert body["fixes"] == []


def test_clock_panel_fail_attaches_catalog_fixes():
    state = DiagnosticState()
    state.set_clock_offset(42.0)
    body = _client(state).get("/api/panels/clock").json()
    assert body["status"] == "FAIL"
    assert len(body["fixes"]) >= 1
    assert "fix" in body["fixes"][0]


def test_clock_panel_unknown_when_no_offset():
    body = _client(DiagnosticState()).get("/api/panels/clock").json()
    assert body["status"] == "UNKNOWN"


def test_sensors_panel_reports_scan_rate():
    state = DiagnosticState()
    for t in [i * 0.1 for i in range(11)]:  # ~10 Hz
        state.record_scan(t)
    body = _client(state).get("/api/panels/sensors").json()
    assert body["scan"]["rate_hz"] > TARGET_SCAN_RATE
    assert body["scan"]["status"] in ("OK", "WARN", "FAIL")


def test_sensors_panel_fail_when_no_data_attaches_fixes():
    body = _client(DiagnosticState()).get("/api/panels/sensors").json()
    assert body["scan"]["rate_hz"] == 0.0
    assert body["scan"]["status"] == "FAIL"
    assert len(body["scan"]["fixes"]) >= 1


def test_tf_panel_reports_graph_and_broken_edges():
    state = DiagnosticState()
    now = time.time()
    state.set_tf([("map", "odom", now), ("odom", "base_link", now - 100.0)])
    body = _client(state).get("/api/panels/tf").json()
    assert set(body["nodes"]) == {"map", "odom", "base_link"}
    assert body["broken"] == ["odom->base_link"]
    assert body["status"] == "FAIL"
    assert len(body["fixes"]) >= 1


def test_tf_panel_ok_when_all_fresh():
    state = DiagnosticState()
    now = time.time()
    state.set_tf([("map", "odom", now)])
    body = _client(state).get("/api/panels/tf").json()
    assert body["broken"] == []
    assert body["status"] == "OK"
    assert body["fixes"] == []


def test_dds_panel_marks_missing_expected_nodes():
    state = DiagnosticState()
    state.set_nodes(["/amcl"])
    body = _client(state, expected_nodes=["/amcl", "/planner_server"]).get("/api/panels/dds").json()
    assert body["missing"] == ["/planner_server"]
    assert body["status"] == "FAIL"
    assert len(body["fixes"]) >= 1


def test_dds_panel_ok_when_all_present():
    state = DiagnosticState()
    state.set_nodes(["/amcl", "/planner_server"])
    body = _client(state, expected_nodes=["/amcl", "/planner_server"]).get("/api/panels/dds").json()
    assert body["missing"] == []
    assert body["status"] == "OK"


def test_index_route_serves_html():
    client = _client(DiagnosticState())
    resp = client.get("/")
    assert resp.status_code == HTTP_OK
    assert "text/html" in resp.headers["content-type"]
    assert "robobench diagnostics" in resp.text


def test_static_assets_are_mounted():
    """The /static mount serves files from the package static dir."""
    client = _client(DiagnosticState())
    resp = client.get("/static/index.html")
    assert resp.status_code == HTTP_OK


def test_connectivity_panel_unknown_then_fail():
    state = DiagnosticState()
    client = TestClient(create_app(state, namespace="tb", expected_nodes=[]))

    # No probe yet -> UNKNOWN
    body = client.get("/api/panels/connectivity").json()
    assert body["status"] == "UNKNOWN"

    # Discovery Server down -> FAIL at that layer, with fixes
    state.set_connectivity(RobotState(True, False, True, 0, False, True))
    body = client.get("/api/panels/connectivity").json()
    assert body["status"] == "FAIL"
    assert body["first_broken"] == "discovery_server_ok"
    assert body["fixes"]
    assert [layer["name"] for layer in body["layers"]][0] == "rpi_reachable"


def _fake_controller():
    class FakeJob:
        def snapshot(self):
            return {
                "status": "idle",
                "outcome": None,
                "actions": [],
                "steps": [],
                "error": None,
                "started_at": None,
                "finished_at": None,
            }

    class FakeController:
        def __init__(self):
            self.job = FakeJob()
            self.allow_start = True

        def preview(self, conn):
            return {
                "available": True,
                "failing_layer": "discovery_server_ok",
                "would_try": ["restart_discovery_server"],
            }

        def start_apply(self):
            return self.allow_start

    return FakeController()


def test_recover_preview_apply_and_conflict():
    ctrl = _fake_controller()
    client = TestClient(
        create_app(DiagnosticState(), namespace="tb", expected_nodes=[], recovery=ctrl)
    )

    r = client.post("/api/recover", json={"mode": "preview"})
    assert r.status_code == HTTP_OK
    assert r.json()["would_try"] == ["restart_discovery_server"]

    assert client.post("/api/recover", json={"mode": "apply"}).status_code == HTTP_ACCEPTED

    ctrl.allow_start = False
    assert client.post("/api/recover", json={"mode": "apply"}).status_code == HTTP_CONFLICT

    assert client.post("/api/recover", json={"mode": "nope"}).status_code == HTTP_UNPROCESSABLE

    body = client.get("/api/recover/status").json()
    assert body["available"] is True
    assert body["status"] == "idle"


def test_recover_unavailable_without_controller():
    client = TestClient(create_app(DiagnosticState(), namespace="tb", expected_nodes=[]))
    assert client.post("/api/recover", json={"mode": "apply"}).status_code == HTTP_FORBIDDEN
    assert client.get("/api/recover/status").json() == {"available": False, "status": "idle"}


def test_history_panel_returns_samples():
    state = DiagnosticState()
    state.append_history(100.0, 0.1, 10.0)
    state.append_history(110.0, None, 0.0)
    body = _client(state).get("/api/panels/history").json()
    assert body["samples"] == [
        {"ts": 100.0, "clock_offset": 0.1, "scan_hz": 10.0},
        {"ts": 110.0, "clock_offset": None, "scan_hz": 0.0},
    ]


def test_history_panel_empty():
    assert _client(DiagnosticState()).get("/api/panels/history").json() == {"samples": []}


HTTP_NOT_FOUND = 404

_SESSION_JSONL = (
    '{"ts": "2026-05-31T02:55:53+00:00", "session_id": "abc12345", "event": "probe",'
    ' "data": {"rpi_reachable": true, "discovery_server_ok": false, "clock_synced": true,'
    ' "create3_topics": 5, "tb4_nodes_present": true, "odom_publishing": true}}\n'
    '{"ts": "2026-05-31T02:55:54+00:00", "session_id": "abc12345", "event": "action",'
    ' "data": {"aspect": "discovery_server_ok", "name": "restart_discovery_server"}}\n'
    '{"ts": "2026-05-31T02:56:34+00:00", "session_id": "abc12345", "event": "outcome",'
    ' "data": {"outcome": "CONVERGED"}}\n'
)


def _sessions_client(tmp_path) -> TestClient:
    app = create_app(DiagnosticState(), namespace="tb", expected_nodes=[], log_dir=tmp_path)
    return TestClient(app)


def test_sessions_list_returns_summaries_newest_first(tmp_path):
    (tmp_path / "events_20260101_000000_old1.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "events_20260102_000000_abc1.jsonl").write_text(_SESSION_JSONL, encoding="utf-8")
    body = _sessions_client(tmp_path).get("/api/sessions").json()
    assert [s["name"] for s in body["sessions"]] == [
        "events_20260102_000000_abc1.jsonl",
        "events_20260101_000000_old1.jsonl",
    ]
    newest = body["sessions"][0]
    assert newest["outcome"] == "CONVERGED"
    assert newest["kind"] == "recover"
    assert newest["actions"] == 1


def test_sessions_list_empty_dir(tmp_path):
    assert _sessions_client(tmp_path).get("/api/sessions").json() == {"sessions": []}


def test_session_detail_returns_records_and_summary(tmp_path):
    (tmp_path / "events_20260102_000000_abc1.jsonl").write_text(_SESSION_JSONL, encoding="utf-8")
    body = _sessions_client(tmp_path).get("/api/sessions/events_20260102_000000_abc1.jsonl").json()
    assert body["name"] == "events_20260102_000000_abc1.jsonl"
    assert [r["event"] for r in body["records"]] == ["probe", "action", "outcome"]
    assert body["summary"]["outcome"] == "CONVERGED"
    # pre-rendered human-readable timeline (same renderer as `robobench report`)
    assert "summary:" in body["report"]
    assert "restart_discovery_server" in body["report"]


def test_session_detail_404_on_missing(tmp_path):
    resp = _sessions_client(tmp_path).get("/api/sessions/events_20990101_000000_nope.jsonl")
    assert resp.status_code == HTTP_NOT_FOUND


def test_session_detail_rejects_non_session_names(tmp_path):
    """Anything that isn't a plain events_*.jsonl filename is refused (no traversal)."""
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    client = _sessions_client(tmp_path)
    assert client.get("/api/sessions/secret.txt").status_code == HTTP_NOT_FOUND
    assert client.get("/api/sessions/..%5Csecret.txt").status_code == HTTP_NOT_FOUND
    assert client.get("/api/sessions/events_..%5C..%5Cx.jsonl").status_code == HTTP_NOT_FOUND
