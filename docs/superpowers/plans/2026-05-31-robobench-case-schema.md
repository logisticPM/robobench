# Case Schema + Catalog-as-Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote robobench's hardcoded `FAILURE_CATALOG` into a robot-agnostic, versioned, file-based **case** format with a loader and validator, keeping the dashboard consumers behaving identically.

**Architecture:** A new pure `robobench.cases` package owns the schema types (`Case`, `SUBSYSTEMS`), validation (`validate_case`), and a cached file loader (`load_cases`/`find_cases`). Cases ship as one-file-per-case YAML under `robobench/data/cases/`. `panels.catalog` is reimplemented to map its internal check keys onto the robot-agnostic `subsystem` vocabulary and read fixes from loaded cases — its public `lookup_fixes` signature is preserved, so `server.py` and `connectivity.py` are untouched. No network/SSH/rclpy; 100% unit-testable.

**Tech Stack:** Python 3.11+, PyYAML (already a dependency), pytest, ruff (line length 100). Spec: `docs/superpowers/specs/2026-05-31-robobench-case-schema-design.md`.

---

## Conventions for every task

- **Run tests with the project venv.** On this machine: `.venv/Scripts/python.exe -m pytest …` and `.venv/Scripts/python.exe -m ruff check …`. Commands below write `python`/`ruff` for brevity — substitute the venv binaries. Run from the repo root `C:/Users/chntw/Documents/robotic/robobench`.
- **TDD:** write the failing test, watch it fail, implement the minimum, watch it pass, commit.
- **Commits:** Conventional prefixes (`feat:`/`test:`/`refactor:`/`chore:`). **Do NOT add a `Co-Authored-By: Claude` trailer** (project preference). Author identity is already configured — never run `git config`.
- **Branch:** work on `main` directly (project pattern). Subagents commit locally only; the coordinator tags/pushes after review.
- **ruff must stay clean** (`ruff check src tests`) and lines ≤ 100 chars.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/robobench/cases/__init__.py` (create) | Package: `Case` dataclass, `CaseValidationError`, `load_cases`, `find_cases`; re-exports `SUBSYSTEMS`, `validate_case` |
| `src/robobench/cases/validate.py` (create) | `SUBSYSTEMS` vocab + `validate_case(raw) -> list[str]` (pure, dependency-free) |
| `src/robobench/data/cases/*.yaml` (create, ×14) | The shipped verified cases (packaged data) |
| `src/robobench/panels/catalog.py` (rewrite) | `_KEY_TO_SUBSYSTEM` + data-driven `lookup_fixes` (signature preserved) |
| `pyproject.toml` (modify) | `package-data` entry + version bump |
| `src/robobench/__init__.py` (modify) | version bump |
| `CHANGELOG.md` (modify) | release notes |
| `tests/unit/cases/__init__.py` (create) | test package marker |
| `tests/unit/cases/test_validate.py` (create) | `validate_case` + `SUBSYSTEMS` tests |
| `tests/unit/cases/test_loader.py` (create) | `load_cases`/`find_cases` tests |
| `tests/unit/cases/test_shipped_cases.py` (create) | integrity of the 14 packaged cases |
| `tests/unit/panels/test_catalog.py` (rewrite) | data-driven `lookup_fixes` tests (drops `FAILURE_CATALOG` import) |

---

## Task 1: `cases.validate` — vocabulary + schema validation

**Files:**
- Create: `src/robobench/cases/__init__.py` (docstring-only for now)
- Create: `src/robobench/cases/validate.py`
- Create: `tests/unit/cases/__init__.py`
- Test: `tests/unit/cases/test_validate.py`

- [ ] **Step 1: Create the test package marker**

Create `tests/unit/cases/__init__.py` (empty file).

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/cases/test_validate.py`:

```python
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
    assert SUBSYSTEMS == {
        "networking",
        "time_sync",
        "transform",
        "sensor",
        "lifecycle",
        "base",
    }


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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/unit/cases/test_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'robobench.cases'`.

- [ ] **Step 4: Create the package docstring file**

Create `src/robobench/cases/__init__.py`:

```python
"""Robobench case library: the data-backed failure catalog.

A *case* is a structured, robot-agnostic record of one failure and its fix.
Cases ship as YAML files under ``robobench/data/cases/`` and load into ``Case``
objects. Pure file reads — no network, SSH, or rclpy.
"""

from __future__ import annotations
```

- [ ] **Step 5: Implement `validate.py`**

Create `src/robobench/cases/validate.py`:

```python
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


def validate_case(raw: object) -> list[str]:
    """Return a list of validation errors for a raw case dict (empty == valid)."""
    if not isinstance(raw, dict):
        return ["case must be a mapping"]

    errors: list[str] = []

    for key in _REQUIRED:
        if key not in raw:
            errors.append(f"missing required field: {key}")

    case_id = raw.get("id")
    if "id" in raw and (not isinstance(case_id, str) or not _SLUG_RE.match(case_id)):
        errors.append("id must be a slug matching [a-z0-9-]+")

    if "schema_version" in raw and raw.get("schema_version") != KNOWN_SCHEMA_VERSION:
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

    match = raw.get("match")
    if "match" not in raw:
        errors.append("missing required field: match")
    elif not isinstance(match, dict):
        errors.append("match must be a mapping")
    else:
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/unit/cases/test_validate.py -v`
Expected: PASS (11 tests).

- [ ] **Step 7: Lint**

Run: `ruff check src/robobench/cases tests/unit/cases`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add src/robobench/cases/__init__.py src/robobench/cases/validate.py tests/unit/cases/__init__.py tests/unit/cases/test_validate.py
git commit -m "feat(cases): add subsystem vocabulary + case schema validator"
```

---

## Task 2: `cases` package — `Case` + loader + finder

**Files:**
- Modify: `src/robobench/cases/__init__.py`
- Test: `tests/unit/cases/test_loader.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/cases/test_loader.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/cases/test_loader.py -v`
Expected: FAIL with `ImportError: cannot import name 'Case' from 'robobench.cases'`.

- [ ] **Step 3: Implement the loader in `__init__.py`**

Replace `src/robobench/cases/__init__.py` with:

```python
"""Robobench case library: the data-backed failure catalog.

A *case* is a structured, robot-agnostic record of one failure and its fix.
Cases ship as YAML files under ``robobench/data/cases/`` and load into ``Case``
objects. Pure file reads — no network, SSH, or rclpy.
"""

from __future__ import annotations

import importlib.resources
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
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


@lru_cache(maxsize=None)
def _load_dir(dir_str: str) -> tuple[Case, ...]:
    directory = Path(dir_str)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/cases/test_loader.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint**

Run: `ruff check src/robobench/cases tests/unit/cases`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/robobench/cases/__init__.py tests/unit/cases/test_loader.py
git commit -m "feat(cases): add Case dataclass, cached loader, and finder"
```

---

## Task 3: Ship the 14 verified cases + package data

**Files:**
- Create: `src/robobench/data/cases/*.yaml` (×14)
- Modify: `pyproject.toml` (package-data)
- Test: `tests/unit/cases/test_shipped_cases.py`

- [ ] **Step 1: Write the failing integrity tests**

Create `tests/unit/cases/test_shipped_cases.py`:

```python
"""Integrity checks over the shipped (packaged) verified cases."""

from __future__ import annotations

from robobench.cases import SUBSYSTEMS, load_cases


def test_all_shipped_cases_load():
    assert len(load_cases()) >= 14


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/cases/test_shipped_cases.py -v`
Expected: FAIL — `load_cases()` returns 0 cases (the data dir doesn't exist yet), so the count/subsystem/odom assertions fail.

- [ ] **Step 3: Create the 14 case files**

Create each file under `src/robobench/data/cases/`. (Create the directory first.)

`rpi-unreachable.yaml`:
```yaml
id: rpi-unreachable
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: networking
  tags: [reachability, network, ssh]
title: "Robot host is unreachable"
cause: "The robot's onboard computer is off, not on the network, or at a different IP."
fix: "Check the robot is powered and on the same network; verify `robot.ip` in config.yaml; try `ping <ip>`."
verify: "`ping <robot-ip>` succeeds."
links: []
```

`discovery-server-not-listening.yaml`:
```yaml
id: discovery-server-not-listening
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: networking
  tags: [discovery-server, fastdds]
  robot_model: turtlebot4
title: "FastDDS Discovery Server not listening"
cause: "The FastDDS Discovery Server isn't listening on the robot."
fix: "SSH in and `sudo systemctl restart discovery.service`; confirm port 11811 with `ss -ulnp | grep 11811`."
verify: "`robobench preflight` shows discovery_server_ok = true."
links:
  - "https://github.com/ros-navigation/navigation2/issues/3560"
```

`discovery-server-unreachable-from-workstation.yaml`:
```yaml
id: discovery-server-unreachable-from-workstation
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: networking
  tags: [discovery-server, fastdds, env]
title: "Discovery Server not reachable from the workstation"
cause: "The workstation can't reach the FastDDS Discovery Server."
fix: "Verify the `ROS_DISCOVERY_SERVER` env var and that the server port (default 11811) is listening on the robot."
verify: "`ros2 daemon stop && ros2 node list` shows the robot's nodes."
links: []
```

`node-dropped-under-discovery-server.yaml`:
```yaml
id: node-dropped-under-discovery-server
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: networking
  tags: [discovery-server, fastdds, late-joiner, lifecycle]
title: "Expected node dropped under Discovery Server"
cause: "An expected node never came up or crashed; FastDDS Discovery Server can silently drop late joiners."
fix: "Re-run `robobench-lifecycle-activator` and check the node's log. (Nav2 #3560)"
verify: "`ros2 node list` shows the expected node."
links:
  - "https://github.com/ros-navigation/navigation2/issues/3560"
```

`clocks-drifted.yaml`:
```yaml
id: clocks-drifted
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: time_sync
  tags: [clock, chrony, ntp]
title: "Workstation and robot clocks drifted apart"
cause: "The workstation and robot clocks have drifted apart, breaking TF and message timestamps."
fix: "Run `robobench bringup` (configures chrony), or manually: `ssh <robot> 'sudo chronyc -a makestep'`."
verify: "`robobench check` reports a sub-second offset."
links:
  - "https://docs.ros.org/en/rolling/Tutorials/Demos/Time.html"
```

`workstation-not-serving-ntp.yaml`:
```yaml
id: workstation-not-serving-ntp
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: time_sync
  tags: [clock, chrony, ntp]
title: "Workstation isn't serving NTP"
cause: "The workstation isn't serving NTP, so the robot can't follow its clock."
fix: "Add `allow 192.168.0.0/16` and `local stratum 10` to /etc/chrony/chrony.conf, then `sudo systemctl restart chrony`."
verify: "`chronyc sources` on the robot lists the workstation."
links: []
```

`tf-publisher-died.yaml`:
```yaml
id: tf-publisher-died
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: transform
  tags: [tf, tf2]
title: "A TF publisher died"
cause: "A TF publisher died, leaving a stale or broken edge in the transform tree."
fix: "Identify the broken parent->child edge, find which node should publish it (`ros2 topic info /tf`), and restart that node."
verify: "`ros2 run tf2_tools view_frames` shows a connected tree."
links:
  - "https://docs.ros.org/en/rolling/Concepts/About-Tf2.html"
```

`tf-stale-from-clock-skew.yaml`:
```yaml
id: tf-stale-from-clock-skew
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: transform
  tags: [tf, clock]
title: "TF looks stale due to clock skew"
cause: "Clock skew makes fresh transforms look stale."
fix: "Fix clock sync first (see the clock panel) — TF staleness is often a symptom of clock drift, not a missing publisher."
verify: "After clock sync, transforms are no longer reported stale."
links: []
```

`create3-not-bridging-odom-tf.yaml`:
```yaml
id: create3-not-bridging-odom-tf
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: transform
  tags: [tf, odom, create3]
  robot_model: turtlebot4
title: "Create3 isn't bridging the odom->base_link TF"
cause: "The Create3 firmware isn't publishing the odom->base_link transform."
fix: "Run `robobench odom-tf --robot turtlebot4 --config config.yaml` to republish odom->base_link from /odom."
verify: "`ros2 topic echo /tf` shows odom->base_link updating."
links: []
```

`sensor-not-publishing-or-qos-mismatch.yaml`:
```yaml
id: sensor-not-publishing-or-qos-mismatch
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: sensor
  tags: [lidar, imu, qos]
title: "Sensor not publishing or QoS mismatch"
cause: "A sensor (LiDAR/IMU) isn't publishing, or there's a QoS mismatch (BEST_EFFORT vs RELIABLE)."
fix: "Check the sensor is powered and the driver node is up (`ros2 node list`); confirm your subscriber QoS matches the publisher."
verify: "`ros2 topic hz <topic>` shows the expected rate."
links: []
```

`network-saturation-dropping-sensor-data.yaml`:
```yaml
id: network-saturation-dropping-sensor-data
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: sensor
  tags: [network, wifi, bandwidth]
title: "Network saturation dropping sensor data"
cause: "Network saturation is dropping sensor packets."
fix: "Check WiFi signal / switch to ethernet; inspect `ros2 topic hz` for the raw rate at the source."
verify: "`ros2 topic hz <topic>` is stable at the source rate."
links: []
```

`nav-nodes-did-not-activate.yaml`:
```yaml
id: nav-nodes-did-not-activate
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: lifecycle
  tags: [nav2, lifecycle, bringup]
  robot_model: turtlebot4
title: "Navigation nodes didn't come up"
cause: "The TurtleBot4 ROS nodes (Nav2 etc.) didn't come up or failed to activate."
fix: "Re-run `robobench-lifecycle-activator`, or `robobench recover`; check the bring-up service: `systemctl status turtlebot4`."
verify: "`ros2 node list` shows the Nav2 lifecycle nodes."
links: []
```

`create3-base-not-publishing-topics.yaml`:
```yaml
id: create3-base-not-publishing-topics
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: base
  tags: [create3, base, topics]
  robot_model: turtlebot4
title: "Create3 base isn't publishing topics"
cause: "No /<namespace>/ topics — the Create3 base isn't publishing."
fix: "Restart the Create3 app, or run `robobench recover`. Check the Create3 web UI at http://192.168.186.2."
verify: "`ros2 topic list` shows the namespaced Create3 topics."
links: []
```

`odom-not-publishing.yaml` (the previously-uncatalogued gap):
```yaml
id: odom-not-publishing
schema_version: 1
provenance: verified
contributed_by: robobench
match:
  subsystem: base
  tags: [odom, create3]
  robot_model: turtlebot4
title: "Odometry isn't being published"
cause: "The /odom topic is absent — the Create3 base isn't publishing odometry."
fix: "Confirm the Create3 base is up (`robobench recover`), then republish the TF with `robobench odom-tf` if /odom exists but the transform doesn't."
verify: "`ros2 topic hz /odom` shows a steady rate."
links: []
```

- [ ] **Step 4: Add package-data so the YAML ships in the wheel**

In `pyproject.toml`, find the existing block:

```toml
[tool.setuptools.package-data]
"robobench.panels" = ["static/**/*"]
```

and add the new line so it reads:

```toml
[tool.setuptools.package-data]
"robobench.panels" = ["static/**/*"]
"robobench" = ["data/cases/*.yaml"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/unit/cases/test_shipped_cases.py -v`
Expected: PASS (5 tests). If `test_every_subsystem_has_a_shipped_case` fails, a subsystem has no file — check all six are represented.

- [ ] **Step 6: Lint**

Run: `ruff check src/robobench/cases tests/unit/cases`
Expected: no errors. (YAML files are not linted.)

- [ ] **Step 7: Commit**

```bash
git add src/robobench/data/cases pyproject.toml tests/unit/cases/test_shipped_cases.py
git commit -m "feat(cases): ship 14 verified cases + package data (closes odom gap)"
```

---

## Task 4: Data-driven `panels.catalog`

**Files:**
- Rewrite: `src/robobench/panels/catalog.py`
- Rewrite: `tests/unit/panels/test_catalog.py`

- [ ] **Step 1: Rewrite the catalog test (drops the `FAILURE_CATALOG` import)**

Replace `tests/unit/panels/test_catalog.py` with:

```python
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


def test_key_to_subsystem_maps_to_valid_subsystems():
    for key, subsystem in _KEY_TO_SUBSYSTEM.items():
        assert subsystem in SUBSYSTEMS, f"{key} -> {subsystem} not a known subsystem"


def test_every_mapped_key_has_at_least_one_fix():
    for key in _KEY_TO_SUBSYSTEM:
        assert lookup_fixes(key, "FAIL"), f"no fixes for {key}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/unit/panels/test_catalog.py -v`
Expected: FAIL with `ImportError: cannot import name '_KEY_TO_SUBSYSTEM' from 'robobench.panels.catalog'`.

- [ ] **Step 3: Rewrite `catalog.py`**

Replace `src/robobench/panels/catalog.py` with:

```python
"""Failure catalog: maps each diagnostic check to candidate causes + fixes.

This is the "tell me how to fix it" half of robobench. When a panel reports
WARN or FAIL, the server attaches matching cases so the user sees concrete next
steps, not just a red light. The fixes live as data in
``robobench/data/cases/*.yaml`` (loaded via ``robobench.cases``); this module
maps robobench's internal panel/aspect keys onto the robot-agnostic
``subsystem`` vocabulary and projects matching cases to the
``{cause, fix, link}`` shape the dashboard panels expect.
"""

from __future__ import annotations

from robobench.cases import find_cases, load_cases

# robobench's internal panel/aspect keys -> robot-agnostic case subsystem.
_KEY_TO_SUBSYSTEM: dict[str, str] = {
    "dds_graph": "networking",
    "discovery_server_ok": "networking",
    "rpi_reachable": "networking",
    "clock_offset": "time_sync",
    "clock_synced": "time_sync",
    "tf_tree": "transform",
    "sensor_rate": "sensor",
    "tb4_nodes_present": "lifecycle",
    "create3_topics": "base",
    "odom_publishing": "base",
}


def lookup_fixes(
    check_name: str, status: str, *, robot_model: str | None = None
) -> list[dict]:
    """Return catalog fixes for a check when its status is WARN/FAIL.

    OK/UNKNOWN -> [] (nothing to fix). Unknown check names -> [] (no canned
    advice yet) rather than raising. Each entry is ``{"cause", "fix", "link"}``
    for backward compatibility with the dashboard panels. ``robot_model=None``
    (the default) returns every case in the matched subsystem.
    """
    if status not in ("WARN", "FAIL"):
        return []
    subsystem = _KEY_TO_SUBSYSTEM.get(check_name)
    if subsystem is None:
        return []
    cases = find_cases(load_cases(), subsystem=subsystem, robot_model=robot_model)
    return [
        {"cause": c.cause, "fix": c.fix, "link": c.links[0] if c.links else None}
        for c in cases
    ]
```

- [ ] **Step 4: Run the catalog test to verify it passes**

Run: `python -m pytest tests/unit/panels/test_catalog.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Run the consumer tests to confirm no behavior regression**

Run: `python -m pytest tests/unit/panels/test_server.py tests/unit/panels/test_connectivity.py -v`
Expected: PASS — these assert only `len(fixes) >= 1` / `fixes == []`, which still holds. If any fails, the matched subsystem has no shipped case for that FAIL path (re-check Task 3).

- [ ] **Step 6: Lint**

Run: `ruff check src/robobench/panels/catalog.py tests/unit/panels/test_catalog.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/robobench/panels/catalog.py tests/unit/panels/test_catalog.py
git commit -m "refactor(catalog): read fixes from the case library (dedupe + odom gap)"
```

---

## Task 5: Release — version bump + changelog

**Files:**
- Modify: `src/robobench/__init__.py`
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Run the full suite + lint (pre-release gate)**

Run: `python -m pytest`
Expected: PASS — all existing tests plus the new ones (Task 1: 11, Task 2: 7, Task 3: 5, Task 4: 8 = 31 added), so the suite grows from 241 to ≈ 272.

Run: `ruff check src tests`
Expected: no errors.

- [ ] **Step 2: Bump the package version**

In `src/robobench/__init__.py` change:

```python
__version__ = "0.14.0a0"
```

to:

```python
__version__ = "0.15.0a0"
```

In `pyproject.toml` change `version = "0.14.0a0"` to `version = "0.15.0a0"`.

- [ ] **Step 3: Add the changelog entry**

In `CHANGELOG.md`, insert this block directly above the previous most-recent
release entry (match the file's existing heading style):

```markdown
## [0.15.0a0] - 2026-05-31

### Changed
- Promoted the hardcoded failure catalog into a robot-agnostic, versioned **case**
  format under `robobench/data/cases/*.yaml`, loaded via the new `robobench.cases`
  module. The dashboard panels are unchanged; fixes are now data — deduped and
  contributable as plain files.

### Added
- `robobench.cases`: `Case`, `load_cases`, `find_cases`, `validate_case`, and the
  six-value `SUBSYSTEMS` vocabulary (`networking`, `time_sync`, `transform`,
  `sensor`, `lifecycle`, `base`).
- A `base` case for the previously-uncatalogued `odom_publishing` failure.
```

- [ ] **Step 4: Verify the version is consistent**

Run: `python -c "import robobench; print(robobench.__version__)"`
Expected: `0.15.0a0`.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/__init__.py pyproject.toml CHANGELOG.md
git commit -m "chore: release v0.15.0a0 (case schema + catalog-as-data)"
```

- [ ] **Step 6: Tag (coordinator, after review)**

The coordinator tags + pushes after the final review:

```bash
git tag v0.15.0a0
git push && git push --tags
```

---

## Done criteria

- `robobench.cases` module exists with `Case`, `SUBSYSTEMS`, `validate_case`, `load_cases`, `find_cases`.
- 14 verified YAML cases ship under `src/robobench/data/cases/` and are packaged via `pyproject.toml`.
- `panels.catalog.lookup_fixes` is data-driven; `server.py` and `connectivity.py` are unedited and their tests pass.
- The `odom_publishing` gap is closed.
- Full suite green, ruff clean, version `0.15.0a0`.
