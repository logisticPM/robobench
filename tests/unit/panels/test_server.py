"""Tests for the diagnostic FastAPI server (TestClient + injected state)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from robobench.panels.server import create_app
from robobench.panels.state import DiagnosticState

# Test constants for magic number suppression
SMALL_OFFSET = 0.3
TARGET_SCAN_RATE = 8.0
HTTP_OK = 200


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
    from fastapi.testclient import TestClient

    from robobench.panels.server import create_app
    from robobench.panels.state import DiagnosticState
    from robobench.recovery.state import RobotState

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
