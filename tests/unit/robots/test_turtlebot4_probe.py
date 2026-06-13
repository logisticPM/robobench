"""Tests for TurtleBot4Probe (SSH + local probing → RobotState)."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

from robobench._process import ProcessResult
from robobench.robots.turtlebot4_probe import (
    TurtleBot4Probe,
    _parse_int,
    _ping_cmd,
    _ping_succeeded,
)

_CONNECTIVITY_TOPIC_COUNT = 12


def _probe(ssh_results, local_results=None):
    """Build a probe with a fake SSHClient factory + fake run_local."""
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.run.side_effect = ssh_results
    default_local = [_ok("\n".join(f"/t{i}" for i in range(8)))]
    p = TurtleBot4Probe(
        ip="192.168.50.31",
        ssh_user="ubuntu",
        ssh_pass="pw",
        namespace="tb4",
        ssh_factory=lambda *a, **k: fake_client,
        run_local=MagicMock(side_effect=local_results or default_local),
        ping=MagicMock(return_value=True),
    )
    return p


def _ok(stdout):
    return MagicMock(returncode=0, stdout=stdout, stderr="")


def _fail(stderr="err"):
    return MagicMock(returncode=1, stdout="", stderr=stderr)


_TOPIC_COUNT = 12
_PORT_LISTENING = 1
_PORT_NOT_LISTENING = 0
_SECOND_SAMPLE_VALUE = 5


def test_probe_reads_healthy_state():
    # ssh.run order: discovery-port, clock-date, create3-topic-count, tb4-nodes, odom x2
    ssh = [
        _ok(f"{_PORT_LISTENING}\n"),  # ss -ulnp | grep 11811 | wc -l -> listening
        _ok("1748347205\n"),  # date +%s
        _ok(f"{_TOPIC_COUNT}\n"),  # create3 topic count
        _ok("/tb4/robot_state_publisher\n"),  # tb4 nodes present
        _ok("position:\n"),  # odom sample 1
        _ok("position:\n"),  # odom sample 2
    ]
    p = _probe(ssh)
    p._now = lambda: 1748347205.0  # clock drift ~0
    state = p.read()
    assert state.rpi_reachable is True
    assert state.discovery_server_ok is True
    assert state.clock_synced is True
    assert state.create3_topics == _TOPIC_COUNT
    assert state.tb4_nodes_present is True
    assert state.odom_publishing is True
    assert state.is_healthy() is True


def test_probe_unreachable_short_circuits():
    p = TurtleBot4Probe(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="tb4",
        ssh_factory=MagicMock(),
        run_local=MagicMock(),
        ping=MagicMock(return_value=False),
    )
    state = p.read()
    assert state.rpi_reachable is False
    assert state.is_healthy() is False


def test_probe_marks_discovery_down_when_port_not_listening():
    ssh = [
        _ok(f"{_PORT_NOT_LISTENING}\n"),  # port NOT listening
        _ok("1748347205\n"),
        _ok("0\n"),
        _ok(""),  # no tb4 nodes
        _fail("timeout"),  # odom sample 1
        _fail("timeout"),  # odom sample 2
    ]
    p = _probe(ssh)
    p._now = lambda: 1748347205.0
    state = p.read()
    assert state.discovery_server_ok is False


def test_probe_odom_requires_two_consecutive_samples():
    """One good sample then a timeout => NOT stable => odom_publishing False."""
    ssh = [
        _ok(f"{_PORT_LISTENING}\n"),
        _ok("1748347205\n"),
        _ok(f"{_TOPIC_COUNT}\n"),
        _ok("/tb4/x\n"),
        _ok("position:\n"),  # sample 1 OK
        _fail("timeout"),  # sample 2 fails -> not stable
    ]
    p = _probe(ssh)
    p._now = lambda: 1748347205.0
    state = p.read()
    assert state.odom_publishing is False


def test_parse_int_is_defensive_against_trailing_warning():
    assert _parse_int(f"{_TOPIC_COUNT}\n") == _TOPIC_COUNT
    assert (
        _parse_int(f"[WARN] something\n{_SECOND_SAMPLE_VALUE}\n") == _SECOND_SAMPLE_VALUE
    )  # last line is the count
    assert _parse_int("[WARN] not a number\n") == _PORT_NOT_LISTENING  # non-int -> 0
    assert _parse_int("") == _PORT_NOT_LISTENING


class _RecordingSSH:
    """Fake SSHClient context manager that records issued commands."""

    def __init__(self, commands: list):
        self._commands = commands

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cmd, timeout=None):
        self._commands.append(cmd)
        text = " ".join(cmd)
        if "11811" in text:
            out = "1"
        elif cmd[:2] == ["date", "+%s"]:
            out = "0"  # ancient time -> clock NOT synced (drift huge)
        elif "topic list" in text:
            out = str(_CONNECTIVITY_TOPIC_COUNT)
        elif "node list" in text:
            out = "/tb/node\n"
        else:
            out = ""
        return subprocess.CompletedProcess(cmd, 0, out, "")


def test_read_connectivity_skips_odom_echo():
    commands: list = []
    probe = TurtleBot4Probe(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="tb",
        ssh_factory=lambda *a, **k: _RecordingSSH(commands),
        ping=lambda _ip: True,
    )
    state = probe.read_connectivity()

    # odom echo must NOT have been issued
    assert not any("odom" in " ".join(c) for c in commands)
    # odom_publishing is the documented "not checked" sentinel
    assert state.odom_publishing is True
    # the five transport layers reflect the fake responses
    assert state.rpi_reachable is True
    assert state.discovery_server_ok is True
    assert state.create3_topics == _CONNECTIVITY_TOPIC_COUNT
    assert state.tb4_nodes_present is True


def test_read_connectivity_short_circuits_on_unreachable():
    commands: list = []
    probe = TurtleBot4Probe(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="tb",
        ssh_factory=lambda *a, **k: _RecordingSSH(commands),
        ping=lambda _ip: False,
    )
    state = probe.read_connectivity()
    assert state.rpi_reachable is False
    assert commands == []  # no SSH attempted when ping fails


def test_discovery_check_uses_configured_port():
    """A non-default discovery_port is what gets grepped (not hardcoded 11811)."""
    commands: list = []
    probe = TurtleBot4Probe(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="tb",
        discovery_port=11888,
        ssh_factory=lambda *a, **k: _RecordingSSH(commands),
        ping=lambda _ip: True,
    )
    probe.read_connectivity()
    discovery = next(" ".join(c) for c in commands if "ss -ulnp" in " ".join(c))
    assert ":11888" in discovery
    assert "11811" not in discovery


def test_discovery_port_defaults_to_11811():
    commands: list = []
    probe = TurtleBot4Probe(
        ip="1.2.3.4",
        ssh_user="u",
        ssh_pass="p",
        namespace="tb",
        ssh_factory=lambda *a, **k: _RecordingSSH(commands),
        ping=lambda _ip: True,
    )
    probe.read_connectivity()
    discovery = next(" ".join(c) for c in commands if "ss -ulnp" in " ".join(c))
    assert ":11811" in discovery


def test_ping_cmd_is_platform_aware():
    """Windows ping needs -n/-w (ms); POSIX ping needs -c/-W (s). Regression:
    the Linux flags were hardcoded, so every Windows probe reported the robot
    unreachable."""
    assert _ping_cmd("1.2.3.4", "win32") == ["ping", "-n", "1", "-w", "2000", "1.2.3.4"]
    assert _ping_cmd("1.2.3.4", "linux") == ["ping", "-c", "1", "-W", "2", "1.2.3.4"]


def test_ping_succeeded_requires_ttl_on_windows():
    """Windows ping exits 0 even for 'Destination host unreachable' replies
    (the gateway answered), so success additionally requires TTL= in stdout."""
    reply = ProcessResult(0, "Reply from 1.2.3.4: bytes=32 time=1ms TTL=64", "")
    unreachable = ProcessResult(0, "Reply from 192.168.1.5: Destination host unreachable.", "")
    assert _ping_succeeded(reply, "win32") is True
    assert _ping_succeeded(unreachable, "win32") is False
    assert _ping_succeeded(ProcessResult(1, "", ""), "win32") is False


def test_ping_succeeded_uses_exit_code_on_posix():
    assert _ping_succeeded(ProcessResult(0, "", ""), "linux") is True
    assert _ping_succeeded(ProcessResult(1, "", ""), "linux") is False
