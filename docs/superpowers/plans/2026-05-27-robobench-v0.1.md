# Robobench v0.1 Implementation Plan — Repository Bootstrap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap `robobench` — an open-source ROS2 platform for academic robot hardware bring-up and debugging — as a clean Apache-2.0 repository with a defined `RobotAdapter` interface, a first reference adapter for TurtleBot4, a `robobench` CLI, CI, contribution governance, and one end-to-end tutorial.

**Architecture:**
- v0.1 is **pure Python** (no ROS2 ament packages yet). The CLI invokes `subprocess`/`ssh` to interact with a robot, mirroring how the upstream `deploy.sh` does it. This lets students `pip install robobench` without first building a ROS2 workspace.
- The original `CS5335TurtleBot` repository is treated as a **reference implementation** (sibling directory, untouched). Code is imported into `examples/campus_guide/` and `ui/` only **after license clarification** (see Prerequisites).
- A `RobotAdapter` Abstract Base Class defines the contract for any robot the platform supports. `TurtleBot4Adapter` is the first reference implementation, exposing one concrete diagnostic method (`check_clock_offset`) in v0.1; remaining methods are scaffolded as `NotImplementedError` for later plans (Phase B+).
- ROS2 integration, the dashboard, diagnostic panels, the bring-up wizard, and the bring-up of the campus_guide demo are all deferred to **Phase B / C / D plans** (see "Future Plans" section at the bottom).

**Tech Stack:**
- Python 3.11+ (matches ROS2 Jazzy interpreter)
- `pytest` + `pytest-mock` for tests
- `ruff` for lint + format
- GitHub Actions for CI
- `argparse` for the CLI (no extra dep)
- `paramiko` deferred — v0.1 shells out to `ssh` via `subprocess` to avoid pulling in cryptography deps

**Repo root:** `C:\Users\chntw\Documents\robotic\robobench\` (already exists; this plan file is inside it)

**Reference repo:** `C:\Users\chntw\Documents\robotic\CS5335TurtleBot\` (sibling, do not modify)

---

## Prerequisites — RESOLVE BEFORE TASKS 5 & 6

The upstream `CS5335TurtleBot` repo has **no LICENSE file** (its own README confirms: *"License — Add/confirm license information for this repository (currently unspecified at top-level)"*). Under default copyright law, all rights are reserved, so we **cannot** copy code from it into an Apache-2.0 project without one of:

1. **Permission from original authors** (`En-PingSu` and any co-authors) to relicense their contribution as Apache 2.0 in this fork. Best path; preserves attribution and avoids re-implementation cost.
2. **Clean-room re-implementation** — read upstream as spec only, write fresh code in robobench. Slow and risks subtle drift, but legally safe.
3. **Confirm the human driving this plan is an original co-author** with rights to relicense their own contributions.

**Tasks 1-4 and 7-13 are unblocked** (they create greenfield content). **Tasks 5, 6, 14, 15, 17 and the campus-guide tutorial step assume the license question is resolved**; pause at Task 5 and confirm with the user which path was taken before proceeding.

---

## File Structure

```
robobench/
├── .editorconfig
├── .gitignore
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   ├── feature_request.md
│   │   └── hardware_issue.md
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── workflows/
│       └── ci.yml
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── LICENSE                              # Apache 2.0
├── NOTICE                               # Apache 2.0 attribution to upstream
├── README.md
├── pyproject.toml
├── src/
│   └── robobench/
│       ├── __init__.py                  # exports __version__
│       ├── cli.py                       # `robobench` entrypoint
│       ├── adapter_base.py              # RobotAdapter ABC
│       └── robots/
│           ├── __init__.py
│           └── turtlebot4.py            # TurtleBot4Adapter
├── examples/
│   └── campus_guide/                    # (Task 5, license-gated)
│       ├── README.md                    # attribution + how to run
│       └── code/                        # imported tree from upstream
├── ui/                                  # (Task 6, license-gated)
│   ├── README.md
│   ├── dashboard/                       # imported, untouched
│   └── speech_web_ui/                   # imported, untouched
├── docs/
│   ├── index.md                         # site landing copy (Markdown for now; MkDocs in Phase D)
│   ├── tutorials/
│   │   └── connect-turtlebot4.md
│   └── superpowers/
│       └── plans/
│           └── 2026-05-27-robobench-v0.1.md   # this file
└── tests/
    ├── __init__.py
    ├── unit/
    │   ├── __init__.py
    │   ├── test_adapter_base.py
    │   ├── test_cli.py
    │   └── robots/
    │       ├── __init__.py
    │       └── test_turtlebot4.py
    └── conftest.py
