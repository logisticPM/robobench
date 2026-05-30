"""Load adapter configuration from the upstream config.yaml schema."""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def load_adapter_config(path: Path) -> dict:
    """Read ``config.yaml`` and return the kwargs an adapter constructor expects.

    Schema (v0.2.1)::

        robot:
          ip: "192.168.50.31"
          ssh_user: "ubuntu"
          ssh_pass: "turtlebot4"
          namespace: "turtlebot468"
        workspace:
          dir: "~/my_workspace"
        build:                              # optional, defaults to campus_guide
          packages: ["campus_nav_llm"]
        launch:                             # optional, defaults to campus_guide
          package: "campus_nav_llm"
          file: "navigation_mode.launch.py"
        health:                             # optional, defaults to campus_guide
          user_input_topic: "/user_input"
        dds:                                # optional
          discovery_port: 11811
    """
    if not path.exists():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    robot = data.get("robot") or {}
    workspace = data.get("workspace") or {}
    build = data.get("build") or {}
    launch = data.get("launch") or {}
    health = data.get("health") or {}
    dds = data.get("dds") or {}

    required = ("ip", "ssh_user", "ssh_pass", "namespace")
    missing = [k for k in required if not robot.get(k)]
    if missing:
        raise ValueError(f"config.yaml missing required robot.{{}} field(s): {', '.join(missing)}")

    workspace_dir_raw = workspace.get("dir")
    workspace_dir = os.path.expanduser(workspace_dir_raw) if workspace_dir_raw else None

    return {
        "ip": robot["ip"],
        "ssh_user": robot["ssh_user"],
        "ssh_pass": robot["ssh_pass"],
        "namespace": robot["namespace"],
        "workspace_dir": workspace_dir,
        "build_packages": build.get("packages", ["campus_nav_llm"]),
        "launch_package": launch.get("package", "campus_nav_llm"),
        "launch_file": launch.get("file", "navigation_mode.launch.py"),
        "user_input_topic": health.get("user_input_topic", "/user_input"),
        "discovery_port": int(dds.get("discovery_port", 11811)),
    }
