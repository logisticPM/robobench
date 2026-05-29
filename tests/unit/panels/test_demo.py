"""Tests for synthetic demo state seeding."""

from __future__ import annotations

from robobench.panels.analyzers import (
    build_dds_graph,
    build_tf_graph,
    classify_clock_offset,
    compute_topic_rate,
)
from robobench.panels.demo import DEMO_EXPECTED_NODES, seed_demo_state
from robobench.panels.state import DiagnosticState

MIN_HEALTHY_HZ = 8.0


def test_seed_demo_state_produces_a_mixed_health_picture():
    """The demo data should exercise OK, a healthy rate, and at least one FAIL
    so every panel has something interesting to render."""
    state = DiagnosticState()
    now = 1000.0
    seed_demo_state(state, now=now)

    snap = state.snapshot()

    # Clock: small offset => OK
    assert classify_clock_offset(snap["clock_offset"]) == "OK"

    # Scan: ~10 Hz => healthy
    assert compute_topic_rate(snap["scan_timestamps"]) > MIN_HEALTHY_HZ

    # TF: exactly one stale edge (broken)
    tf = build_tf_graph(snap["tf"], now=now, stale_after=1.0)
    assert len(tf["broken"]) == 1

    # DDS: at least one expected node missing
    dds = build_dds_graph(visible_nodes=snap["nodes"], expected_nodes=DEMO_EXPECTED_NODES)
    assert len(dds["missing"]) >= 1
