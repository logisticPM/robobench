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
