"""Tests for relocalization — timer-based, non-blocking, cancellable."""
import threading
import time
import pytest

from campus_nav_llm.task_executor_node import TaskExecutorCore


@pytest.fixture
def executor(sample_semantic_map):
    return TaskExecutorCore(sample_semantic_map, navigator=None)


class TestRelocalize:
    """Test the relocalize tool dispatch."""

    def test_relocalize_no_callback(self, executor):
        """Without ROS context, relocalize returns error."""
        result = executor.execute("relocalize", {})
        assert result["status"] == "error"
        assert "not available" in result["error"]

    def test_relocalize_with_callback(self, executor):
        """With a callback set, relocalize delegates to it."""
        executor._relocalize_callback = lambda **kw: {"status": "success", "localization": {"healthy": True}}
        result = executor.execute("relocalize", {})
        assert result["status"] == "success"

    def test_relocalize_callback_exception(self, executor):
        """Exception in callback is caught and returned as error."""
        def bad_callback(**kw):
            raise RuntimeError("service down")
        executor._relocalize_callback = bad_callback
        result = executor.execute("relocalize", {})
        assert result["status"] == "error"
        assert "service down" in result["error"]

    def test_relocalize_cancel_check_passed(self, executor):
        """cancel_check kwarg is forwarded to the callback."""
        received = {}
        def capture_callback(**kwargs):
            received.update(kwargs)
            return {"status": "success", "localization": {"healthy": True}}
        executor._relocalize_callback = capture_callback
        cancel_fn = lambda: False
        result = executor._relocalize({"_cancel_check": cancel_fn})
        assert "cancel_check" in received
        assert received["cancel_check"] is cancel_fn


class TestRelocalizeCancellation:
    """Test that cancellation propagates through the full dispatch chain."""

    def test_cancel_check_injected_for_relocalize(self, executor):
        """When _cancel_check is in tool_input, it's forwarded to callback."""
        received_kwargs = {}

        def mock_callback(**kwargs):
            received_kwargs.update(kwargs)
            return {"status": "success", "localization": {"healthy": True}}

        executor._relocalize_callback = mock_callback
        cancel_fn = lambda: True

        result = executor.execute("relocalize", {"_cancel_check": cancel_fn})
        assert "cancel_check" in received_kwargs
        assert received_kwargs["cancel_check"]() is True
        assert result["status"] == "success"

    def test_relocalize_without_cancel_check(self, executor):
        """Without _cancel_check, callback receives no cancel_check kwarg."""
        received_kwargs = {}

        def mock_callback(**kwargs):
            received_kwargs.update(kwargs)
            return {"status": "success", "localization": {"healthy": True}}

        executor._relocalize_callback = mock_callback
        result = executor.execute("relocalize", {})
        assert "cancel_check" not in received_kwargs
        assert result["status"] == "success"
