import builtins

import pytest

from robobench._rosenv import require_rclpy


def test_require_rclpy_raises_when_rclpy_missing(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "rclpy":
            raise ImportError("no rclpy here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="requires ROS2"):
        require_rclpy()
