"""Tests for the robobench CLI."""

from __future__ import annotations

import pytest

from robobench import __version__
from robobench.cli import main

# argparse exit code when subcommand is required but not provided
_ARGPARSE_USAGE_ERROR = 2


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
    assert exc_info.value.code == _ARGPARSE_USAGE_ERROR
    captured = capsys.readouterr()
    assert "usage:" in captured.err.lower() or "usage:" in captured.out.lower()
