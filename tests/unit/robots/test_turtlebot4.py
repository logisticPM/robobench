"""Tests for TurtleBot4Adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from robobench.adapter_base import RobotAdapter
from robobench.robots.turtlebot4 import TurtleBot4Adapter


def test_turtlebot4_adapter_is_a_robot_adapter():
    """Sanity check: the concrete class extends the ABC."""
    assert issubclass(TurtleBot4Adapter, RobotAdapter)


def test_turtlebot4_adapter_instantiates_with_required_fields():
    """Constructor accepts ip, ssh user/pass, namespace, workspace_dir."""
    adapter = TurtleBot4Adapter(
        ip="192.168.50.31",
        ssh_user="ubuntu",
        ssh_pass="turtlebot4",
        namespace="turtlebot468",
        workspace_dir="~/CS5335TurtleBot",
    )
    assert adapter.ip == "192.168.50.31"
    assert adapter.namespace == "turtlebot468"


@pytest.mark.parametrize(
    "method,args",
    [
        ("activate_lifecycle", ()),
        ("set_initial_pose", (1.0, 2.0, 0.0)),
        ("health_check", ()),
        ("shutdown", ()),
    ],
)
def test_unimplemented_methods_raise_not_implemented(method, args):
    """v0.2 Phase B implements build(); the rest signal not-yet-done."""
    adapter = TurtleBot4Adapter(
        ip="192.168.50.31",
        ssh_user="ubuntu",
        ssh_pass="turtlebot4",
        namespace="turtlebot468",
        workspace_dir="~/CS5335TurtleBot",
    )
    with pytest.raises(NotImplementedError):
        getattr(adapter, method)(*args)


def _adapter():
    return TurtleBot4Adapter(
        ip="192.168.50.31",
        ssh_user="ubuntu",
        ssh_pass="turtlebot4",
        namespace="turtlebot468",
        workspace_dir="~/CS5335TurtleBot",
    )


def test_check_clock_offset_returns_seconds(mocker):
    """Opens SSH to the robot, reads epoch via `date +%s`, subtracts from local time."""
    fake_local = datetime(2026, 5, 27, 12, 0, 10, tzinfo=UTC)
    mocker.patch("robobench.robots.turtlebot4._now_utc", return_value=fake_local)

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.run.return_value = MagicMock(returncode=0, stdout="1779883205\n", stderr="")
    sshclient_ctor = mocker.patch("robobench.robots.turtlebot4.SSHClient", return_value=fake_client)

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
    mocker.patch("robobench.robots.turtlebot4.SSHClient", return_value=fake_client)

    with pytest.raises(RuntimeError, match="date: command not found"):
        _adapter().check_clock_offset()


def test_setup_clock_sync_writes_chrony_conf_and_restarts(mocker):
    """setup_clock_sync writes /etc/chrony/chrony.conf, restarts chrony, hits Create3."""
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    # Sequence of expected ssh.run() calls (in order)
    fake_client.run.side_effect = [
        MagicMock(returncode=0, stdout="ii  chrony\n", stderr=""),  # dpkg -l chrony
        MagicMock(returncode=0, stdout="", stderr=""),  # tee + restart chrony
        MagicMock(returncode=0, stdout="1779883210\n", stderr=""),  # date +%s for drift
        MagicMock(returncode=0, stdout='{"status":"ok"}', stderr=""),  # curl Create3
    ]
    mocker.patch("robobench.robots.turtlebot4.SSHClient", return_value=fake_client)
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
        MagicMock(returncode=1, stdout="", stderr=""),  # dpkg —not installed
        MagicMock(returncode=0, stdout="", stderr=""),  # apt-get install
        MagicMock(returncode=0, stdout="", stderr=""),  # tee + restart
        MagicMock(returncode=0, stdout="1779883210\n", stderr=""),  # date +%s
        MagicMock(returncode=0, stdout="ok", stderr=""),  # curl
    ]
    mocker.patch("robobench.robots.turtlebot4.SSHClient", return_value=fake_client)
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


def test_build_runs_colcon_in_workspace(mocker):
    """build() shells out to `colcon build --packages-select campus_nav_llm` in workspace_dir."""
    fake_result = MagicMock(returncode=0, stdout="Summary: 1 package built\n", stderr="")
    run_mock = mocker.patch("robobench.robots.turtlebot4.run_local", return_value=fake_result)

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
    fake_result = MagicMock(returncode=1, stdout="", stderr="error: cmake compile failed\n")
    mocker.patch("robobench.robots.turtlebot4.run_local", return_value=fake_result)

    with pytest.raises(RuntimeError, match="cmake compile failed"):
        _adapter().build()


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
    write_mock = mocker.patch("robobench.robots.turtlebot4.Path.write_text")

    _adapter().launch()

    write_mock.assert_called_once_with("99\n")
