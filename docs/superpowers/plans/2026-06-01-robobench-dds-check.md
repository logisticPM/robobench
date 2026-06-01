# `robobench dds-check` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `robobench dds-check` — a deterministic, offline command that lints the workstation's FastDDS Discovery Server environment and tells the user whether their shell is configured to see the robot's graph.

**Architecture:** A new pure module `robobench.dds_check` exposes `lint_dds_env(environ, expected_server) -> list[DdsFinding]` (three checks: rmw / discovery_server / super_client), with zero ROS2/SSH/network. A thin CLI command `_cmd_dds_check` reads `os.environ` + (optional) `config.yaml`, prints the findings, surfaces the `connected-as-client-not-super-client` case fix on a super-client error, and exits 0/1.

**Tech Stack:** Python 3.11+, argparse, pytest (with `monkeypatch`/`capsys`), ruff (line length 100). Spec: `docs/superpowers/specs/2026-06-01-robobench-dds-check-design.md`.

---

## Conventions for every task

- **Run with the project venv:** `.venv/Scripts/python.exe -m pytest …` and `.venv/Scripts/python.exe -m ruff check …`. Run from the repo root `C:/Users/chntw/Documents/robotic/robobench` (Windows, Git Bash).
- **TDD:** write the failing test, watch it fail, implement the minimum, watch it pass, commit.
- **Commits:** Conventional prefixes. **Do NOT add a `Co-Authored-By: Claude` trailer.** Identity is already configured — never run `git config`. Work on `main`; commit locally only (the coordinator tags/pushes after review).
- **ruff clean** (`ruff check src tests`), lines ≤ 100, double-quoted strings.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/robobench/dds_check.py` (create) | `DdsFinding` dataclass + `lint_dds_env` (pure linter, three checks) |
| `src/robobench/cli.py` (modify) | add `import os`; import `lint_dds_env`; register `dds-check` subparser; add `_cmd_dds_check` |
| `tests/unit/test_dds_check.py` (create) | exhaustive rule-table tests for `lint_dds_env` |
| `tests/unit/test_cli.py` (modify) | `_cmd_dds_check` via `main(["dds-check", …])` |
| `pyproject.toml` / `src/robobench/__init__.py` / `CHANGELOG.md` / `README.md` (modify) | release: version bump, changelog, CLI table row |

---

## Task 1: The pure linter — `robobench.dds_check`

**Files:**
- Create: `src/robobench/dds_check.py`
- Test: `tests/unit/test_dds_check.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_dds_check.py`:

```python
"""Tests for robobench.dds_check (pure env linter)."""

from __future__ import annotations

from robobench.dds_check import DdsFinding, lint_dds_env


def _by_check(findings: list[DdsFinding]) -> dict[str, DdsFinding]:
    return {f.check: f for f in findings}


def test_always_three_findings_in_order():
    findings = lint_dds_env({})
    assert [f.check for f in findings] == ["rmw", "discovery_server", "super_client"]


def test_all_correct_env_is_all_ok():
    env = {
        "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
        "ROS_DISCOVERY_SERVER": "192.168.50.31:11811",
        "ROS_SUPER_CLIENT": "True",
    }
    findings = lint_dds_env(env, "192.168.50.31:11811")
    assert all(f.level == "ok" for f in findings)


def test_rmw_unset_warns():
    env = {"ROS_DISCOVERY_SERVER": "x:1", "ROS_SUPER_CLIENT": "True"}
    assert _by_check(lint_dds_env(env))["rmw"].level == "warn"


def test_rmw_wrong_is_error():
    f = _by_check(lint_dds_env({"RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp"}))["rmw"]
    assert f.level == "error"
    assert "rmw_cyclonedds_cpp" in f.message


def test_discovery_server_unset_is_error():
    assert _by_check(lint_dds_env({}))["discovery_server"].level == "error"


def test_discovery_server_mismatch_warns():
    env = {"ROS_DISCOVERY_SERVER": "10.0.0.1:11811"}
    f = _by_check(lint_dds_env(env, "192.168.50.31:11811"))["discovery_server"]
    assert f.level == "warn"
    assert "192.168.50.31:11811" in f.message


def test_discovery_server_match_is_ok():
    env = {"ROS_DISCOVERY_SERVER": "192.168.50.31:11811"}
    f = _by_check(lint_dds_env(env, "192.168.50.31:11811"))["discovery_server"]
    assert f.level == "ok"
    assert "matches config" in f.message


