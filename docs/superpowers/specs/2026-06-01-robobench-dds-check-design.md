# `robobench dds-check` — Design Spec

**Date:** 2026-06-01
**Status:** Approved (brainstorming) — pending implementation plan
**Topic:** A deterministic, offline command that lints the **workstation's** FastDDS Discovery Server environment and tells the user whether their shell is actually configured to see the robot's graph — catching the CLIENT-vs-SUPER_CLIENT / wrong-RMW / missing-server gotcha before they waste time debugging a robot that's actually fine.

## Problem

robobench connects to the robot via a FastDDS **Discovery Server** (see
`docs/architecture.md` §5). For a workstation participant to connect **and see
the full graph**, three env settings must agree:

- `RMW_IMPLEMENTATION=rmw_fastrtps_cpp` (Discovery Server is FastDDS-only),
- `ROS_DISCOVERY_SERVER=<robot-ip>:<port>` (unicast, not multicast),
- `ROS_SUPER_CLIENT=True` (a plain CLIENT connects but only sees what the server
  forwards; a SUPER_CLIENT gets the whole graph — required for `ros2 topic list`
  / `ros2 node list`).

The single most common, most confusing failure of this mode is omitting
`ROS_SUPER_CLIENT`: you connect fine, but `ros2 topic list` is **empty** even
though the robot is healthy. robobench ships a catalog case for it
(`connected-as-client-not-super-client`, v0.15.1a0), but nothing **detects** the
condition — the user has to already suspect it and read the case.

robobench's own commands don't expose this gap (the probe SSHes to the robot and
introspects there as a super-client; the dashboard sets its own env via
`panels/bridge.py::dds_env`). So a user's broken shell env never breaks
robobench — but it silently breaks **their own** `ros2` CLI and nodes. A
`dds-check` command closes that blind spot.

## Design decisions (resolved during brainstorming)

1. **Deterministic env-lint, not a live graph-count comparison.** Detection
   inspects the workstation's env vars against the expected server. The
   "SSH-ground-truth vs local-view" comparison is genuinely robobench's unique
   trick, but it needs local ROS2 + reproducing the user's shell view, and for
   *this* failure the env **is** the diagnosis (if `ROS_SUPER_CLIENT` is unset,
   that's the answer; measuring the empty graph only confirms it). The live
   comparison is scoped out as a clean future tier (`dds-check --live`).
2. **Pure linter, no ROS2 / SSH / network.** `lint_dds_env(environ,
   expected_server)` is a pure function over an injected env dict → exhaustively
   unit-testable, consistent with the rest of robobench.
3. **Standalone `robobench dds-check`, `--config` optional.** Conceptually it
   lints *your workstation*, not the *robot's* bring-up — so it's its own command,
   not folded into `preflight`. `--config` is optional: with it, the env's server
   is cross-checked against `ip:discovery_port`; without it, the other checks
   still run. Works with **zero setup and no robot**.
4. **Reuse the case at the CLI layer.** On a super-client error, the command also
   surfaces the `connected-as-client-not-super-client` case fix (via
   `robobench.cases`) so guidance is single-sourced. The pure linter stays
   case-library-free.
5. **No `--robot`.** This is robot-agnostic (it lints the local env), unlike the
   other subcommands.

## The linter: `src/robobench/dds_check.py` (pure)

```python
from collections.abc import Mapping
from dataclasses import dataclass

_FASTRTPS = "rmw_fastrtps_cpp"
_TRUTHY = frozenset({"true", "1", "yes"})


@dataclass(frozen=True)
class DdsFinding:
    level: str     # "ok" | "warn" | "error"
    check: str     # "rmw" | "discovery_server" | "super_client"
    message: str


def lint_dds_env(
    environ: Mapping[str, str], expected_server: str | None = None
) -> list[DdsFinding]: ...
```

`lint_dds_env` always returns exactly three findings, in this order:

| check | condition | level | message (shape) |
|-------|-----------|-------|-----------------|
| `rmw` | `RMW_IMPLEMENTATION` unset/empty | warn | "RMW_IMPLEMENTATION not set — relying on the ROS distro default; export `rmw_fastrtps_cpp` to be sure the Discovery Server works." |
| `rmw` | set, ≠ `rmw_fastrtps_cpp` | error | "RMW_IMPLEMENTATION=`<x>` — the FastDDS Discovery Server needs `rmw_fastrtps_cpp`; `<x>` can't join it." |
| `rmw` | `rmw_fastrtps_cpp` | ok | "RMW_IMPLEMENTATION=rmw_fastrtps_cpp" |
| `discovery_server` | `ROS_DISCOVERY_SERVER` unset/empty | error | "ROS_DISCOVERY_SERVER not set — you're on Simple Discovery (multicast), which won't reach the robot's Discovery Server." |
| `discovery_server` | set, `expected_server` given and not a substring of it | warn | "ROS_DISCOVERY_SERVER=`<v>` but config expects `<expected>`." |
| `discovery_server` | set (matches expected, or no expected given) | ok | "ROS_DISCOVERY_SERVER=`<v>`" (append " (matches config)" when matched) |
| `super_client` | `ROS_SUPER_CLIENT` truthy | ok | "ROS_SUPER_CLIENT=`<v>`" |
| `super_client` | not truthy, but `FASTRTPS_DEFAULT_PROFILES_FILE` set | ok | "ROS_SUPER_CLIENT not set; using FASTRTPS_DEFAULT_PROFILES_FILE (ensure that profile declares SUPER_CLIENT)." |
| `super_client` | not truthy, no XML, **and** `ROS_DISCOVERY_SERVER` set | error | "ROS_SUPER_CLIENT not set — connected as a plain CLIENT; `ros2 topic list`/`node list` will look empty even though the robot is fine. Fix: export ROS_SUPER_CLIENT=True." |
| `super_client` | not truthy, no XML, `ROS_DISCOVERY_SERVER` **unset** | warn | "ROS_SUPER_CLIENT not set." |

- Truthy test: `environ.get("ROS_SUPER_CLIENT", "").strip().lower() in _TRUTHY`.
- The super-client **error** only fires when `ROS_DISCOVERY_SERVER` is set —
  otherwise the missing server is the headline problem and super-client is moot
  (reported as a mild warn so the output is still complete).
- `expected_server` match is a substring test (`expected_server in value`)
  because `ROS_DISCOVERY_SERVER` may be a `;`-separated list.

## CLI: `src/robobench/cli.py` — `dds-check` subcommand + `_cmd_dds_check`

- Subparser `dds-check`: a single optional `--config` (no `--robot`).
- `_cmd_dds_check(args)`:
  1. `expected = None`; if `args.config`: `kwargs = load_adapter_config(Path(args.config))`,
     `expected = f"{kwargs['ip']}:{kwargs['discovery_port']}"`.
     (Bad/missing config path → `load_adapter_config` raises; `main()` already
     catches `FileNotFoundError`/`ValueError` → clean exit 2.)
  2. `findings = lint_dds_env(dict(os.environ), expected)`.
  3. Print each finding as `[dds-check] <message>    <OK|WARN|ERROR>` (level
     upper-cased, right-aligned tag).
  4. If any finding has `check == "super_client"` and `level == "error"`, also
     print the `connected-as-client-not-super-client` case's `fix` (looked up via
     `robobench.cases.load_cases()` — `next(c for c in load_cases() if c.id == …)`,
     guarded so a missing case never crashes the command).
  5. `errors = [f for f in findings if f.level == "error"]`. Print a summary line:
     - errors: `f"result: {len(errors)} error(s) — your shell won't see the robot's graph"`, return 1.
     - none: `"result: OK — your shell is configured to see the robot's graph"`
       (warnings, if any, were already printed), return 0.

