"""FastAPI app exposing diagnostic panels as JSON.

The app holds a reference to a DiagnosticState (filled by the bridge thread)
and a set of expected node names (for the DDS panel). Endpoints run pure
analyzers over state snapshots and attach failure-catalog hints on WARN/FAIL.
The flight-recorder session endpoints only read JSONL files from ``log_dir``.

The app never imports rclpy — it only reads DiagnosticState. That keeps it
testable with a plain injected state object.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from robobench.eventreport import (
    format_report,
    list_event_logs,
    parse_events,
    summarize_session,
)
from robobench.panels.analyzers import (
    build_dds_graph,
    build_tf_graph,
    classify_clock_offset,
    compute_topic_rate,
)
from robobench.panels.catalog import lookup_fixes
from robobench.panels.connectivity import diagnose as diagnose_connectivity
from robobench.panels.state import DiagnosticState

_STATIC_DIR = Path(__file__).parent / "static"

# Strict session-log filename shape: no separators, so a URL path segment can
# never escape log_dir.
_SESSION_NAME_RE = re.compile(r"^events_[A-Za-z0-9_]+\.jsonl$")

# Cap how many logs the list endpoint parses per request (each is a file read).
_MAX_SESSIONS_LISTED = 50


def _register_session_routes(app: FastAPI) -> None:
    """Flight-recorder session endpoints (read-only over ``app.state.log_dir``)."""

    @app.get("/api/sessions")
    def sessions() -> dict:
        out = []
        for path in list_event_logs(app.state.log_dir)[:_MAX_SESSIONS_LISTED]:
            records = parse_events(path.read_text(encoding="utf-8"))
            out.append({"name": path.name, **summarize_session(records)})
        return {"sessions": out}

    @app.get("/api/sessions/{name}")
    def session_detail(name: str) -> dict:
        if not _SESSION_NAME_RE.match(name):
            raise HTTPException(status_code=404, detail="no such session")
        candidates = {p.name: p for p in list_event_logs(app.state.log_dir)}
        path = candidates.get(name)
        if path is None:
            raise HTTPException(status_code=404, detail="no such session")
        records = parse_events(path.read_text(encoding="utf-8"))
        return {
            "name": name,
            "records": records,
            "summary": summarize_session(records),
            "report": format_report(records),
        }


class RecoverRequest(BaseModel):
    mode: Literal["preview", "apply"]


def create_app(
    state: DiagnosticState,
    namespace: str,
    expected_nodes: list[str] | None = None,
    *,
    recovery: object | None = None,
    log_dir: Path | None = None,
) -> FastAPI:
    """Build the FastAPI app bound to a given DiagnosticState.

    ``log_dir`` is where the flight recorder writes ``events_*.jsonl``
    (None -> the default ~/.robobench/logs).
    """
    app = FastAPI(title="robobench diagnostics")
    app.state.diag = state
    app.state.namespace = namespace
    app.state.expected_nodes = expected_nodes or []
    app.state.recovery = recovery
    app.state.log_dir = log_dir

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    # Scan-rate thresholds (Hz). Below WARN: effectively dead.
    SCAN_OK_HZ = 5.0
    SCAN_WARN_HZ = 2.0

    @app.get("/api/panels/clock")
    def clock_panel() -> dict:
        offset = app.state.diag.clock_offset()
        status = classify_clock_offset(offset)
        return {
            "status": status,
            "offset_seconds": offset,
            "fixes": lookup_fixes("clock_offset", status),
        }

    @app.get("/api/panels/sensors")
    def sensors_panel() -> dict:
        timestamps = list(app.state.diag.scan_timestamps())
        rate = compute_topic_rate(timestamps)
        if rate >= SCAN_OK_HZ:
            status = "OK"
        elif rate >= SCAN_WARN_HZ:
            status = "WARN"
        else:
            status = "FAIL"
        return {
            "scan": {
                "rate_hz": round(rate, 2),
                "status": status,
                "fixes": lookup_fixes("sensor_rate", status),
            }
        }

    @app.get("/api/panels/tf")
    def tf_panel() -> dict:
        graph = build_tf_graph(app.state.diag.tf_transforms(), now=time.time(), stale_after=1.0)
        status = "FAIL" if graph["broken"] else "OK"
        return {**graph, "status": status, "fixes": lookup_fixes("tf_tree", status)}

    @app.get("/api/panels/dds")
    def dds_panel() -> dict:
        graph = build_dds_graph(
            visible_nodes=app.state.diag.node_names(),
            expected_nodes=app.state.expected_nodes,
        )
        status = "FAIL" if graph["missing"] else "OK"
        return {**graph, "status": status, "fixes": lookup_fixes("dds_graph", status)}

    @app.get("/api/panels/connectivity")
    def connectivity_panel() -> dict:
        return diagnose_connectivity(app.state.diag.connectivity())

    @app.get("/api/panels/history")
    def history_panel() -> dict:
        return {
            "samples": [
                {"ts": ts, "clock_offset": offset, "scan_hz": hz}
                for ts, offset, hz in app.state.diag.history()
            ]
        }

    @app.post("/api/recover", response_model=None)
    def recover(req: RecoverRequest) -> dict | JSONResponse:
        rec = app.state.recovery
        if rec is None:
            raise HTTPException(
                status_code=403, detail="recovery unavailable (demo or no SSH config)"
            )
        if req.mode == "preview":
            return rec.preview(app.state.diag.connectivity())
        if not rec.start_apply():
            raise HTTPException(status_code=409, detail="a recovery is already running")
        return JSONResponse(status_code=202, content=rec.job.snapshot())

    @app.get("/api/recover/status")
    def recover_status() -> dict:
        rec = app.state.recovery
        if rec is None:
            return {"available": False, "status": "idle"}
        return {"available": True, **rec.job.snapshot()}

    _register_session_routes(app)

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "index.html"))

    return app
