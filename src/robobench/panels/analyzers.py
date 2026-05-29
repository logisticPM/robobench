"""Pure diagnostic analyzers.

Every function here takes plain Python data and returns plain Python data —
no ROS, no HTTP, no I/O. This is the unit-testable core of the diagnostic
backend. The FastAPI layer feeds these functions snapshots from
DiagnosticState and serializes the results.
"""

from __future__ import annotations

# Clock offset severity thresholds (seconds). Single source of truth for the
# whole project; the adapter and CLI should eventually import these too.
CLOCK_OK_THRESHOLD = 2.0
CLOCK_WARN_THRESHOLD = 10.0

# Minimum samples needed for rate computation (requires at least 2 to compute an interval).
MIN_RATE_SAMPLES = 2


def classify_clock_offset(offset: float | None) -> str:
    """Map a clock offset (seconds) to OK / WARN / FAIL / UNKNOWN."""
    if offset is None:
        return "UNKNOWN"
    magnitude = abs(offset)
    if magnitude < CLOCK_OK_THRESHOLD:
        return "OK"
    if magnitude < CLOCK_WARN_THRESHOLD:
        return "WARN"
    return "FAIL"


def compute_topic_rate(timestamps: list[float]) -> float:
    """Compute the publish rate (Hz) from a list of message timestamps.

    Returns 0.0 if there are fewer than two samples or the time span is zero
    (avoids division by zero on identical stamps).
    """
    if len(timestamps) < MIN_RATE_SAMPLES:
        return 0.0
    span = max(timestamps) - min(timestamps)
    if span <= 0.0:
        return 0.0
    intervals = len(timestamps) - 1
    return intervals / span


def build_tf_graph(
    transforms: list[tuple[str, str, float]],
    now: float,
    stale_after: float = 1.0,
) -> dict:
    """Build a TF frame graph from (parent, child, stamp) transforms.

    An edge is "stale" if ``now - stamp > stale_after`` — the #1 symptom of a
    broken TF tree (a publisher died, or clock skew makes stamps look old).

    Returns::

        {
          "nodes": ["map", "odom", "base_link"],
          "edges": [{"parent": "map", "child": "odom", "stale": False}, ...],
          "broken": ["odom->base_link"],   # parent->child of every stale edge
        }
    """
    nodes: list[str] = []
    edges: list[dict] = []
    broken: list[str] = []
    for parent, child, stamp in transforms:
        for frame in (parent, child):
            if frame not in nodes:
                nodes.append(frame)
        stale = (now - stamp) > stale_after
        edges.append({"parent": parent, "child": child, "stale": stale})
        if stale:
            broken.append(f"{parent}->{child}")
    return {"nodes": nodes, "edges": edges, "broken": broken}
