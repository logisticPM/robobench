"""Tests for the robobench CLI."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from robobench import __version__, cli
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


def test_dashboard_demo_flag_seeds_state_and_skips_bridge(mocker, tmp_path):
    """`robobench dashboard --demo` seeds demo state + starts the demo refresh
    loop, NOT the bridge."""
    cfg = _write_config(tmp_path)

    fake_state = MagicMock()
    mocker.patch("robobench.cli.DiagnosticState", return_value=fake_state)
    create_app_mock = mocker.patch("robobench.cli.create_app", return_value="APP")
    seed_mock = mocker.patch("robobench.cli.seed_demo_state")
    thread_mock = mocker.patch("robobench.cli.threading.Thread")
    mocker.patch("robobench.cli.uvicorn.run")

    rc = main(["dashboard", "--robot", "turtlebot4", "--config", str(cfg), "--demo"])

    assert rc == 0
    seed_mock.assert_called_once()
    # the thread started in demo mode is the refresh loop, NOT the bridge
    thread_mock.assert_called_once()
    assert thread_mock.call_args.kwargs.get("target") is cli._demo_refresh_loop
    assert thread_mock.call_args.kwargs.get("daemon") is True
    # demo mode checks against the demo's own expected-node set (self-consistent)
    assert create_app_mock.call_args.kwargs.get("expected_nodes") is cli.DEMO_EXPECTED_NODES


def test_preflight_prints_state_and_planned_actions(mocker, tmp_path, capsys):
    """`robobench preflight` reads state (no fixes) and prints JSON + would-do actions."""
    cfg = _write_config(tmp_path)

    from robobench.recovery.state import RobotState  # noqa: PLC0415

    bad_state = RobotState(
        rpi_reachable=True,
        discovery_server_ok=True,
        clock_synced=True,
        create3_topics=12,
        tb4_nodes_present=True,
        odom_publishing=False,
    )
    fake_probe = MagicMock()
    fake_probe.read.return_value = bad_state
    mocker.patch("robobench.cli.TurtleBot4Probe", return_value=fake_probe)

    rc = main(["preflight", "--robot", "turtlebot4", "--config", str(cfg)])
    out = capsys.readouterr().out

    assert rc == 1  # not healthy -> nonzero
    assert "odom_publishing" in out
    assert "restart_create3_app" in out  # the action that WOULD run


def test_preflight_healthy_exits_zero(mocker, tmp_path):
    cfg = _write_config(tmp_path)
    from robobench.recovery.state import RobotState  # noqa: PLC0415

    good = RobotState(
        rpi_reachable=True,
        discovery_server_ok=True,
        clock_synced=True,
        create3_topics=12,
        tb4_nodes_present=True,
        odom_publishing=True,
    )
    fake_probe = MagicMock()
    fake_probe.read.return_value = good
    mocker.patch("robobench.cli.TurtleBot4Probe", return_value=fake_probe)
    rc = main(["preflight", "--robot", "turtlebot4", "--config", str(cfg)])
    assert rc == 0


def test_recover_runs_engine_and_reports_outcome(mocker, tmp_path, capsys):
    cfg = _write_config(tmp_path)
    from robobench.recovery.engine import RecoveryResult  # noqa: PLC0415

    fake_engine = MagicMock()
    fake_engine.run.return_value = RecoveryResult(
        outcome="CONVERGED", actions_taken=["restart_local_daemon"], trace=["healthy"]
    )
    build_mock = mocker.patch("robobench.cli.build_turtlebot4_recovery", return_value=fake_engine)

    rc = main(
        [
            "recover",
            "--robot",
            "turtlebot4",
            "--config",
            str(cfg),
            "--deadline",
            "60",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "CONVERGED" in out
    fake_engine.run.assert_called_once()
    assert build_mock.call_args.kwargs.get("allow_reboot") is False  # OFF by default


def test_recover_allow_reboot_flag_is_passed(mocker, tmp_path):
    cfg = _write_config(tmp_path)
    from robobench.recovery.engine import RecoveryResult  # noqa: PLC0415

    fake_engine = MagicMock()
    fake_engine.run.return_value = RecoveryResult(outcome="CONVERGED")
    build_mock = mocker.patch("robobench.cli.build_turtlebot4_recovery", return_value=fake_engine)

    main(
        [
            "recover",
            "--robot",
            "turtlebot4",
            "--config",
            str(cfg),
            "--allow-reboot",
            "--deadline",
            "300",
        ]
    )
    assert build_mock.call_args.kwargs.get("allow_reboot") is True


def test_recover_dry_run_does_not_run_engine(mocker, tmp_path, capsys):
    cfg = _write_config(tmp_path)
    from robobench.recovery.state import RobotState  # noqa: PLC0415

    bad = RobotState(
        rpi_reachable=True,
        discovery_server_ok=False,
        clock_synced=True,
        create3_topics=0,
        tb4_nodes_present=False,
        odom_publishing=False,
    )
    fake_probe = MagicMock()
    fake_probe.read.return_value = bad
    mocker.patch("robobench.cli.TurtleBot4Probe", return_value=fake_probe)
    build_mock = mocker.patch("robobench.cli.build_turtlebot4_recovery")

    rc = main(["recover", "--robot", "turtlebot4", "--config", str(cfg), "--dry-run"])
    out = capsys.readouterr().out

    assert rc == 0
    build_mock.assert_not_called()  # dry-run never builds/runs the engine
    assert "restart_discovery_server" in out  # prints the plan instead


def test_recover_nonzero_when_not_converged(mocker, tmp_path):
    cfg = _write_config(tmp_path)
    from robobench.recovery.engine import RecoveryResult  # noqa: PLC0415

    fake_engine = MagicMock()
    fake_engine.run.return_value = RecoveryResult(outcome="STUCK")
    mocker.patch("robobench.cli.build_turtlebot4_recovery", return_value=fake_engine)

    rc = main(["recover", "--robot", "turtlebot4", "--config", str(cfg), "--deadline", "30"])
    assert rc == 1
