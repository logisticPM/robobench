"""Tests for DiagnosticState."""

from __future__ import annotations

from robobench.panels.state import DiagnosticState


def test_record_scan_keeps_bounded_timestamps():
    """record_scan appends a timestamp; the deque is bounded to maxlen."""
    s = DiagnosticState(scan_window=3)
    for t in [1.0, 2.0, 3.0, 4.0]:
        s.record_scan(t)
    assert list(s.scan_timestamps()) == [2.0, 3.0, 4.0]


def test_set_and_get_tf_transforms_round_trips():
    """TF transforms are stored as (parent, child, stamp) tuples."""
    s = DiagnosticState()
    s.set_tf([("map", "odom", 100.0), ("odom", "base_link", 100.1)])
    assert s.tf_transforms() == [("map", "odom", 100.0), ("odom", "base_link", 100.1)]


def test_set_and_get_node_names():
    s = DiagnosticState()
    s.set_nodes(["/amcl", "/controller_server"])
    assert s.node_names() == ["/amcl", "/controller_server"]


def test_clock_offset_defaults_to_none_then_settable():
    offset = 0.42
    s = DiagnosticState()
    assert s.clock_offset() is None
    s.set_clock_offset(offset)
    assert s.clock_offset() == offset


def test_snapshot_returns_consistent_copy():
    """snapshot() returns a plain dict copy that won't mutate with later writes."""
    s = DiagnosticState()
    s.set_clock_offset(1.0)
    s.set_nodes(["/a"])
    snap = s.snapshot()
    s.set_clock_offset(2.0)
    s.set_nodes(["/a", "/b"])
    assert snap["clock_offset"] == 1.0
    assert snap["nodes"] == ["/a"]


def test_clear_scans_empties_the_deque():
    """clear_scans drops all recorded timestamps (demo re-seed uses it)."""
    s = DiagnosticState()
    for t in [1.0, 2.0, 3.0]:
        s.record_scan(t)
    s.clear_scans()
    assert list(s.scan_timestamps()) == []
