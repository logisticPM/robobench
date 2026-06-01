# robobench Case Schema + Catalog-as-Data — Design Spec

**Date:** 2026-05-31
**Status:** Approved (brainstorming) — pending implementation plan
**Topic:** Promote the hardcoded `FAILURE_CATALOG` into a robot-agnostic, versioned, file-based **case** format with a loader and a schema validator, keeping the dashboard/connectivity consumers behaving identically. This is the one-way-door data format that a future community case repo (`sync`/`search`) will build on — but none of that networked machinery is in this spec.

## Problem

robobench's "how to fix it" half lives in `src/robobench/panels/catalog.py` as
`FAILURE_CATALOG: dict[str, list[dict]]` — a hardcoded dict keyed by a flat
string that *mixes two namespaces*: dashboard panel checks (`clock_offset`,
`sensor_rate`, `tf_tree`, `dds_graph`) and `RobotState` aspect names
(`rpi_reachable`, `discovery_server_ok`, `clock_synced`, `create3_topics`,
`tb4_nodes_present`). Each entry is `{"cause", "fix", "link"}`. It is consumed in
two places via `lookup_fixes(check_name, status)`:

- `panels/server.py` — the four main panels (clock/sensor/tf/dds).
- `panels/connectivity.py` — the DDS-blind fallback panel (keyed by aspect).

(`recover`/`report` do **not** read the catalog — they use the engine ladder.)

Three structural problems make this unsuitable as the foundation for a shared,
community-grown knowledge base:

1. **Not contributable.** Fixes live in Python source. A user who solved a new
   failure can't add it without editing code and opening a code PR against the
   core package.
2. **Not robot-agnostic.** The keys are robobench/TB4-internal names. A
   contributor on a Jackal has no `discovery_server_ok` aspect to key on.
3. **No provenance, no structure.** There is no notion of *who* contributed a
   fix or whether it's *verified*, and no machine-usable match metadata (robot
   model, ROS distro, tags) beyond the single flat key.

There is also a concrete content gap: the `odom_publishing` aspect has **no**
catalog entry today.

This spec promotes the catalog into a structured, robot-agnostic, file-based
format so that (a) the data is published and contributable as plain files, and
(b) the later `sync`/`search` step is purely additive. It deliberately does
**not** build any networked or matching machinery.

## Design decisions (resolved during brainstorming)

1. **Structured match block, robot-agnostic (one-way door).** Each case carries
   a `match` block — `{subsystem, tags, robot_model?, ros_distro?}` — plus
   human-readable `title`/`cause`/`fix`/`verify?`/`links`. The *match logic* for
   this spec stays simple (subsystem lookup); `tags`/`ros_distro` are recorded
   but not yet used to match. This future-proofs the format without overbuilding
   matching against an empty corpus and a single adapter.
2. **Controlled `subsystem` vocabulary + free `tags`.** A case's symptom
   category is one of six robot-agnostic values: `networking`, `time_sync`,
   `transform`, `sensor`, `lifecycle`, `base`. robobench's internal panel/aspect
   keys map onto these via a small table. Free-text `tags` add granularity
   without breaking consistency. (Rejected: reusing robobench's TB4-internal keys
   as the public vocabulary; free-text-only categories.)
3. **Intentional dedupe + slight coarsening.** Today the clock-drift fix is
   stored *twice* (`clock_offset` and `clock_synced`). Grouping by subsystem
   dedupes it, and a panel now shows *all* cases in its subsystem. This is a
   deliberate, documented behavior change (better, deduped) — existing
   dashboard/connectivity tests must update their expected fix lists.
4. **Flat layout, one file per case.** `src/robobench/data/cases/<id>.yaml`.
   Subsystem is a field, not a folder. Cleanest PR diffs, no merge conflicts —
   the community-future rationale.
5. **`odom_publishing` gap closed.** The refactor adds a `base` case for it.
6. **Consumers untouched.** `lookup_fixes(check_name, status)` keeps its exact
   signature (plus an optional keyword-only `robot_model=None`); `server.py` and
   `connectivity.py` are not edited.
7. **100% unit-testable, zero hardware.** Pure file reads + dataclasses, like
   `init`/`report`.

## The case schema

One YAML file per case in `src/robobench/data/cases/<id>.yaml`:

