"""Pure connectivity diagnosis for the dashboard's SSH-probe fallback.

Turns a recovery RobotState into a layered "which transport layer is broken"
panel payload. Deliberately ignores ``odom_publishing`` (the sensor panel owns
liveness) — only the five upstream transport layers matter for "why is the
dashboard blind". No SSH, no rclpy: trivially unit-testable.
"""

from __future__ import annotations

from robobench.panels.catalog import lookup_fixes
from robobench.recovery.state import RobotState

# Upstream -> downstream: (aspect_name, human label). Excludes odom_publishing.
CONNECTIVITY_ASPECTS: tuple[tuple[str, str], ...] = (
    ("rpi_reachable", "RPi reachable"),
    ("discovery_server_ok", "Discovery Server up"),
    ("clock_synced", "Clock synced"),
    ("create3_topics", "Create3 topics present"),
    ("tb4_nodes_present", "TB4 nodes present"),
)


def _aspect_ok(state: RobotState, aspect: str) -> bool:
    if aspect == "create3_topics":
        return state.create3_topics > 0
    return bool(getattr(state, aspect))


def first_broken_layer(state: RobotState) -> str | None:
    """Most-upstream failing connectivity aspect (odom ignored), or None."""
    for aspect, _label in CONNECTIVITY_ASPECTS:
        if not _aspect_ok(state, aspect):
            return aspect
    return None


def diagnose(state: RobotState | None) -> dict:
    """Build the connectivity panel payload.

    ``None`` (probe hasn't run / disabled) -> UNKNOWN. Otherwise OK when all
    five layers pass, else FAIL with the first broken layer and its catalog fixes.
    """
    if state is None:
        return {"status": "UNKNOWN", "layers": [], "first_broken": None, "fixes": []}
    layers = [
        {"name": aspect, "label": label, "ok": _aspect_ok(state, aspect)}
        for aspect, label in CONNECTIVITY_ASPECTS
    ]
    broken = first_broken_layer(state)
    return {
        "status": "FAIL" if broken else "OK",
        "layers": layers,
        "first_broken": broken,
        "fixes": lookup_fixes(broken, "FAIL") if broken else [],
    }
