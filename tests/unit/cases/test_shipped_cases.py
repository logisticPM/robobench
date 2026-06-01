"""Integrity checks over the shipped (packaged) verified cases."""

from __future__ import annotations

from robobench.cases import SUBSYSTEMS, load_cases

MIN_SHIPPED_CASES = 15


def test_all_shipped_cases_load():
    assert len(load_cases()) >= MIN_SHIPPED_CASES


def test_every_subsystem_has_a_shipped_case():
    assert {c.subsystem for c in load_cases()} == set(SUBSYSTEMS)


def test_shipped_cases_are_all_verified():
    assert all(c.provenance == "verified" for c in load_cases())


def test_shipped_case_ids_are_unique():
    ids = [c.id for c in load_cases()]
    assert len(ids) == len(set(ids))


def test_odom_publishing_gap_is_closed():
    by_id = {c.id: c for c in load_cases()}
    assert "odom-not-publishing" in by_id
    assert by_id["odom-not-publishing"].subsystem == "base"


def test_super_client_gotcha_case_present():
    by_id = {c.id: c for c in load_cases()}
    case = by_id.get("connected-as-client-not-super-client")
    assert case is not None and case.subsystem == "networking"
    assert "ROS_SUPER_CLIENT" in case.fix