```yaml
id: discovery-server-not-listening      # stable unique slug ([a-z0-9-]+)
schema_version: 1
provenance: verified                    # verified | community
contributed_by: robobench               # free-text handle
match:
  subsystem: networking                 # controlled vocab (required)
  tags: [discovery-server, fastdds]     # free-text list (optional, default [])
  robot_model: turtlebot4               # optional; omitted/null = any robot
  ros_distro: [humble, jazzy]           # optional list; omitted = any distro
title: "FastDDS Discovery Server not listening"
cause: "The FastDDS Discovery Server isn't listening on the robot."
fix: "SSH in and `sudo systemctl restart discovery.service`; confirm port 11811 with `ss -ulnp | grep 11811`."
verify: "`robobench preflight` shows discovery_server_ok = true."   # optional
links:
  - "https://github.com/ros-navigation/navigation2/issues/3560"     # optional, default []
```

**Field reference:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | str | yes | Unique slug `[a-z0-9-]+`; also the filename stem |
| `schema_version` | int | yes | Must equal `1` (known version) |
| `provenance` | str | yes | `verified` or `community` |
| `contributed_by` | str | yes | Free-text author handle |
| `match.subsystem` | str | yes | One of the six controlled values |
| `match.tags` | list[str] | no | Default `[]` |
| `match.robot_model` | str \| null | no | Omitted/null ⇒ applies to any robot |
| `match.ros_distro` | list[str] | no | Default `[]` ⇒ any distro |
| `title` | str | yes | Short headline |
| `cause` | str | yes | One-line root cause |
| `fix` | str | yes | Actionable fix (may contain backticked commands) |
| `verify` | str \| null | no | How to confirm the fix worked |
| `links` | list[str] | no | Default `[]`; reference URLs |

All shipped cases use `provenance: verified` and `contributed_by: robobench`.
The `community` value and a future second load directory exist for the later
`sync` step; **no community cases ship in this spec.**

Generic cases (clock drift, QoS mismatch, TF publisher died, network
saturation) **omit `robot_model`** so they apply to any robot. TB4-specific
cases (Create3, `discovery.service`, `turtlebot4` service) set
`robot_model: turtlebot4`. This exercises the robot-agnostic design from day one.

## Controlled subsystem vocabulary + key mapping

Six values: `networking`, `time_sync`, `transform`, `sensor`, `lifecycle`,
`base`.

robobench's internal keys map onto them (`_KEY_TO_SUBSYSTEM` in `catalog.py`):

| internal key (panel/aspect) | subsystem |
|---|---|
| `dds_graph`, `discovery_server_ok`, `rpi_reachable` | networking |
| `clock_offset`, `clock_synced` | time_sync |
| `tf_tree` | transform |
| `sensor_rate` | sensor |
| `tb4_nodes_present` | lifecycle |
| `create3_topics`, `odom_publishing` | base |

## Architecture

A new pure module `src/robobench/cases/` owns the schema, loader, and validator.
`panels/catalog.py` is reimplemented to read from it while keeping its public
function. No network, SSH, or rclpy.

```
src/robobench/cases/__init__.py   -- Case dataclass, SUBSYSTEMS, load_cases, find_cases
src/robobench/cases/validate.py   -- validate_case (schema validation)
src/robobench/data/cases/*.yaml   -- 14 shipped verified cases (packaged data)
src/robobench/panels/catalog.py   -- _KEY_TO_SUBSYSTEM + reimplemented lookup_fixes
```

### `src/robobench/cases/__init__.py`

```python
SUBSYSTEMS: frozenset[str] = frozenset(
    {"networking", "time_sync", "transform", "sensor", "lifecycle", "base"}
)

@dataclass(frozen=True)
class Case:
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

def load_cases(dirs: Sequence[Path] | None = None) -> list[Case]: ...
def find_cases(
    cases: Iterable[Case], *, subsystem: str, robot_model: str | None = None
) -> list[Case]: ...
```

- The YAML's nested `match:` block is **flattened** into the `Case` dataclass
  fields (`subsystem`, `tags`, `robot_model`, `ros_distro`) for ergonomic
  consumers. Lists become tuples (frozen dataclass).
