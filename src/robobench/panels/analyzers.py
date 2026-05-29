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


def build_dds_graph(visible_nodes: list[str], expected_nodes: list[str]) -> dict:
    """Build a DDS node-presence graph.

    Every node is classified ``present`` (currently discoverable) or
    ``missing`` (expected but not seen — the usual symptom of a node that
    crashed or never came up under FastDDS Discovery Server).

    Returns::

        {
          "nodes": [{"name": "/amcl", "status": "present"}, ...],
          "missing": ["/planner_server"],   # expected but not visible
        }
    """
    visible_set = set(visible_nodes)
    all_names = list(dict.fromkeys([*visible_nodes, *expected_nodes]))

    nodes: list[dict] = []
    for name in all_names:
        status = "present" if name in visible_set else "missing"
        nodes.append({"name": name, "status": status})
    missing = [n for n in expected_nodes if n not in visible_set]
    return {"nodes": nodes, "missing": missing}
