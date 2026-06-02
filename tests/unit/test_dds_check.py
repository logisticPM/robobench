"""Tests for robobench.dds_check (pure env linter)."""

from __future__ import annotations

from robobench.dds_check import DdsFinding, lint_dds_env


def _by_check(findings: list[DdsFinding]) -> dict[str, DdsFinding]:
    return {f.check: f for f in findings}


def test_always_three_findings_in_order():
    findings = lint_dds_env({})
    assert [f.check for f in findings] == ["rmw", "discovery_server", "super_client"]


def test_all_correct_env_is_all_ok():
    env = {
        "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
        "ROS_DISCOVERY_SERVER": "192.168.50.31:11811",
        "ROS_SUPER_CLIENT": "True",
    }
    findings = lint_dds_env(env, "192.168.50.31:11811")
    assert all(f.level == "ok" for f in findings)


def test_rmw_unset_warns():
    env = {"ROS_DISCOVERY_SERVER": "x:1", "ROS_SUPER_CLIENT": "True"}
    assert _by_check(lint_dds_env(env))["rmw"].level == "warn"


def test_rmw_wrong_is_error():
    f = _by_check(lint_dds_env({"RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp"}))["rmw"]
    assert f.level == "error"
    assert "rmw_cyclonedds_cpp" in f.message


def test_discovery_server_unset_is_error():
    assert _by_check(lint_dds_env({}))["discovery_server"].level == "error"


def test_discovery_server_mismatch_warns():
    env = {"ROS_DISCOVERY_SERVER": "10.0.0.1:11811"}
    f = _by_check(lint_dds_env(env, "192.168.50.31:11811"))["discovery_server"]
    assert f.level == "warn"
    assert "192.168.50.31:11811" in f.message


def test_discovery_server_match_is_ok():
    env = {"ROS_DISCOVERY_SERVER": "192.168.50.31:11811"}
    f = _by_check(lint_dds_env(env, "192.168.50.31:11811"))["discovery_server"]
    assert f.level == "ok"
    assert "matches config" in f.message


def test_super_client_truthy_variants_ok():
    for value in ("True", "true", "1", "yes"):
        env = {"ROS_DISCOVERY_SERVER": "x:1", "ROS_SUPER_CLIENT": value}
        f = _by_check(lint_dds_env(env))["super_client"]
        assert f.level == "ok"
        assert "ROS_SUPER_CLIENT=" in f.message


def test_super_client_xml_is_ok():
    env = {"ROS_DISCOVERY_SERVER": "x:1", "FASTRTPS_DEFAULT_PROFILES_FILE": "/p.xml"}
    assert _by_check(lint_dds_env(env))["super_client"].level == "ok"


def test_plain_client_with_server_is_error():
    f = _by_check(lint_dds_env({"ROS_DISCOVERY_SERVER": "x:1"}))["super_client"]
    assert f.level == "error"
    assert "plain CLIENT" in f.message


def test_super_client_unset_without_server_is_warn():
    # No server set -> the headline problem is the missing server; super-client
    # is a mild warn, not the dire CLIENT error.
    assert _by_check(lint_dds_env({}))["super_client"].level == "warn"


def test_discovery_server_set_no_expected_is_ok():
    env = {"ROS_DISCOVERY_SERVER": "192.168.50.31:11811"}
    f = _by_check(lint_dds_env(env))["discovery_server"]
    assert f.level == "ok"
    assert "matches config" not in f.message


def test_super_client_explicit_false_is_error_naming_value():
    env = {"ROS_DISCOVERY_SERVER": "x:1", "ROS_SUPER_CLIENT": "False"}
    f = _by_check(lint_dds_env(env))["super_client"]
    assert f.level == "error"
    assert "False" in f.message and "plain CLIENT" in f.message