- `load_cases(dirs=None)` — `dirs=None` resolves to the packaged data dir via
  `importlib.resources.files("robobench") / "data" / "cases"` (wheel-safe). Reads
  every `*.yaml`, runs `validate_case` on each, and **raises**
  `CaseValidationError` (listing file + errors) on the first invalid file — the
  packaged data is curated, so an invalid shipped case is a build bug that must
  fail loudly. Results are cached (an internal `functools.lru_cache` keyed by the
  resolved dir tuple; `dirs=None` caches the default load). The `dirs` parameter
  exists so a future synced community dir is just an extra entry — but only the
  packaged dir loads here. (Tolerant skip-invalid behavior for community dirs is
  deferred to the `sync` step.)
- `find_cases(...)` — returns cases where `c.subsystem == subsystem` **and**
  (`robot_model is None` **or** `c.robot_model is None` **or**
  `c.robot_model == robot_model`). So a `None` query returns all cases in the
  subsystem; a concrete query returns generic + that-robot cases and excludes
  other robots'.

### `src/robobench/cases/validate.py`

```python
def validate_case(raw: dict) -> list[str]: ...
```

Returns a list of human-readable error strings (empty list ⇒ valid). Checks:

- Required keys present: `id`, `schema_version`, `provenance`, `contributed_by`,
  `match`, `title`, `cause`, `fix`.
- `id` is a non-empty `[a-z0-9-]+` slug.
- `schema_version == 1`.
- `provenance in {"verified", "community"}`.
- `match` is a dict; `match.subsystem in SUBSYSTEMS`; `match.tags` (if present)
  is a list of str; `match.robot_model` (if present) is str or null;
  `match.ros_distro` (if present) is a list of str.
- `title`, `cause`, `fix` are non-empty str; `verify` (if present) is str;
  `links` (if present) is a list of str.

`validate_case` operates on the raw parsed dict (not the `Case`) so it can report
on contributor files before construction.

### `src/robobench/panels/catalog.py` (reimplemented)