```

**Responsibilities:**
- `src/robobench/adapter_base.py`: defines the `RobotAdapter` ABC — the contract every robot adapter implements. Single responsibility: the interface.
- `src/robobench/robots/turtlebot4.py`: TurtleBot4-specific concrete adapter. Adapters in this folder are the only place vendor-specific knowledge lives.
- `src/robobench/cli.py`: argparse wiring. Translates CLI flags → adapter calls.
- `examples/campus_guide/`: the upstream demo, kept runnable as a reference. Robobench's diagnostics layer eventually consumes this as one of many "robots in the wild" to test against.
- `ui/`: the upstream dashboard + speech UI, kept as v0 baseline. Phase C overlays new diagnostic panels here.

---

## Task 1: Initialize empty repo

**Files:**
- Create: `.git/` (via `git init`)

- [ ] **Step 1: Initialize the git repository**

The folder already exists (this plan file lives inside it). Just init.

Run:
```bash
cd C:/Users/chntw/Documents/robotic/robobench
git init -b main
```

Expected: `Initialized empty Git repository in C:/Users/chntw/Documents/robotic/robobench/.git/`

- [ ] **Step 2: Configure repo-local identity (if needed)**

If `git config user.email` is unset globally, configure it here. Otherwise skip.
Run: `git config user.email` — if empty, ask the user how they want to be attributed.

- [ ] **Step 3: First commit with the plan file**

```bash
git add docs/superpowers/plans/2026-05-27-robobench-v0.1.md
git commit -m "chore: bootstrap robobench repo with v0.1 plan"
```

Expected: a commit hash printed, `main` branch created.

---

## Task 2: Add Apache 2.0 LICENSE

**Files:**
- Create: `LICENSE`
- Create: `NOTICE`

- [ ] **Step 1: Write the LICENSE file**

Create `LICENSE` with the full standard Apache 2.0 license text. Pull verbatim from <https://www.apache.org/licenses/LICENSE-2.0.txt>. Replace the `[yyyy]` and `[name of copyright owner]` placeholders in the boilerplate at the bottom with `2026` and `The Robobench Contributors`.

- [ ] **Step 2: Write the NOTICE file**

Create `NOTICE`:

```text
Robobench — Open-source ROS2 platform for robot hardware bring-up and debugging.
Copyright 2026 The Robobench Contributors.

This product includes work derived from the following projects:

