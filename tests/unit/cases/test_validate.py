"""Tests for robobench.cases.validate."""

from __future__ import annotations

from robobench.cases.validate import SUBSYSTEMS, validate_case


def _valid() -> dict:
    return {
        "id": "sample-case",
        "schema_version": 1,
        "provenance": "verified",
        "contributed_by": "tester",
        "match": {"subsystem": "networking", "tags": ["x"]},
        "title": "A sample",
        "cause": "Something broke.",
        "fix": "Do the thing.",
    }


def test_subsystems_has_six_expected_values():
    assert {
        "networking",
        "time_sync",
        "transform",
        "sensor",
        "lifecycle",
        "base",
    } == SUBSYSTEMS


def test_valid_case_has_no_errors():
    assert validate_case(_valid()) == []


def test_non_mapping_is_invalid():
    assert validate_case(["not", "a", "dict"]) != []


def test_missing_required_field_reported():
    raw = _valid()
    del raw["fix"]
    assert any("fix" in e for e in validate_case(raw))


def test_missing_match_reported():
    raw = _valid()
    del raw["match"]
    assert any("match" in e for e in validate_case(raw))


def test_bad_schema_version_reported():
    raw = _valid()
    raw["schema_version"] = 2
    assert any("schema_version" in e for e in validate_case(raw))


def test_bad_provenance_reported():
    raw = _valid()
    raw["provenance"] = "rumor"
    assert any("provenance" in e for e in validate_case(raw))


def test_bad_subsystem_reported():
    raw = _valid()
    raw["match"]["subsystem"] = "telepathy"
    assert any("subsystem" in e for e in validate_case(raw))


def test_bad_slug_reported():
    raw = _valid()
    raw["id"] = "Not A Slug"
    assert any("slug" in e for e in validate_case(raw))


def test_tags_must_be_list():
    raw = _valid()
    raw["match"]["tags"] = "notalist"
    assert any("tags" in e for e in validate_case(raw))


def test_links_must_be_list():
    raw = _valid()
    raw["links"] = "http://single"
    assert any("links" in e for e in validate_case(raw))
