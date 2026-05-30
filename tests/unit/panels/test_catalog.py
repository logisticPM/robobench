"""Tests for the failure catalog."""

from __future__ import annotations

from robobench.panels.catalog import FAILURE_CATALOG, lookup_fixes


def test_catalog_has_entries_for_core_checks():
    """Every core diagnostic check has at least one catalog entry."""
    for check in ("clock_offset", "sensor_rate", "tf_tree", "dds_graph"):
        assert check in FAILURE_CATALOG
        assert len(FAILURE_CATALOG[check]) >= 1
        for entry in FAILURE_CATALOG[check]:
            assert {"cause", "fix"} <= entry.keys()


def test_lookup_fixes_returns_matching_entries():
    """A FAIL status returns the catalog entries for that check."""
    fixes = lookup_fixes("clock_offset", status="FAIL")
    assert isinstance(fixes, list)
    assert len(fixes) >= 1
    assert "fix" in fixes[0]


def test_lookup_fixes_ok_status_returns_empty():
    """An OK status has nothing to fix."""
    assert lookup_fixes("clock_offset", status="OK") == []


def test_lookup_fixes_unknown_check_returns_empty():
    assert lookup_fixes("nonexistent_check", status="FAIL") == []


def test_tf_tree_suggests_odom_tf_helper():
    fixes = lookup_fixes("tf_tree", "FAIL")
    assert any("robobench odom-tf" in f["fix"] for f in fixes)


def test_connectivity_aspect_fixes_present():
    for aspect in (
        "rpi_reachable",
        "discovery_server_ok",
        "clock_synced",
        "create3_topics",
        "tb4_nodes_present",
    ):
        fixes = lookup_fixes(aspect, "FAIL")
        assert fixes, f"no catalog fixes for {aspect}"
        assert "fix" in fixes[0] and "cause" in fixes[0]
