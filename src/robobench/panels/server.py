"""FastAPI app exposing diagnostic panels as JSON.

The app holds a reference to a DiagnosticState (filled by the bridge thread)
and a set of expected node names (for the DDS panel). Endpoints run pure
analyzers over state snapshots and attach failure-catalog hints on WARN/FAIL.

The app never imports rclpy — it only reads DiagnosticState. That keeps it
testable with a plain injected state object.
"""

from __future__ import annotations

from fastapi import FastAPI

from robobench.panels.state import DiagnosticState


def create_app(
    state: DiagnosticState,
    namespace: str,
    expected_nodes: list[str] | None = None,
) -> FastAPI:
    """Build the FastAPI app bound to a given DiagnosticState."""
    app = FastAPI(title="robobench diagnostics")
    app.state.diag = state
    app.state.namespace = namespace
    app.state.expected_nodes = expected_nodes or []

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app
