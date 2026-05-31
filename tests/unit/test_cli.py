"""Tests for the robobench CLI."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from robobench import __version__, cli
from robobench.cli import main
from robobench.panels.connectivity_probe import run_connectivity_probe
from robobench.panels.recovery_controller import RecoveryController

_DEFAULT_SSH_PROBE_INTERVAL = 20.0

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
    assert thread_mock.call_count >= 1  # bridge thread + optional probe thread
    assert all(c.kwargs.get("daemon") is True for c in thread_mock.call_args_list)
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


def test_dashboard_passes_discovery_server_from_config(mocker, tmp_path):
    """Non-demo dashboard derives discovery_server from config ip+port and
    hands it to the bridge thread."""
    cfg = _write_config(tmp_path)  # ip 192.168.50.31, default port 11811

    fake_state = MagicMock()
    mocker.patch("robobench.cli.DiagnosticState", return_value=fake_state)
    mocker.patch("robobench.cli.create_app", return_value="APP")
    thread_mock = mocker.patch("robobench.cli.threading.Thread")
    mocker.patch("robobench.cli.uvicorn.run")

    rc = main(["dashboard", "--robot", "turtlebot4", "--config", str(cfg)])

    assert rc == 0
    # The bridge thread is the first Thread() call; check its args contain the discovery server
    bridge_call = thread_mock.call_args_list[0]
    args = bridge_call.kwargs.get("args")
    assert args is not None
    assert "192.168.50.31:11811" in args


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


def test_odom_tf_invokes_runner(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "robot:\n  ip: 1.2.3.4\n  ssh_user: u\n  ssh_pass: p\n  namespace: tb\n",
        encoding="utf-8",
    )
    seen = {}
    monkeypatch.setattr(
        "robobench.diagnostics.odom_tf.run_odom_tf_publisher",
        lambda namespace: seen.update(namespace=namespace),
    )

    rc = main(["odom-tf", "--robot", "turtlebot4", "--config", str(cfg)])
    assert rc == 0
    assert seen == {"namespace": "tb"}


def test_bridge_invokes_runner(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "robot:\n"
        "  ip: 1.2.3.4\n"
        "  ssh_user: ubuntu\n"
        "  ssh_pass: pw\n"
        "  namespace: tb\n"
        "dds:\n"
        "  discovery_port: 11811\n",
        encoding="utf-8",
    )
    calls = {}

    def fake_run(namespace, discovery_server):
        calls["namespace"] = namespace
        calls["discovery_server"] = discovery_server

    monkeypatch.setattr("robobench.relay.runner.run_dds_bridge", fake_run)

    rc = main(["bridge", "--robot", "turtlebot4", "--config", str(cfg)])
    assert rc == 0
    assert calls == {"namespace": "tb", "discovery_server": "1.2.3.4:11811"}


def test_recover_writes_event_log(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "robot:\n  ip: 1.2.3.4\n  ssh_user: u\n  ssh_pass: p\n  namespace: tb\n",
        encoding="utf-8",
    )

    class FakeResult:
        outcome = "CONVERGED"
        actions_taken: list[str] = []

    class FakeEngine:
        def run(self):
            return FakeResult()

    captured = {}

    def fake_build(**kwargs):
        captured["event_log"] = kwargs.get("event_log")
        return FakeEngine()

    monkeypatch.setattr("robobench.cli.build_turtlebot4_recovery", fake_build)

    rc = main(["recover", "--robot", "turtlebot4", "--config", str(cfg)])
    assert rc == 0
    assert captured["event_log"] is not None  # a real EventLogger was passed
    assert "event log:" in capsys.readouterr().out


def _dashboard_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "robot:\n  ip: 1.2.3.4\n  ssh_user: u\n  ssh_pass: p\n  namespace: tb\n"
        "dds:\n  discovery_port: 11811\n",
        encoding="utf-8",
    )
    return cfg


def test_dashboard_starts_connectivity_probe_thread(monkeypatch, tmp_path):
    created = []

    class FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=False):
            created.append({"target": target, "kwargs": kwargs or {}})

        def start(self):
            pass

    monkeypatch.setattr("robobench.cli.threading.Thread", FakeThread)
    monkeypatch.setattr("robobench.cli.uvicorn.run", lambda *a, **k: None)

    rc = main(["dashboard", "--robot", "turtlebot4", "--config", str(_dashboard_config(tmp_path))])
    assert rc == 0
    probe_threads = [c for c in created if c["target"] is run_connectivity_probe]
    assert len(probe_threads) == 1
    assert probe_threads[0]["kwargs"]["interval"] == _DEFAULT_SSH_PROBE_INTERVAL


def test_dashboard_no_ssh_probe_skips_thread(monkeypatch, tmp_path):
    created = []

    class FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=False):
            created.append(target)

        def start(self):
            pass

    monkeypatch.setattr("robobench.cli.threading.Thread", FakeThread)
    monkeypatch.setattr("robobench.cli.uvicorn.run", lambda *a, **k: None)

    rc = main(
        [
            "dashboard",
            "--robot",
            "turtlebot4",
            "--config",
            str(_dashboard_config(tmp_path)),
            "--no-ssh-probe",
        ]
    )
    assert rc == 0
    assert run_connectivity_probe not in created


def test_bringup_resolves_named_pose(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "robot:\n  ip: i\n  ssh_user: u\n  ssh_pass: p\n  namespace: tb\n"
        "workspace:\n  dir: /ws\n"
        "known_poses:\n  front_door: {x: 5.19, y: 2.56, theta: 0.0}\n",
        encoding="utf-8",
    )
    poses_set: list[tuple] = []

    class FakeAdapter:
        def __init__(self, **kw):
            pass

        def setup_clock_sync(self, **kw):
            pass

        def build(self):
            pass

        def launch(self):
            pass

        def activate_lifecycle(self, map_yaml=None):
            pass

        def set_initial_pose(self, x, y, theta):
            poses_set.append((x, y, theta))

        def health_check(self):
            return {"overall": "HEALTHY", "checks": {}}

    monkeypatch.setattr("robobench.cli.TurtleBot4Adapter", FakeAdapter)

    rc = main(
        [
            "bringup",
            "--robot",
            "turtlebot4",
            "--config",
            str(cfg),
            "--workstation-ip",
            "192.168.1.2",
            "--map-yaml",
            "/m.yaml",
            "--pose",
            "front_door",
            "--skip-clock",
            "--skip-build",
        ]
    )
    assert rc == 0
    assert poses_set == [(5.19, 2.56, 0.0)]


def _fake_thread_factory():
    class _T:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    return _T


def test_dashboard_injects_recovery_controller(monkeypatch, tmp_path):
    captured = {}

    def fake_create_app(state, namespace, expected_nodes=None, *, recovery=None):
        captured["recovery"] = recovery
        return FastAPI()

    monkeypatch.setattr("robobench.cli.create_app", fake_create_app)
    monkeypatch.setattr("robobench.cli.uvicorn.run", lambda *a, **k: None)
    monkeypatch.setattr("robobench.cli.threading.Thread", _fake_thread_factory())

    rc = main(["dashboard", "--robot", "turtlebot4", "--config", str(_dashboard_config(tmp_path))])
    assert rc == 0
    assert isinstance(captured["recovery"], RecoveryController)


def test_dashboard_demo_has_no_recovery(monkeypatch, tmp_path):
    captured = {}

    def fake_create_app(state, namespace, expected_nodes=None, *, recovery=None):
        captured["recovery"] = recovery
        return FastAPI()

    monkeypatch.setattr("robobench.cli.create_app", fake_create_app)
    monkeypatch.setattr("robobench.cli.uvicorn.run", lambda *a, **k: None)
    monkeypatch.setattr("robobench.cli.threading.Thread", _fake_thread_factory())

    rc = main(
        [
            "dashboard",
            "--robot",
            "turtlebot4",
            "--config",
            str(_dashboard_config(tmp_path)),
            "--demo",
        ]
    )
    assert rc == 0
    assert captured["recovery"] is None
