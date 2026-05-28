# Robobench v0.2 (Phase B) Implementation Plan — Adapter Completeness

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `TurtleBot4Adapter` fully implement the `RobotAdapter` contract — wire up `build`, `launch`, `activate_lifecycle`, `set_initial_pose`, `health_check`, `shutdown` on top of a paramiko-based SSH layer and a local-subprocess helper, plus extract the upstream `lifecycle_activator` into robobench's own tree, plus add `robobench bringup` / `health` / `shutdown` CLI subcommands. Ship as v0.2.0a0.

**Architecture:**
- **SSH boundary:** introduce `robobench.ssh.SSHClient` thin wrapper around paramiko. Replaces `sshpass + subprocess` (which doesn't work on native Windows). Tests mock the wrapper, not paramiko internals.
- **Local subprocess boundary:** introduce `robobench._process` helpers (`run_local`, `stream_local`). All `subprocess.run` calls go through this module so tests have one clean mock surface.
- **`lifecycle_activator` move:** copy the upstream ROS2 Python node into `src/robobench/diagnostics/lifecycle_activator.py`. `rclpy` and related imports become lazy (inside functions) so robobench remains `pip install`-able without ROS2.
- **`health_check` schema:** structured dict — `{"checks": {...}, "overall": "HEALTHY|DEGRADED|UNHEALTHY"}`. Same dict surfaces in `robobench health` JSON output and (in Phase C) the dashboard.
- **CLI orchestration:** `robobench bringup` walks `setup_clock_sync → build → launch → activate_lifecycle → health_check`. Each step logs to stderr; on failure, surfaces the actionable error and stops.
- **Hardware-touching tests:** marked `@pytest.mark.hardware`, deselected by default. CI never runs them; humans run them on demand against real robots.

**Tech Stack:**
- New dependency: `paramiko>=3.4` (SSH), `types-paramiko` in dev (stubs)
- New dev dependency: `pytest-mock` (already present from Phase A)
- ROS2 components used at runtime only: `colcon`, `ros2 launch`, `ros2 topic pub`, `rclpy` (lazy import for `lifecycle_activator`)
- Python 3.11+ (unchanged)

**Prerequisites:** v0.1.0a0 must be tagged (Phase A complete). Phase A's `TurtleBot4Adapter` exists at `src/robobench/robots/turtlebot4.py` with `check_clock_offset` implemented via `sshpass`; this plan replaces that implementation.

**Repo root:** `C:\Users\chntw\Documents\robotic\robobench\`

---

## File Structure (after this plan)

```
robobench/
├── pyproject.toml                              # +paramiko dep, +hardware marker
├── src/robobench/
│   ├── __init__.py                             # version bump to 0.2.0a0
│   ├── cli.py                                  # +bringup +health +shutdown subcommands
│   ├── adapter_base.py                         # unchanged
│   ├── ssh.py                                  # NEW — paramiko wrapper
│   ├── _process.py                             # NEW — subprocess helpers
│   ├── config.py                               # NEW — config.yaml loader
│   ├── diagnostics/
│   │   ├── __init__.py                         # NEW
│   │   └── lifecycle_activator.py              # NEW — moved from upstream
│   └── robots/
│       └── turtlebot4.py                       # 7 methods filled in
├── tests/unit/
│   ├── test_adapter_base.py                    # unchanged
│   ├── test_cli.py                             # +6 tests for new subcommands
│   ├── test_ssh.py                             # NEW
│   ├── test_process.py                         # NEW
│   ├── test_config.py                          # NEW
│   ├── diagnostics/
│   │   ├── __init__.py                         # NEW (empty)
│   │   └── test_lifecycle_activator.py         # NEW (light — most logic deferred to ROS2)
│   └── robots/
│       └── test_turtlebot4.py                  # +many tests
├── docs/tutorials/
│   ├── connect-turtlebot4.md                   # unchanged
│   └── bringup-walkthrough.md                  # NEW
├── CHANGELOG.md                                # NEW
└── docs/superpowers/plans/
    └── 2026-05-27-robobench-v0.2-phase-b.md    # this file
```

**Responsibility map:**
- `robobench.ssh` — one class `SSHClient`. Methods: `run(cmd: list[str], timeout: float) -> SSHResult`, `put_text(remote_path, content)`. Wraps paramiko. Single connection per instance, context-manager-friendly.
- `robobench._process` — two functions: `run_local(cmd, timeout, cwd=None) -> ProcessResult` and `stream_local(cmd, cwd=None) -> Iterator[str]`. No state. The `_` prefix marks it internal.
- `robobench.config` — `load_adapter_config(path: Path) -> dict` reads upstream `config.yaml` shape and returns the kwargs `TurtleBot4Adapter(**kwargs)` expects.
- `robobench.diagnostics.lifecycle_activator` — the Python ROS2 node, callable as `python -m robobench.diagnostics.lifecycle_activator --namespace X --map-yaml Y ...`. Lazy-imports rclpy so the module itself is importable without ROS2.
- `robobench.robots.turtlebot4.TurtleBot4Adapter` — all 7 RobotAdapter methods implemented. The class stays a dataclass; methods only orchestrate `SSHClient` + `_process` + `lifecycle_activator` invocations.

---

## Task 1: Add paramiko dependency + hardware test marker

**Files:** `pyproject.toml`

- [ ] **Step 1: Add `paramiko` to runtime deps and `types-paramiko` to dev deps**

Edit `pyproject.toml`:

Replace this block:
```toml
dependencies = [
  "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-mock>=3.12",
  "ruff>=0.4",
]
```

With:
```toml
dependencies = [
  "pyyaml>=6.0",
  "paramiko>=3.4",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-mock>=3.12",
  "ruff>=0.4",
  "types-paramiko>=3.4",
]
```

- [ ] **Step 2: Register the `hardware` pytest marker**

Replace this block:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
```

With:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers -m 'not hardware'"
markers = [
  "hardware: tests that require a real robot on the network (skipped by default; opt in with -m hardware)",
]
```

- [ ] **Step 3: Refresh editable install + verify pytest still green**

```bash
cd C:/Users/chntw/Documents/robotic/robobench
source .venv/Scripts/activate
pip install -e ".[dev]"
pytest -q
ruff check . && ruff format --check .
```
Expected: 15 passed (Phase A's tests), ruff clean.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore(deps): add paramiko and register hardware test marker"
```

---

## Task 2: SSHClient wrapper (TDD)

**Files:**
- Create: `src/robobench/ssh.py`
- Create: `tests/unit/test_ssh.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_ssh.py`:

```python
"""Tests for robobench.ssh."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from robobench.ssh import SSHClient, SSHResult


def test_sshclient_run_returns_stdout_and_returncode(mocker):
    """A successful run returns SSHResult with rc=0 and stdout."""
    fake_client = MagicMock()
    fake_stdout = MagicMock()
    fake_stdout.read.return_value = b"1748347205\n"
    fake_stdout.channel.recv_exit_status.return_value = 0
    fake_stderr = MagicMock()
    fake_stderr.read.return_value = b""
    fake_client.exec_command.return_value = (MagicMock(), fake_stdout, fake_stderr)

    mocker.patch("robobench.ssh.paramiko.SSHClient", return_value=fake_client)

    with SSHClient("192.168.50.31", "ubuntu", "turtlebot4") as client:
        result = client.run(["date", "+%s"], timeout=5.0)

    assert isinstance(result, SSHResult)
    assert result.returncode == 0
    assert result.stdout == "1748347205\n"
    assert result.stderr == ""


def test_sshclient_run_nonzero_returncode_is_preserved(mocker):
    """A nonzero exit is returned, not raised."""
    fake_client = MagicMock()
    fake_stdout = MagicMock()
    fake_stdout.read.return_value = b""
    fake_stdout.channel.recv_exit_status.return_value = 127
    fake_stderr = MagicMock()
    fake_stderr.read.return_value = b"command not found\n"
    fake_client.exec_command.return_value = (MagicMock(), fake_stdout, fake_stderr)
    mocker.patch("robobench.ssh.paramiko.SSHClient", return_value=fake_client)

    with SSHClient("192.168.50.31", "ubuntu", "turtlebot4") as client:
        result = client.run(["nope"], timeout=5.0)

    assert result.returncode == 127
    assert "command not found" in result.stderr


def test_sshclient_connect_failure_raises_runtime_error(mocker):
    """A paramiko connect error becomes a RuntimeError with the host in the message."""
    import paramiko

    fake_client = MagicMock()
    fake_client.connect.side_effect = paramiko.SSHException("auth failed")
    mocker.patch("robobench.ssh.paramiko.SSHClient", return_value=fake_client)

    with pytest.raises(RuntimeError, match="192.168.50.31"):
        with SSHClient("192.168.50.31", "ubuntu", "wrong-pass"):
            pass


def test_sshclient_put_text_writes_via_sftp(mocker):
    """put_text opens an SFTP channel and writes the bytes."""
    fake_client = MagicMock()
    fake_sftp = MagicMock()
    fake_file = MagicMock()
    fake_sftp.open.return_value.__enter__.return_value = fake_file
    fake_client.open_sftp.return_value = fake_sftp
    mocker.patch("robobench.ssh.paramiko.SSHClient", return_value=fake_client)

    with SSHClient("192.168.50.31", "ubuntu", "turtlebot4") as client:
        client.put_text("/tmp/x.conf", "hello\n")

    fake_sftp.open.assert_called_once_with("/tmp/x.conf", "w")
    fake_file.write.assert_called_once_with("hello\n")
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/test_ssh.py -v
```
Expected: `ImportError: cannot import name 'SSHClient' from 'robobench.ssh'`.

- [ ] **Step 3: Implement `src/robobench/ssh.py`**

```python
"""Thin wrapper around paramiko for robot SSH operations.

Why a wrapper? Tests mock `SSHClient` instead of poking at paramiko's
internals. Real code uses the same boring interface — ``with SSHClient(...) as c:
result = c.run([...])`` — regardless of whether keys, passwords, or agents are
in play later.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from types import TracebackType

import paramiko


@dataclass(frozen=True)
class SSHResult:
    """Outcome of one remote command."""

    returncode: int
    stdout: str
    stderr: str


class SSHClient:
    """Single-connection SSH helper for one robot.

    Use as a context manager so the connection is closed deterministically::

        with SSHClient(host, user, password) as c:
            result = c.run(["date", "+%s"], timeout=5.0)
    """

    def __init__(self, host: str, user: str, password: str, port: int = 22) -> None:
        self.host = host
        self.user = user
        self._password = password
        self.port = port
        self._client: paramiko.SSHClient | None = None

    def __enter__(self) -> SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self._password,
                timeout=10,
                allow_agent=False,
                look_for_keys=False,
            )
        except paramiko.SSHException as exc:
            raise RuntimeError(f"SSH connect to {self.host}:{self.port} failed: {exc}") from exc
        self._client = client
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def run(self, cmd: list[str], timeout: float) -> SSHResult:
        """Run a command on the robot and return its outcome."""
        if self._client is None:
            raise RuntimeError("SSHClient not connected; use as a context manager")
        # shlex.join produces a safe single string for the remote shell.
        joined = shlex.join(cmd)
        _stdin, stdout, stderr = self._client.exec_command(joined, timeout=timeout)
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return SSHResult(returncode=rc, stdout=out, stderr=err)

    def put_text(self, remote_path: str, content: str) -> None:
        """Write a text file to the robot via SFTP."""
        if self._client is None:
            raise RuntimeError("SSHClient not connected; use as a context manager")
        sftp = self._client.open_sftp()
        try:
            with sftp.open(remote_path, "w") as f:
                f.write(content)
        finally:
            sftp.close()
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/unit/test_ssh.py -v
ruff check src tests && ruff format src tests
```
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/ssh.py tests/unit/test_ssh.py
git commit -m "feat(ssh): add paramiko-based SSHClient wrapper"
```

---

## Task 3: Migrate `check_clock_offset` from `sshpass` to `SSHClient`

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Update the two existing `check_clock_offset` tests to mock `SSHClient` instead of subprocess**

In `tests/unit/robots/test_turtlebot4.py`, replace the two `check_clock_offset` tests (`test_check_clock_offset_returns_seconds` and `test_check_clock_offset_raises_on_ssh_failure`) with:

```python
from unittest.mock import MagicMock


def test_check_clock_offset_returns_seconds(mocker):
    """Opens SSH to the robot, reads epoch via `date +%s`, subtracts from local time."""
    fake_local = datetime(2026, 5, 27, 12, 0, 10, tzinfo=UTC)
    mocker.patch("robobench.robots.turtlebot4._now_utc", return_value=fake_local)

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.run.return_value = MagicMock(returncode=0, stdout="1748347205\n", stderr="")
    sshclient_ctor = mocker.patch(
        "robobench.robots.turtlebot4.SSHClient", return_value=fake_client
    )

    offset = _adapter().check_clock_offset()

    assert offset == pytest.approx(5.0, abs=0.01)
    sshclient_ctor.assert_called_once_with("192.168.50.31", "ubuntu", "turtlebot4")
    fake_client.run.assert_called_once_with(["date", "+%s"], timeout=10)


def test_check_clock_offset_raises_on_ssh_failure(mocker):
    """A non-zero remote exit becomes a RuntimeError with stderr in the message."""
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.run.return_value = MagicMock(
        returncode=127,
        stdout="",
        stderr="bash: date: command not found",
    )
    mocker.patch(
        "robobench.robots.turtlebot4.SSHClient", return_value=fake_client
    )

    with pytest.raises(RuntimeError, match="date: command not found"):
        _adapter().check_clock_offset()
```

Also: at the top of the file, ensure these imports exist (add `UTC` if missing):
```python
from datetime import UTC, datetime
```
Remove now-unused imports of `subprocess` and `MagicMock` if they were imported only for these two tests (`MagicMock` is still used above, leave it).

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/robots/test_turtlebot4.py -v
```
Expected: the two `check_clock_offset` tests fail (current impl still uses `subprocess` + `sshpass`).

- [ ] **Step 3: Rewrite `check_clock_offset` in `src/robobench/robots/turtlebot4.py`**

At the top of the file, replace:
```python
import subprocess
```
with:
```python
from robobench.ssh import SSHClient
```

Replace the entire `check_clock_offset` method body with:

```python
    def check_clock_offset(self) -> float:
        """Return ``local_time - robot_time`` in seconds (positive = robot is behind)."""
        with SSHClient(self.ip, self.ssh_user, self.ssh_pass) as ssh:
            result = ssh.run(["date", "+%s"], timeout=10)
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
pytest -q
ruff check src tests && ruff format --check src tests
```
Expected: all 15+ tests pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/robots/turtlebot4.py tests/unit/robots/test_turtlebot4.py
git commit -m "refactor(robots): switch check_clock_offset from sshpass to paramiko"
```

---

## Task 4: Local subprocess helper (TDD)

**Files:**
- Create: `src/robobench/_process.py`
- Create: `tests/unit/test_process.py`

- [ ] **Step 1: Failing tests at `tests/unit/test_process.py`**

```python
"""Tests for robobench._process."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from robobench._process import ProcessResult, run_local


def test_run_local_returns_process_result(mocker):
    """A wrapper that captures rc/stdout/stderr from subprocess.run."""
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "hello\n"
    completed.stderr = ""
    mocker.patch("robobench._process.subprocess.run", return_value=completed)

    result = run_local(["echo", "hello"], timeout=5.0)

    assert isinstance(result, ProcessResult)
    assert result.returncode == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""


def test_run_local_passes_cwd_through(mocker):
    """The cwd argument is forwarded to subprocess.run."""
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = ""
    completed.stderr = ""
    run_mock = mocker.patch("robobench._process.subprocess.run", return_value=completed)

    run_local(["pwd"], timeout=5.0, cwd="/tmp")

    assert run_mock.call_args.kwargs["cwd"] == "/tmp"


def test_run_local_timeout_raises(mocker):
    """A subprocess.TimeoutExpired bubbles up as RuntimeError with the cmd."""
    mocker.patch(
        "robobench._process.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="sleep", timeout=1.0),
    )
    with pytest.raises(RuntimeError, match="timed out"):
        run_local(["sleep", "10"], timeout=1.0)
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/test_process.py -v
```
Expected: ImportError on `robobench._process`.

- [ ] **Step 3: Implement `src/robobench/_process.py`**

```python
"""Local subprocess helpers used by robobench adapters.

All subprocess calls in robobench go through ``run_local`` so tests have a
single, boring mock surface. Adapters never call ``subprocess.run`` directly.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessResult:
    """Outcome of one local subprocess invocation."""

    returncode: int
    stdout: str
    stderr: str


def run_local(
    cmd: list[str],
    *,
    timeout: float,
    cwd: str | None = None,
) -> ProcessResult:
    """Run a local command, return its result. Raises RuntimeError on timeout."""
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Local command timed out after {timeout}s: {' '.join(cmd)}"
        ) from exc
    return ProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
