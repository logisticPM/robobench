"""Tests for TurtleBot4RecoveryActions (atomic fixes over SSH/local)."""

from __future__ import annotations

from unittest.mock import MagicMock

from robobench.recovery.actions import RecoveryActions
from robobench.robots.turtlebot4_recovery import TurtleBot4RecoveryActions


def _actions():
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    run_local = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    a = TurtleBot4RecoveryActions(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="tb4",
        ssh_factory=lambda *args, **kw: fake_client,
        run_local_func=run_local,
    )
    return a, fake_client, run_local


def test_is_a_recovery_actions():
    a, _, _ = _actions()
    assert isinstance(a, RecoveryActions)


def test_restart_local_daemon_uses_run_local_not_ssh():
    a, ssh, run_local = _actions()
    a.restart_local_daemon()
    assert run_local.called
    ssh.run.assert_not_called()  # local-only action


def test_restart_discovery_server_cleans_shm_and_restarts():
    a, ssh, _ = _actions()
    a.restart_discovery_server()
    joined = " ".join(" ".join(c.args[0]) for c in ssh.run.call_args_list)
    assert "discovery" in joined.lower()


def test_sync_clock_calls_chronyc_makestep():
    a, ssh, _ = _actions()
    a.sync_clock()
    joined = " ".join(" ".join(c.args[0]) for c in ssh.run.call_args_list)
    assert "chronyc" in joined.lower()
    assert "makestep" in joined.lower()


def test_restart_tb4_service_restarts_systemd_unit():
    a, ssh, _ = _actions()
    a.restart_tb4_service()
    joined = " ".join(" ".join(c.args[0]) for c in ssh.run.call_args_list)
    assert "turtlebot4.service" in joined.lower()


def test_reboot_create3_hits_reboot_endpoint():
    a, ssh, _ = _actions()
    a.reboot_create3()
    joined = " ".join(" ".join(c.args[0]) for c in ssh.run.call_args_list)
    assert "reboot" in joined.lower()


def test_restart_create3_app_hits_restart_app_endpoint():
    a, ssh, _ = _actions()
    a.restart_create3_app()
    joined = " ".join(" ".join(c.args[0]) for c in ssh.run.call_args_list)
    assert "restart-app" in joined.lower()
