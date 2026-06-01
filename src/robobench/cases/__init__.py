"""Robobench case library: the data-backed failure catalog.

A *case* is a structured, robot-agnostic record of one failure and its fix.
Cases ship as YAML files under ``robobench/data/cases/`` and load into ``Case``
objects. Pure file reads — no network, SSH, or rclpy.
"""

from __future__ import annotations

import importlib.resources
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from robobench.cases.validate import SUBSYSTEMS, validate_case

__all__ = [
    "SUBSYSTEMS",
    "Case",
    "CaseValidationError",
    "find_cases",
    "load_cases",
    "validate_case",
]


class CaseValidationError(ValueError):
    """A case file failed schema validation or could not be parsed."""


@dataclass(frozen=True)
class Case:
    """One failure-and-fix record (a flattened, validated case file)."""

    id: str
    schema_version: int
    provenance: str
    contributed_by: str
    subsystem: str
    tags: tuple[str, ...]
    robot_model: str | None
    ros_distro: tuple[str, ...]
    title: str
    cause: str
    fix: str
    verify: str | None
    links: tuple[str, ...]


def _case_from_raw(raw: dict) -> Case:
    match = raw["match"]
    return Case(
        id=raw["id"],
        schema_version=raw["schema_version"],
        provenance=raw["provenance"],
        contributed_by=raw["contributed_by"],
        subsystem=match["subsystem"],
        tags=tuple(match.get("tags", ())),
        robot_model=match.get("robot_model"),
        ros_distro=tuple(match.get("ros_distro", ())),
        title=raw["title"],
        cause=raw["cause"],
        fix=raw["fix"],
        verify=raw.get("verify"),
        links=tuple(raw.get("links", ())),
    )


def _default_cases_dir() -> Path:
    return Path(str(importlib.resources.files("robobench"))) / "data" / "cases"


@cache
def _load_dir(dir_str: str) -> tuple[Case, ...]:
    """Load + validate all ``*.yaml`` cases in *dir_str* (cached per directory).

    Results are cached for the process lifetime; call ``_load_dir.cache_clear()``
    in tests that must reload the same directory. ``@cache`` stores only
    successful results, so a raising call is not memoized.
    """
    directory = Path(dir_str)
    if not directory.is_dir():
        return ()
    cases: list[Case] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise CaseValidationError(f"{path.name}: invalid YAML: {exc}") from exc
        errors = validate_case(raw)
        if errors:
            raise CaseValidationError(f"{path.name}: " + "; ".join(errors))
        cases.append(_case_from_raw(raw))
    return tuple(cases)


def load_cases(dirs: Sequence[Path] | None = None) -> list[Case]:
    """Load + validate every case file in ``dirs`` (default: packaged cases).

    Raises ``CaseValidationError`` on the first malformed/invalid file — the
    packaged data is curated, so a bad shipped case must fail loudly. Results
    are cached per directory.
    """
    if dirs is None:
        dirs = [_default_cases_dir()]
    result: list[Case] = []
    for d in dirs:
        result.extend(_load_dir(str(Path(d))))
    return result


def find_cases(
    cases: Iterable[Case], *, subsystem: str, robot_model: str | None = None
) -> list[Case]:
    """Cases in ``subsystem``; ``robot_model=None`` matches all, else generic + that robot."""
    out: list[Case] = []
    for c in cases:
        if c.subsystem != subsystem:
            continue
        if robot_model is None or c.robot_model is None or c.robot_model == robot_model:
            out.append(c)
    return out
