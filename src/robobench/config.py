"""Load adapter configuration from the upstream config.yaml schema."""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def load_adapter_config(path: Path) -> dict:
    """Read ``config.yaml`` and return the kwargs an adapter constructor expects.

    Schema (subset relevant to v0.2)::

        robot:
          ip: "192.168.50.31"
          ssh_user: "ubuntu"
          ssh_pass: "turtlebot4"
          namespace: "turtlebot468"
        workspace:
          dir: "~/CS5335TurtleBot"
    """
    if not path.exists():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    robot = data.get("robot") or {}
    workspace = data.get("workspace") or {}

    required = ("ip", "ssh_user", "ssh_pass", "namespace")
    missing = [k for k in required if not robot.get(k)]
    if missing:
        raise ValueError(f"config.yaml missing required robot.{{}} field(s): {', '.join(missing)}")

    workspace_dir = workspace.get("dir", "~/robobench_ws")
    return {
        "ip": robot["ip"],
        "ssh_user": robot["ssh_user"],
        "ssh_pass": robot["ssh_pass"],
        "namespace": robot["namespace"],
        "workspace_dir": os.path.expanduser(workspace_dir),
    }