```

- [ ] **Step 4: Run, confirm pass + ruff**

```bash
pytest tests/unit/test_process.py -v
ruff check src tests && ruff format src tests
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/robobench/_process.py tests/unit/test_process.py
git commit -m "feat(_process): add subprocess wrapper for adapter use"
```

---

## Task 5: `setup_clock_sync` method (TDD)

This is a new concrete method on `TurtleBot4Adapter` (not on the ABC — too vendor-specific). It encodes deploy.sh Step 1: SSH in, install chrony if missing, write chrony.conf pointing at the workstation, restart chrony, hit the Create3 NTP restart REST endpoint, verify drift.

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Add failing tests at end of `tests/unit/robots/test_turtlebot4.py`**

```python
def test_setup_clock_sync_writes_chrony_conf_and_restarts(mocker):
    """setup_clock_sync writes /etc/chrony/chrony.conf, restarts chrony, hits Create3."""
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    # Sequence of expected ssh.run() calls (in order, simplified)
    fake_client.run.side_effect = [
        MagicMock(returncode=0, stdout="ii  chrony\n", stderr=""),   # dpkg -l chrony
        MagicMock(returncode=0, stdout="", stderr=""),               # sudo tee + restart chrony (combined)
        MagicMock(returncode=0, stdout="1748347210\n", stderr=""),   # date +%s for drift verify
        MagicMock(returncode=0, stdout='{"status":"ok"}', stderr=""),# curl Create3
    ]
    mocker.patch(
        "robobench.robots.turtlebot4.SSHClient", return_value=fake_client
    )
    mocker.patch(
        "robobench.robots.turtlebot4._now_utc",
        return_value=datetime(2026, 5, 27, 12, 0, 11, tzinfo=UTC),
    )

    report = _adapter().setup_clock_sync(workstation_ip="192.168.50.10")

    assert report["chrony_installed"] is True
    assert report["chrony_configured"] is True
    assert report["create3_ntp_restarted"] is True
    assert report["drift_seconds"] == pytest.approx(1.0, abs=0.5)


