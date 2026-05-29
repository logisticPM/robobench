"""Tests for the diagnostic FastAPI server (TestClient + injected state)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from robobench.panels.server import create_app
from robobench.panels.state import DiagnosticState

# Test constants for magic number suppression
SMALL_OFFSET = 0.3
TARGET_SCAN_RATE = 8.0


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
