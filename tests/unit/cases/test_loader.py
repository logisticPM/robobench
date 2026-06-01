"""Tests for robobench.cases loader + finder."""

from __future__ import annotations

from pathlib import Path

import pytest

from robobench.cases import Case, CaseValidationError, find_cases, load_cases

_VALID = """\
id: sample-case
schema_version: 1
provenance: verified
contributed_by: tester
match:
  subsystem: networking
  tags: [a, b]
  robot_model: turtlebot4
  ros_distro: [humble]
title: A sample
cause: Something broke.
fix: Do the thing.
verify: It works.
links:
  - https://example.com
"""

_GENERIC = """\
id: generic-case
schema_version: 1
provenance: verified
contributed_by: tester
match:
  subsystem: networking
title: Generic
cause: Broke.
fix: Fix it.
"""


def _case(case_id: str, subsystem: str, robot_model: str | None) -> Case:
    return Case(
        id=case_id,
        schema_version=1,
        provenance="verified",
        contributed_by="x",
        subsystem=subsystem,
        tags=(),
        robot_model=robot_model,
        ros_distro=(),
        title="t",
        cause="c",
        fix="f",
        verify=None,
        links=(),
    )


def test_load_cases_parses_and_flattens(tmp_path: Path):
    (tmp_path / "sample-case.yaml").write_text(_VALID, encoding="utf-8")
    cases = load_cases([tmp_path])
    assert len(cases) == 1
    c = cases[0]
    assert isinstance(c, Case)
    assert c.id == "sample-case"
    assert c.subsystem == "networking"
    assert c.tags == ("a", "b")  # list -> tuple
    assert c.robot_model == "turtlebot4"
    assert c.ros_distro == ("humble",)
    assert c.links == ("https://example.com",)


def test_load_cases_defaults_optional_fields(tmp_path: Path):
    (tmp_path / "generic-case.yaml").write_text(_GENERIC, encoding="utf-8")
    c = load_cases([tmp_path])[0]
    assert c.tags == ()
    assert c.robot_model is None
    assert c.ros_distro == ()
    assert c.verify is None
    assert c.links == ()


def test_load_cases_raises_on_invalid(tmp_path: Path):
    (tmp_path / "bad.yaml").write_text("id: bad\nschema_version: 1\n", encoding="utf-8")
    with pytest.raises(CaseValidationError):
        load_cases([tmp_path])


def test_load_cases_raises_on_malformed_yaml(tmp_path: Path):
    (tmp_path / "broken.yaml").write_text("id: [unclosed\n", encoding="utf-8")
    with pytest.raises(CaseValidationError):
        load_cases([tmp_path])


def test_load_cases_raises_on_non_dict_yaml(tmp_path: Path):
    (tmp_path / "list.yaml").write_text("- item\n- item2\n", encoding="utf-8")
    with pytest.raises(CaseValidationError, match="case must be a mapping"):
        load_cases([tmp_path])


def test_find_cases_filters_by_subsystem():
    cases = [_case("a", "networking", None), _case("b", "sensor", None)]
    assert [c.id for c in find_cases(cases, subsystem="networking")] == ["a"]


def test_find_cases_robot_model_none_matches_all():
    cases = [_case("g", "base", None), _case("t", "base", "turtlebot4")]
    found = find_cases(cases, subsystem="base", robot_model=None)
    assert {c.id for c in found} == {"g", "t"}


def test_find_cases_robot_model_excludes_other_robots():
    cases = [
        _case("g", "base", None),
        _case("tb", "base", "turtlebot4"),
        _case("jk", "base", "jackal"),
    ]
    found = find_cases(cases, subsystem="base", robot_model="turtlebot4")
    assert {c.id for c in found} == {"g", "tb"}  # generic + turtlebot4, not jackal
