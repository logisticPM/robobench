"""Tests for TurtleBot4Adapter."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from robobench.adapter_base import RobotAdapter
from robobench.robots import turtlebot4
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


def _adapter():
    return TurtleBot4Adapter(
        ip="192.168.50.31",
        ssh_user="ubuntu",
        ssh_pass="turtlebot4",
        namespace="turtlebot468",
        workspace_dir="~/CS5335TurtleBot",
    )


def _ok():
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


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
        MagicMock(returncode=0, stdout="", stderr=""),  # chronyc makestep
        MagicMock(returncode=0, stdout="1779883210\n", stderr=""),  # date +%s for drift
        MagicMock(returncode=0, stdout='{"status":"ok"}', stderr=""),  # curl Create3
    ]
    mocker.patch("robobench.robots.turtlebot4.SSHClient", return_value=fake_client)
    mocker.patch(
        "robobench.robots.turtlebot4._now_utc",
        return_value=datetime(2026, 5, 27, 12, 0, 11, tzinfo=UTC),
    )

    report = _adapter().setup_clock_sync(workstation_ip="192.168.50.10", sleep=lambda _s: None)

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
        MagicMock(returncode=0, stdout="", stderr=""),  # chronyc makestep
        MagicMock(returncode=0, stdout="1779883210\n", stderr=""),  # date +%s
        MagicMock(returncode=0, stdout="ok", stderr=""),  # curl
    ]
    mocker.patch("robobench.robots.turtlebot4.SSHClient", return_value=fake_client)
    mocker.patch(
        "robobench.robots.turtlebot4._now_utc",
        return_value=datetime(2026, 5, 27, 12, 0, 11, tzinfo=UTC),
    )

    report = _adapter().setup_clock_sync(workstation_ip="192.168.50.10", sleep=lambda _s: None)

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


def test_shutdown_publishes_zero_cmdvel_and_kills_pid(mocker, tmp_path):
    """shutdown() publishes zero cmd_vel, then kills the PID, then pkills stragglers."""
    pid_path = tmp_path / "launch.pid"
    pid_path.write_text("12345\n")
    run_mock = mocker.patch(
        "robobench.robots.turtlebot4.run_local",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )

    _adapter().shutdown(pid_path=pid_path, sleep=lambda _s: None)

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

    _adapter().shutdown(pid_path=pid_path, sleep=lambda _s: None)  # no exception raised


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
    """Asserts a RuntimeError when BOTH the activator and the CLI fallback fail."""
    mocker.patch(
        "robobench.robots.turtlebot4.run_local",
        return_value=MagicMock(returncode=1, stdout="", stderr="map_server stuck in UNCONFIGURED"),
    )
    with pytest.raises(RuntimeError, match="CLI fallback could not activate any node"):
        _adapter().activate_lifecycle(map_yaml="/tmp/my_map.yaml")


def test_activate_lifecycle_requires_map_yaml():
    """Calling without map_yaml raises ValueError."""
    with pytest.raises(ValueError, match="map_yaml"):
        _adapter().activate_lifecycle()


def test_activate_lifecycle_passes_initial_pose_flags_to_activator(mocker):
    """activate_lifecycle(initial_pose=...) appends --initial-pose-* flags to the command."""
    run_mock = mocker.patch(
        "robobench.robots.turtlebot4.run_local",
        return_value=MagicMock(returncode=0, stdout="all activated\n", stderr=""),
    )

    _adapter().activate_lifecycle(map_yaml="/m.yaml", initial_pose=(1.0, 2.0, 0.5))

    cmd = run_mock.call_args.args[0]
    assert "--initial-pose-x" in cmd
    assert "1.0" in cmd
    assert "--initial-pose-y" in cmd
    assert "2.0" in cmd
    assert "--initial-pose-yaw" in cmd
    assert "0.5" in cmd


def test_activate_lifecycle_omits_pose_flags_when_initial_pose_is_none(mocker):
    """activate_lifecycle without initial_pose does NOT include --initial-pose-x."""
    run_mock = mocker.patch(
        "robobench.robots.turtlebot4.run_local",
        return_value=MagicMock(returncode=0, stdout="all activated\n", stderr=""),
    )

    _adapter().activate_lifecycle(map_yaml="/m.yaml")

    cmd = run_mock.call_args.args[0]
    assert "--initial-pose-x" not in cmd


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


def test_health_check_returns_structured_dict_all_ok(mocker):
    """When every probe succeeds, overall is HEALTHY."""
    mocker.patch.object(TurtleBot4Adapter, "check_clock_offset", return_value=0.1)

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["ros2", "topic", "echo"]:
            return MagicMock(returncode=0, stdout="header:\n  stamp:\n  frame_id: map\n", stderr="")
        if cmd[:3] == ["ros2", "action", "list"]:
            return MagicMock(returncode=0, stdout="/turtlebot468/navigate_to_pose\n", stderr="")
        if cmd[:3] == ["ros2", "topic", "info"]:
            return MagicMock(
                returncode=0, stdout="Subscription count: 1\nPublisher count: 1\n", stderr=""
            )
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

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["ros2", "topic", "echo"]:
            return MagicMock(returncode=0, stdout="header", stderr="")
        if cmd[:3] == ["ros2", "action", "list"]:
            return MagicMock(returncode=0, stdout="/turtlebot468/navigate_to_pose\n", stderr="")
        if cmd[:3] == ["ros2", "topic", "info"]:
            return MagicMock(
                returncode=0, stdout="Subscription count: 1\nPublisher count: 1\n", stderr=""
            )
        return MagicMock(returncode=0, stdout="ok", stderr="")

    mocker.patch("robobench.robots.turtlebot4.run_local", side_effect=fake_run)

    report = _adapter().health_check()
    assert report["overall"] == "DEGRADED"
    assert report["checks"]["clock_offset"]["status"] == "WARN"


def test_health_check_unhealthy_when_amcl_missing(mocker):
    """If AMCL is not publishing, overall is UNHEALTHY regardless of others."""
    mocker.patch.object(TurtleBot4Adapter, "check_clock_offset", return_value=0.0)

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["ros2", "topic", "echo"]:
            return MagicMock(returncode=124, stdout="", stderr="timeout")
        if cmd[:3] == ["ros2", "action", "list"]:
            return MagicMock(returncode=0, stdout="/turtlebot468/navigate_to_pose\n", stderr="")
        if cmd[:3] == ["ros2", "topic", "info"]:
            return MagicMock(returncode=0, stdout="Subscription count: 1\n", stderr="")
        return MagicMock(returncode=0, stdout="ok", stderr="")

    mocker.patch("robobench.robots.turtlebot4.run_local", side_effect=fake_run)

    report = _adapter().health_check()
    assert report["overall"] == "UNHEALTHY"
    assert report["checks"]["amcl_pose"]["status"] == "FAIL"


def test_health_check_amcl_echo_timeout_is_fail_not_crash(mocker):
    """`ros2 topic echo --once` blocks forever when AMCL is silent, so run_local
    raises RuntimeError on its subprocess timeout. health_check must report that
    as a FAIL check, not crash (regression: the RuntimeError propagated)."""
    mocker.patch.object(TurtleBot4Adapter, "check_clock_offset", return_value=0.0)

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["ros2", "topic", "echo"]:
            raise RuntimeError("Local command timed out after 15s: ros2 topic echo ...")
        if cmd[:3] == ["ros2", "action", "list"]:
            return MagicMock(returncode=0, stdout="/turtlebot468/navigate_to_pose\n", stderr="")
        if cmd[:3] == ["ros2", "topic", "info"]:
            return MagicMock(returncode=0, stdout="Subscription count: 1\n", stderr="")
        return MagicMock(returncode=0, stdout="ok", stderr="")

    mocker.patch("robobench.robots.turtlebot4.run_local", side_effect=fake_run)

    report = _adapter().health_check()

    assert report["checks"]["amcl_pose"]["status"] == "FAIL"
    assert report["checks"]["amcl_pose"]["detail"] == "no pose in 15s"
    assert report["overall"] == "UNHEALTHY"


def test_fallback_lifecycle_nodes_match_activator_list():
    """The CLI-fallback node list must stay in sync with the activator's
    canonical 9-node list (regression: smoother_server and waypoint_follower
    were missing, so the fallback never activated them)."""
    from robobench.diagnostics.lifecycle_activator import LIFECYCLE_NODES  # noqa: PLC0415

    assert tuple(LIFECYCLE_NODES) == TurtleBot4Adapter._LIFECYCLE_NODES


def test_build_raises_clear_error_when_workspace_dir_is_none():
    """If workspace_dir is None, build() raises a ValueError that says so."""
    adapter = TurtleBot4Adapter(
        ip="192.168.50.31",
        ssh_user="ubuntu",
        ssh_pass="turtlebot4",
        namespace="turtlebot468",
        workspace_dir=None,
    )
    with pytest.raises(ValueError, match="workspace_dir"):
        adapter.build()


def test_adapter_accepts_optional_build_launch_health_fields():
    """The dataclass accepts the new optional fields with v0.2-compatible defaults."""
    a = TurtleBot4Adapter(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="ns",
        workspace_dir="/ws",
    )
    assert a.build_packages == ["campus_nav_llm"]
    assert a.launch_package == "campus_nav_llm"
    assert a.launch_file == "navigation_mode.launch.py"
    assert a.user_input_topic == "/user_input"


def test_adapter_accepts_explicit_build_launch_health_fields():
    """Explicit field values override the defaults."""
    a = TurtleBot4Adapter(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="ns",
        workspace_dir="/ws",
        build_packages=["my_pkg"],
        launch_package="my_pkg",
        launch_file="custom.launch.py",
        user_input_topic="/custom_topic",
    )
    assert a.build_packages == ["my_pkg"]
    assert a.launch_package == "my_pkg"
    assert a.launch_file == "custom.launch.py"
    assert a.user_input_topic == "/custom_topic"


def test_health_check_uses_configured_user_input_topic(mocker):
    """health_check probes self.user_input_topic, not the hard-coded /user_input."""
    mocker.patch.object(TurtleBot4Adapter, "check_clock_offset", return_value=0.0)

    captured_topics = []

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["ros2", "topic", "info"]:
            captured_topics.append(cmd[3])
            return MagicMock(returncode=0, stdout="Subscription count: 1\n", stderr="")
        if cmd[:3] == ["ros2", "topic", "echo"]:
            return MagicMock(returncode=0, stdout="ok", stderr="")
        if cmd[:3] == ["ros2", "action", "list"]:
            return MagicMock(returncode=0, stdout="/ns/navigate_to_pose\n", stderr="")
        return MagicMock(returncode=0, stdout="ok", stderr="")

    mocker.patch("robobench.robots.turtlebot4.run_local", side_effect=fake_run)

    adapter = TurtleBot4Adapter(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="ns",
        workspace_dir="/ws",
        user_input_topic="/my_custom_input",
    )

    adapter.health_check()

    assert "/my_custom_input" in captured_topics


def test_build_uses_configured_packages_list(mocker):
    """build() iterates self.build_packages into the colcon --packages-select flag."""
    fake_result = MagicMock(returncode=0, stdout="", stderr="")
    run_mock = mocker.patch("robobench.robots.turtlebot4.run_local", return_value=fake_result)
    adapter = TurtleBot4Adapter(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="ns",
        workspace_dir="/ws",
        build_packages=["pkg_a", "pkg_b"],
    )

    adapter.build()

    cmd = run_mock.call_args.args[0]
    assert cmd[0] == "colcon"
    assert "--packages-select" in cmd
    pkg_select_idx = cmd.index("--packages-select")
    assert cmd[pkg_select_idx + 1] == "pkg_a"
    assert cmd[pkg_select_idx + 2] == "pkg_b"


def test_launch_uses_configured_package_and_file(mocker, tmp_path):
    """launch() passes self.launch_package and self.launch_file to ros2 launch."""
    fake_popen = MagicMock()
    fake_popen.pid = 1
    popen_mock = mocker.patch(
        "robobench.robots.turtlebot4.subprocess.Popen", return_value=fake_popen
    )
    pid_path = tmp_path / "p.pid"
    adapter = TurtleBot4Adapter(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="ns",
        workspace_dir="/ws",
        launch_package="my_pkg",
        launch_file="custom.launch.py",
    )

    adapter.launch(pid_path=pid_path)

    cmd = popen_mock.call_args.args[0]
    assert cmd[:2] == ["ros2", "launch"]
    assert cmd[2] == "my_pkg"
    assert cmd[3] == "custom.launch.py"


def test_shutdown_is_graceful_then_forceful(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        turtlebot4,
        "run_local",
        lambda cmd, timeout=None, **kw: calls.append(list(cmd)) or _ok(),
    )
    sleeps: list[float] = []

    adapter = turtlebot4.TurtleBot4Adapter(ip="1.2.3.4", ssh_user="u", ssh_pass="p", namespace="tb")
    missing_pid = tmp_path / "nope.pid"
    adapter.shutdown(pid_path=missing_pid, settle_s=5.0, sleep=sleeps.append)

    flat = [" ".join(c) for c in calls]
    term_idx = next(i for i, c in enumerate(flat) if "pkill" in c and "-TERM" in c)
    kill_idx = next(i for i, c in enumerate(flat) if "pkill" in c and "-9" in c)
    assert term_idx < kill_idx, "SIGTERM must precede SIGKILL"
    assert sleeps == [5.0]
    assert any("fastdds" in c and "shm" in c for c in flat)
    assert any("daemon" in c and "stop" in c for c in flat)
    assert any("daemon" in c and "start" in c for c in flat)


def test_setup_clock_sync_includes_workstation_chrony_check_in_report(mocker):
    """setup_clock_sync's report includes a workstation_chrony field from the local check."""
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.run.side_effect = [
        MagicMock(returncode=0, stdout="ii  chrony\n", stderr=""),  # dpkg
        MagicMock(returncode=0, stdout="", stderr=""),  # tee + restart
        MagicMock(returncode=0, stdout="", stderr=""),  # chronyc makestep
        MagicMock(returncode=0, stdout="1748347210\n", stderr=""),  # date +%s
        MagicMock(returncode=0, stdout="ok", stderr=""),  # curl
    ]
    mocker.patch("robobench.robots.turtlebot4.SSHClient", return_value=fake_client)
    mocker.patch(
        "robobench.robots.turtlebot4._now_utc",
        return_value=datetime(2026, 5, 27, 12, 0, 11, tzinfo=UTC),
    )
    mocker.patch(
        "robobench.robots.turtlebot4.check_workstation_chrony_config",
        return_value={
            "status": "WARN",
            "has_allow": False,
            "has_local_stratum": False,
            "hint": "...",
        },
    )

    report = _adapter().setup_clock_sync(workstation_ip="10.0.0.5", sleep=lambda _s: None)

    assert "workstation_chrony" in report
    assert report["workstation_chrony"]["status"] == "WARN"


