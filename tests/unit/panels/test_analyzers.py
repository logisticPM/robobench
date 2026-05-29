"""Tests for the pure diagnostic analyzer functions."""

from __future__ import annotations

import pytest

from robobench.panels.analyzers import classify_clock_offset, compute_topic_rate


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
