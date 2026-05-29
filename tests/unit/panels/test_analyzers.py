"""Tests for the pure diagnostic analyzer functions."""

from __future__ import annotations

import pytest

from robobench.panels.analyzers import (
    build_tf_graph,
    classify_clock_offset,
    compute_topic_rate,
)


@pytest.mark.parametrize(
    "offset,expected",
    [
        (0.0, "OK"),
        (1.9, "OK"),
        (-1.9, "OK"),
        (2.0, "WARN"),
        (5.0, "WARN"),
        (-9.9, "WARN"),
        (10.0, "FAIL"),
        (-50.0, "FAIL"),
    ],
)
def test_classify_clock_offset(offset, expected):
    assert classify_clock_offset(offset) == expected


def test_classify_clock_offset_none_is_unknown():
    assert classify_clock_offset(None) == "UNKNOWN"


def test_compute_topic_rate_basic():
    """10 evenly spaced stamps over 1.0s window => ~10 Hz."""
    timestamps = [i * 0.1 for i in range(11)]  # 0.0 .. 1.0, 11 samples, 10 intervals
    rate = compute_topic_rate(timestamps)
    assert rate == pytest.approx(10.0, abs=0.1)


def test_compute_topic_rate_too_few_samples_returns_zero():
    assert compute_topic_rate([]) == 0.0
    assert compute_topic_rate([1.0]) == 0.0


def test_compute_topic_rate_zero_span_returns_zero():
    """All-identical timestamps => no measurable span => 0.0 (not a div-by-zero)."""
    assert compute_topic_rate([5.0, 5.0, 5.0]) == 0.0


def test_build_tf_graph_nodes_and_edges():
    """A simple two-edge chain produces 3 nodes and 2 edges."""
    transforms = [("map", "odom", 100.0), ("odom", "base_link", 100.0)]
    graph = build_tf_graph(transforms, now=100.0, stale_after=1.0)
    assert set(graph["nodes"]) == {"map", "odom", "base_link"}
    assert {"parent": "map", "child": "odom", "stale": False} in graph["edges"]
    assert {"parent": "odom", "child": "base_link", "stale": False} in graph["edges"]
    assert graph["broken"] == []


def test_build_tf_graph_flags_stale_edges():
    """An edge whose stamp is older than stale_after is flagged stale and broken."""
    transforms = [("map", "odom", 100.0), ("odom", "base_link", 90.0)]
    graph = build_tf_graph(transforms, now=100.0, stale_after=1.0)
    stale_edges = [e for e in graph["edges"] if e["stale"]]
    assert stale_edges == [{"parent": "odom", "child": "base_link", "stale": True}]
    assert graph["broken"] == ["odom->base_link"]


def test_build_tf_graph_empty():
    graph = build_tf_graph([], now=0.0, stale_after=1.0)
    assert graph == {"nodes": [], "edges": [], "broken": []}
