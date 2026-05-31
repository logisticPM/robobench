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
        raise RuntimeError(f"Local command timed out after {timeout}s: {' '.join(cmd)}") from exc
    except FileNotFoundError as exc:
        return ProcessResult(
            returncode=127, stdout="", stderr=f"command not found: {cmd[0]} ({exc})"
        )
    return ProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
