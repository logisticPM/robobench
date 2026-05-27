"""Tests for the RobotAdapter abstract base class."""

from __future__ import annotations

import pytest

from robobench.adapter_base import RobotAdapter


def test_robot_adapter_cannot_be_instantiated_directly():
    """RobotAdapter is abstract — instantiating it must fail."""
    with pytest.raises(TypeError):
        RobotAdapter()  # type: ignore[abstract]


def test_concrete_subclass_must_implement_all_methods():
    """A subclass missing any abstract method cannot be instantiated."""

    class Incomplete(RobotAdapter):
        pass

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_fully_implemented_subclass_is_instantiable():
    """A subclass that implements every abstract method instantiates cleanly."""

    class Complete(RobotAdapter):
        def check_clock_offset(self) -> float:
            return 0.0

        def build(self) -> None:
            return None

        def launch(self) -> None:
            return None

        def activate_lifecycle(self) -> None:
            return None

        def set_initial_pose(self, x: float, y: float, theta: float) -> None:
            return None

        def health_check(self) -> dict:
            return {}

        def shutdown(self) -> None:
            return None

    adapter = Complete()
    assert adapter.check_clock_offset() == 0.0
