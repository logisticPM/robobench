"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_event_log_dir(tmp_path, monkeypatch):
    """Redirect every default log dir to a per-test temp dir.

    CLI tests exercise code that constructs ``EventLogger()`` (and the
    lifecycle activator's ``_ActivationLog``) with no explicit directory;
    without this, every test run litters the developer's real
    ``~/.robobench/logs`` — which the dashboard's Sessions panel now displays.

    ``eventreport`` imports ``_DEFAULT_LOG_DIR`` by value, so its copy must be
    patched separately from ``eventlog``'s. (The lifecycle activator's
    ``_LOG_DIR`` is left alone: only its dedicated test constructs
    ``_ActivationLog``, and that test patches the dir itself.)
    """
    log_dir = tmp_path / "robobench-logs"
    monkeypatch.setattr("robobench.eventlog._DEFAULT_LOG_DIR", log_dir)
    monkeypatch.setattr("robobench.eventreport._DEFAULT_LOG_DIR", log_dir)
    return log_dir