def test_setup_clock_sync_issues_makestep_before_drift_read(mocker):
    """chronyc makestep is called AFTER chrony restart and BEFORE date +%s drift read."""
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None

    calls: list[list] = []

    def recording_run(cmd, **kwargs):
        calls.append(list(cmd))
        # Provide realistic return values for each call
        if cmd[0] == "dpkg":
            return MagicMock(returncode=0, stdout="ii  chrony\n", stderr="")
        if cmd[0] == "date":
            return MagicMock(returncode=0, stdout="1779883210\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    fake_client.run.side_effect = recording_run
    mocker.patch("robobench.robots.turtlebot4.SSHClient", return_value=fake_client)
    mocker.patch(
        "robobench.robots.turtlebot4._now_utc",
        return_value=datetime(2026, 5, 27, 12, 0, 11, tzinfo=UTC),
    )

    _adapter().setup_clock_sync(workstation_ip="192.168.50.10", sleep=lambda _s: None)

    makestep_cmd = ["sudo", "chronyc", "-a", "makestep"]
    date_cmd = ["date", "+%s"]
    assert makestep_cmd in calls, f"chronyc makestep not found in calls: {calls}"
    assert date_cmd in calls, f"date +%s not found in calls: {calls}"
    makestep_idx = calls.index(makestep_cmd)
    date_idx = calls.index(date_cmd)
    assert makestep_idx < date_idx, (
        f"makestep (index {makestep_idx}) must precede date +%s (index {date_idx})"
    )


def test_activate_lifecycle_falls_back_to_cli(monkeypatch):
    def fake_run(cmd, timeout=None, **kw):
        rc = 1 if "robobench-lifecycle-activator" in cmd else 0
        return subprocess.CompletedProcess(cmd, rc, "", "boom" if rc else "")

    calls: list[list[str]] = []
    monkeypatch.setattr(
        turtlebot4,
        "run_local",
        lambda cmd, timeout=None, **kw: calls.append(list(cmd)) or fake_run(cmd, timeout),
    )
    adapter = turtlebot4.TurtleBot4Adapter(ip="i", ssh_user="u", ssh_pass="p", namespace="tb")
    adapter.activate_lifecycle(map_yaml="/m.yaml")  # must NOT raise — fallback succeeds

    flat = [" ".join(c) for c in calls]
    assert any("lifecycle" in c and "configure" in c for c in flat)
    assert any("lifecycle" in c and "activate" in c for c in flat)


def test_activate_lifecycle_raises_when_fallback_also_fails(monkeypatch):
    def fake_run(cmd, timeout=None, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "fail")

    monkeypatch.setattr(turtlebot4, "run_local", fake_run)
    adapter = turtlebot4.TurtleBot4Adapter(ip="i", ssh_user="u", ssh_pass="p", namespace="tb")
    with pytest.raises(RuntimeError, match="lifecycle"):
        adapter.activate_lifecycle(map_yaml="/m.yaml")


def _clock_ssh(mocker, stdout: str):
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = None
    fake.run.return_value = MagicMock(returncode=0, stdout=stdout, stderr="")
    mocker.patch("robobench.robots.turtlebot4.SSHClient", return_value=fake)


def test_check_clock_offset_tolerates_banner_before_epoch(mocker):
    """A MOTD/profile banner leaking onto the SSH channel ahead of the epoch
    must not crash: the last non-empty line is parsed."""
    mocker.patch(
        "robobench.robots.turtlebot4._now_utc",
        return_value=datetime(2026, 5, 27, 12, 0, 10, tzinfo=UTC),
    )
    _clock_ssh(mocker, "Welcome to Ubuntu\n1779883205\n")
    assert _adapter().check_clock_offset() == pytest.approx(5.0, abs=0.01)


def test_check_clock_offset_raises_on_unparseable_epoch(mocker):
    """Garbled `date +%s` output raises RuntimeError (which health_check catches
    as a structured FAIL) instead of a bare ValueError crash."""
    _clock_ssh(mocker, "command not found\n")
    with pytest.raises(RuntimeError, match="date"):
        _adapter().check_clock_offset()