```python
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

- Signature stays backward compatible: existing `lookup_fixes(name, status)`
  calls work unchanged; `robot_model` is keyword-only with default `None`
  (no robot filter — returns all cases in the subsystem, matching today's "show
  the relevant fixes" behavior).
- The old `FAILURE_CATALOG` dict is **removed** (its content moves into the YAML
  files). `lookup_fixes` keeps the same `{cause, fix, link}` output shape.

## The 14 shipped cases

Converted from the existing catalog, deduped, with the `odom_publishing` gap
filled. `robot_model` shown where set (otherwise omitted = any robot).

**networking (4):**
- `rpi-unreachable` — RPi off / wrong IP / not on network. *(any)*
- `discovery-server-not-listening` — Discovery Server not up (`discovery.service`). *(turtlebot4)*
- `discovery-server-unreachable-from-workstation` — `ROS_DISCOVERY_SERVER` / port 11811. *(any)*
- `node-dropped-under-discovery-server` — FastDDS drops late joiners (Nav2 #3560). *(any)*

**time_sync (2):**
- `clocks-drifted` — workstation/robot clocks drifted (merged dup). *(any)*
- `workstation-not-serving-ntp` — chrony `allow` + `local stratum`. *(any)*

**transform (3):**
- `tf-publisher-died` — a TF publisher died, stale/broken edge. *(any)*
- `tf-stale-from-clock-skew` — clock skew makes fresh transforms look stale. *(any)*
- `create3-not-bridging-odom-tf` — run `robobench odom-tf`. *(turtlebot4)*

**sensor (2):**
- `sensor-not-publishing-or-qos-mismatch` — driver down / QoS mismatch. *(any)*
- `network-saturation-dropping-sensor-data` — WiFi/ethernet, `ros2 topic hz`. *(any)*

**lifecycle (1):**
- `nav-nodes-did-not-activate` — re-run lifecycle activator; `systemctl status turtlebot4`. *(turtlebot4)*

**base (2):**
- `create3-base-not-publishing-topics` — restart Create3 app / web UI. *(turtlebot4)*
- `odom-not-publishing` — **NEW** (gap): `/odom` absent; check Create3 / `robobench odom-tf`. *(turtlebot4)*

Each subsystem has ≥1 case; every key in `_KEY_TO_SUBSYSTEM` maps to a subsystem
with ≥1 case; `odom_publishing` is now covered.

## Packaging

The YAML data files must ship in the wheel. `pyproject.toml` already uses
setuptools with a `[tool.setuptools.package-data]` table (`"robobench.panels" =
["static/**/*"]`); add a sibling entry for the top-level `robobench` package
(the `data/` dir is package data, not a subpackage):

```toml
[tool.setuptools.package-data]
"robobench.panels" = ["static/**/*"]   # existing
"robobench" = ["data/cases/*.yaml"]    # new
```

At runtime `load_cases()` resolves the dir with
`importlib.resources.files("robobench") / "data" / "cases"`, which works for both
editable (`pip install -e`) and wheel installs. YAML parsing reuses the existing
**PyYAML ≥6.0** dependency (already used by `config.py`). No new runtime
dependency.

## Data flow

1. Dashboard panel goes WARN/FAIL → `server.py`/`connectivity.py` call
   `lookup_fixes(key, status)` (unchanged call sites).
2. `lookup_fixes` maps key → subsystem → `find_cases(load_cases(), …)` →
   projects each `Case` to `{cause, fix, link}`.
3. `load_cases()` reads + validates the packaged YAML once (cached).
4. The panel renders the fixes exactly as before.

## Error handling

- **Invalid packaged case** → `load_cases()` raises `CaseValidationError`
  (file + error list). A test validates every shipped case, so this surfaces at
  test time, not runtime.
- **Malformed YAML in the packaged dir** → raises (same rationale).
- **Unknown `check_name`** in `lookup_fixes` → `[]` (unchanged: missing mapping
  just means "no canned advice").
- **`status` not WARN/FAIL** → `[]` (unchanged).
- Tolerant skip-invalid loading for a future community dir is **deferred** to the
  `sync` step (not implemented here).

## Testing strategy (no hardware)

- **`validate_case`:** a fully valid raw dict → `[]`; each broken variant yields
  a specific error — missing required key, `schema_version != 1`, bad
  `provenance`, `subsystem` not in vocab, `tags`/`links` not a list, bad slug.
- **`load_cases`:** a `tmp_path` dir with two known YAML cases → exactly those
  `Case`s, lists coerced to tuples, nested `match` flattened; a malformed/invalid
  YAML in the dir → raises `CaseValidationError`; the default (no-arg) load
  returns the packaged set.
- **`find_cases`:** subsystem filter selects only that subsystem; `robot_model=None`
  returns generic + robot-specific; `robot_model="turtlebot4"` returns generic +
  turtlebot4 and **excludes** a synthetic `jackal` case.
- **Shipped-data integrity:** every packaged case passes `validate_case`; every
  value in `_KEY_TO_SUBSYSTEM` is in `SUBSYSTEMS`; every subsystem has ≥1 shipped
  case; `odom_publishing` maps to a subsystem with a case.
- **`lookup_fixes` backward-compat:** returns a list of `{cause, fix, link}`;
  `OK`/`UNKNOWN` status → `[]`; unknown `check_name` → `[]`;
  `lookup_fixes("clock_offset", "FAIL")` returns the `time_sync` cases.
- **Consumer tests updated:** existing `server.py`/`connectivity.py` tests that
  assert on exact fix lists are updated for the dedupe/coarsening (e.g.
  `clock_synced` now returns both `time_sync` cases). No production edits to those
  two files.
- All via `tmp_path` / packaged data; no network/SSH/rclpy.

## Out of scope (YAGNI — the later step)

- `robobench sync` (cloning a community case repo) and the `~/.robobench/cases/`
  load directory.
- Matching cases against a *live* failure / `RobotState`, scoring, ranking.
- `search`, a `robobench cases` CLI, browse/list commands.
- Log-signature / regex matchers; using `tags`/`ros_distro` in matching.
- The community repo itself, contributor docs, PR templates for cases.
- LLM / any non-deterministic interpretation.
- Tolerant skip-invalid loading of untrusted dirs.

## Honest caveats

- Pure Python + file reads; fully unit-testable, no hardware (like `init`/`report`).
- The value of this step is almost entirely the *format* (the one-way door), not
  a new user-visible capability — the dashboard shows the same kind of fixes, just
  sourced from data and slightly deduped. The payoff is realized later, when
  `sync`/`search` and community contributions build on this format. Shipping it
  now is justified because the schema is the irreversible decision and is cheapest
  to get right before any external case exists.
- The match logic is intentionally minimal (subsystem + optional robot filter).
  `tags`/`ros_distro` are stored but unused until a later step needs them.
