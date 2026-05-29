"""Synthetic demo data so the dashboard is viewable without a real robot.

`robobench dashboard --demo` calls seed_demo_state() instead of starting the
rclpy bridge. The data is chosen to exercise every panel: a healthy clock and
sensor rate, but a deliberately broken TF edge and a missing Nav2 node, so the
TF and DDS panels show their FAIL state + catalog fixes.
"""

from __future__ import annotations

from robobench.panels.state import DiagnosticState

# The Nav2 node set the demo pretends to expect. `planner_server` is absent
# from the seeded visible nodes so the DDS panel shows a FAIL.
DEMO_EXPECTED_NODES = [
    "/map_server",
    "/amcl",
    "/controller_server",
    "/planner_server",
    "/bt_navigator",
]


def seed_demo_state(state: DiagnosticState, now: float) -> None:
    """Fill ``state`` with a realistic mixed-health snapshot.

    - clock offset 0.12s (OK)
    - 20 scan stamps at ~10 Hz ending at ``now`` (healthy)
    - TF chain map->odom->base_link fresh, base_link->laser stale (broken)
    - visible nodes missing ``/planner_server`` (DDS FAIL)
    """
    state.set_clock_offset(0.12)

    # ~10 Hz: 20 samples spanning ~1.9s ending at `now`. Clear first so repeated
    # demo re-seeding (the refresh loop) replaces rather than accumulates — else
    # the rate inflates as old timestamps pile up in the deque.
    state.clear_scans()
    for i in range(20):
        state.record_scan(now - 1.9 + i * 0.1)

    state.set_tf(
        [
            ("map", "odom", now),
            ("odom", "base_link", now),
            ("base_link", "laser", now - 100.0),  # stale -> broken
        ]
    )

    state.set_nodes(
        ["/map_server", "/amcl", "/controller_server", "/bt_navigator"]
    )  # /planner_server intentionally missing
