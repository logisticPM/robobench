"""Tests for the robobench CLI."""

from __future__ import annotations

from unittest.mock import MagicMock

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


def _write_config(tmp_path):
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
    mocker.patch("robobench.cli.TurtleBot4Adapter", return_value=fake_adapter)
    cfg = _write_config(tmp_path)

    rc = main(
        [
            "bringup",
            "--robot",
            "turtlebot4",
            "--config",
            str(cfg),
            "--workstation-ip",
            "192.168.50.10",
            "--map-yaml",
            "/tmp/my_map.yaml",
            "--initial-pose",
            "5.19",
            "2.56",
            "0.0",
        ]
    )

    assert rc == 0
    method_calls = [c[0] for c in fake_adapter.method_calls]
    assert method_calls.index("setup_clock_sync") < method_calls.index("build")
    assert method_calls.index("build") < method_calls.index("launch")
    assert method_calls.index("launch") < method_calls.index("activate_lifecycle")
    assert method_calls.index("activate_lifecycle") < method_calls.index("health_check")


def test_bringup_exits_nonzero_on_unhealthy(mocker, tmp_path):
    """If health_check reports UNHEALTHY, bringup returns 1."""
    fake_adapter = MagicMock()
    fake_adapter.health_check.return_value = {"overall": "UNHEALTHY", "checks": {}}
    mocker.patch("robobench.cli.TurtleBot4Adapter", return_value=fake_adapter)
    cfg = _write_config(tmp_path)

    rc = main(
        [
            "bringup",
            "--robot",
            "turtlebot4",
            "--config",
            str(cfg),
            "--workstation-ip",
            "192.168.50.10",
            "--map-yaml",
            "/tmp/my_map.yaml",
            "--initial-pose",
            "0.0",
            "0.0",
            "0.0",
        ]
    )
    assert rc == 1


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


def test_shutdown_calls_adapter_shutdown(mocker, tmp_path):
    fake_adapter = MagicMock()
    mocker.patch("robobench.cli.TurtleBot4Adapter", return_value=fake_adapter)
    cfg = _write_config(tmp_path)

    rc = main(["shutdown", "--robot", "turtlebot4", "--config", str(cfg)])

    assert rc == 0
    fake_adapter.shutdown.assert_called_once()


def test_dashboard_subcommand_starts_server(mocker, tmp_path):
    """`robobench dashboard` builds the app, starts the bridge thread, runs uvicorn."""
    cfg = _write_config(tmp_path)

    fake_state = MagicMock()
    mocker.patch("robobench.cli.DiagnosticState", return_value=fake_state)
    create_app_mock = mocker.patch("robobench.cli.create_app", return_value="APP")
    thread_mock = mocker.patch("robobench.cli.threading.Thread")
    run_mock = mocker.patch("robobench.cli.uvicorn.run")

    rc = main(["dashboard", "--robot", "turtlebot4", "--config", str(cfg), "--port", "9090"])

    assert rc == 0
    create_app_mock.assert_called_once()
    thread_mock.assert_called_once()
    assert thread_mock.call_args.kwargs.get("daemon") is True
    run_mock.assert_called_once()
    assert run_mock.call_args.kwargs.get("port") == 9090  # noqa: PLR2004