def test_setup_clock_sync_installs_chrony_if_missing(mocker):
    """If `dpkg -l chrony` reports no install, the apt-get install is run."""
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.run.side_effect = [
        MagicMock(returncode=1, stdout="", stderr=""),               # dpkg -l chrony — not installed
        MagicMock(returncode=0, stdout="", stderr=""),               # sudo apt-get install -y chrony
        MagicMock(returncode=0, stdout="", stderr=""),               # tee + restart
        MagicMock(returncode=0, stdout="1748347210\n", stderr=""),   # date +%s
        MagicMock(returncode=0, stdout="ok", stderr=""),             # curl
    ]
    mocker.patch(
        "robobench.robots.turtlebot4.SSHClient", return_value=fake_client
    )
    mocker.patch(
        "robobench.robots.turtlebot4._now_utc",
        return_value=datetime(2026, 5, 27, 12, 0, 11, tzinfo=UTC),
    )

    report = _adapter().setup_clock_sync(workstation_ip="192.168.50.10")

    # First call: dpkg check; second call: install
    first_call_cmd = fake_client.run.call_args_list[0].args[0]
    second_call_cmd = fake_client.run.call_args_list[1].args[0]
    assert "dpkg" in first_call_cmd[0]
    assert any("apt-get" in part for part in second_call_cmd)
    assert report["chrony_installed"] is True
```

- [ ] **Step 2: Run, confirm fail** (`NotImplementedError` or AttributeError)

```bash
pytest tests/unit/robots/test_turtlebot4.py -v -k clock_sync
```

- [ ] **Step 3: Implement `setup_clock_sync`**

In `src/robobench/robots/turtlebot4.py`, just below `check_clock_offset`, add:

```python
    def setup_clock_sync(self, workstation_ip: str) -> dict:
        """Configure chrony on the robot to follow the workstation; restart Create3 NTP.

        Returns a structured report dict. Mirrors upstream ``deploy.sh`` Step 1
        without the human-friendly logging.
        """
        report: dict = {
            "chrony_installed": False,
            "chrony_configured": False,
            "create3_ntp_restarted": False,
            "drift_seconds": None,
        }

        chrony_conf = (
            f"server {workstation_ip} prefer iburst minpoll 0 maxpoll 2\n"
            "pool ntp.ubuntu.com iburst maxsources 2\n"
            "local stratum 11\n"
            "allow 192.168.0.0/16\n"
            "makestep 0.1 -1\n"
            "rtcsync\n"
        )

        with SSHClient(self.ip, self.ssh_user, self.ssh_pass) as ssh:
            # 1. Check if chrony is installed; install if not.
            check = ssh.run(["dpkg", "-l", "chrony"], timeout=15)
            if check.returncode == 0 and "ii" in check.stdout:
                report["chrony_installed"] = True
            else:
                install = ssh.run(
                    ["sudo", "apt-get", "install", "-y", "chrony"], timeout=120
                )
                report["chrony_installed"] = install.returncode == 0
                if install.returncode != 0:
                    raise RuntimeError(
                        f"chrony install failed: {install.stderr.strip()}"
                    )

            # 2. Write config + restart chrony. Use stdin-redirected tee to avoid
            #    leaking the config via the process listing.
            write_cmd = [
                "sh",
                "-c",
                (
                    f"echo {shlex.quote(chrony_conf)} "
                    "| sudo tee /etc/chrony/chrony.conf > /dev/null "
                    "&& sudo systemctl restart chrony"
                ),
            ]
            write = ssh.run(write_cmd, timeout=30)
            report["chrony_configured"] = write.returncode == 0
            if write.returncode != 0:
                raise RuntimeError(
                    f"chrony config/restart failed: {write.stderr.strip()}"
                )

            # 3. Verify drift with a fresh date +%s read.
            date_res = ssh.run(["date", "+%s"], timeout=10)
            if date_res.returncode == 0:
                robot_epoch = float(date_res.stdout.strip())
                local_epoch = _now_utc().timestamp()
                report["drift_seconds"] = local_epoch - robot_epoch

            # 4. Kick Create3 NTP restart (HTTP REST, runs from the robot).
            create3 = ssh.run(
                [
                    "curl",
                    "-s",
                    "-m",
                    "10",
                    "-X",
                    "POST",
                    "http://192.168.186.2/api/restart-ntpd",
                ],
                timeout=15,
            )
            failure_markers = ("fail", "error", "refused")
            report["create3_ntp_restarted"] = (
                create3.returncode == 0
                and not any(m in create3.stdout.lower() for m in failure_markers)
            )

        return report
```

At the top of the file, add `import shlex` if not already present (used by `shlex.quote`).

- [ ] **Step 4: Run, confirm pass + ruff**

```bash
pytest tests/unit/robots/test_turtlebot4.py -v
ruff check src tests && ruff format src tests
```

- [ ] **Step 5: Commit**

```bash
git add src/robobench/robots/turtlebot4.py tests/unit/robots/test_turtlebot4.py
git commit -m "feat(robots): add setup_clock_sync to configure chrony + Create3 NTP"
```

---

## Task 6: `build()` method (TDD)

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Failing tests**

Append to `tests/unit/robots/test_turtlebot4.py`:

```python
def test_build_runs_colcon_in_workspace(mocker):
    """build() shells out to `colcon build --packages-select campus_nav_llm` in workspace_dir."""
    fake_result = MagicMock(returncode=0, stdout="Summary: 1 package built\n", stderr="")
    run_mock = mocker.patch(
        "robobench.robots.turtlebot4.run_local", return_value=fake_result
    )

    _adapter().build()

    call = run_mock.call_args
    cmd = call.args[0]
    assert cmd[0] == "colcon"
    assert "build" in cmd
    assert "--packages-select" in cmd
    assert "campus_nav_llm" in cmd
    assert call.kwargs["cwd"] == "~/CS5335TurtleBot"


def test_build_raises_on_nonzero(mocker):
    """A nonzero colcon exit becomes a RuntimeError with stderr."""
    fake_result = MagicMock(
        returncode=1, stdout="", stderr="error: cmake compile failed\n"
    )
    mocker.patch("robobench.robots.turtlebot4.run_local", return_value=fake_result)

    with pytest.raises(RuntimeError, match="cmake compile failed"):
        _adapter().build()