def test_super_client_truthy_variants_ok():
    for value in ("True", "true", "1", "yes"):
        env = {"ROS_DISCOVERY_SERVER": "x:1", "ROS_SUPER_CLIENT": value}
        assert _by_check(lint_dds_env(env))["super_client"].level == "ok"


def test_super_client_xml_is_ok():
    env = {"ROS_DISCOVERY_SERVER": "x:1", "FASTRTPS_DEFAULT_PROFILES_FILE": "/p.xml"}
    assert _by_check(lint_dds_env(env))["super_client"].level == "ok"


def test_plain_client_with_server_is_error():
    f = _by_check(lint_dds_env({"ROS_DISCOVERY_SERVER": "x:1"}))["super_client"]
    assert f.level == "error"
    assert "plain CLIENT" in f.message


def test_super_client_unset_without_server_is_warn():
    # No server set -> the headline problem is the missing server; super-client
    # is a mild warn, not the dire CLIENT error.
    assert _by_check(lint_dds_env({}))["super_client"].level == "warn"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_dds_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'robobench.dds_check'`.

- [ ] **Step 3: Implement `dds_check.py`**

Create `src/robobench/dds_check.py`:

```python
"""Lint the workstation's FastDDS Discovery Server environment.

Pure function over an env mapping — no ROS2, SSH, or network. Tells the user
whether their shell is configured to actually see the robot's graph, catching
the CLIENT-vs-SUPER_CLIENT / wrong-RMW / missing-server gotcha. See
docs/architecture.md section 5 for the connection mode.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_FASTRTPS = "rmw_fastrtps_cpp"
_TRUTHY = frozenset({"true", "1", "yes", "on"})


@dataclass(frozen=True)
class DdsFinding:
    """One environment check result."""

    level: str  # "ok" | "warn" | "error"
    check: str  # "rmw" | "discovery_server" | "super_client"
    message: str


def _lint_rmw(environ: Mapping[str, str]) -> DdsFinding:
    rmw = environ.get("RMW_IMPLEMENTATION", "").strip()
    if not rmw:
        return DdsFinding(
            "warn",
            "rmw",
            "RMW_IMPLEMENTATION not set — relying on the ROS distro default; "
            "export rmw_fastrtps_cpp to be sure the Discovery Server works.",
        )
    if rmw != _FASTRTPS:
        return DdsFinding(
            "error",
            "rmw",
            f"RMW_IMPLEMENTATION={rmw} — the FastDDS Discovery Server needs "
            f"rmw_fastrtps_cpp; {rmw} can't join it.",
        )
    return DdsFinding("ok", "rmw", "RMW_IMPLEMENTATION=rmw_fastrtps_cpp")


def _lint_discovery_server(environ: Mapping[str, str], expected_server: str | None) -> DdsFinding:
    value = environ.get("ROS_DISCOVERY_SERVER", "").strip()
    if not value:
        return DdsFinding(
            "error",
            "discovery_server",
            "ROS_DISCOVERY_SERVER not set — you're on Simple Discovery (multicast), "
            "which won't reach the robot's Discovery Server.",
        )
    if expected_server and expected_server not in value:
        return DdsFinding(
            "warn",
            "discovery_server",
            f"ROS_DISCOVERY_SERVER={value} but config expects {expected_server}.",
        )
    suffix = " (matches config)" if expected_server else ""
    return DdsFinding("ok", "discovery_server", f"ROS_DISCOVERY_SERVER={value}{suffix}")


def _lint_super_client(environ: Mapping[str, str]) -> DdsFinding:
    raw = environ.get("ROS_SUPER_CLIENT", "")
    if raw.strip().lower() in _TRUTHY:
        return DdsFinding("ok", "super_client", f"ROS_SUPER_CLIENT={raw.strip()}")
    if environ.get("FASTRTPS_DEFAULT_PROFILES_FILE", "").strip():
        return DdsFinding(
            "ok",
            "super_client",
            "ROS_SUPER_CLIENT not set; using FASTRTPS_DEFAULT_PROFILES_FILE "
            "(ensure that profile declares SUPER_CLIENT).",
        )
    if environ.get("ROS_DISCOVERY_SERVER", "").strip():
        return DdsFinding(
            "error",
            "super_client",
            "ROS_SUPER_CLIENT not set — connected as a plain CLIENT; "
            "ros2 topic list/node list will look empty even though the robot is "
            "fine. Fix: export ROS_SUPER_CLIENT=True.",
        )
    return DdsFinding("warn", "super_client", "ROS_SUPER_CLIENT not set.")


def lint_dds_env(
    environ: Mapping[str, str], expected_server: str | None = None
) -> list[DdsFinding]:
    """Return findings for the three DDS env checks (rmw, server, super-client).

    Always returns exactly three findings in order. ``expected_server`` is the
    config's ``ip:port`` (omitted -> the server-address cross-check is skipped).
    Never raises.
    """
    return [
        _lint_rmw(environ),
        _lint_discovery_server(environ, expected_server),
        _lint_super_client(environ),
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_dds_check.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Lint**

Run: `.venv/Scripts/python.exe -m ruff check src/robobench/dds_check.py tests/unit/test_dds_check.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/robobench/dds_check.py tests/unit/test_dds_check.py
git commit -m "feat(dds-check): add pure DDS env linter (lint_dds_env)"
```

---

## Task 2: CLI `dds-check` subcommand

**Files:**
- Modify: `src/robobench/cli.py`
- Test: `tests/unit/test_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

Append to `tests/unit/test_cli.py`:

```python
def test_dds_check_flags_plain_client(monkeypatch, capsys):
    from robobench.cli import main

    monkeypatch.setenv("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp")
    monkeypatch.setenv("ROS_DISCOVERY_SERVER", "192.168.50.31:11811")
    monkeypatch.delenv("ROS_SUPER_CLIENT", raising=False)
    monkeypatch.delenv("FASTRTPS_DEFAULT_PROFILES_FILE", raising=False)

    rc = main(["dds-check"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "plain CLIENT" in out
    assert "ROS_SUPER_CLIENT=True" in out  # the reused case fix text


def test_dds_check_all_ok(monkeypatch, capsys):
    from robobench.cli import main

    monkeypatch.setenv("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp")
    monkeypatch.setenv("ROS_DISCOVERY_SERVER", "192.168.50.31:11811")
    monkeypatch.setenv("ROS_SUPER_CLIENT", "True")

    rc = main(["dds-check"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "result: OK" in out


def test_dds_check_cross_checks_config(monkeypatch, capsys, tmp_path):
    from pathlib import Path  # noqa: PLC0415

    from robobench.cli import main

    cfg = Path(tmp_path) / "config.yaml"
    cfg.write_text(
        'robot:\n'
        '  ip: "192.168.50.31"\n'
        '  ssh_user: "u"\n'
        '  ssh_pass: "p"\n'
        '  namespace: "tb"\n'
        'dds:\n'
        '  discovery_port: 11811\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp")
    monkeypatch.setenv("ROS_DISCOVERY_SERVER", "10.0.0.9:11811")  # wrong host
    monkeypatch.setenv("ROS_SUPER_CLIENT", "True")

    rc = main(["dds-check", "--config", str(cfg)])
    out = capsys.readouterr().out
    assert "config expects 192.168.50.31:11811" in out
    assert rc == 0  # a server mismatch is a warn, not an error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli.py -v -k dds_check`
Expected: FAIL — argparse exits with code 2 ("invalid choice: 'dds-check'") since the subcommand isn't registered yet.

- [ ] **Step 3: Add the `os` import and the linter import**

In `src/robobench/cli.py`, the stdlib import block currently is:

```python
import argparse
import dataclasses
import json
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
```

Add `import os` (alphabetical, after `json`):

```python
import argparse
import dataclasses
import json
import os
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
```

And add this import alongside the other `from robobench....` imports near the top (after the `from robobench.eventreport import ...` line):

```python
from robobench.dds_check import lint_dds_env
```

- [ ] **Step 4: Register the `dds-check` subparser**

In `_build_parser`, immediately after the `watch.set_defaults(func=_cmd_watch)` line, add:

```python
    dds_check = subparsers.add_parser(
        "dds-check",
        help="Lint your shell's DDS env (Discovery Server / SUPER_CLIENT / RMW).",
    )
    dds_check.add_argument(
        "--config",
        default=None,
        help="Optional: cross-check ROS_DISCOVERY_SERVER against config's ip:discovery_port.",
    )
    dds_check.set_defaults(func=_cmd_dds_check)
```

- [ ] **Step 5: Add the `_cmd_dds_check` function**

Add this function next to the other `_cmd_*` functions (e.g. directly after `_cmd_watch`):

```python
def _cmd_dds_check(args: argparse.Namespace) -> int:
    expected = None
    if args.config:
        kwargs = load_adapter_config(Path(args.config))
        expected = f"{kwargs['ip']}:{kwargs['discovery_port']}"

    findings = lint_dds_env(dict(os.environ), expected)
    for finding in findings:
        print(f"[dds-check] {finding.message}  [{finding.level.upper()}]")

    if any(f.check == "super_client" and f.level == "error" for f in findings):
        from robobench.cases import load_cases  # noqa: PLC0415

        case = next(
            (c for c in load_cases() if c.id == "connected-as-client-not-super-client"),
            None,
        )
        if case is not None:
            print(f"  -> {case.fix}")

    errors = [f for f in findings if f.level == "error"]
    if errors:
        print(f"result: {len(errors)} error(s) — your shell won't see the robot's graph")
        return 1
    print("result: OK — your shell is configured to see the robot's graph")
    return 0
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_cli.py -v -k dds_check`
Expected: PASS (3 tests).

- [ ] **Step 7: Lint**

Run: `.venv/Scripts/python.exe -m ruff check src/robobench/cli.py tests/unit/test_cli.py`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add src/robobench/cli.py tests/unit/test_cli.py
git commit -m "feat(dds-check): add dds-check CLI subcommand reusing the super-client case"
```

---

## Task 3: Docs + release (v0.16.0a0)

**Files:**
- Modify: `README.md`
- Modify: `src/robobench/__init__.py`
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Pre-release gate**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: ALL pass (the pre-existing suite + the 11 linter tests + 3 CLI tests = 14 added). Report the exact count.

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: no errors.

If anything fails, STOP and report BLOCKED — do not bump the version over a red suite.

- [ ] **Step 2: Add the CLI table row in `README.md`**

In `README.md`, the CLI table has rows like `| \`robobench watch\` | … |`. Add a row (place it after the `robobench report` row to group the no-robot/diagnostic commands):

```markdown
| `robobench dds-check` | Lint your shell's DDS env (Discovery Server / SUPER_CLIENT / RMW) — no robot needed |
```

- [ ] **Step 3: Bump the version**

In `src/robobench/__init__.py` change `__version__ = "0.15.1a0"` to `__version__ = "0.16.0a0"`.
In `pyproject.toml` change `version = "0.15.1a0"` to `version = "0.16.0a0"`.

- [ ] **Step 4: Add the changelog entry**

In `CHANGELOG.md`, insert directly under `## [Unreleased]` (match the existing `## [x.y.z] — YYYY-MM-DD` em-dash style):

```markdown
## [0.16.0a0] — 2026-06-01

### Added
- **`robobench dds-check`** — a deterministic, offline linter for the workstation's
  FastDDS Discovery Server environment. Checks `RMW_IMPLEMENTATION`,
  `ROS_DISCOVERY_SERVER` (optionally cross-checked against `config.yaml`), and
  `ROS_SUPER_CLIENT`, and tells you whether your shell can actually see the robot's
  graph — catching the "connected but `ros2 topic list` is empty" CLIENT-vs-
  SUPER_CLIENT gotcha. No robot, no ROS2 required.
```

- [ ] **Step 5: Verify version consistency**

Run: `.venv/Scripts/python.exe -c "import robobench; print(robobench.__version__)"`
Expected: `0.16.0a0`.

- [ ] **Step 6: Commit**

```bash
git add README.md src/robobench/__init__.py pyproject.toml CHANGELOG.md
git commit -m "chore: release v0.16.0a0 (robobench dds-check)"
```

- [ ] **Step 7: Tag (coordinator, after review)**

The coordinator tags + pushes after the final review:

```bash
git tag v0.16.0a0
git push origin main && git push origin v0.16.0a0
```

---

## Done criteria

- `robobench.dds_check.lint_dds_env` exists (pure, three findings, never raises).
- `robobench dds-check [--config …]` prints findings, surfaces the
  `connected-as-client-not-super-client` case fix on a super-client error, exits 0/1.
- `--config` optional; no `--robot`; bad config path → clean exit 2 via existing `main()` catch.
- Full suite green, ruff clean, version `0.16.0a0`.
- No `Co-Authored-By: Claude` trailers.