### Output example
```
$ robobench dds-check --config config.yaml
[dds-check] RMW_IMPLEMENTATION=rmw_fastrtps_cpp                       OK
[dds-check] ROS_DISCOVERY_SERVER=192.168.50.31:11811 (matches config) OK
[dds-check] ROS_SUPER_CLIENT not set — connected as a plain CLIENT;
            ros2 topic list will look empty even though the robot is fine.
            Fix: export ROS_SUPER_CLIENT=True                          ERROR
  -> Export ROS_SUPER_CLIENT=True (alongside RMW_IMPLEMENTATION=rmw_fastrtps_cpp
     and ROS_DISCOVERY_SERVER=<robot-ip>:<port>), or point
     FASTRTPS_DEFAULT_PROFILES_FILE at a super_client XML profile, then retry.
result: 1 error(s) — your shell won't see the robot's graph
```

## Data flow
1. User runs `robobench dds-check [--config config.yaml]`.
2. CLI computes `expected_server` from config (if given) + reads `os.environ`.
3. `lint_dds_env` returns three findings (pure).
4. CLI prints findings + (on super-client error) the matching case fix; exits 0/1.

No robot, no ROS2, no SSH — verifiable end to end in tests.

## Error handling
- Missing/invalid `--config` → handled by existing `main()` catch → exit 2, clean message.
- The case lookup is guarded (`next(..., None)`); a missing/renamed case degrades
  to "no extra fix text", never a crash.
- `lint_dds_env` never raises — every branch returns a finding.

## Testing strategy (no hardware, no ROS2)
- **`lint_dds_env`** (pure, injected env dict), one assertion per row of the rule
  table:
  - rmw: unset → warn; `rmw_cyclonedds_cpp` → error; `rmw_fastrtps_cpp` → ok.
  - discovery_server: unset → error; set with mismatching `expected_server` → warn;
    set matching expected → ok ("matches config"); set with no expected → ok.
  - super_client: truthy variants (`True`/`true`/`1`) → ok; XML set (no super) → ok;
    not-super + no-XML + server-set → error; not-super + no-XML + server-unset → warn.
  - a fully-correct env → all three `ok`, zero errors.
  - a fully-broken env (cyclone + no server + no super) → rmw error + server error
    + super warn (super is warn because server is unset).
- **`_cmd_dds_check`** (CLI): monkeypatch `os.environ` (or pass via a fake) +
  a tmp `config.yaml`:
  - broken super-client env → exit 1, output contains "plain CLIENT" and the
    case fix text.
  - correct env → exit 0, output contains "result: OK".
  - no `--config` → still runs (no server cross-check), exits per env.
- All via injected env / `tmp_path`; no network/SSH/rclpy.

## Out of scope (YAGNI)
- **`dds-check --live`** — the SSH robot-side-count vs local-view comparison
  (the "uniquely positioned" confirmation tier). Future, needs local ROS2.
- Parsing/validating the contents of a `FASTRTPS_DEFAULT_PROFILES_FILE` XML
  (we trust that the user set it intentionally; we only note it).
- Auto-fixing the env (printing `export` lines is guidance; we don't write to the
  user's shell rc).
- Multi-server / non-zero server-id setups (robobench assumes server id 0).
- A dashboard panel for this (the dashboard already sets its own env correctly;
  this check is for the user's *own* shell).

## Honest caveats
- Pure env + config read; fully unit-testable, no hardware (like `report`/`init`).
- The lint reflects the env **robobench sees** (the process's `os.environ`). If a
  user's `ros2` runs in a different shell with different exports, the check
  describes robobench's environment, not that other shell — the output names the
  exact vars so the user can compare. This is the inherent limit of env-linting
  and the reason the `--live` tier exists as a future option.
