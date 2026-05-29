"""Structured snapshot of a robot's bring-up health.

No I/O — a probe fills this in, the engine reasons over it. Aspects are
ordered most-upstream-first: a failure upstream (e.g. Discovery Server down)
usually causes the downstream symptoms (no topics, no odom), so the engine
should fix upstream first.
"""

from __future__ import annotations

from dataclasses import dataclass

# Aspects in upstream → downstream order. failing_aspect() returns the first
# one that's bad, so the engine targets the root, not the symptom.
_ASPECT_ORDER = (
    "rpi_reachable",
    "discovery_server_ok",
    "clock_synced",
    "create3_topics",
    "tb4_nodes_present",
    "odom_publishing",
)


@dataclass(frozen=True)
class RobotState:
    """A structured read of the robot's bring-up health."""

    rpi_reachable: bool
    discovery_server_ok: bool
    clock_synced: bool
    create3_topics: int
    tb4_nodes_present: bool
    odom_publishing: bool

    def _aspect_ok(self, aspect: str) -> bool:
        if aspect == "create3_topics":
            return self.create3_topics > 0
        return bool(getattr(self, aspect))

    def is_healthy(self) -> bool:
        return all(self._aspect_ok(a) for a in _ASPECT_ORDER)

    def failing_aspect(self) -> str | None:
        """Return the most-upstream failing aspect, or None if healthy."""
        for aspect in _ASPECT_ORDER:
            if not self._aspect_ok(aspect):
                return aspect
        return None
