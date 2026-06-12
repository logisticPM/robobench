"""Smoke tests for the lifecycle_activator module.

The activator itself is a ROS2 node — its substantive behavior is exercised
only with a real robot (marked ``@pytest.mark.hardware``). The unit suite
just verifies the module imports cleanly without ROS2 installed and that
``_lazy_imports`` surfaces a clear error when ROS2 is missing.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_module_is_importable_without_ros2():
    """Importing the module should not require rclpy."""
    import robobench.diagnostics.lifecycle_activator  # noqa: F401, PLC0415


def test_log_dir_is_under_robobench_logs():
    """_LOG_DIR must point to ~/.robobench/logs, not the upstream ~/.campus_nav_logs."""
    from robobench.diagnostics.lifecycle_activator import _LOG_DIR  # noqa: PLC0415

    assert _LOG_DIR.parts[-2:] == (".robobench", "logs"), (
        f"Expected _LOG_DIR to end with (.robobench, logs), got {_LOG_DIR.parts[-2:]}"
    )


def test_activation_log_constructs_and_writes_jsonl(tmp_path, monkeypatch):
    """_ActivationLog must work without ROS2 (regression: datetime.now(datetime.UTC)
    raised AttributeError at construction, crashing the activator on startup)."""
    import json  # noqa: PLC0415

    import robobench.diagnostics.lifecycle_activator as la  # noqa: PLC0415

    monkeypatch.setattr(la, "_LOG_DIR", tmp_path)
    log = la._ActivationLog()
    log.log("init", nodes=["map_server"])
    log.close()

    files = list(tmp_path.glob("lifecycle_*.jsonl"))
    assert len(files) == 1
    record = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
    assert record["event"] == "init"
    assert record["nodes"] == ["map_server"]
    assert record["ts"]


def test_lazy_imports_raises_clear_runtime_error_when_rclpy_missing():
    """When rclpy can't be imported, _lazy_imports() raises a RuntimeError
    that mentions ROS2 — not a cryptic ImportError."""
    from robobench.diagnostics.lifecycle_activator import _lazy_imports  # noqa: PLC0415

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "rclpy" or name.startswith("rclpy."):
            raise ImportError("No module named 'rclpy'")
        return real_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=fake_import),
        pytest.raises(RuntimeError, match="ROS2"),
    ):
        _lazy_imports()
