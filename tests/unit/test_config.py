"""Tests for robobench.config."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from robobench.config import (
    load_adapter_config,
    load_known_poses,
    render_config_template,
    resolve_pose,
)

DEFAULT_DISCOVERY_PORT = 11811
CUSTOM_DISCOVERY_PORT = 11888


def test_load_adapter_config_returns_expected_kwargs(tmp_path: Path):
    """A minimal config.yaml yields TurtleBot4Adapter-compatible kwargs."""
    yaml_text = """
robot:
  ip: "192.168.50.31"
  ssh_user: "ubuntu"
  ssh_pass: "turtlebot4"
  namespace: "turtlebot468"
workspace:
  dir: "~/CS5335TurtleBot"
"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml_text)

    kwargs = load_adapter_config(cfg)

    assert kwargs["ip"] == "192.168.50.31"
    assert kwargs["ssh_user"] == "ubuntu"
    assert kwargs["ssh_pass"] == "turtlebot4"
    assert kwargs["namespace"] == "turtlebot468"
    assert kwargs["workspace_dir"].endswith("CS5335TurtleBot")


def test_load_adapter_config_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_adapter_config(tmp_path / "nope.yaml")


def test_load_adapter_config_missing_required_field_raises(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("robot:\n  ip: 1.2.3.4\n")
    with pytest.raises(ValueError, match="ssh_user"):
        load_adapter_config(cfg)


def test_load_adapter_config_missing_field_message_is_clean(tmp_path: Path):
    """The error names the missing fields without f-string artifacts
    (regression: '{{}}' rendered a literal 'robot.{}' in the message)."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("robot:\n  ip: 1.2.3.4\n")
    with pytest.raises(ValueError) as exc_info:
        load_adapter_config(cfg)
    msg = str(exc_info.value)
    assert "{}" not in msg
    assert "ssh_user" in msg
    assert "ssh_pass" in msg
    assert "namespace" in msg


def test_load_adapter_config_returns_build_and_launch_fields(tmp_path: Path):
    """Optional build/launch/health fields in config.yaml flow into the kwargs."""
    yaml_text = """
robot:
  ip: "192.168.1.10"
  ssh_user: "ubuntu"
  ssh_pass: "pw"
  namespace: "myrobot"
workspace:
  dir: "/home/me/ws"
build:
  packages: ["my_nav", "my_safety"]
launch:
  package: "my_nav"
  file: "bringup.launch.py"
health:
  user_input_topic: "/my_cmd_input"
"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml_text)

    kwargs = load_adapter_config(cfg)

    assert kwargs["build_packages"] == ["my_nav", "my_safety"]
    assert kwargs["launch_package"] == "my_nav"
    assert kwargs["launch_file"] == "bringup.launch.py"
    assert kwargs["user_input_topic"] == "/my_cmd_input"


def test_load_adapter_config_defaults_match_v0_2_behavior(tmp_path: Path):
    """When the new fields are absent, defaults match v0.2's hard-coded values
    so existing configs keep working unchanged."""
    yaml_text = """
robot:
  ip: "192.168.1.10"
  ssh_user: "ubuntu"
  ssh_pass: "pw"
  namespace: "myrobot"
workspace:
  dir: "/home/me/ws"
"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml_text)

    kwargs = load_adapter_config(cfg)

    assert kwargs["build_packages"] == ["campus_nav_llm"]
    assert kwargs["launch_package"] == "campus_nav_llm"
    assert kwargs["launch_file"] == "navigation_mode.launch.py"
    assert kwargs["user_input_topic"] == "/user_input"


def test_load_adapter_config_reads_dds_discovery_port(tmp_path: Path):
    """An explicit dds.discovery_port flows into the kwargs."""
    yaml_text = f"""
robot:
  ip: "192.168.50.31"
  ssh_user: "ubuntu"
  ssh_pass: "pw"
  namespace: "tb4"
dds:
  discovery_port: {CUSTOM_DISCOVERY_PORT}
"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml_text)
    kwargs = load_adapter_config(cfg)
    assert kwargs["discovery_port"] == CUSTOM_DISCOVERY_PORT


def test_load_adapter_config_discovery_port_defaults_to_11811(tmp_path: Path):
    """When dds.discovery_port is absent, default to the upstream default."""
    yaml_text = """
robot:
  ip: "192.168.50.31"
  ssh_user: "ubuntu"
  ssh_pass: "pw"
  namespace: "tb4"
"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml_text)
    kwargs = load_adapter_config(cfg)
    assert kwargs["discovery_port"] == DEFAULT_DISCOVERY_PORT


def test_load_known_poses(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "robot:\n  ip: i\n  ssh_user: u\n  ssh_pass: p\n  namespace: tb\n"
        "known_poses:\n"
        "  front_door: {x: 5.19, y: 2.56, theta: 0.0}\n",
        encoding="utf-8",
    )
    poses = load_known_poses(cfg)
    assert poses == {"front_door": {"x": 5.19, "y": 2.56, "theta": 0.0}}


def test_load_known_poses_empty_when_absent(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("robot:\n  ip: i\n  ssh_user: u\n  ssh_pass: p\n  namespace: tb\n", "utf-8")
    assert load_known_poses(cfg) == {}


def test_resolve_pose_named():
    poses = {"front_door": {"x": 5.19, "y": 2.56, "theta": 0.0}}
    assert resolve_pose("front_door", poses) == (5.19, 2.56, 0.0)


def test_resolve_pose_raw_coords():
    assert resolve_pose("1.0 -2.0 3.14", {}) == (1.0, -2.0, 3.14)


def test_resolve_pose_malformed_known_pose_raises_value_error():
    """A known_poses entry missing x/y/theta raises ValueError naming the pose
    (regression: a raw KeyError escaped past the CLI's error handling)."""
    with pytest.raises(ValueError, match="front_door"):
        resolve_pose("front_door", {"front_door": {"x": 1.0}})


def test_resolve_pose_unknown_raises():
    with pytest.raises(ValueError, match="unknown pose"):
        resolve_pose("garage", {"front_door": {"x": 0, "y": 0, "theta": 0}})


def test_render_defaults_have_placeholders():
    text = render_config_template()
    assert "192.168.x.x" in text
    assert "turtlebot468" in text
    assert "rmw_implementation" not in text  # dead field intentionally omitted


def test_render_fills_provided_flags():
    text = render_config_template(ip="10.0.0.5", ssh_user="pi", ssh_pass="pw", namespace="bot")
    assert '"10.0.0.5"' in text
    assert '"pi"' in text
    assert '"pw"' in text
    assert '"bot"' in text


def test_render_is_valid_yaml_and_roundtrips(tmp_path):
    text = render_config_template(ip="10.0.0.5", namespace="bot")
    assert yaml.safe_load(text) is not None  # parses as YAML

    cfg = tmp_path / "config.yaml"
    cfg.write_text(text, encoding="utf-8")
    loaded = load_adapter_config(cfg)
    assert loaded["ip"] == "10.0.0.5"
    assert loaded["namespace"] == "bot"
    assert loaded["discovery_port"] == DEFAULT_DISCOVERY_PORT
    # optional sections are commented out -> loader falls back to defaults
    assert loaded["workspace_dir"] is None
    assert loaded["build_packages"] == ["campus_nav_llm"]
    assert loaded["ssh_user"] == "ubuntu"   # placeholder default
    assert loaded["ssh_pass"] == "turtlebot4"  # placeholder default


def test_render_escapes_special_chars_safely(tmp_path):
    text = render_config_template(namespace='bot"x\nevil: y')
    parsed = yaml.safe_load(text)  # must not raise
    assert parsed["robot"]["namespace"] == 'bot"x\nevil: y'  # value preserved
    assert "evil" not in parsed  # NOT injected as a top-level key

    cfg = tmp_path / "c.yaml"
    cfg.write_text(text, encoding="utf-8")
    loaded = load_adapter_config(cfg)
    assert loaded["namespace"] == 'bot"x\nevil: y'
