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
