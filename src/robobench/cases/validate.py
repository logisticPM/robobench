"""Schema validation for robobench case files.

Pure, dependency-free checks over a raw parsed case dict. Returns a list of
human-readable error strings (empty list == valid) so a loader can report which
file is bad and why, and a future contributor tool can lint files.
"""

from __future__ import annotations

import re

SUBSYSTEMS: frozenset[str] = frozenset(
    {"networking", "time_sync", "transform", "sensor", "lifecycle", "base"}
)

KNOWN_SCHEMA_VERSION = 1
_PROVENANCE = frozenset({"verified", "community"})
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_REQUIRED = ("id", "schema_version", "provenance", "contributed_by", "title", "cause", "fix")
_NONEMPTY_STR = ("contributed_by", "title", "cause", "fix")


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _validate_id(value: object) -> list[str]:
    """Return errors for the ``id`` field."""
    if not isinstance(value, str):
        return ["id must be a string"]
    if not _SLUG_RE.match(value):
        return ["id must be a slug matching [a-z0-9-]+"]
    return []


def _validate_match(match: object) -> list[str]:
    """Return errors for the ``match`` sub-mapping."""
    if not isinstance(match, dict):
        return ["match must be a mapping"]

    errors: list[str] = []
    if match.get("subsystem") not in SUBSYSTEMS:
        errors.append(f"match.subsystem must be one of {sorted(SUBSYSTEMS)}")
    if "tags" in match and not _is_str_list(match["tags"]):
        errors.append("match.tags must be a list of strings")
    rm = match.get("robot_model")
    if "robot_model" in match and rm is not None and not isinstance(rm, str):
        errors.append("match.robot_model must be a string or null")
    if "ros_distro" in match and not _is_str_list(match["ros_distro"]):
        errors.append("match.ros_distro must be a list of strings")
    return errors


def validate_case(raw: object) -> list[str]:
    """Return a list of validation errors for a raw case dict (empty == valid)."""
    if not isinstance(raw, dict):
        return ["case must be a mapping"]

    errors: list[str] = []

    for key in _REQUIRED:
        if key not in raw:
            errors.append(f"missing required field: {key}")

    if "id" in raw:
        errors.extend(_validate_id(raw["id"]))

    sv = raw.get("schema_version")
    if "schema_version" in raw and (isinstance(sv, bool) or sv != KNOWN_SCHEMA_VERSION):
        errors.append(f"schema_version must be {KNOWN_SCHEMA_VERSION}")

    if "provenance" in raw and raw.get("provenance") not in _PROVENANCE:
        errors.append("provenance must be 'verified' or 'community'")

    for key in _NONEMPTY_STR:
        if key in raw and (not isinstance(raw[key], str) or not raw[key].strip()):
            errors.append(f"{key} must be a non-empty string")

    if "verify" in raw and raw["verify"] is not None and not isinstance(raw["verify"], str):
        errors.append("verify must be a string or null")

    if "links" in raw and not _is_str_list(raw["links"]):
        errors.append("links must be a list of strings")

    # match is required too, but validated separately (needs the _validate_match dispatch).
    if "match" not in raw:
        errors.append("missing required field: match")
    else:
        errors.extend(_validate_match(raw["match"]))

    return errors
