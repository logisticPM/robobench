"""Tests for the data-driven failure catalog (panels.catalog)."""

from __future__ import annotations

from robobench.cases import SUBSYSTEMS
from robobench.panels.catalog import _KEY_TO_SUBSYSTEM, lookup_fixes


def test_lookup_fixes_returns_backward_compatible_shape():
    fixes = lookup_fixes("clock_offset", status="FAIL")
    assert isinstance(fixes, list)
    assert len(fixes) >= 1
    assert {"cause", "fix", "link"} <= fixes[0].keys()


def test_lookup_fixes_warn_also_returns_fixes():
    assert lookup_fixes("sensor_rate", status="WARN")


def test_lookup_fixes_ok_status_returns_empty():
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
        "odom_publishing",
    ):
        fixes = lookup_fixes(aspect, "FAIL")
        assert fixes, f"no catalog fixes for {aspect}"
        assert {"cause", "fix"} <= fixes[0].keys()


def test_lookup_fixes_link_is_first_link_or_none():
    # clocks-drifted has a link; workstation-not-serving-ntp has none.
    links = [f["link"] for f in lookup_fixes("clock_offset", "FAIL")]
    assert any(lnk is not None for lnk in links), "expected at least one non-None link"
    assert any(lnk is None for lnk in links), "expected at least one None link"


def test_key_to_subsystem_maps_to_valid_subsystems():
    # Whitebox: drives directly off _KEY_TO_SUBSYSTEM so new keys are auto-covered.
    for key, subsystem in _KEY_TO_SUBSYSTEM.items():
        assert subsystem in SUBSYSTEMS, f"{key} -> {subsystem} not a known subsystem"


def test_every_mapped_key_has_at_least_one_fix():
    # Whitebox: every registered key must resolve to at least one shipped case.
    for key in _KEY_TO_SUBSYSTEM:
        assert lookup_fixes(key, "FAIL"), f"no fixes for {key}"