- CS5335TurtleBot (https://github.com/En-PingSu/CS5335TurtleBot)
  Used as reference and, where licensed for redistribution, as imported code
  in examples/campus_guide/ and ui/. See examples/campus_guide/README.md for
  the exact license terms of imported portions.
```

- [ ] **Step 3: Commit**

```bash
git add LICENSE NOTICE
git commit -m "docs: add Apache 2.0 LICENSE and NOTICE"
```

---

## Task 3: Add .gitignore and .editorconfig

**Files:**
- Create: `.gitignore`
- Create: `.editorconfig`

- [ ] **Step 1: Write .gitignore**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
.eggs/
build/
dist/
.venv/
venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# ROS2 (relevant once Phase B+ adds ament packages)
install/
log/
build_isolated/

# Local secrets
.env
.env.local
*.openrouter_key
```

- [ ] **Step 2: Write .editorconfig**

```ini
root = true

[*]
indent_style = space
indent_size = 4
end_of_line = lf
charset = utf-8
trim_trailing_whitespace = true
insert_final_newline = true

[*.{yaml,yml,json,md}]
indent_size = 2

[*.{bat,cmd,ps1}]
end_of_line = crlf

[Makefile]
indent_style = tab
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore .editorconfig
git commit -m "chore: add .gitignore and .editorconfig"
```

---

## Task 4: Scaffold top-level folder structure

**Files:**
- Create: `src/robobench/__init__.py`
- Create: `src/robobench/robots/__init__.py`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/unit/robots/__init__.py`
- Create: `tests/conftest.py`
- Create: `examples/.gitkeep`
- Create: `ui/.gitkeep`
- Create: `robots/.gitkeep` (placeholder for future vendor-specific assets outside Python — e.g. URDF, maps; keeps the dir intentional)
- Create: `docs/index.md`

- [ ] **Step 1: Create `src/robobench/__init__.py`**

```python
"""Robobench — Open-source ROS2 platform for robot hardware bring-up and debugging."""

__version__ = "0.1.0a0"
```

- [ ] **Step 2: Create `src/robobench/robots/__init__.py`**

```python
"""Vendor-specific robot adapter implementations."""
```

- [ ] **Step 3: Create `tests/__init__.py`, `tests/unit/__init__.py`, `tests/unit/robots/__init__.py`**

Each file should be empty (zero bytes).

- [ ] **Step 4: Create `tests/conftest.py` (empty for now)**

```python
"""Shared pytest fixtures (none yet)."""
```

- [ ] **Step 5: Create `examples/.gitkeep`, `ui/.gitkeep`, `robots/.gitkeep`**

Empty files; they reserve the directory in git until Tasks 5/6 import content.

- [ ] **Step 6: Create `docs/index.md`**

```markdown
# Robobench

Open-source ROS2 platform for robot hardware bring-up and debugging.

See the [project README](../README.md) for an overview, and the
[tutorials](tutorials/) for hands-on guides.

> v0.1 status: Phase A (repository bootstrap). Diagnostic panels, simulation
> support, and additional robot adapters are in subsequent phases — see the
> [plans directory](superpowers/plans/) for the implementation roadmap.
```

- [ ] **Step 7: Commit**

```bash
git add src/ tests/ examples/.gitkeep ui/.gitkeep robots/.gitkeep docs/index.md
git commit -m "chore: scaffold top-level directory structure"
```

---

## Task 5: Import campus_guide reference into examples/ — LICENSE-GATED

> **STOP**: Before running this task, confirm with the user that Prerequisites step 1, 2, or 3 has been resolved. If still pending, skip to Task 7 and revisit later.

**Files:**
- Create: `examples/campus_guide/README.md`
- Copy tree: `CS5335TurtleBot/campus_guide_bot/` → `examples/campus_guide/code/campus_guide_bot/`
- Copy: every `*.sh` and `*.xml` from upstream root → `examples/campus_guide/code/scripts/`
- Copy: `config.yaml`, `architecture_diagram.md` → `examples/campus_guide/code/`

- [ ] **Step 1: Copy the upstream tree**

Run (Windows PowerShell-compatible bash):
```bash
cp -r ../CS5335TurtleBot/campus_guide_bot examples/campus_guide/code/
mkdir -p examples/campus_guide/code/scripts
cp ../CS5335TurtleBot/*.sh examples/campus_guide/code/scripts/
cp ../CS5335TurtleBot/*.xml examples/campus_guide/code/scripts/
cp ../CS5335TurtleBot/config.yaml examples/campus_guide/code/
cp ../CS5335TurtleBot/architecture_diagram.md examples/campus_guide/code/
```

Expected: `examples/campus_guide/code/` populated with `campus_guide_bot/`, `scripts/`, `config.yaml`, `architecture_diagram.md`.

- [ ] **Step 2: Verify nothing else got pulled in**

Run: `ls examples/campus_guide/code/`
Expected: only the items copied in Step 1. If `.git/` or random files appear, delete them.

- [ ] **Step 3: Write `examples/campus_guide/README.md`**

```markdown
# Campus Guide — Reference Implementation

This directory contains the original `CS5335TurtleBot` codebase, imported as a
runnable end-to-end reference for the robobench platform. It demonstrates a
complete embodied-AI pipeline (speech/text → LLM tool-call → Nav2 →
TurtleBot4) and is the system the robobench diagnostic layer is initially
benchmarked against.

## Provenance

- Upstream: https://github.com/En-PingSu/CS5335TurtleBot
- License of imported code: see top-level [NOTICE](../../NOTICE). The robobench
  Apache-2.0 license applies only to additions made within this fork; original
  files retain their upstream license terms.

## How to run

The original startup guide remains authoritative for running this example:
see `code/STARTUP_GUIDE.md` (if present) and `code/scripts/deploy.sh`.

## Why it lives here

Robobench's diagnostic layer is designed to spot bring-up problems
*before* you reach this kind of full integration. This demo is the
fully-integrated end-state — useful as a smoke test for "did the whole stack
come up correctly?".
```

- [ ] **Step 4: Commit**

```bash
git add examples/campus_guide/
git commit -m "feat(examples): import campus_guide reference implementation"
```

---

## Task 6: Import dashboard and speech UI as v0 baseline — LICENSE-GATED

> **STOP**: Same license gate as Task 5.

**Files:**
- Copy tree: `CS5335TurtleBot/dashboard/` → `ui/dashboard/`
- Copy tree: `CS5335TurtleBot/speech_web_ui/` → `ui/speech_web_ui/`
- Create: `ui/README.md`

- [ ] **Step 1: Copy the upstream UI trees**

```bash
cp -r ../CS5335TurtleBot/dashboard ui/dashboard
cp -r ../CS5335TurtleBot/speech_web_ui ui/speech_web_ui
rm -f ui/.gitkeep
```

- [ ] **Step 2: Write `ui/README.md`**

```markdown
# UI Layer (v0 Baseline)

This directory holds the dashboard and speech web UI imported from the
upstream reference repo. They are the v0 baseline; robobench's planned
diagnostic panels and bring-up wizard (Phase C) will be layered on top of —
or replace parts of — these components.

| Component | Port | Role |
|-----------|------|------|
| `dashboard/` | 8080 | Deploy + map + AMCL covariance + chat + nav state |
| `speech_web_ui/` | 8888 | Browser voice recognition → ROS topic |

See top-level [NOTICE](../NOTICE) for upstream provenance and license terms.
```

- [ ] **Step 3: Commit**

```bash
git add ui/
git commit -m "feat(ui): import dashboard and speech UI as v0 baseline"
```

---

## Task 7: Write root README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Draft the README**

```markdown
# Robobench

> Open-source ROS2 platform for **robot hardware bring-up and debugging** —
> built for students and researchers who need to know *why their robot
> isn't doing what they told it to*.

## The problem

Half a robotics lab's calendar is spent fighting bring-up: DDS discovery
gone wrong, clock drift breaking TF, lifecycle nodes refusing to activate,
sensors silently dropping out. The actual research starts after that's
working. Robobench aims to compress that fight from days to minutes.

## What v0.1 ships

- A `RobotAdapter` interface that any ROS2 robot can implement.
- A first reference adapter: TurtleBot4.
- A `robobench` CLI that runs hardware diagnostics against a real robot.
- A runnable end-to-end example (`examples/campus_guide/`) imported from
  upstream as a reference integration to benchmark against.
- A baseline web dashboard + speech UI (`ui/`) to be extended in Phase C.

## What v0.1 does NOT ship (and where it's going)

| Coming in | Feature |
|-----------|---------|
| Phase B   | Full extraction of `deploy.sh` into adapter methods |
| Phase C   | Diagnostic panels (DDS visibility, TF tree, sensor health, clock) |
| Phase C   | Browser-based bring-up wizard replacing `deploy.sh` |
| Phase D   | MkDocs tutorial site + GitHub Pages |
| Phase E   | Simulation support (Gazebo / Ignition) |
| Phase E+  | Additional robot adapters (TurtleBot3, Jackal, custom) |

## Install (v0.1)

```bash
pip install -e .
robobench --help
```

## Quick start

See [docs/tutorials/connect-turtlebot4.md](docs/tutorials/connect-turtlebot4.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Code of conduct: Contributor Covenant
v2.1 — see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Apache 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for attribution of
imported reference material.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add positioning README"
```

---

## Task 8: Write CONTRIBUTING.md

**Files:**
- Create: `CONTRIBUTING.md`

- [ ] **Step 1: Draft CONTRIBUTING.md**

```markdown
# Contributing to Robobench

Thanks for your interest. Robobench is an academic platform — we optimize
for clarity, reproducibility, and helping students/researchers get unstuck
fast. Contributions in any of these areas are welcome.

## Ways to contribute

- **New robot adapter**: implement `RobotAdapter` for a robot we don't yet
  support. See [docs/tutorials/adding-an-adapter.md](docs/tutorials/) (Phase B).
- **Diagnostic panel**: add a panel to the dashboard that exposes a class
  of bring-up failure we don't yet detect.
- **Tutorial**: walk through a real debugging session you ran.
- **Bug report**: especially "the platform said X was healthy but actually
  Y was broken" — those are gold for us.

## Development setup

```bash
git clone https://github.com/<org>/robobench
cd robobench
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

## Code style

- Python: `ruff format` + `ruff check` (configured in `pyproject.toml`).
- Tests: pytest. Mock `subprocess`/SSH at the boundary — don't require a
  real robot in the unit test suite.
- Commit messages: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`,
  `ci:`, `test:`, `refactor:`). Keep the subject under 72 chars.

## Pull request checklist

- [ ] Tests added or updated
- [ ] `ruff check` and `ruff format --check` pass
- [ ] `pytest` passes
- [ ] If you added a new public function/class, it has a one-line docstring
- [ ] CHANGELOG entry under `[Unreleased]` (CHANGELOG arrives in Phase B)

## Filing hardware-debug issues

Use the **Hardware issue** template (`.github/ISSUE_TEMPLATE/hardware_issue.md`).
Include: robot model, ROS distro, network topology, the exact command you ran,
and the platform's diagnostic output. Without those four, we can't reproduce.
```

- [ ] **Step 2: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: add CONTRIBUTING guide"
```

---

## Task 9: Add CODE_OF_CONDUCT.md

**Files:**
- Create: `CODE_OF_CONDUCT.md`

- [ ] **Step 1: Drop in Contributor Covenant v2.1 verbatim**

Pull from <https://www.contributor-covenant.org/version/2/1/code_of_conduct/code_of_conduct.md>. Replace the `[INSERT CONTACT METHOD]` placeholder with `conduct@robobench.dev` (or whatever contact the user wants — pause and ask if uncertain).

- [ ] **Step 2: Commit**

```bash
git add CODE_OF_CONDUCT.md
git commit -m "docs: add Contributor Covenant v2.1 code of conduct"
```

---

## Task 10: GitHub issue + PR templates

**Files:**
- Create: `.github/ISSUE_TEMPLATE/bug_report.md`
- Create: `.github/ISSUE_TEMPLATE/feature_request.md`
- Create: `.github/ISSUE_TEMPLATE/hardware_issue.md`
- Create: `.github/PULL_REQUEST_TEMPLATE.md`

- [ ] **Step 1: `bug_report.md`**

```markdown
---
name: Bug report
about: Something in robobench itself misbehaves
labels: bug
---

## What happened

## What you expected

## How to reproduce

1.
2.
3.

## Environment

- robobench version: (output of `robobench --version`)
- Python version:
- OS:
- ROS2 distro (if relevant):
```

- [ ] **Step 2: `feature_request.md`**

```markdown
---
name: Feature request
about: Propose something new
labels: enhancement
---

## What problem does this solve

## Proposed approach (optional)

## Alternatives considered
```

- [ ] **Step 3: `hardware_issue.md` — the distinctive one**

```markdown
---
name: Hardware issue
about: My robot is doing something weird and I want help diagnosing it
labels: hardware
---

## Robot

- Model:
- Vendor firmware version:
- ROS2 distro on robot:
- ROS2 distro on workstation:

## Network topology

(Workstation ↔ router ↔ robot? Direct ethernet? Multi-machine?)

## What you tried

```text
$ robobench check --robot <model> ...
(paste output)
```

## What you expected vs. what happened

## Diagnostic bundle

If `robobench` produced a diagnostic bundle (Phase C), attach it here.
```

- [ ] **Step 4: `PULL_REQUEST_TEMPLATE.md`**

```markdown
## What this changes

## Why

## Test plan

- [ ] `pytest` passes
- [ ] `ruff check` passes
- [ ] `ruff format --check` passes
- [ ] (If robot-touching) manually verified on at least one physical robot

## Checklist

- [ ] Conventional Commits subject
- [ ] Docstrings on new public APIs
- [ ] CONTRIBUTING.md guidance followed
```

- [ ] **Step 5: Commit**

```bash
git add .github/
git commit -m "chore: add issue and PR templates"
```

---

## Task 11: pyproject.toml + ruff config

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "robobench"
version = "0.1.0a0"
description = "Open-source ROS2 platform for robot hardware bring-up and debugging."
readme = "README.md"
requires-python = ">=3.11"
license = { file = "LICENSE" }
authors = [{ name = "The Robobench Contributors" }]
keywords = ["ros2", "robotics", "diagnostics", "turtlebot", "academic"]
classifiers = [
  "Development Status :: 3 - Alpha",
  "Intended Audience :: Science/Research",
  "Intended Audience :: Education",
  "License :: OSI Approved :: Apache Software License",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Topic :: Scientific/Engineering",
]
dependencies = [
  "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-mock>=3.12",
  "ruff>=0.4",
]

[project.scripts]
robobench = "robobench.cli:main"

[project.urls]
Homepage = "https://github.com/<org>/robobench"
Issues = "https://github.com/<org>/robobench/issues"

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B", "SIM", "PL"]
ignore = ["PLR0913"]   # allow more than 5 args; adapter constructors are wide

[tool.ruff.format]
quote-style = "double"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
```

- [ ] **Step 2: Verify install works**

```bash
python -m venv .venv
source .venv/Scripts/activate    # Windows bash
pip install -e ".[dev]"
robobench --help
```

Expected: install succeeds. `robobench --help` will fail (entry point not implemented yet) — that's fine for now, we just need pip to accept the metadata.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add pyproject.toml with ruff and pytest config"
```

---

## Task 12: GitHub Actions CI (lint + test)

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip

      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Ruff lint
        run: ruff check .

      - name: Ruff format check
        run: ruff format --check .

      - name: Pytest
        run: pytest
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint and test workflow"
```

---

## Task 13: Define `RobotAdapter` ABC (TDD)

**Files:**
- Create: `tests/unit/test_adapter_base.py`
- Create: `src/robobench/adapter_base.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_adapter_base.py`:

```python
"""Tests for the RobotAdapter abstract base class."""
from __future__ import annotations

import pytest

from robobench.adapter_base import RobotAdapter


def test_robot_adapter_cannot_be_instantiated_directly():
    """RobotAdapter is abstract — instantiating it must fail."""
    with pytest.raises(TypeError):
        RobotAdapter()  # type: ignore[abstract]


def test_concrete_subclass_must_implement_all_methods():
    """A subclass missing any abstract method cannot be instantiated."""

    class Incomplete(RobotAdapter):
        pass

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_fully_implemented_subclass_is_instantiable():
    """A subclass that implements every abstract method instantiates cleanly."""

    class Complete(RobotAdapter):
        def check_clock_offset(self) -> float:
            return 0.0

        def build(self) -> None:
            return None

        def launch(self) -> None:
            return None

        def activate_lifecycle(self) -> None:
            return None

        def set_initial_pose(self, x: float, y: float, theta: float) -> None:
            return None

        def health_check(self) -> dict:
            return {}

        def shutdown(self) -> None:
            return None

    adapter = Complete()
    assert adapter.check_clock_offset() == 0.0
```

- [ ] **Step 2: Run the test, confirm it fails**

```bash
pytest tests/unit/test_adapter_base.py -v
```
Expected: `ImportError: cannot import name 'RobotAdapter'` (module doesn't exist yet).

- [ ] **Step 3: Implement `src/robobench/adapter_base.py`**

```python
"""Abstract base class for robot adapters.

A `RobotAdapter` is the contract every supported robot implements. The
robobench CLI and (later) the diagnostic panels only ever interact with
this interface; concrete vendor knowledge lives in subclasses under
``robobench.robots``.

Method contract:

- ``check_clock_offset``: return clock offset in seconds between
  workstation and robot. Negative = robot is behind workstation.
- ``build``: build the robot-side ROS2 workspace (typically over SSH).
- ``launch``: start the navigation stack on the robot.
- ``activate_lifecycle``: bring Nav2 lifecycle nodes through configure
  → activate (works around DDS discovery quirks).
- ``set_initial_pose``: publish an AMCL initial pose.
- ``health_check``: return a structured dict describing all probed
  subsystems and whether each is OK.
- ``shutdown``: kill the navigation stack cleanly.

Adapters MAY raise ``NotImplementedError`` from any method in early
development; the CLI treats that as a "not yet wired up" diagnostic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class RobotAdapter(ABC):
    """Vendor-agnostic interface for ROS2 robot hardware."""

    @abstractmethod
    def check_clock_offset(self) -> float:
        """Return clock offset in seconds (workstation_time - robot_time)."""

    @abstractmethod
    def build(self) -> None:
        """Build the robot-side ROS2 workspace."""

    @abstractmethod
    def launch(self) -> None:
        """Start the navigation stack on the robot."""

    @abstractmethod
    def activate_lifecycle(self) -> None:
        """Bring lifecycle nodes through configure → activate."""

    @abstractmethod
    def set_initial_pose(self, x: float, y: float, theta: float) -> None:
        """Publish an AMCL initial pose at (x, y, theta)."""

    @abstractmethod
    def health_check(self) -> dict:
        """Return a structured health report of all probed subsystems."""

    @abstractmethod
    def shutdown(self) -> None:
        """Cleanly stop the navigation stack."""
```

- [ ] **Step 4: Run the test, confirm it passes**

```bash
pytest tests/unit/test_adapter_base.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/adapter_base.py tests/unit/test_adapter_base.py
git commit -m "feat(core): add RobotAdapter abstract base class"
```

---

## Task 14: TurtleBot4Adapter scaffold (TDD)

**Files:**
- Create: `tests/unit/robots/test_turtlebot4.py`
- Create: `src/robobench/robots/turtlebot4.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/robots/test_turtlebot4.py`:

```python
"""Tests for TurtleBot4Adapter."""
from __future__ import annotations

import pytest

from robobench.adapter_base import RobotAdapter
from robobench.robots.turtlebot4 import TurtleBot4Adapter


def test_turtlebot4_adapter_is_a_robot_adapter():
    """Sanity check: the concrete class extends the ABC."""
    assert issubclass(TurtleBot4Adapter, RobotAdapter)


def test_turtlebot4_adapter_instantiates_with_required_fields():
    """Constructor accepts ip, ssh user/pass, namespace, workspace_dir."""
    adapter = TurtleBot4Adapter(
        ip="192.168.50.31",
        ssh_user="ubuntu",
        ssh_pass="turtlebot4",
        namespace="turtlebot468",
        workspace_dir="~/CS5335TurtleBot",
    )
    assert adapter.ip == "192.168.50.31"
    assert adapter.namespace == "turtlebot468"


@pytest.mark.parametrize(
    "method,args",
    [
        ("build", ()),
        ("launch", ()),
        ("activate_lifecycle", ()),
        ("set_initial_pose", (1.0, 2.0, 0.0)),
        ("health_check", ()),
        ("shutdown", ()),
    ],
)
def test_unimplemented_methods_raise_not_implemented(method, args):
    """v0.1 only implements check_clock_offset; the rest signal not-yet-done."""
    adapter = TurtleBot4Adapter(
        ip="192.168.50.31",
        ssh_user="ubuntu",
        ssh_pass="turtlebot4",
        namespace="turtlebot468",
        workspace_dir="~/CS5335TurtleBot",
    )
    with pytest.raises(NotImplementedError):
        getattr(adapter, method)(*args)
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/robots/test_turtlebot4.py -v
```
Expected: import error — `turtlebot4` module doesn't exist.

- [ ] **Step 3: Implement the scaffold**

`src/robobench/robots/turtlebot4.py`:

```python
"""TurtleBot4 adapter — the reference implementation of ``RobotAdapter``.

v0.1 implements only ``check_clock_offset``. Remaining methods raise
``NotImplementedError`` and will be filled in across subsequent plans
(Phase B: extract from upstream ``deploy.sh``).
"""
from __future__ import annotations

from dataclasses import dataclass

from robobench.adapter_base import RobotAdapter


@dataclass
class TurtleBot4Adapter(RobotAdapter):
    """Adapter for iRobot TurtleBot4 platforms.

    Configuration mirrors the upstream ``config.yaml`` schema so that
    existing campus_guide setups can hand their config dict straight in.
    """

    ip: str
    ssh_user: str
    ssh_pass: str
    namespace: str
    workspace_dir: str

    def check_clock_offset(self) -> float:
        raise NotImplementedError("Filled in by Task 15")

    def build(self) -> None:
        raise NotImplementedError("Phase B: extract from deploy.sh step 2")

    def launch(self) -> None:
        raise NotImplementedError("Phase B: extract from deploy.sh step 3")

    def activate_lifecycle(self) -> None:
        raise NotImplementedError("Phase B: wraps lifecycle_activator")

    def set_initial_pose(self, x: float, y: float, theta: float) -> None:
        raise NotImplementedError("Phase B: extract from deploy.sh step 7")

    def health_check(self) -> dict:
        raise NotImplementedError("Phase B: extract from deploy.sh step 9")

    def shutdown(self) -> None:
        raise NotImplementedError("Phase B: wraps stop.sh")
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/unit/robots/test_turtlebot4.py -v
```
Expected: 8 tests pass (the 2 named + the parametrize set of 6).

- [ ] **Step 5: Commit**

```bash
git add src/robobench/robots/turtlebot4.py tests/unit/robots/test_turtlebot4.py
git commit -m "feat(robots): add TurtleBot4 adapter scaffold"
```

---

## Task 15: Implement `check_clock_offset()` (TDD)

This is the one concrete diagnostic we ship in v0.1. It validates the end-to-end story: install robobench → point at a robot → get one real piece of debug info.

**Files:**
- Modify: `tests/unit/robots/test_turtlebot4.py` (add tests)
- Modify: `src/robobench/robots/turtlebot4.py` (implement method)

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/robots/test_turtlebot4.py`:

```python
import subprocess
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _adapter():
    return TurtleBot4Adapter(
        ip="192.168.50.31",
        ssh_user="ubuntu",
        ssh_pass="turtlebot4",
        namespace="turtlebot468",
        workspace_dir="~/CS5335TurtleBot",
    )


def test_check_clock_offset_returns_seconds(mocker):
    """SSHs to the robot, reads epoch seconds, subtracts from local time."""
    fake_local = datetime(2026, 5, 27, 12, 0, 10, tzinfo=timezone.utc)
    mocker.patch(
        "robobench.robots.turtlebot4._now_utc",
        return_value=fake_local,
    )
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "1748347205\n"  # 5 seconds behind fake_local
    completed.stderr = ""
    run_mock = mocker.patch("robobench.robots.turtlebot4.subprocess.run", return_value=completed)

    offset = _adapter().check_clock_offset()

    assert offset == pytest.approx(5.0, abs=0.01)
    # Confirm we ran ssh, not something else
    args, kwargs = run_mock.call_args
    assert args[0][0] == "sshpass"
    assert "ssh" in args[0]
    assert "ubuntu@192.168.50.31" in args[0]


def test_check_clock_offset_raises_on_ssh_failure(mocker):
    """A non-zero SSH exit becomes a RuntimeError with stderr in the message."""
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 255
    completed.stdout = ""
    completed.stderr = "ssh: connect to host 192.168.50.31 port 22: No route to host"
    mocker.patch("robobench.robots.turtlebot4.subprocess.run", return_value=completed)

    with pytest.raises(RuntimeError, match="No route to host"):
        _adapter().check_clock_offset()
```

Note: `pytest_mock`'s `mocker` fixture is provided by the `pytest-mock` dev dep already in `pyproject.toml`. The `pytest.approx` reference requires `import pytest` already at the top of the file.

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/robots/test_turtlebot4.py::test_check_clock_offset_returns_seconds -v
```
Expected: `NotImplementedError: Filled in by Task 15`.

- [ ] **Step 3: Implement `check_clock_offset`**

Edit `src/robobench/robots/turtlebot4.py`:

Add module-level imports at the top:

```python
import subprocess
from datetime import datetime, timezone
```

Add this helper just below the imports (its own line is what we mock in tests):

```python
def _now_utc() -> datetime:
    """Wrapper so tests can stub local time."""
    return datetime.now(tz=timezone.utc)
```

Replace the body of `TurtleBot4Adapter.check_clock_offset` with:

```python
    def check_clock_offset(self) -> float:
        """Return ``local_time - robot_time`` in seconds (positive = robot is behind)."""
        cmd = [
            "sshpass",
            "-p",
            self.ssh_pass,
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"{self.ssh_user}@{self.ip}",
            "date +%s",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            raise RuntimeError(
                f"SSH to {self.ip} failed (rc={result.returncode}): {result.stderr.strip()}"
            )
        robot_epoch = float(result.stdout.strip())
        local_epoch = _now_utc().timestamp()
        return local_epoch - robot_epoch
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/unit/robots/test_turtlebot4.py -v
```
Expected: all tests in the file pass (originals + 2 new).

- [ ] **Step 5: Run full suite once**

```bash
pytest
ruff check .
ruff format --check .
```
Expected: all green. If ruff complains about formatting, run `ruff format .` and re-test.

- [ ] **Step 6: Commit**

```bash
git add src/robobench/robots/turtlebot4.py tests/unit/robots/test_turtlebot4.py
git commit -m "feat(robots): implement TurtleBot4 check_clock_offset over SSH"
```

---

## Task 16: `robobench` CLI entrypoint (TDD)

**Files:**
- Create: `tests/unit/test_cli.py`
- Create: `src/robobench/cli.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_cli.py`:

```python
"""Tests for the robobench CLI."""
from __future__ import annotations

import pytest

from robobench import __version__
from robobench.cli import main


def test_version_flag_prints_version(capsys):
    """`robobench --version` prints the package version and exits 0."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert __version__ in captured.out


def test_no_args_prints_help_and_exits_nonzero(capsys):
    """`robobench` with no subcommand prints help and exits with code 2."""
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "usage:" in captured.err.lower() or "usage:" in captured.out.lower()
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/test_cli.py -v
```
Expected: `ImportError` on `robobench.cli`.

- [ ] **Step 3: Implement CLI**

`src/robobench/cli.py`:

```python
"""Command-line entry point for the robobench tool.

Usage examples (Phase A — v0.1):

    robobench --version
    robobench check --robot turtlebot4 \\
        --ip 192.168.50.31 --ssh-user ubuntu --ssh-pass turtlebot4 \\
        --namespace turtlebot468
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from robobench import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="robobench")
    parser.add_argument("--version", action="version", version=f"robobench {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Run hardware diagnostics against a robot.")
    check.add_argument("--robot", required=True, choices=["turtlebot4"])
    check.add_argument("--ip", required=True)
    check.add_argument("--ssh-user", required=True)
    check.add_argument("--ssh-pass", required=True)
    check.add_argument("--namespace", required=True)
    check.add_argument("--workspace-dir", default="~/CS5335TurtleBot")
    check.set_defaults(func=_cmd_check)

    return parser


def _cmd_check(args: argparse.Namespace) -> int:
    from robobench.robots.turtlebot4 import TurtleBot4Adapter

    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2

    adapter = TurtleBot4Adapter(
        ip=args.ip,
        ssh_user=args.ssh_user,
        ssh_pass=args.ssh_pass,
        namespace=args.namespace,
        workspace_dir=args.workspace_dir,
    )

    print(f"Checking clock offset against {args.ip} ...")
    try:
        offset = adapter.check_clock_offset()
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    severity = "OK" if abs(offset) < 2.0 else "WARN" if abs(offset) < 10.0 else "FAIL"
    print(f"  clock offset: {offset:+.2f}s  [{severity}]")
    return 0 if severity != "FAIL" else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/unit/test_cli.py -v
```
Expected: both tests pass.

- [ ] **Step 5: Smoke-test the installed CLI**

```bash
pip install -e ".[dev]"
robobench --version
```
Expected: `robobench 0.1.0a0` printed.

- [ ] **Step 6: Commit**

```bash
git add src/robobench/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add robobench CLI with check subcommand"
```

---

## Task 17: First tutorial — "Connect TurtleBot4 in 10 minutes"

**Files:**
- Create: `docs/tutorials/connect-turtlebot4.md`

- [ ] **Step 1: Draft tutorial**

```markdown
# Connect a TurtleBot4 in 10 minutes

This tutorial walks you from "TurtleBot4 boots up" to "robobench tells you
the clock is in sync". It does **not** cover full navigation bring-up —
that's `examples/campus_guide/` and a later tutorial.

## What you need

- A TurtleBot4 (any variant). Powered on.
- A workstation on the same network as the robot.
- The robot's IP, SSH user, SSH password, and namespace. (TurtleBot4 defaults:
  user `ubuntu`, password `turtlebot4`. IP and namespace are set during
  initial robot setup — see iRobot's `turtlebot4_setup` docs.)
- Python 3.11+.
- `sshpass` installed locally (`sudo apt install sshpass` on Linux,
  `brew install hudochenkov/sshpass/sshpass` on macOS).

## Install robobench

```bash
git clone https://github.com/<org>/robobench
cd robobench
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Run the clock check

```bash
robobench check \
  --robot turtlebot4 \
  --ip 192.168.50.31 \
  --ssh-user ubuntu \
  --ssh-pass turtlebot4 \
  --namespace turtlebot468
```

Expected output (healthy):

```
Checking clock offset against 192.168.50.31 ...
  clock offset: +0.12s  [OK]
```

Expected output (drift problem):

```
Checking clock offset against 192.168.50.31 ...
  clock offset: +14.32s  [FAIL]
```

## What it told you

`OK` (< 2s offset): TF stamps will line up. You're safe to continue with
Nav2 bring-up.

`WARN` (2-10s): Subscribers using `tf2_ros.Buffer` with default
`cache_time` will sometimes miss transforms. Run `chrony` on both sides
and recheck.

`FAIL` (> 10s): Nothing using ROS time will work reliably. Stop and fix
this before going further. The upstream campus_guide deploy script
includes an automated chrony setup — see
`examples/campus_guide/code/scripts/deploy.sh` for reference until
robobench's Phase B adapter wraps it natively.

## What's next

- Phase B will add `robobench build`, `robobench launch`, `robobench
  activate`, `robobench health` — full bring-up parity with `deploy.sh`.
- Phase C will add the dashboard with live DDS / TF / sensor panels.

Track progress in [docs/superpowers/plans/](../superpowers/plans/).
```

- [ ] **Step 2: Commit**

```bash
git add docs/tutorials/connect-turtlebot4.md
git commit -m "docs(tutorials): add connect-turtlebot4 quickstart"
```

---

## Task 18: Tag v0.1.0-alpha

**Files:**
- (No file changes; just a tag.)

- [ ] **Step 1: Final sanity sweep**

```bash
pytest
ruff check .
ruff format --check .
```
Expected: all green.

- [ ] **Step 2: Tag**

```bash
git tag -a v0.1.0a0 -m "v0.1.0-alpha — Phase A: repository bootstrap"
```

- [ ] **Step 3: Verify**

```bash
git tag --list
git log --oneline | head -20
```
Expected: `v0.1.0a0` present, ~18 commits visible (one per task plus initial).

---

## Self-Review (Notes from the Plan Author)

**Spec coverage check:**
- Phase A goal "clean OSS repo with adapter + first reference impl + CI + first tutorial" → all covered: LICENSE/NOTICE (Tasks 2, 9), structure (Tasks 3, 4), upstream import (Tasks 5, 6), governance (Tasks 7-10), tooling (Tasks 11, 12), interface + impl (Tasks 13-15), CLI (Task 16), tutorial (Task 17), release tag (Task 18).
- "Original code preserved as reference" → Tasks 5, 6.
- "Reproducible setup" → `pyproject.toml` with `pip install -e .` and pinned dev deps.

**Placeholder scan:** No TBDs, no "implement appropriate X", no "similar to". Every code step shows real code.

**Type consistency:** `RobotAdapter` abstract methods (Task 13) match `TurtleBot4Adapter` overrides (Task 14) match CLI usage (Task 16). The `check_clock_offset` return type is `float` everywhere it appears.

**Known soft spots / risks:**
1. **License gate is real.** Tasks 5 and 6 must not run before Prerequisites is resolved. Anyone executing this plan should pause and confirm with the human driving it.
2. **Windows + `sshpass` portability.** The tutorial and the `check_clock_offset` impl both assume `sshpass` is on `PATH`. On native Windows that's awkward. Phase B should migrate to `paramiko` so the dep stops being a binary. Logged here for later, not a v0.1 blocker (devs on Windows can use WSL).
3. **Datetime mocking precision.** Task 15's test mocks `_now_utc` to a fixed value but the implementation calls `_now_utc()` once and `time.time()` zero times — make sure the implementation matches the mock surface (it does, but worth flagging if anyone refactors).
4. **CI doesn't run on Windows.** Matrix is `ubuntu-latest` only. That's fine for v0.1; add a Windows job in Phase B once we have logic that branches per-OS.

---

## Future Plans (out of scope for this document)

Each gets its own plan file under `docs/superpowers/plans/` when Phase A is shipped:

- **Phase B — Adapter completeness** (~2 weeks)
  Extract `deploy.sh` step-by-step into `TurtleBot4Adapter.{build,launch,activate_lifecycle,set_initial_pose,health_check,shutdown}`. Migrate from `sshpass` to `paramiko`. Add `robobench bringup` subcommand that runs the whole sequence.

- **Phase C — Diagnostic panels + bring-up wizard** (~3 weeks)
  Stand up FastAPI panels on top of the imported dashboard: DDS discovery, TF tree, sensor health, clock. Replace `deploy.sh` with a browser-driven wizard that runs adapter methods one at a time, showing pass/fail + suggested fix per step. Structured failure catalog.

- **Phase D — Documentation site + second adapter** (~2 weeks)
  MkDocs site published to GitHub Pages. Tutorials: hardware-debug walkthrough, writing your own adapter, contributing a panel. Implement `TurtleBot3Adapter` to prove the interface generalizes.

- **Phase E — Simulation support** (~3 weeks)
  Gazebo / Ignition world + a `SimAdapter` that satisfies the same interface. Lets students without hardware do every tutorial.
