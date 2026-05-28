# Robobench v0.2.1 Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the most embarrassing gaps between robobench v0.2's "academic platform" positioning and what actually shipped — remove `campus_nav_llm` hard-coding, fix the misleading `workspace_dir` default, document the architecture, prevent the silent false-positive in `setup_clock_sync`, and label the imported UI as v0 baseline. **No real-robot testing** — that's deferred to lab personnel. **No Phase C work** (diagnostic panels, dashboard wiring, failure catalog) — that's its own plan.

**Architecture:**
- The config-driven generalization is additive: existing v0.2 behavior remains the default. New optional fields in `config.yaml` (and matching dataclass fields on `TurtleBot4Adapter`) let any ROS2 package be the bring-up target — not just `campus_nav_llm`. Backwards compatible.
- The workstation chrony check is a new free function in `robobench.ssh` (no SSH needed — it reads local files). `setup_clock_sync` calls it first and surfaces the result in the report dict.
- Architecture documentation is a single `docs/architecture.md` covering the four design decisions a contributor needs to understand before writing a new adapter or panel.

**Tech Stack:** Same as v0.2 — Python 3.11+, pytest, ruff, paramiko, pyyaml. No new deps.

**Prerequisites:** v0.2.0a0 is tagged and pushed. 41 unit tests passing.

**Repo root:** `C:\Users\chntw\Documents\robotic\robobench\`

---

## File Structure (changes from v0.2)

```
robobench/
├── src/robobench/
│   ├── __init__.py                    # version bump → 0.2.1a0
│   ├── ssh.py                         # +check_workstation_chrony_config()
│   ├── config.py                      # +build/launch/health schema fields
│   └── robots/turtlebot4.py           # workspace_dir → None default
│                                      # +build_packages, launch_package,
│                                      #  launch_file, user_input_topic fields
│                                      # build/launch/health_check read from
│                                      #  these instead of hard-coded strings
│                                      # setup_clock_sync calls workstation check
├── pyproject.toml                     # version 0.2.0a0 → 0.2.1a0
├── ui/README.md                       # +status banner
├── docs/
│   ├── architecture.md                # NEW
│   ├── tutorials/
│   │   ├── connect-turtlebot4.md      # unchanged
│   │   └── bringup-walkthrough.md     # +config.yaml schema reference
│   └── superpowers/plans/
│       └── 2026-05-27-robobench-v0.2.1-stabilization.md   # this file
├── tests/unit/
│   ├── test_ssh.py                    # +tests for workstation chrony check
│   ├── test_config.py                 # +tests for new config fields
│   └── robots/test_turtlebot4.py      # update build/launch/health tests,
│                                      #  add workspace_dir-required test
└── CHANGELOG.md                       # +0.2.1a0 entry
```

---

## Task 1: Fix `workspace_dir` default (small, no TDD ceremony)

The dataclass currently defaults `workspace_dir = "~/CS5335TurtleBot"`. Any user who isn't an upstream author gets confusing colcon failures because that path doesn't exist. Change to `None` and add a clear error in methods that need it.

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Append failing test to `tests/unit/robots/test_turtlebot4.py`**

```python
def test_build_raises_clear_error_when_workspace_dir_is_none():
    """If workspace_dir is None, build() raises a ValueError that says so."""
    adapter = TurtleBot4Adapter(
        ip="192.168.50.31",
        ssh_user="ubuntu",
        ssh_pass="turtlebot4",
        namespace="turtlebot468",
        workspace_dir=None,
    )
    with pytest.raises(ValueError, match="workspace_dir"):
        adapter.build()
```

- [ ] **Step 2: Run, confirm fail**

```bash
source .venv/Scripts/activate
pytest tests/unit/robots/test_turtlebot4.py -v -k workspace_dir
```
Expected: Failure — currently `workspace_dir` accepts `None` because the type hint allows it but build() doesn't validate.

Wait — actually the current type is `workspace_dir: str` (not `str | None`). Passing `None` will fail dataclass type validation? No, dataclass doesn't enforce types at runtime. Construction will succeed; build() will run and pass `None` as `cwd` to subprocess, which silently uses the current working directory. So the test will fail with no error raised (build returns normally), not with the expected ValueError.

- [ ] **Step 3: Make the type optional and validate in build()**

In `src/robobench/robots/turtlebot4.py`, find the dataclass field:

```python
    workspace_dir: str
```

Change to:

```python
    workspace_dir: str | None = None