```

- [ ] **Step 2: Run, confirm fail** (currently `NotImplementedError`).

- [ ] **Step 3: Implement**

At the top of `turtlebot4.py`, add:
```python
from robobench._process import run_local
```

Replace `build()` body:
```python
    def build(self) -> None:
        """Run ``colcon build --packages-select campus_nav_llm`` in the workspace."""
        result = run_local(
            [
                "colcon",
                "build",
                "--packages-select",
                "campus_nav_llm",
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

- [ ] **Step 4: Run, confirm pass + ruff**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(robots): implement TurtleBot4 build() via colcon"
```

---

## Task 7: `launch()` method (TDD)

Launches the navigation stack in the background and writes a PID file.

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Failing tests**

Append to `tests/unit/robots/test_turtlebot4.py`:

```python
def test_launch_starts_ros2_launch_in_background_and_writes_pidfile(mocker, tmp_path):
    """launch() invokes Popen on `ros2 launch ...` and stores PID to the configured pid_path."""
    fake_popen = MagicMock()
    fake_popen.pid = 12345
    popen_mock = mocker.patch(
        "robobench.robots.turtlebot4.subprocess.Popen", return_value=fake_popen
    )
    pid_path = tmp_path / "launch.pid"

    _adapter().launch(pid_path=pid_path)

    assert pid_path.read_text().strip() == "12345"
    cmd = popen_mock.call_args.args[0]
    assert cmd[0] == "ros2"
    assert "launch" in cmd
    assert "campus_nav_llm" in cmd
    assert "navigation_mode.launch.py" in cmd


def test_launch_uses_default_pid_path_if_none_given(mocker):
    """When pid_path is None, /tmp/robobench_launch.pid is used."""
    fake_popen = MagicMock()
    fake_popen.pid = 99
    mocker.patch("robobench.robots.turtlebot4.subprocess.Popen", return_value=fake_popen)
    write_mock = mocker.patch(
        "robobench.robots.turtlebot4.Path.write_text"
    )

    _adapter().launch()

    write_mock.assert_called_once_with("99\n")
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement**

At the top of `turtlebot4.py`, ensure imports include `subprocess` (for `Popen`) and `from pathlib import Path`:

```python
import shlex
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from robobench._process import run_local
from robobench.adapter_base import RobotAdapter
from robobench.ssh import SSHClient
```

Replace `launch()` body:
```python
    def launch(self, pid_path: Path | None = None) -> None:
        """Start ``ros2 launch campus_nav_llm navigation_mode.launch.py`` in the background.

        Writes the launcher PID to ``pid_path`` (defaults to
        ``/tmp/robobench_launch.pid``) so ``shutdown()`` can find it later.
        """
        proc = subprocess.Popen(  # noqa: S603 — controlled cmd list
            [
                "ros2",
                "launch",
                "campus_nav_llm",
                "navigation_mode.launch.py",
                f"namespace:={self.namespace}",
            ]
        )
        target = pid_path if pid_path is not None else Path("/tmp/robobench_launch.pid")
        target.write_text(f"{proc.pid}\n")
```

Note: `subprocess.Popen` is used directly (not via `_process`) because it's intentionally fire-and-forget — `_process.run_local` is for synchronous calls.

- [ ] **Step 4: Run, confirm pass.** Ruff may add `# noqa: S603` complaint — keep the comment if it does, or remove the bandit category from ruff's selectors. The cmd list is fully controlled so it's safe.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(robots): implement TurtleBot4 launch() via ros2 launch"
```

---

## Task 8: `shutdown()` method (TDD)

Mirrors `stop.sh`: zero cmd_vel, kill the PID-file process, pkill the known set of nav nodes.

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Failing tests**

```python
def test_shutdown_publishes_zero_cmdvel_and_kills_pid(mocker, tmp_path):
    """shutdown() publishes zero cmd_vel, then kills the PID, then pkills stragglers."""
    pid_path = tmp_path / "launch.pid"
    pid_path.write_text("12345\n")
    run_mock = mocker.patch(
        "robobench.robots.turtlebot4.run_local",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )

    _adapter().shutdown(pid_path=pid_path)

    # First call must be a ros2 topic pub publishing zeros to /<ns>/cmd_vel.
    first_cmd = run_mock.call_args_list[0].args[0]
    assert first_cmd[:2] == ["ros2", "topic"]
    assert "/turtlebot468/cmd_vel" in first_cmd
    # PID file is removed after kill
    assert not pid_path.exists()


def test_shutdown_is_idempotent_when_no_pidfile(mocker, tmp_path):
    """shutdown() with no pid_path-pointed file still publishes cmd_vel + pkills."""
    pid_path = tmp_path / "absent.pid"
    mocker.patch(
        "robobench.robots.turtlebot4.run_local",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )

    _adapter().shutdown(pid_path=pid_path)  # no exception raised
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement**

Replace `shutdown()` body in `turtlebot4.py`:

```python
    _PKILL_PATTERNS = (
        "navigation_mode.launch",
        "lifecycle_manager",
        "lifecycle_activator",
        "/map_server ",
        "/amcl ",
        "/controller_server ",
        "/planner_server ",
        "/behavior_server ",
        "/bt_navigator ",
        "/waypoint_follower ",
        "/velocity_smoother ",
        "task_executor",
        "llm_planner",
        "odom_tf_publisher",
    )

    def shutdown(self, pid_path: Path | None = None) -> None:
        """Stop the navigation stack: zero cmd_vel, kill the launcher PID, pkill stragglers."""
        target = pid_path if pid_path is not None else Path("/tmp/robobench_launch.pid")

        # 1. Zero velocity, in case the robot is moving.
        run_local(
            [
                "ros2",
                "topic",
                "pub",
                "--once",
                f"/{self.namespace}/cmd_vel",
                "geometry_msgs/msg/Twist",
                "{linear: {x: 0.0}, angular: {z: 0.0}}",
            ],
            timeout=5.0,
        )

        # 2. Kill the recorded launcher PID, if the PID file still exists.
        if target.exists():
            try:
                pid = int(target.read_text().strip())
                run_local(["kill", str(pid)], timeout=2.0)
            except (ValueError, OSError):
                pass
            target.unlink(missing_ok=True)

        # 3. pkill known nav stack process names.
        for pattern in self._PKILL_PATTERNS:
            run_local(["pkill", "-9", "-f", pattern], timeout=2.0)
```

- [ ] **Step 4: Run, confirm pass.**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(robots): implement TurtleBot4 shutdown()"
```

---

## Task 9: Copy `lifecycle_activator.py` into robobench tree

This is a verbatim copy of the upstream node, with `rclpy` imports made lazy so non-ROS users can still import the module.

**Files:**
- Create: `src/robobench/diagnostics/__init__.py`
- Create: `src/robobench/diagnostics/lifecycle_activator.py`
- Create: `tests/unit/diagnostics/__init__.py`
- Create: `tests/unit/diagnostics/test_lifecycle_activator.py`

- [ ] **Step 1: Create the package**

```bash
mkdir -p src/robobench/diagnostics
mkdir -p tests/unit/diagnostics
```

Write `src/robobench/diagnostics/__init__.py`:

```python
"""Robobench diagnostic nodes (ROS2-dependent)."""
```

Write `tests/unit/diagnostics/__init__.py` as empty (0 bytes).

- [ ] **Step 2: Copy the upstream file**

```bash
cp examples/campus_guide/code/campus_guide_bot/campus_nav_llm/campus_nav_llm/lifecycle_activator.py src/robobench/diagnostics/lifecycle_activator.py
```

- [ ] **Step 3: Make rclpy imports lazy + add module docstring update**

Open `src/robobench/diagnostics/lifecycle_activator.py`. Replace the top-level rclpy/ROS imports block:

```python
import rclpy
from rclpy.node import Node
from lifecycle_msgs.srv import ChangeState, GetState
from lifecycle_msgs.msg import Transition
from geometry_msgs.msg import PoseWithCovarianceStamped


# Optional: nav2_msgs may not be installed in all environments
try:
    from nav2_msgs.srv import LoadMap
    HAS_LOAD_MAP = True
except ImportError:
    HAS_LOAD_MAP = False
```

with a `_lazy_imports` helper:

```python
# rclpy and the ROS message packages are only available inside a ROS2
# environment. We defer the imports so this module is importable in plain
# Python (e.g. during unit tests, packaging, docs generation).
def _lazy_imports():
    """Import rclpy and ROS message packages, raising a clear error if missing."""
    try:
        import rclpy  # noqa: F401
        from rclpy.node import Node  # noqa: F401
        from lifecycle_msgs.srv import ChangeState, GetState  # noqa: F401
        from lifecycle_msgs.msg import Transition  # noqa: F401
        from geometry_msgs.msg import PoseWithCovarianceStamped  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "lifecycle_activator requires ROS2 (rclpy, lifecycle_msgs, "
            "geometry_msgs). Source your ROS2 setup before running it."
        ) from exc

    has_load_map = True
    try:
        from nav2_msgs.srv import LoadMap  # noqa: F401
    except ImportError:
        has_load_map = False

    # Re-import into module globals so the rest of the file can use them.
    import rclpy as _rclpy
    from rclpy.node import Node as _Node
    from lifecycle_msgs.srv import ChangeState as _ChangeState, GetState as _GetState
    from lifecycle_msgs.msg import Transition as _Transition
    from geometry_msgs.msg import PoseWithCovarianceStamped as _Pose

    globals().update(
        rclpy=_rclpy,
        Node=_Node,
        ChangeState=_ChangeState,
        GetState=_GetState,
        Transition=_Transition,
        PoseWithCovarianceStamped=_Pose,
        HAS_LOAD_MAP=has_load_map,
    )
    if has_load_map:
        from nav2_msgs.srv import LoadMap as _LoadMap
        globals()["LoadMap"] = _LoadMap
```

Then at the bottom of the file, find the `main()` (or equivalent entry point) and have it call `_lazy_imports()` first thing:

```python
def main(argv=None):
    _lazy_imports()
    # ... rest of the original main ...
```

If the upstream file doesn't have a `main()` and instead runs code at module top-level, wrap that code in an `if __name__ == "__main__":` block that also calls `_lazy_imports()` first.

Also: the upstream module-level constants that referenced `Transition.TRANSITION_CONFIGURE` etc. must move into a function that runs after `_lazy_imports()`. The cleanest path: move them inside `main()`. Open the upstream file (`examples/campus_guide/code/.../lifecycle_activator.py`) for reference; the rewrite mirrors its structure but with everything ROS-dependent inside `main()`.

- [ ] **Step 4: Smoke test that the module is importable without ROS2**

Write `tests/unit/diagnostics/test_lifecycle_activator.py`:

```python
"""Smoke tests for the lifecycle_activator module.

The activator itself is a ROS2 node — its substantive behavior is exercised
only with a real robot (marked ``@pytest.mark.hardware``). The unit suite
just verifies the module imports cleanly without ROS2 installed and that
``_lazy_imports`` surfaces a clear error when ROS2 is missing.
"""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


def test_module_is_importable_without_ros2():
    """Importing the module should not require rclpy."""
    # If rclpy is already on sys.modules, fine — we just verify the import
    # path doesn't try to use it at module-load time.
    import robobench.diagnostics.lifecycle_activator  # noqa: F401


def test_lazy_imports_raises_clear_runtime_error_when_rclpy_missing():
    """When rclpy can't be imported, _lazy_imports() raises a RuntimeError
    that mentions ROS2 — not a cryptic ImportError."""
    from robobench.diagnostics.lifecycle_activator import _lazy_imports

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "rclpy" or name.startswith("rclpy."):
            raise ImportError("No module named 'rclpy'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        with pytest.raises(RuntimeError, match="ROS2"):
            _lazy_imports()
```

- [ ] **Step 5: Run, confirm pass + ruff**

```bash
pytest tests/unit/diagnostics/ -v
ruff check src tests && ruff format src tests
```

If the imported activator code has lots of upstream-style formatting issues that conflict with our ruff config, add it to ruff's `extend-exclude` temporarily — but prefer to fix them in-file since this is now robobench-owned code. (Use judgment: cosmetic ruff fixes are fine; structural rewrites are out of scope for this task.)

- [ ] **Step 6: Add a script entry point in `pyproject.toml`**

In `[project.scripts]`, add:
```toml
robobench-lifecycle-activator = "robobench.diagnostics.lifecycle_activator:main"
```

(So the activator can be invoked as `robobench-lifecycle-activator --namespace ...` from a ROS2-sourced shell.)

- [ ] **Step 7: Commit**

```bash
git add src/robobench/diagnostics/ tests/unit/diagnostics/ pyproject.toml
git commit -m "feat(diagnostics): extract lifecycle_activator into robobench (lazy rclpy)"
```

---

## Task 10: `activate_lifecycle()` method (TDD)

Shells out to `robobench-lifecycle-activator` (registered in Task 9). The adapter doesn't reach into the activator's ROS2 internals — it composes the CLI call.

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Failing tests**

```python
def test_activate_lifecycle_runs_activator_subprocess(mocker):
    """activate_lifecycle() runs robobench-lifecycle-activator with namespace + map."""
    run_mock = mocker.patch(
        "robobench.robots.turtlebot4.run_local",
        return_value=MagicMock(returncode=0, stdout="all activated\n", stderr=""),
    )

    _adapter().activate_lifecycle(map_yaml="/tmp/my_map.yaml")

    cmd = run_mock.call_args.args[0]
    assert cmd[0] == "robobench-lifecycle-activator"
    assert "--namespace" in cmd
    assert "turtlebot468" in cmd
    assert "--map-yaml" in cmd
    assert "/tmp/my_map.yaml" in cmd


def test_activate_lifecycle_raises_on_failure(mocker):
    """Nonzero exit becomes a RuntimeError that includes stderr."""
    mocker.patch(
        "robobench.robots.turtlebot4.run_local",
        return_value=MagicMock(returncode=1, stdout="", stderr="map_server stuck in UNCONFIGURED"),
    )
    with pytest.raises(RuntimeError, match="map_server stuck"):
        _adapter().activate_lifecycle(map_yaml="/tmp/my_map.yaml")
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement** in `turtlebot4.py`:

```python
    def activate_lifecycle(self, map_yaml: str | None = None) -> None:
        """Run the lifecycle activator to configure+activate all Nav2 nodes."""
        if map_yaml is None:
            raise ValueError("activate_lifecycle requires map_yaml path")
        result = run_local(
            [
                "robobench-lifecycle-activator",
                "--namespace",
                self.namespace,
                "--map-yaml",
                map_yaml,
            ],
            timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"lifecycle activation failed (rc={result.returncode}): {result.stderr.strip()}"
            )
```

Note: this changes the method signature compared to the ABC (`activate_lifecycle(self) -> None`). Update the ABC accordingly:

In `src/robobench/adapter_base.py`, replace the abstract method:

```python
    @abstractmethod
    def activate_lifecycle(self) -> None:
        """Bring lifecycle nodes through configure -> activate."""
```

with:

```python
    @abstractmethod
    def activate_lifecycle(self, map_yaml: str | None = None) -> None:
        """Bring lifecycle nodes through configure -> activate.

        Args:
            map_yaml: Absolute path to the static map YAML to load.
        """
```

Also update the Phase A test fixture `class Complete(RobotAdapter):` in `tests/unit/test_adapter_base.py` so its `activate_lifecycle` signature matches:

```python
        def activate_lifecycle(self, map_yaml: str | None = None) -> None:
            return None
```

- [ ] **Step 4: Run full suite, confirm pass + ruff.**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(robots): implement activate_lifecycle via robobench-lifecycle-activator"
```

---

## Task 11: `set_initial_pose()` method (TDD)

Publishes a `PoseWithCovarianceStamped` to `/<ns>/initialpose` via `ros2 topic pub --once`.

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Failing tests**

```python
def test_set_initial_pose_publishes_to_initialpose(mocker):
    """set_initial_pose runs ros2 topic pub --once on /<ns>/initialpose."""
    run_mock = mocker.patch(
        "robobench.robots.turtlebot4.run_local",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )

    _adapter().set_initial_pose(1.0, 2.0, 0.0)

    cmd = run_mock.call_args.args[0]
    assert cmd[:3] == ["ros2", "topic", "pub"]
    assert "--once" in cmd
    assert "/turtlebot468/initialpose" in cmd
    msg = cmd[-1]
    assert "1.0" in msg
    assert "2.0" in msg


def test_set_initial_pose_raises_on_failure(mocker):
    mocker.patch(
        "robobench.robots.turtlebot4.run_local",
        return_value=MagicMock(returncode=2, stdout="", stderr="topic publish error"),
    )
    with pytest.raises(RuntimeError, match="topic publish error"):
        _adapter().set_initial_pose(0.0, 0.0, 0.0)
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement.** Replace `set_initial_pose` in `turtlebot4.py`:

```python
    def set_initial_pose(self, x: float, y: float, theta: float) -> None:
        """Publish an AMCL initial pose at (x, y, theta) once."""
        import math

        qz = math.sin(theta / 2.0)
        qw = math.cos(theta / 2.0)
        msg = (
            "{header: {frame_id: 'map'}, "
            f"pose: {{pose: {{position: {{x: {x}, y: {y}, z: 0.0}}, "
            f"orientation: {{x: 0.0, y: 0.0, z: {qz}, w: {qw}}}}}, "
            "covariance: [0.25, 0, 0, 0, 0, 0,  0, 0.25, 0, 0, 0, 0,  "
            "0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0,  "
            "0, 0, 0, 0, 0, 0.06853892326654787]}}"
        )
        result = run_local(
            [
                "ros2",
                "topic",
                "pub",
                "--once",
                f"/{self.namespace}/initialpose",
                "geometry_msgs/msg/PoseWithCovarianceStamped",
                msg,
            ],
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"set_initial_pose publish failed: {result.stderr.strip()}"
            )
```

- [ ] **Step 4: Run, confirm pass + ruff.**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(robots): implement set_initial_pose via ros2 topic pub"
```

---

## Task 12: `health_check()` method (TDD)

Returns a structured `{"checks": {...}, "overall": "..."}` dict. v0.2 checks: `clock_offset` (reuse `check_clock_offset`), `amcl_pose` (is `/<ns>/amcl_pose` publishing?), `navigate_to_pose_action` (is the action server visible?), `nav_subscribers` (does `/user_input` have a subscriber?).

**Files:**
- Modify: `src/robobench/robots/turtlebot4.py`
- Modify: `tests/unit/robots/test_turtlebot4.py`

- [ ] **Step 1: Failing tests**

```python
def test_health_check_returns_structured_dict_all_ok(mocker):
    """When every probe succeeds, overall is HEALTHY."""
    mocker.patch.object(TurtleBot4Adapter, "check_clock_offset", return_value=0.1)
    # AMCL topic: ros2 topic echo --once <topic> returns successfully
    # navigate_to_pose: ros2 action list contains it
    # /user_input subs: ros2 topic info reports Subscription count: 1
    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["ros2", "topic", "echo"]:
            return MagicMock(returncode=0, stdout="header:\n  stamp:\n  frame_id: map\n", stderr="")
        if cmd[:3] == ["ros2", "action", "list"]:
            return MagicMock(returncode=0, stdout="/turtlebot468/navigate_to_pose\n", stderr="")
        if cmd[:3] == ["ros2", "topic", "info"]:
            return MagicMock(returncode=0, stdout="Subscription count: 1\nPublisher count: 1\n", stderr="")
        return MagicMock(returncode=1, stdout="", stderr="unhandled")
    mocker.patch("robobench.robots.turtlebot4.run_local", side_effect=fake_run)

    report = _adapter().health_check()

    assert report["overall"] == "HEALTHY"
    assert report["checks"]["clock_offset"]["status"] == "OK"
    assert report["checks"]["amcl_pose"]["status"] == "OK"
    assert report["checks"]["navigate_to_pose_action"]["status"] == "OK"
    assert report["checks"]["nav_subscribers"]["status"] == "OK"


def test_health_check_degraded_when_clock_warn(mocker):
    """A WARN clock offset alone makes overall DEGRADED."""
    mocker.patch.object(TurtleBot4Adapter, "check_clock_offset", return_value=5.0)
    mocker.patch(
        "robobench.robots.turtlebot4.run_local",
        return_value=MagicMock(returncode=0, stdout="ok", stderr=""),
    )
    report = _adapter().health_check()
    assert report["overall"] == "DEGRADED"
    assert report["checks"]["clock_offset"]["status"] == "WARN"


def test_health_check_unhealthy_when_amcl_missing(mocker):
    """If AMCL is not publishing, overall is UNHEALTHY regardless of others."""
    mocker.patch.object(TurtleBot4Adapter, "check_clock_offset", return_value=0.0)
    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["ros2", "topic", "echo"]:
            return MagicMock(returncode=124, stdout="", stderr="timeout")
        return MagicMock(returncode=0, stdout="ok", stderr="")
    mocker.patch("robobench.robots.turtlebot4.run_local", side_effect=fake_run)
    report = _adapter().health_check()
    assert report["overall"] == "UNHEALTHY"
    assert report["checks"]["amcl_pose"]["status"] == "FAIL"
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement.** Replace `health_check` in `turtlebot4.py`:

```python
    _CLOCK_OK = 2.0
    _CLOCK_WARN = 10.0

    def health_check(self) -> dict:
        """Return a structured health report. See module docstring for schema."""
        checks: dict[str, dict] = {}

        # 1. Clock offset
        try:
            offset = self.check_clock_offset()
            abs_offset = abs(offset)
            if abs_offset < self._CLOCK_OK:
                status = "OK"
            elif abs_offset < self._CLOCK_WARN:
                status = "WARN"
            else:
                status = "FAIL"
            checks["clock_offset"] = {"status": status, "value": offset, "unit": "s"}
        except RuntimeError as exc:
            checks["clock_offset"] = {"status": "FAIL", "detail": str(exc)}

        # 2. AMCL publishing
        amcl_topic = f"/{self.namespace}/amcl_pose"
        amcl = run_local(
            ["ros2", "topic", "echo", "--once", amcl_topic], timeout=15
        )
        checks["amcl_pose"] = {
            "status": "OK" if amcl.returncode == 0 else "FAIL",
            "detail": "publishing" if amcl.returncode == 0 else "no pose in 15s",
        }

        # 3. navigate_to_pose action server visible
        actions = run_local(["ros2", "action", "list"], timeout=10)
        nav_action = f"/{self.namespace}/navigate_to_pose"
        action_ok = actions.returncode == 0 and nav_action in actions.stdout
        checks["navigate_to_pose_action"] = {
            "status": "OK" if action_ok else "FAIL",
        }

        # 4. /user_input has at least one subscriber
        info = run_local(["ros2", "topic", "info", "/user_input"], timeout=10)
        sub_count = 0
        for line in info.stdout.splitlines():
            if line.strip().startswith("Subscription count:"):
                try:
                    sub_count = int(line.split(":", 1)[1].strip())
                except ValueError:
                    sub_count = 0
                break
        checks["nav_subscribers"] = {
            "status": "OK" if sub_count > 0 else "FAIL",
            "count": sub_count,
        }

        # Overall
        if any(c["status"] == "FAIL" for c in checks.values()):
            overall = "UNHEALTHY"
        elif any(c["status"] == "WARN" for c in checks.values()):
            overall = "DEGRADED"
        else:
            overall = "HEALTHY"

        return {"checks": checks, "overall": overall}
```

- [ ] **Step 4: Run, confirm pass + ruff.**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(robots): implement TurtleBot4 health_check"
```

---

## Task 13: Config loader (TDD)

Reads upstream `config.yaml` shape (which both campus_guide and robobench respect) into kwargs for the adapter.

**Files:**
- Create: `src/robobench/config.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Failing tests**

```python
"""Tests for robobench.config."""
from __future__ import annotations

from pathlib import Path

import pytest

from robobench.config import load_adapter_config


def test_load_adapter_config_returns_expected_kwargs(tmp_path: Path):
    """A minimal config.yaml yields TurtleBot4Adapter-compatible kwargs."""
    yaml_text = """
robot:
  ip: "192.168.50.31"
  ssh_user: "ubuntu"
  ssh_pass: "turtlebot4"
  namespace: "turtlebot468"
workspace:
  dir: "~/CS5335TurtleBot"
"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml_text)

    kwargs = load_adapter_config(cfg)

    assert kwargs["ip"] == "192.168.50.31"
    assert kwargs["ssh_user"] == "ubuntu"
    assert kwargs["ssh_pass"] == "turtlebot4"
    assert kwargs["namespace"] == "turtlebot468"
    assert kwargs["workspace_dir"].endswith("CS5335TurtleBot")


def test_load_adapter_config_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_adapter_config(tmp_path / "nope.yaml")


def test_load_adapter_config_missing_required_field_raises(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("robot:\n  ip: 1.2.3.4\n")  # missing ssh_user, ssh_pass, etc.
    with pytest.raises(ValueError, match="ssh_user"):
        load_adapter_config(cfg)
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement `src/robobench/config.py`**

```python
"""Load adapter configuration from the upstream config.yaml schema."""
from __future__ import annotations

import os
from pathlib import Path

import yaml


def load_adapter_config(path: Path) -> dict:
    """Read ``config.yaml`` and return the kwargs an adapter constructor expects.

    Schema (subset relevant to v0.2)::

        robot:
          ip: "192.168.50.31"
          ssh_user: "ubuntu"
          ssh_pass: "turtlebot4"
          namespace: "turtlebot468"
        workspace:
          dir: "~/CS5335TurtleBot"
    """
    if not path.exists():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    robot = data.get("robot") or {}
    workspace = data.get("workspace") or {}

    required = ("ip", "ssh_user", "ssh_pass", "namespace")
    missing = [k for k in required if not robot.get(k)]
    if missing:
        raise ValueError(
            f"config.yaml missing required robot.{{}} field(s): {', '.join(missing)}"
        )

    workspace_dir = workspace.get("dir", "~/robobench_ws")
    return {
        "ip": robot["ip"],
        "ssh_user": robot["ssh_user"],
        "ssh_pass": robot["ssh_pass"],
        "namespace": robot["namespace"],
        "workspace_dir": os.path.expanduser(workspace_dir),
    }
```

- [ ] **Step 4: Run, confirm pass + ruff.**

- [ ] **Step 5: Commit**

```bash
git add src/robobench/config.py tests/unit/test_config.py
git commit -m "feat(config): add load_adapter_config for config.yaml"
```

---

## Task 14: `robobench bringup` CLI subcommand (TDD)

**Files:**
- Modify: `src/robobench/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Failing tests**

Append to `tests/unit/test_cli.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "robot:\n"
        "  ip: '192.168.50.31'\n"
        "  ssh_user: 'ubuntu'\n"
        "  ssh_pass: 'turtlebot4'\n"
        "  namespace: 'turtlebot468'\n"
        "workspace:\n"
        "  dir: '~/CS5335TurtleBot'\n"
    )
    return cfg


def test_bringup_runs_all_steps_in_order(mocker, tmp_path):
    """`robobench bringup` calls setup_clock_sync, build, launch, activate, health in order."""
    fake_adapter = MagicMock()
    fake_adapter.health_check.return_value = {"overall": "HEALTHY", "checks": {}}
    mocker.patch(
        "robobench.cli.TurtleBot4Adapter", return_value=fake_adapter
    )
    cfg = _write_config(tmp_path)

    rc = main(
        [
            "bringup",
            "--robot", "turtlebot4",
            "--config", str(cfg),
            "--workstation-ip", "192.168.50.10",
            "--map-yaml", "/tmp/my_map.yaml",
            "--initial-pose", "5.19", "2.56", "0.0",
        ]
    )

    assert rc == 0
    # The order matters
    method_calls = [c[0] for c in fake_adapter.method_calls]
    assert method_calls.index("setup_clock_sync") < method_calls.index("build")
    assert method_calls.index("build") < method_calls.index("launch")
    assert method_calls.index("launch") < method_calls.index("activate_lifecycle")
    assert method_calls.index("activate_lifecycle") < method_calls.index("health_check")


def test_bringup_exits_nonzero_on_unhealthy(mocker, tmp_path):
    """If health_check reports UNHEALTHY, bringup returns 1."""
    fake_adapter = MagicMock()
    fake_adapter.health_check.return_value = {"overall": "UNHEALTHY", "checks": {}}
    mocker.patch(
        "robobench.cli.TurtleBot4Adapter", return_value=fake_adapter
    )
    cfg = _write_config(tmp_path)

    rc = main(
        [
            "bringup",
            "--robot", "turtlebot4",
            "--config", str(cfg),
            "--workstation-ip", "192.168.50.10",
            "--map-yaml", "/tmp/my_map.yaml",
            "--initial-pose", "0.0", "0.0", "0.0",
        ]
    )
    assert rc == 1
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement** — extend `src/robobench/cli.py`:

Add to the imports:
```python
from pathlib import Path

from robobench.config import load_adapter_config
```

After the existing `check` subparser setup, add a `bringup` subparser inside `_build_parser`:

```python
    bringup = subparsers.add_parser(
        "bringup", help="Run full bring-up: clock sync, build, launch, activate, health."
    )
    bringup.add_argument("--robot", required=True, choices=["turtlebot4"])
    bringup.add_argument("--config", required=True, help="Path to config.yaml")
    bringup.add_argument("--workstation-ip", required=True)
    bringup.add_argument("--map-yaml", required=True)
    bringup.add_argument(
        "--initial-pose",
        nargs=3,
        metavar=("X", "Y", "THETA"),
        type=float,
        required=True,
    )
    bringup.add_argument("--skip-clock", action="store_true")
    bringup.add_argument("--skip-build", action="store_true")
    bringup.set_defaults(func=_cmd_bringup)
```

Implement the new `_cmd_bringup`:

```python
def _cmd_bringup(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    kwargs = load_adapter_config(Path(args.config))
    adapter = TurtleBot4Adapter(**kwargs)

    x, y, theta = args.initial_pose
    print(f"[1/5] clock sync ({'skipped' if args.skip_clock else 'running'}) ...")
    if not args.skip_clock:
        adapter.setup_clock_sync(workstation_ip=args.workstation_ip)
    print(f"[2/5] build ({'skipped' if args.skip_build else 'running'}) ...")
    if not args.skip_build:
        adapter.build()
    print("[3/5] launch ...")
    adapter.launch()
    print("[4/5] activate lifecycle ...")
    adapter.activate_lifecycle(map_yaml=args.map_yaml)
    adapter.set_initial_pose(x, y, theta)
    print("[5/5] health check ...")
    report = adapter.health_check()
    print(f"  overall: {report['overall']}")
    for name, check in report["checks"].items():
        print(f"    {name}: {check['status']}")
    return 0 if report["overall"] != "UNHEALTHY" else 1
```

- [ ] **Step 4: Run, confirm pass + ruff + smoke test**

```bash
pytest -q
robobench bringup --help
```

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(cli): add robobench bringup subcommand"
```

---

## Task 15: `robobench health` CLI subcommand (TDD)

JSON output of `adapter.health_check()`.

**Files:**
- Modify: `src/robobench/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Failing test**

```python
def test_health_prints_json_report(mocker, tmp_path, capsys):
    """`robobench health` prints adapter.health_check() as JSON."""
    fake_adapter = MagicMock()
    fake_adapter.health_check.return_value = {
        "overall": "HEALTHY",
        "checks": {"clock_offset": {"status": "OK", "value": 0.1, "unit": "s"}},
    }
    mocker.patch("robobench.cli.TurtleBot4Adapter", return_value=fake_adapter)
    cfg = _write_config(tmp_path)

    rc = main(["health", "--robot", "turtlebot4", "--config", str(cfg)])
    out = capsys.readouterr().out

    assert rc == 0
    assert '"overall": "HEALTHY"' in out
    assert '"clock_offset"' in out
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement.** In `cli.py`, add to `_build_parser`:

```python
    health = subparsers.add_parser("health", help="Print JSON health report.")
    health.add_argument("--robot", required=True, choices=["turtlebot4"])
    health.add_argument("--config", required=True)
    health.set_defaults(func=_cmd_health)
```

And add:
```python
def _cmd_health(args: argparse.Namespace) -> int:
    import json

    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    adapter = TurtleBot4Adapter(**load_adapter_config(Path(args.config)))
    report = adapter.health_check()
    print(json.dumps(report, indent=2))
    return 0 if report["overall"] != "UNHEALTHY" else 1
```

- [ ] **Step 4: Run, confirm pass + ruff.**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(cli): add robobench health subcommand"
```

---

## Task 16: `robobench shutdown` CLI subcommand (TDD)

**Files:**
- Modify: `src/robobench/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Failing test**

```python
def test_shutdown_calls_adapter_shutdown(mocker, tmp_path):
    fake_adapter = MagicMock()
    mocker.patch("robobench.cli.TurtleBot4Adapter", return_value=fake_adapter)
    cfg = _write_config(tmp_path)

    rc = main(["shutdown", "--robot", "turtlebot4", "--config", str(cfg)])

    assert rc == 0
    fake_adapter.shutdown.assert_called_once()
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement.** Add to `_build_parser`:

```python
    shutdown = subparsers.add_parser("shutdown", help="Stop the navigation stack cleanly.")
    shutdown.add_argument("--robot", required=True, choices=["turtlebot4"])
    shutdown.add_argument("--config", required=True)
    shutdown.set_defaults(func=_cmd_shutdown)
```

And:
```python
def _cmd_shutdown(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    adapter = TurtleBot4Adapter(**load_adapter_config(Path(args.config)))
    adapter.shutdown()
    print("shutdown complete")
    return 0
```

- [ ] **Step 4: Run, confirm pass + ruff.**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(cli): add robobench shutdown subcommand"
```

---

## Task 17: Tutorial — "Full bring-up walkthrough"

**Files:** `docs/tutorials/bringup-walkthrough.md`

- [ ] **Step 1: Write the tutorial**

```markdown
# Full bring-up walkthrough

You've already run `robobench check` from the [10-minute tutorial](connect-turtlebot4.md).
Now we bring the whole Nav2 stack up and verify it's healthy.

## Prerequisites

- A TurtleBot4 reachable on the network.
- ROS2 (Humble or Jazzy) installed on the workstation, with `colcon`, `ros2`,
  `rclpy`, `lifecycle_msgs`, `geometry_msgs`, and `nav2_*` packages.
- The `campus_guide` example workspace built locally (or your own ROS2 workspace
  containing the `campus_nav_llm` package).
- A `config.yaml` matching the upstream schema — copy from
  `examples/campus_guide/code/config.yaml`.
- A map YAML (e.g. `examples/campus_guide/code/campus_guide_bot/.../my_map.yaml`).

## Run it

```bash
robobench bringup \
  --robot turtlebot4 \
  --config ./config.yaml \
  --workstation-ip 192.168.50.10 \
  --map-yaml /abs/path/to/my_map.yaml \
  --initial-pose 5.19 2.56 0.0
```

Output is five labelled phases:

```
[1/5] clock sync (running) ...
[2/5] build (running) ...
[3/5] launch ...
[4/5] activate lifecycle ...
[5/5] health check ...
  overall: HEALTHY
    clock_offset: OK
    amcl_pose: OK
    navigate_to_pose_action: OK
    nav_subscribers: OK
```

If something is wrong, the phase that failed surfaces a `RuntimeError` with
actionable stderr. Each phase is independently runnable:

| Phase | Standalone command |
|-------|-------------------|
| 1 | (clock sync is not standalone in v0.2 — runs inside bringup; use `robobench check` to read the offset) |
| 2 | `colcon build --packages-select campus_nav_llm` (in your workspace) |
| 3 | `ros2 launch campus_nav_llm navigation_mode.launch.py` |
| 4 | `robobench-lifecycle-activator --namespace turtlebot468 --map-yaml /path/to/my_map.yaml` |
| 5 | `robobench health --robot turtlebot4 --config ./config.yaml` |

## When something fails

Run `robobench health --robot turtlebot4 --config ./config.yaml` again to get
the JSON report. Each entry has a `status` and, where applicable, a `detail`
field with the failure mode. Common patterns:

- `clock_offset: FAIL` — clock_sync didn't take. SSH manually, run
  `sudo chronyc -a makestep`.
- `amcl_pose: FAIL` — AMCL didn't activate, or initial pose is wrong. Re-run
  `robobench bringup` with a correct `--initial-pose`.
- `navigate_to_pose_action: FAIL` — Nav2 lifecycle didn't fully activate.
  Re-run `robobench-lifecycle-activator` and read its log under
  `~/.campus_nav_logs/`.

## Stopping

```bash
robobench shutdown --robot turtlebot4 --config ./config.yaml
```

Zeros `/cmd_vel`, kills the launcher PID, then `pkill -9`s the Nav2 nodes.

## Next

Phase C will replace `bringup` with a browser-driven wizard that runs the
same steps interactively, surfacing failures with one-click fixes.
```

- [ ] **Step 2: Commit**

```bash
git add docs/tutorials/bringup-walkthrough.md
git commit -m "docs(tutorials): add full bring-up walkthrough"
```

---

## Task 18: CHANGELOG + README update

**Files:**
- Create: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 1: Write `CHANGELOG.md`**

```markdown
# Changelog

All notable changes to this project will be documented in this file.
Format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.2.0a0] — 2026-05-27

### Added

- `robobench.ssh.SSHClient` — paramiko-based SSH wrapper (replaces `sshpass`).
- `robobench._process.run_local` — single mock point for adapter subprocess calls.
- `robobench.config.load_adapter_config` — load adapter kwargs from `config.yaml`.
- `robobench.diagnostics.lifecycle_activator` — Nav2 lifecycle activator, moved
  from upstream. Lazy `rclpy` import so the module is importable without ROS2.
- `TurtleBot4Adapter.setup_clock_sync` — chrony + Create3 NTP automation.
- `TurtleBot4Adapter.build / launch / activate_lifecycle / set_initial_pose /
  health_check / shutdown` — full RobotAdapter contract implemented.
- CLI: `robobench bringup`, `robobench health`, `robobench shutdown`.
- Tutorial: `docs/tutorials/bringup-walkthrough.md`.
- `@pytest.mark.hardware` marker for tests that need a real robot.

### Changed

- `check_clock_offset` now uses paramiko instead of `sshpass`, making the
  command work on native Windows without external binaries.

## [0.1.0a0] — 2026-05-27

Initial release: `RobotAdapter` ABC, `TurtleBot4Adapter` scaffold,
`check_clock_offset` over SSH, `robobench check` CLI, governance, CI.
```

- [ ] **Step 2: Update `README.md`** — replace the "What v0.1 ships / does NOT ship" section with a v0.2-aware version.

Replace:
```markdown
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
```

with:

```markdown
## What v0.2 ships

- `RobotAdapter` interface — 7 methods, all implemented on TurtleBot4.
- `TurtleBot4Adapter` covers clock sync, build, launch, lifecycle activation,
  initial pose, structured health check, and graceful shutdown.
- CLI: `robobench check / bringup / health / shutdown` plus the
  `robobench-lifecycle-activator` ROS2 node entry point.
- Two tutorials: 10-minute clock check, full bring-up walkthrough.
- Reference integration (`examples/campus_guide/`) + UI baseline (`ui/`).

## What v0.2 does NOT ship (and where it's going)

| Coming in | Feature |
|-----------|---------|
| Phase C   | Diagnostic panels (DDS visibility, TF tree, sensor health) |
| Phase C   | Browser-based bring-up wizard replacing `robobench bringup` |
| Phase D   | MkDocs tutorial site + GitHub Pages |
| Phase E   | Simulation support (Gazebo / Ignition) |
| Phase E+  | Additional robot adapters (TurtleBot3, Jackal, custom) |
```

Also update the "Install" section to mention bringup:

```markdown
## Install

```bash
pip install -e .
robobench --help
```

Sub-commands:

- `robobench check` — quick clock diagnostic (no ROS2 required)
- `robobench bringup` — full Nav2 bring-up (requires ROS2 workspace)
- `robobench health` — JSON health report
- `robobench shutdown` — graceful stop
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs: add CHANGELOG, update README for v0.2"
```

---

## Task 19: Bump version + final sweep + tag v0.2.0a0

**Files:** `src/robobench/__init__.py`, `pyproject.toml`

- [ ] **Step 1: Bump version**

In `src/robobench/__init__.py`, change `__version__ = "0.1.0a0"` to `__version__ = "0.2.0a0"`.
In `pyproject.toml`, change `version = "0.1.0a0"` to `version = "0.2.0a0"`.

- [ ] **Step 2: Final sweep**

```bash
cd C:/Users/chntw/Documents/robotic/robobench
source .venv/Scripts/activate
pip install -e ".[dev]"
pytest -q
ruff check . && ruff format --check .
```

Expected: all tests pass, ruff clean.

- [ ] **Step 3: Smoke-test CLI**

```bash
robobench --version       # robobench 0.2.0a0
robobench bringup --help
robobench health --help
robobench shutdown --help
```

- [ ] **Step 4: Commit + tag + push**

```bash
git add src/robobench/__init__.py pyproject.toml
git commit -m "chore: bump version to 0.2.0a0"
git tag -a v0.2.0a0 -m "v0.2.0-alpha - Phase B: adapter completeness"
git push origin main
git push origin v0.2.0a0
```

- [ ] **Step 5: Verify**

```bash
git tag --list
git log --oneline | head -20
```

---

## Self-Review (Plan Author Notes)

**Spec coverage check:**
- `paramiko` migration → Tasks 1, 2, 3 ✅
- 6 ABC methods implemented → Tasks 5 (clock_sync, bonus), 6 (build), 7 (launch), 8 (shutdown), 10 (activate_lifecycle), 11 (set_initial_pose), 12 (health_check) ✅
- `robobench bringup` CLI → Task 14 ✅
- `lifecycle_activator` extraction → Task 9 ✅
- Tag v0.2.0a0 → Task 19 ✅

**Placeholder scan:** No TBDs, all code blocks contain real code, no "implement appropriate X".

**Type consistency:**
- `SSHResult` and `ProcessResult` dataclasses defined in Tasks 2 and 4, used downstream.
- `health_check` return schema documented once in Task 12 and consumed by the bringup CLI in Task 14 (just checks `report["overall"]`).
- The `activate_lifecycle` signature change (`map_yaml` parameter) is propagated to the ABC in Task 10 with a matching test-fixture update.

**Known soft spots:**
1. **`launch()` is fire-and-forget.** It doesn't verify the launched process is actually up before returning. The next phase (`activate_lifecycle`) catches that, but a paranoid user might want a "is launch alive?" check. v0.3 candidate.
2. **No Windows CI yet.** Phase B introduces paramiko (Windows-friendly), so adding a Windows CI matrix slot is reasonable here, but I scoped it to Phase C. If a user pushes from Windows and ruff somehow finds CRLF issues, they'll discover it manually.
3. **`lifecycle_activator` formatting.** The upstream file's style may clash with our ruff rules. Task 9 advises to fix in-file, but the size of the file (495 lines) means this could balloon. If it does, the implementer should escalate as DONE_WITH_CONCERNS and we'll extend `extend-exclude` selectively.
4. **`set_initial_pose` covariance constant.** The covariance value `0.06853892326654787` is the standard Nav2 default; I'm keeping it inline as a magic number for v0.2 since extracting it adds noise without benefit.

---

## Future Plans (separate plan files)

- **Phase C — Diagnostic panels + bring-up wizard** (~3 weeks)
  Stand up FastAPI panels on top of the imported dashboard: DDS discovery,
  TF tree, sensor health, clock. Replace the CLI `bringup` with a
  browser-driven wizard that runs adapter methods one at a time, showing
  pass/fail + suggested fix per step. Add a structured failure catalog.

- **Phase D — Documentation site + second adapter** (~2 weeks)
  MkDocs site published to GitHub Pages. Tutorials: hardware-debug
  walkthrough, writing your own adapter, contributing a panel. Implement
  `TurtleBot3Adapter` to prove the interface generalizes.

- **Phase E — Simulation support** (~3 weeks)
  Gazebo / Ignition world + a `SimAdapter` that satisfies the same
  interface. Lets students without hardware do every tutorial.
