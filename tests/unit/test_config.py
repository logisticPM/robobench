"""Tests for robobench.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from robobench.config import load_adapter_config


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