```

Then in `build()`, add validation as the first statement:

```python
    def build(self) -> None:
        """Run ``colcon build --packages-select campus_nav_llm`` in the workspace."""
        if self.workspace_dir is None:
            raise ValueError(
                "workspace_dir is required for build(); set it in config.yaml "
                "under workspace.dir or pass workspace_dir=... to the adapter."
            )
        result = run_local(
            ...  # rest unchanged
```

- [ ] **Step 4: Update the existing `test_turtlebot4_adapter_instantiates_with_required_fields` test**

It currently constructs `TurtleBot4Adapter(..., workspace_dir="~/CS5335TurtleBot")`. Leave that alone — it still works. The new test above covers the `None` case.

But the existing `test_build_runs_colcon_in_workspace` test asserts `call.kwargs["cwd"] == "~/CS5335TurtleBot"`. That still works because `_adapter()` helper passes `workspace_dir="~/CS5335TurtleBot"` explicitly. No change needed.

- [ ] **Step 5: Run, confirm pass + ruff**

```bash
pytest -q
ruff check src tests && ruff format --check src tests
```
Expected: 42 tests pass (41 + 1 new).

- [ ] **Step 6: Commit**

```bash
git add src/robobench/robots/turtlebot4.py tests/unit/robots/test_turtlebot4.py
git commit -m "fix(robots): make workspace_dir optional with clear error when missing"
```

---

## Task 2: UI status banner (trivial)

**Files:** `ui/README.md`

- [ ] **Step 1: Prepend status banner to `ui/README.md`**

The current file starts with `# UI Layer (v0 Baseline)`. Add a status banner at the very top — before the existing heading:

```markdown
> **Status: v0 baseline, not yet wired up.** The dashboard and speech UI in this
> directory are imported from upstream as reference. Robobench's own code does
> NOT import or invoke them yet — they are scheduled to be wired into Phase C's
> diagnostic-panel work. Until then, they run independently as documented below.

```

Then the existing `# UI Layer (v0 Baseline)` heading and rest of the file follow.

- [ ] **Step 2: Commit**

```bash
git add ui/README.md
git commit -m "docs(ui): add status banner clarifying v0 baseline not yet wired up"
```

---

## Task 3: Extend config schema for build/launch/health (TDD)

This is the central task: introduce optional fields in `config.yaml` and the adapter dataclass so the package names, launch file, and health-probe topic stop being hard-coded.

**Files:**
- Modify: `src/robobench/config.py`
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/test_config.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Failing tests in `tests/unit/test_config.py`**

Append to the file:

```python
def test_load_adapter_config_returns_build_and_launch_fields(tmp_path: Path):
    """Optional build/launch/health fields in config.yaml flow into the kwargs."""
    yaml_text = """
robot:
  ip: "192.168.1.10"
  ssh_user: "ubuntu"
  ssh_pass: "pw"
  namespace: "myrobot"
workspace:
  dir: "/home/me/ws"
build:
  packages: ["my_nav", "my_safety"]
launch:
  package: "my_nav"
  file: "bringup.launch.py"
health:
  user_input_topic: "/my_cmd_input"
"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml_text)

    kwargs = load_adapter_config(cfg)

    assert kwargs["build_packages"] == ["my_nav", "my_safety"]
    assert kwargs["launch_package"] == "my_nav"
    assert kwargs["launch_file"] == "bringup.launch.py"
    assert kwargs["user_input_topic"] == "/my_cmd_input"


def test_load_adapter_config_defaults_match_v0_2_behavior(tmp_path: Path):
    """When the new fields are absent, defaults match v0.2's hard-coded values
    so existing configs keep working unchanged."""
    yaml_text = """
robot:
  ip: "192.168.1.10"
  ssh_user: "ubuntu"
  ssh_pass: "pw"
  namespace: "myrobot"
workspace:
  dir: "/home/me/ws"
"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml_text)

    kwargs = load_adapter_config(cfg)

    assert kwargs["build_packages"] == ["campus_nav_llm"]
    assert kwargs["launch_package"] == "campus_nav_llm"
    assert kwargs["launch_file"] == "navigation_mode.launch.py"
    assert kwargs["user_input_topic"] == "/user_input"
```

- [ ] **Step 2: Run, confirm fail**

```bash
source .venv/Scripts/activate
pytest tests/unit/test_config.py -v
```
Expected: KeyError or missing-key failures.

- [ ] **Step 3: Update `src/robobench/config.py`**

Replace the entire `load_adapter_config` function body with:

```python
def load_adapter_config(path: Path) -> dict:
    """Read ``config.yaml`` and return the kwargs an adapter constructor expects.

    Schema (v0.2.1)::

        robot:
          ip: "192.168.50.31"
          ssh_user: "ubuntu"
          ssh_pass: "turtlebot4"
          namespace: "turtlebot468"
        workspace:
          dir: "~/my_workspace"
        build:                              # optional, defaults to campus_guide
          packages: ["campus_nav_llm"]
        launch:                             # optional, defaults to campus_guide
          package: "campus_nav_llm"
          file: "navigation_mode.launch.py"
        health:                             # optional, defaults to campus_guide
          user_input_topic: "/user_input"
    """
    if not path.exists():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    robot = data.get("robot") or {}
    workspace = data.get("workspace") or {}
    build = data.get("build") or {}
    launch = data.get("launch") or {}
    health = data.get("health") or {}

    required = ("ip", "ssh_user", "ssh_pass", "namespace")
    missing = [k for k in required if not robot.get(k)]
    if missing:
        raise ValueError(
            f"config.yaml missing required robot.{{}} field(s): {', '.join(missing)}"
        )

    workspace_dir_raw = workspace.get("dir")
    workspace_dir = os.path.expanduser(workspace_dir_raw) if workspace_dir_raw else None

    return {
        "ip": robot["ip"],
        "ssh_user": robot["ssh_user"],
        "ssh_pass": robot["ssh_pass"],
        "namespace": robot["namespace"],
        "workspace_dir": workspace_dir,
        "build_packages": build.get("packages", ["campus_nav_llm"]),
        "launch_package": launch.get("package", "campus_nav_llm"),
        "launch_file": launch.get("file", "navigation_mode.launch.py"),
        "user_input_topic": health.get("user_input_topic", "/user_input"),
    }
```

Note: `workspace_dir` now also accepts being absent (matches Task 1's `None` default).

- [ ] **Step 4: Run config tests, confirm pass**

```bash
pytest tests/unit/test_config.py -v
```
Expected: all config tests pass.

- [ ] **Step 5: Failing tests in `tests/unit/robots/test_turtlebot4.py`**

Append:

```python
def test_adapter_accepts_optional_build_launch_health_fields():
    """The dataclass accepts the new optional fields with v0.2-compatible defaults."""
    a = TurtleBot4Adapter(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="ns",
        workspace_dir="/ws",
    )
    # Defaults preserve v0.2 behavior
    assert a.build_packages == ["campus_nav_llm"]
    assert a.launch_package == "campus_nav_llm"
    assert a.launch_file == "navigation_mode.launch.py"
    assert a.user_input_topic == "/user_input"


def test_adapter_accepts_explicit_build_launch_health_fields():
    """Explicit field values override the defaults."""
    a = TurtleBot4Adapter(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="ns",
        workspace_dir="/ws",
        build_packages=["my_pkg"],
        launch_package="my_pkg",
        launch_file="custom.launch.py",
        user_input_topic="/custom_topic",
    )
    assert a.build_packages == ["my_pkg"]
    assert a.launch_package == "my_pkg"
    assert a.launch_file == "custom.launch.py"
    assert a.user_input_topic == "/custom_topic"
```

- [ ] **Step 6: Run, confirm fail**

```bash
pytest tests/unit/robots/test_turtlebot4.py -v -k "accepts_optional or accepts_explicit"
```
Expected: TypeError — TurtleBot4Adapter doesn't have those fields.

- [ ] **Step 7: Add the fields to the dataclass in `src/robobench/robots/turtlebot4.py`**

Find the `@dataclass` block. The current shape is:

```python
@dataclass
class TurtleBot4Adapter(RobotAdapter):
    """..."""

    ip: str
    ssh_user: str
    ssh_pass: str
    namespace: str
    workspace_dir: str | None = None
```

Append four new fields after `workspace_dir`. Dataclass fields with defaults can't be followed by fields without defaults — `workspace_dir` already has a default, so adding more defaulted fields is fine:

```python
@dataclass
class TurtleBot4Adapter(RobotAdapter):
    """..."""

    ip: str
    ssh_user: str
    ssh_pass: str
    namespace: str
    workspace_dir: str | None = None
    build_packages: list[str] = field(default_factory=lambda: ["campus_nav_llm"])
    launch_package: str = "campus_nav_llm"
    launch_file: str = "navigation_mode.launch.py"
    user_input_topic: str = "/user_input"
```

Add `from dataclasses import dataclass, field` at the top of the file if `field` isn't already imported (the existing import is likely just `from dataclasses import dataclass`).

- [ ] **Step 8: Run, confirm pass + ruff**

```bash
pytest tests/unit/robots/test_turtlebot4.py -v
pytest -q
ruff check src tests && ruff format --check src tests
```
Expected: 46 total tests pass (42 from Task 1 + 4 new).

- [ ] **Step 9: Commit**

```bash
git add src/robobench/config.py src/robobench/robots/turtlebot4.py tests/unit/test_config.py tests/unit/robots/test_turtlebot4.py
git commit -m "feat(config): add build/launch/health config fields, default to v0.2 behavior"
```

---

## Task 4: Make `build()` use `self.build_packages` (TDD)

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Failing test**

Append to `tests/unit/robots/test_turtlebot4.py`:

```python
def test_build_uses_configured_packages_list(mocker):
    """build() iterates self.build_packages into the colcon --packages-select flag."""
    fake_result = MagicMock(returncode=0, stdout="", stderr="")
    run_mock = mocker.patch(
        "robobench.robots.turtlebot4.run_local", return_value=fake_result
    )
    adapter = TurtleBot4Adapter(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="ns",
        workspace_dir="/ws",
        build_packages=["pkg_a", "pkg_b"],
    )

    adapter.build()

    cmd = run_mock.call_args.args[0]
    assert cmd[0] == "colcon"
    assert "--packages-select" in cmd
    pkg_select_idx = cmd.index("--packages-select")
    # `--packages-select pkg_a pkg_b` — args after the flag are the packages
    assert cmd[pkg_select_idx + 1] == "pkg_a"
    assert cmd[pkg_select_idx + 2] == "pkg_b"
```

- [ ] **Step 2: Run, confirm fail** — current build() hard-codes `campus_nav_llm` so it'll be in the cmd, not `pkg_a`/`pkg_b`.

- [ ] **Step 3: Rewrite `build()` body**

Replace the current `build()` body in `turtlebot4.py`:

```python
    def build(self) -> None:
        """Run ``colcon build --packages-select <packages>`` in the workspace."""
        if self.workspace_dir is None:
            raise ValueError(
                "workspace_dir is required for build(); set it in config.yaml "
                "under workspace.dir or pass workspace_dir=... to the adapter."
            )
        result = run_local(
            [
                "colcon",
                "build",
                "--packages-select",
                *self.build_packages,
                "--symlink-install",
            ],
            timeout=600,
            cwd=self.workspace_dir,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"colcon build failed (rc={result.returncode}): {result.stderr.strip()}"
            )
```

- [ ] **Step 4: Run all tests, confirm pass**

```bash
pytest -q
ruff check src tests && ruff format --check src tests
```
Expected: 47 tests pass (46 + 1 new). The existing `test_build_runs_colcon_in_workspace` test still passes because the default `build_packages=["campus_nav_llm"]` produces the same cmd.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/robots/turtlebot4.py tests/unit/robots/test_turtlebot4.py
git commit -m "feat(robots): build() uses configured build_packages list"
```

---

## Task 5: Make `launch()` use `self.launch_package` + `self.launch_file` (TDD)

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Failing test**

Append:

```python
def test_launch_uses_configured_package_and_file(mocker, tmp_path):
    """launch() passes self.launch_package and self.launch_file to ros2 launch."""
    fake_popen = MagicMock()
    fake_popen.pid = 1
    popen_mock = mocker.patch(
        "robobench.robots.turtlebot4.subprocess.Popen", return_value=fake_popen
    )
    pid_path = tmp_path / "p.pid"
    adapter = TurtleBot4Adapter(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="ns",
        workspace_dir="/ws",
        launch_package="my_pkg",
        launch_file="custom.launch.py",
    )

    adapter.launch(pid_path=pid_path)

    cmd = popen_mock.call_args.args[0]
    assert cmd[:2] == ["ros2", "launch"]
    assert cmd[2] == "my_pkg"
    assert cmd[3] == "custom.launch.py"
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Rewrite `launch()` body**

```python
    def launch(self, pid_path: Path | None = None) -> None:
        """Start ``ros2 launch <pkg> <file>`` in the background.

        Writes the launcher PID to ``pid_path`` (defaults to
        ``/tmp/robobench_launch.pid``) so ``shutdown()`` can find it later.
        """
        proc = subprocess.Popen(  # noqa: S603 — controlled cmd list
            [
                "ros2",
                "launch",
                self.launch_package,
                self.launch_file,
                f"namespace:={self.namespace}",
            ]
        )
        target = pid_path if pid_path is not None else Path("/tmp/robobench_launch.pid")
        target.write_text(f"{proc.pid}\n")
```

- [ ] **Step 4: Run all tests, confirm pass + ruff**

Expected: 48 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/robots/turtlebot4.py tests/unit/robots/test_turtlebot4.py
git commit -m "feat(robots): launch() uses configured launch_package and launch_file"
```

---

## Task 6: Make `health_check()` use `self.user_input_topic` (TDD)

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Failing test**

```python
def test_health_check_uses_configured_user_input_topic(mocker):
    """health_check probes self.user_input_topic, not the hard-coded /user_input."""
    mocker.patch.object(TurtleBot4Adapter, "check_clock_offset", return_value=0.0)

    captured_topics = []
    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["ros2", "topic", "info"]:
            captured_topics.append(cmd[3])
            return MagicMock(returncode=0, stdout="Subscription count: 1\n", stderr="")
        if cmd[:3] == ["ros2", "topic", "echo"]:
            return MagicMock(returncode=0, stdout="ok", stderr="")
        if cmd[:3] == ["ros2", "action", "list"]:
            return MagicMock(returncode=0, stdout="/ns/navigate_to_pose\n", stderr="")
        return MagicMock(returncode=0, stdout="ok", stderr="")
    mocker.patch("robobench.robots.turtlebot4.run_local", side_effect=fake_run)

    adapter = TurtleBot4Adapter(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="ns",
        workspace_dir="/ws",
        user_input_topic="/my_custom_input",
    )

    adapter.health_check()

    assert "/my_custom_input" in captured_topics
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Modify `health_check()` in `turtlebot4.py`**

Find the line that says:
```python
        info = run_local(["ros2", "topic", "info", "/user_input"], timeout=10)
```

Replace `"/user_input"` with `self.user_input_topic`:
```python
        info = run_local(["ros2", "topic", "info", self.user_input_topic], timeout=10)
```

That's the only change for this task.

- [ ] **Step 4: Run all tests, confirm pass + ruff**

Expected: 49 tests pass. The existing health_check tests still pass because the default `user_input_topic="/user_input"` matches what they assert.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/robots/turtlebot4.py tests/unit/robots/test_turtlebot4.py
git commit -m "feat(robots): health_check probes configured user_input_topic"
```

---

## Task 7: Workstation chrony config check (TDD)

The upstream `deploy.sh` warns "Add 'allow 192.168.0.0/16' and 'local stratum 10' to laptop chrony.conf" — but doesn't enforce it. As a result, our `setup_clock_sync` returns success even when the workstation isn't actually serving NTP, leaving a silent false positive. This task adds a check + integrates into the report.

**Files:**
- Modify: `src/robobench/ssh.py`
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/test_ssh.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Failing tests in `tests/unit/test_ssh.py`**

Append:

```python
import pathlib

from robobench.ssh import check_workstation_chrony_config


def test_check_workstation_chrony_ok_when_required_lines_present(tmp_path: pathlib.Path):
    """When chrony.conf has both 'allow' for 192.168.* and 'local stratum N', returns OK."""
    conf = tmp_path / "chrony.conf"
    conf.write_text(
        "server pool.ntp.org iburst\n"
        "allow 192.168.0.0/16\n"
        "local stratum 10\n"
    )
    report = check_workstation_chrony_config(conf_path=conf)
    assert report["status"] == "OK"
    assert report["has_allow"] is True
    assert report["has_local_stratum"] is True


def test_check_workstation_chrony_warns_when_missing_lines(tmp_path: pathlib.Path):
    """Missing 'allow' or 'local stratum' yields WARN with actionable hint."""
    conf = tmp_path / "chrony.conf"
    conf.write_text("server pool.ntp.org iburst\n")
    report = check_workstation_chrony_config(conf_path=conf)
    assert report["status"] == "WARN"
    assert report["has_allow"] is False
    assert report["has_local_stratum"] is False
    assert "allow 192.168" in report["hint"]


def test_check_workstation_chrony_skips_when_no_chrony(tmp_path: pathlib.Path):
    """If the chrony.conf path doesn't exist (Windows or chrony not installed),
    return SKIPPED with a clear reason."""
    report = check_workstation_chrony_config(conf_path=tmp_path / "absent.conf")
    assert report["status"] == "SKIPPED"
    assert "chrony.conf" in report["reason"]
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/test_ssh.py -v -k workstation_chrony
```
Expected: ImportError on `check_workstation_chrony_config`.

- [ ] **Step 3: Implement `check_workstation_chrony_config` in `src/robobench/ssh.py`**

Append to the file (after the `SSHClient` class):

```python
def check_workstation_chrony_config(
    conf_path: "pathlib.Path | str" = "/etc/chrony/chrony.conf",
) -> dict:
    """Check the workstation's chrony.conf has the lines required to serve the robot.

    The robot's chrony follows the workstation as its NTP server. For that to
    work, the workstation must:
      1. Allow the robot's subnet (``allow 192.168.0.0/16`` or similar)
      2. Advertise a local stratum so chrony will serve time even without
         upstream sync (``local stratum 10``)

    Returns a structured dict::

        {
          "status": "OK" | "WARN" | "SKIPPED",
          "has_allow": bool,           # not present if SKIPPED
          "has_local_stratum": bool,   # not present if SKIPPED
          "hint": str,                 # present on WARN
          "reason": str,               # present on SKIPPED
        }

    SKIPPED indicates chrony.conf was not found — either the workstation has no
    chrony installed (Windows, or a minimal Linux), or the path is non-standard.
    Callers should treat SKIPPED as "user needs to verify manually".
    """
    import pathlib
    import re

    path = pathlib.Path(conf_path)
    if not path.exists():
        return {
            "status": "SKIPPED",
            "reason": f"chrony.conf not found at {path}; install chrony or pass conf_path=",
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    has_allow = bool(re.search(r"^\s*allow\s+192\.168", text, re.MULTILINE))
    has_local_stratum = bool(re.search(r"^\s*local\s+stratum\s+\d+", text, re.MULTILINE))
    if has_allow and has_local_stratum:
        return {"status": "OK", "has_allow": True, "has_local_stratum": True}
    return {
        "status": "WARN",
        "has_allow": has_allow,
        "has_local_stratum": has_local_stratum,
        "hint": (
            "Add the following lines to /etc/chrony/chrony.conf and run "
            "'sudo systemctl restart chrony':\n"
            "    allow 192.168.0.0/16\n"
            "    local stratum 10"
        ),
    }
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/unit/test_ssh.py -v
```
Expected: 7 tests pass in `test_ssh.py` (4 existing + 3 new).

- [ ] **Step 5: Failing test for `setup_clock_sync` integration in `tests/unit/robots/test_turtlebot4.py`**

Append:

```python
def test_setup_clock_sync_includes_workstation_chrony_check_in_report(mocker):
    """setup_clock_sync's report includes a workstation_chrony field from the local check."""
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.run.side_effect = [
        MagicMock(returncode=0, stdout="ii  chrony\n", stderr=""),   # dpkg
        MagicMock(returncode=0, stdout="", stderr=""),               # tee + restart
        MagicMock(returncode=0, stdout="1748347210\n", stderr=""),   # date
        MagicMock(returncode=0, stdout="ok", stderr=""),             # curl
    ]
    mocker.patch(
        "robobench.robots.turtlebot4.SSHClient", return_value=fake_client
    )
    mocker.patch(
        "robobench.robots.turtlebot4._now_utc",
        return_value=datetime(2026, 5, 27, 12, 0, 11, tzinfo=UTC),
    )
    mocker.patch(
        "robobench.robots.turtlebot4.check_workstation_chrony_config",
        return_value={"status": "WARN", "has_allow": False, "has_local_stratum": False, "hint": "..."},
    )

    report = _adapter().setup_clock_sync(workstation_ip="10.0.0.5")

    assert "workstation_chrony" in report
    assert report["workstation_chrony"]["status"] == "WARN"
```

- [ ] **Step 6: Run, confirm fail**

```bash
pytest tests/unit/robots/test_turtlebot4.py -v -k workstation_chrony_check_in_report
```

- [ ] **Step 7: Wire `check_workstation_chrony_config` into `setup_clock_sync`**

In `src/robobench/robots/turtlebot4.py`:

(a) Add to imports — find the existing `from robobench.ssh import SSHClient` line and change it to:

```python
from robobench.ssh import SSHClient, check_workstation_chrony_config
```

(b) Inside `setup_clock_sync`, add the workstation check at the start of the method body (right after the `report: dict = {...}` initialization). Update the report dict initialization to include the new field:

```python
    def setup_clock_sync(self, workstation_ip: str) -> dict:
        """Configure chrony on the robot to follow the workstation; restart Create3 NTP.

        Returns a structured report dict. Mirrors upstream ``deploy.sh`` Step 1
        without the human-friendly logging.
        """
        report: dict = {
            "workstation_chrony": None,
            "chrony_installed": False,
            "chrony_configured": False,
            "create3_ntp_restarted": False,
            "drift_seconds": None,
        }
        report["workstation_chrony"] = check_workstation_chrony_config()

        chrony_conf = (
            ...  # rest of method unchanged
```

The rest of the method (chrony_conf string, the `with SSHClient(...)` block, etc.) stays exactly as it was.

- [ ] **Step 8: Run, confirm pass + ruff**

```bash
pytest -q
ruff check src tests && ruff format --check src tests
```
Expected: 53 total tests pass (49 from Task 6 + 3 new ssh tests + 1 new robot test).

- [ ] **Step 9: Commit**

```bash
git add src/robobench/ssh.py src/robobench/robots/turtlebot4.py tests/unit/test_ssh.py tests/unit/robots/test_turtlebot4.py
git commit -m "feat(ssh): check workstation chrony config to prevent setup_clock_sync false positive"
```

---

## Task 8: Architecture documentation

**Files:** `docs/architecture.md`

- [ ] **Step 1: Write the architecture doc**

Create `docs/architecture.md` with this exact content:

````markdown
# Robobench Architecture

This document covers the four design decisions a contributor needs to
understand before adding a new robot adapter, diagnostic panel, or CLI
subcommand.

## 1. Why an Abstract Base Class (not a Protocol)?

`RobotAdapter` is an `abc.ABC` with `@abstractmethod` decorators. We did NOT
use `typing.Protocol` even though Protocol would give us structural typing.

**Reason:** runtime enforcement. With ABC, instantiating an adapter that's
missing a method fails at construction time with a clear `TypeError`. With
Protocol, the same mistake fails much later — usually at the first method
call that uses the missing piece, often in the middle of a bring-up. For an
academic platform where students will write their own adapters, the
fail-fast behavior matters more than the duck-typing flexibility.

A second-order benefit: ABC subclasses *must* be explicit about their
parent (`class FooAdapter(RobotAdapter):`). This serves as in-code
documentation — anyone reading `robobench/robots/foo.py` immediately knows
what contract it fulfills.

## 2. Why paramiko (not sshpass or fabric)?

`robobench.ssh.SSHClient` wraps paramiko. Earlier drafts used
`sshpass + subprocess`; current code does not.

**Reasons:**
- **No external binary.** `pip install robobench` is enough — no
  `apt install sshpass` or Homebrew formula required. Works on native
  Windows + Git Bash for students who don't yet have WSL set up.
- **Tests mock at the right level.** Tests patch
  `robobench.ssh.paramiko.SSHClient`. With sshpass+subprocess, tests had
  to assert command list shape including auth-flag positioning — brittle.
- **Programmatic SFTP.** `put_text()` writes config files to the robot
  cleanly. With sshpass we needed `cat | ssh user@host 'sudo tee path'`
  which is error-prone around quoting.

We did NOT use `fabric` because (a) it's a heavy dep with strong opinions
about task scheduling that don't match robobench's per-method calls, and
(b) it would force a third abstraction layer (fabric → paramiko →
robobench). Paramiko directly gives us what we need.

## 3. Why lazy `rclpy` import in `robobench.diagnostics`?

`robobench.diagnostics.lifecycle_activator` is a ROS2 Python node — it
extends `rclpy.node.Node` and calls services via lifecycle_msgs and
geometry_msgs. Those are NOT pip packages; they only exist on a ROS2-sourced
system.

The naïve approach — `import rclpy` at module top — would break
`pip install robobench` for anyone without ROS2. Students on Windows
machines (where ROS2 native install is awkward) couldn't even install the
tool to read its help text.

**Solution:** all ROS-dependent imports live inside a `_lazy_imports()`
function that's called as the first statement of `main()`. The module
itself is importable in plain Python; failures only happen at execution
time, with a clear error message that says "source your ROS2 setup".

The `LifecycleActivator(Node)` class definition was also moved inside
`main()` because subclassing `Node` requires `Node` to be importable —
which it isn't at module top. This is the only invasive change required
by lazy imports.

**When you write a new diagnostic node:** put your ROS2 imports in a
`_lazy_imports()` helper, define your `Node` subclass inside `main()`,
and you're good.

## 4. Why shell out to the ROS2 CLI (instead of using rclpy directly)?

`build()`, `launch()`, `health_check()`, etc. all run `subprocess.Popen` /
`subprocess.run` against the `ros2` / `colcon` / `pkill` binaries.

**Reasons (v0.2-era):**
- **No rclpy at module top.** Same reason as decision #3 — keeps the
  adapter pip-installable without ROS2.
- **Matches deploy.sh's mental model.** Anyone who can read the upstream
  bash deploy can read the adapter. Easy onboarding.
- **Subprocess is the same on Linux and Mac.** rclpy-direct probes would
  require a DDS participant in robobench's own process, which adds
  startup cost and FastDDS Discovery Server complexity to every CLI call.

**The cost:** each `ros2 topic echo --once` takes 10-15 seconds with the
default timeout. `health_check` is currently ~45 seconds for four probes.

**Phase C will likely move the diagnostic-panel layer to rclpy direct.**
A persistent FastAPI server can hold one rclpy node alive across many
requests, paying the DDS-discovery cost once. Adapters stay subprocess-
based; only the panel layer switches.

## File-by-file map

| File | Owns |
|------|------|
| `src/robobench/adapter_base.py` | The `RobotAdapter` ABC. The single source of truth for the per-robot contract. |
| `src/robobench/ssh.py` | All paramiko interaction. `SSHClient` + free helpers like `check_workstation_chrony_config`. |
| `src/robobench/_process.py` | Local subprocess. `run_local` is the only function adapters use to invoke local binaries. |
| `src/robobench/config.py` | Reads `config.yaml`, returns adapter constructor kwargs. |
| `src/robobench/cli.py` | argparse + subcommand dispatch. Thin — does not contain robot logic. |
| `src/robobench/diagnostics/lifecycle_activator.py` | The Nav2 lifecycle activator, moved from upstream with lazy rclpy. |
| `src/robobench/robots/turtlebot4.py` | The reference robot adapter. Future adapters mirror this file's shape. |

## How to add a new robot adapter

1. Create `src/robobench/robots/<robot>.py`.
2. `@dataclass class <Robot>Adapter(RobotAdapter):` with the same field
   shape as `TurtleBot4Adapter` (ip, ssh_user, ssh_pass, namespace,
   workspace_dir, build_packages, launch_package, launch_file,
   user_input_topic). Vendor-specific fields go after these.
3. Implement all 7 abstract methods from `RobotAdapter`. Use
   `SSHClient` for anything that talks to the robot; `run_local` for
   anything that runs on the workstation.
4. Add the robot's name to the `--robot` choices in `cli.py` and
   teach `_cmd_check` / `_cmd_bringup` / `_cmd_health` / `_cmd_shutdown`
   how to construct your class. (We'll generalize this dispatch in a
   future plan.)
5. Write unit tests in `tests/unit/robots/test_<robot>.py`. Mock
   `SSHClient`, `run_local`, and `subprocess.Popen` at the module level
   of your adapter file — never call the real ROS2 or paramiko in unit
   tests.

For real-robot validation, add a `@pytest.mark.hardware` test alongside
the unit tests. Those are deselected by default; lab personnel run them
manually.
````

- [ ] **Step 2: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: add architecture.md covering ABC, paramiko, lazy rclpy, CLI subprocess"
```

---

## Task 9: Tutorial updates

**Files:** `docs/tutorials/bringup-walkthrough.md`

- [ ] **Step 1: Insert a "Customizing for a non-campus_guide workspace" section**

Open `docs/tutorials/bringup-walkthrough.md`. Find the section heading `## Stopping`. Before that section, insert this new section:

```markdown
## Customizing for your own workspace

The defaults assume you're using the upstream `campus_guide` package layout.
If your ROS2 workspace has different package names or launch files, extend
your `config.yaml` with optional `build`, `launch`, and `health` sections:

```yaml
robot:
  ip: "192.168.50.31"
  ssh_user: "ubuntu"
  ssh_pass: "turtlebot4"
  namespace: "turtlebot468"

workspace:
  dir: "~/my_workspace"

build:
  packages: ["my_nav_pkg", "my_safety_pkg"]   # default: ["campus_nav_llm"]

launch:
  package: "my_nav_pkg"                       # default: "campus_nav_llm"
  file: "bringup.launch.py"                   # default: "navigation_mode.launch.py"

health:
  user_input_topic: "/my_cmd_topic"           # default: "/user_input"
```

Any field you omit falls back to the campus_guide default, so a minimal
`config.yaml` keeps working unchanged.

```

(The closing ``` after `"/user_input"` ends the yaml block; the next
``` after that ends the prose block before `## Stopping`.)

- [ ] **Step 2: Commit**

```bash
git add docs/tutorials/bringup-walkthrough.md
git commit -m "docs(tutorials): document config.yaml build/launch/health customization"
```

---

## Task 10: CHANGELOG + version bump + tag + push

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `src/robobench/__init__.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Update CHANGELOG.md**

Replace the existing `## [Unreleased]` block with:

```markdown
## [Unreleased]

## [0.2.1a0] — 2026-05-27

### Added

- `robobench.ssh.check_workstation_chrony_config` — verifies the workstation's
  chrony.conf has the `allow` and `local stratum` lines required for the
  robot to follow it as an NTP source. Surfaces as `workstation_chrony` in
  `setup_clock_sync`'s report.
- `TurtleBot4Adapter` gained four optional config fields with v0.2-compatible
  defaults: `build_packages`, `launch_package`, `launch_file`,
  `user_input_topic`. Set them in `config.yaml` (`build.packages`,
  `launch.package`, `launch.file`, `health.user_input_topic`) to point
  robobench at any ROS2 workspace — not just campus_guide.
- `docs/architecture.md` — documents the ABC, paramiko, lazy rclpy, and
  subprocess design decisions for contributors.

### Changed

- `TurtleBot4Adapter.workspace_dir` is now `str | None` (was `str` with a
  misleading `~/CS5335TurtleBot` default). `build()` raises a clear
  `ValueError` if it's needed but not set.
- `build()` / `launch()` / `health_check()` no longer hard-code
  `campus_nav_llm`-specific names; they read from the new dataclass fields.
- `ui/README.md` now leads with a status banner clarifying the dashboard
  and speech UI are imported v0 baseline and not yet wired into robobench.

### Fixed

- `setup_clock_sync` no longer silently reports success when the workstation
  itself isn't configured to serve NTP. The report's new `workstation_chrony`
  field surfaces a `WARN` with an actionable fix when chrony.conf is missing
  the required lines.
```

- [ ] **Step 2: Bump version**

In `src/robobench/__init__.py`, change `__version__ = "0.2.0a0"` to `__version__ = "0.2.1a0"`.

In `pyproject.toml`, change `version = "0.2.0a0"` to `version = "0.2.1a0"`.

- [ ] **Step 3: Final sweep**

```bash
source .venv/Scripts/activate
pip install -e ".[dev]"
pytest -q
ruff check . && ruff format --check .
robobench --version       # robobench 0.2.1a0
```
Expected: all tests pass (53+), ruff clean, version prints correctly.

- [ ] **Step 4: Commit + tag + push**

```bash
git add CHANGELOG.md src/robobench/__init__.py pyproject.toml
git commit -m "chore: bump version to 0.2.1a0 and update CHANGELOG"
git tag -a v0.2.1a0 -m "v0.2.1-alpha — stabilization: config generalization, workstation chrony check, architecture doc"
git push origin main
git push origin v0.2.1a0
```

- [ ] **Step 5: Verify**

```bash
git tag --list
```
Expected: `v0.1.0a0`, `v0.2.0a0`, `v0.2.1a0` all present.

---

## Self-Review (Plan Author Notes)

**Spec coverage check:**
- #2 remove campus_nav_llm hardcoding → Tasks 3, 4, 5, 6 ✅
- #3 workspace_dir default fix → Task 1 ✅
- #4 ui/ status banner → Task 2 ✅
- #5 architecture.md → Task 8 ✅
- #6 workstation chrony false-positive fix → Task 7 ✅
- Tutorial update for new config schema → Task 9 ✅
- CHANGELOG + tag → Task 10 ✅

**Placeholder scan:** No "TBD", no "implement appropriate X", no "similar to". Every code step contains the exact code to write.

**Type consistency:**
- New dataclass fields (`build_packages: list[str]`, `launch_package: str`, `launch_file: str`, `user_input_topic: str`) are introduced in Task 3 and consumed verbatim in Tasks 4, 5, 6. Names match.
- `check_workstation_chrony_config` signature `(conf_path: pathlib.Path | str = "/etc/chrony/chrony.conf")` returns a dict with keys `status`, `has_allow`, `has_local_stratum`, `hint`, `reason` — these are used identically in test assertions (Task 7 Steps 1, 5) and the integration in `setup_clock_sync` (Task 7 Step 7).
- `workspace_dir: str | None = None` introduced in Task 1, referenced by `build()` validation in Task 4.

**Risk notes:**
1. **No real-robot verification** — by design (user's call). Lab personnel will run integration tests; their findings are out of scope for v0.2.1.
2. **`check_workstation_chrony_config` on Windows.** The default path `/etc/chrony/chrony.conf` doesn't exist on Windows; the function returns SKIPPED gracefully. No crash, but Windows users running `bringup` get a SKIPPED workstation-chrony status. That's correct behavior — Windows users should use WSL for the chrony side.
3. **`ui/README.md` banner placement.** Task 2 prepends to the existing file. If the current file's first line is the heading, the banner goes above it. Confirm the file state before editing.
4. **`workspace_dir` default change is a behavior change.** Any code calling `TurtleBot4Adapter()` without `workspace_dir` previously got the implicit `"~/CS5335TurtleBot"`. Now they get `None`, and `build()` raises. Tests in `tests/unit/test_adapter_base.py` use a `Complete(RobotAdapter)` fixture that's unrelated to this dataclass — no change needed there. The Phase A test that constructs `TurtleBot4Adapter(..., workspace_dir="~/CS5335TurtleBot")` is explicit so it still works.

**Estimated effort:** 10 tasks, ~3-4 hours total for a focused implementer using subagent-driven mode. Most tasks are 15-20 minutes; Task 7 and Task 8 are 30-40 minutes each.

---

## Out of scope for v0.2.1 (explicitly deferred)

- **Real-robot validation** — lab personnel handle this in their own workflow.
- **Diagnostic panels** (DDS, TF, sensor health) — Phase C.
- **Actionable failure catalog** with symptom → cause → fix mappings — Phase C.
- **rclpy-direct probes** (replacing CLI shell-outs for speed) — Phase C.
- **Second robot adapter** (TurtleBot3) — Phase D.
- **MkDocs site / GitHub Pages** — Phase D.
- **Generalizing CLI dispatch** so `--robot` choices auto-populate from
  registered adapters — Phase D when we add the second adapter.
- **Workstation chrony auto-fix** (writing to `/etc/chrony/chrony.conf` with
  sudo) — too invasive for a debug tool; warn + hint is the right level.
