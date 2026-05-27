"""Integration test — simulates the full Phase 1.1 pipeline.

No ROS, no real LLM API. Tests that LLMPlannerCore + TaskExecutorCore
work together correctly via mock API responses.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from campus_nav_llm.llm_planner_node import LLMPlannerCore
from campus_nav_llm.task_executor_node import TaskExecutorCore


@pytest.fixture
def system(sample_semantic_map):
    """Set up a connected Planner + Executor system."""
    planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
    executor = TaskExecutorCore(sample_semantic_map, navigator=None)
    return planner, executor


# ── Mock helpers for OpenAI-compatible responses ──

def _make_tool_call(name, arguments, tc_id="t1"):
    tc = MagicMock()
    tc.id = tc_id
    tc.type = "function"
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


def _make_choice(finish_reason, content=None, tool_calls=None):
    choice = MagicMock()
    choice.finish_reason = finish_reason
    choice.message = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls
    choice.message.model_dump = MagicMock(return_value={
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in (tool_calls or [])
        ] if tool_calls else None,
    })
    return choice


def _make_response(finish_reason, content=None, tool_calls=None):
    resp = MagicMock()
    resp.choices = [_make_choice(finish_reason, content, tool_calls)]
    return resp


class TestEndToEndNavigation:
    """User says 'go to whiteboard' -> LLM calls navigate_to -> executor navigates -> LLM replies."""

    def test_single_navigation(self, system):
        planner, executor = system

        # Step 1: LLM decides to call navigate_to
        tc1 = _make_tool_call("navigate_to", {"location_name": "whiteboard"})
        tool_resp = _make_response("tool_calls", tool_calls=[tc1])

        # Step 2: LLM sees the result and speaks
        tc2 = _make_tool_call("speak", {"text": "I've arrived at the whiteboard!"}, "t2")
        speak_resp = _make_response("tool_calls", tool_calls=[tc2])

        # Step 3: LLM finishes
        final_resp = _make_response("stop", content="Done! I'm at the whiteboard now.")

        with patch.object(
            planner.client.chat.completions,
            "create",
            side_effect=[tool_resp, speak_resp, final_resp],
        ):
            result = planner.run_tool_loop(
                "go to the whiteboard",
                lambda name, inp: executor.execute(name, inp),
            )
            assert "whiteboard" in result.lower()


class TestMultiStepNavigation:
    """User says 'go to desk 1 then entrance' -> 2 navigations."""

    def test_two_step_navigation(self, system):
        planner, executor = system

        # Step 1: navigate to desk_1
        tc1 = _make_tool_call("navigate_to", {"location_name": "desk_1"}, "t1")
        resp1 = _make_response("tool_calls", tool_calls=[tc1])

        # Step 2: navigate to entrance
        tc2 = _make_tool_call("navigate_to", {"location_name": "entrance"}, "t2")
        resp2 = _make_response("tool_calls", tool_calls=[tc2])

        # Step 3: done
        resp3 = _make_response("stop", content="Visited desk 1 and entrance.")

        call_log = []

        def logging_executor(name, inp):
            result = executor.execute(name, inp)
            call_log.append((name, inp, result))
            return result

        with patch.object(
            planner.client.chat.completions,
            "create",
            side_effect=[resp1, resp2, resp3],
        ):
            result = planner.run_tool_loop(
                "go to desk 1 then the entrance",
                logging_executor,
            )
            assert len(call_log) == 2
            assert call_log[0][0] == "navigate_to"
            assert call_log[0][2]["target"] == "desk_1"
            assert call_log[1][0] == "navigate_to"
            assert call_log[1][2]["target"] == "entrance"


class TestPositionQuery:
    """User asks 'where am I?' -> LLM calls get_robot_position."""

    def test_position_query(self, system):
        planner, executor = system
        executor.update_pose(2.0, 3.5, 1.57)

        tc = _make_tool_call("get_robot_position", {})
        pos_resp = _make_response("tool_calls", tool_calls=[tc])

        final_resp = _make_response("stop", content="You are near the whiteboard at (2.0, 3.5).")

        with patch.object(
            planner.client.chat.completions,
            "create",
            side_effect=[pos_resp, final_resp],
        ):
            result = planner.run_tool_loop(
                "where am I?",
                lambda name, inp: executor.execute(name, inp),
            )
            assert "whiteboard" in result.lower()


class TestUnknownLocationHandling:
    """User asks to go to a non-existent location -> error, LLM handles it."""

    def test_unknown_location_error_recovery(self, system):
        planner, executor = system

        # LLM tries to navigate to 'library' (doesn't exist)
        tc = _make_tool_call("navigate_to", {"location_name": "library"})
        nav_resp = _make_response("tool_calls", tool_calls=[tc])

        # LLM sees the error and responds with text
        final_resp = _make_response(
            "stop",
            content="I don't know where the library is. Available locations are: "
                    "whiteboard, desk_1, entrance.",
        )

        with patch.object(
            planner.client.chat.completions,
            "create",
            side_effect=[nav_resp, final_resp],
        ):
            result = planner.run_tool_loop(
                "go to the library",
                lambda name, inp: executor.execute(name, inp),
            )
            # LLM should report the error gracefully
            assert "library" in result.lower() or "don't know" in result.lower()


class TestNavigationRecovery:
    """Test navigation failure with recovery via clear_costmap."""

    def test_nav_fail_then_clear_then_retry(self, system):
        planner, executor = system

        # Step 1: LLM calls navigate_to -> fails
        tc1 = _make_tool_call("navigate_to", {"location_name": "whiteboard"}, "t1")
        resp1 = _make_response("tool_calls", tool_calls=[tc1])

        # Step 2: LLM calls clear_costmap
        tc2 = _make_tool_call("clear_costmap", {}, "t2")
        resp2 = _make_response("tool_calls", tool_calls=[tc2])

        # Step 3: LLM retries navigate_to -> succeeds
        tc3 = _make_tool_call("navigate_to", {"location_name": "whiteboard"}, "t3")
        resp3 = _make_response("tool_calls", tool_calls=[tc3])

        # Step 4: done
        resp4 = _make_response("stop", content="Arrived at whiteboard after clearing costmap.")

        call_log = []

        def fail_then_succeed(name, inp):
            result = executor.execute(name, inp)
            call_log.append(name)
            if name == "navigate_to" and len([c for c in call_log if c == "navigate_to"]) == 1:
                # First nav attempt "fails" (simulated — in test mode it always succeeds)
                result["status"] = "failed"
                result["error"] = "Path blocked"
                result["recovery_hint"] = "Try clear_costmap then retry."
            return result

        with patch.object(
            planner.client.chat.completions,
            "create",
            side_effect=[resp1, resp2, resp3, resp4],
        ):
            result = planner.run_tool_loop(
                "go to the whiteboard",
                fail_then_succeed,
            )
            assert "clear_costmap" in call_log
            assert call_log.count("navigate_to") == 2


class TestCancelNavigation:
    """Test cancel_navigation tool in integration."""

    def test_cancel_when_idle(self, system):
        planner, executor = system

        tc = _make_tool_call("cancel_navigation", {})
        cancel_resp = _make_response("tool_calls", tool_calls=[tc])

        final_resp = _make_response("stop", content="No navigation was active.")

        with patch.object(
            planner.client.chat.completions,
            "create",
            side_effect=[cancel_resp, final_resp],
        ):
            result = planner.run_tool_loop(
                "stop",
                lambda name, inp: executor.execute(name, inp),
            )
            assert "no navigation" in result.lower() or "not" in result.lower() or "active" in result.lower()


class TestFastPathIntegration:
    """Test that fast path commands execute correctly end-to-end."""

    def test_fast_path_navigation(self, system):
        planner, executor = system

        fast = planner.try_fast_path("go to whiteboard")
        assert fast is not None
        tool_name, tool_input = fast
        result = executor.execute(tool_name, tool_input)
        assert result["status"] == "arrived"
        assert result["target"] == "whiteboard"

    def test_fast_path_position(self, system):
        planner, executor = system
        executor.update_pose(2.0, 3.5, 0.0)

        fast = planner.try_fast_path("where am I?")
        assert fast is not None
        tool_name, tool_input = fast
        result = executor.execute(tool_name, tool_input)
        assert result["x"] == 2.0
        assert "nearby_locations" in result

    def test_fast_path_cancel(self, system):
        planner, executor = system

        fast = planner.try_fast_path("stop")
        assert fast is not None
        tool_name, tool_input = fast
        result = executor.execute(tool_name, tool_input)
        assert result["status"] == "no_navigation_active"


class TestTier1Commands:
    """Simulate Tier 1 evaluation commands (direct navigation)."""

    TIER1_COMMANDS = [
        ("go to the whiteboard", "whiteboard"),
        ("navigate to desk 1", "desk_1"),
        ("go to the entrance", "entrance"),
        ("take me to the board", "whiteboard"),  # alias
        ("go to the door", "entrance"),  # alias
    ]

    @pytest.mark.parametrize("command,expected_target", TIER1_COMMANDS)
    def test_tier1_command(self, system, command, expected_target):
        planner, executor = system

        tc = _make_tool_call("navigate_to", {"location_name": expected_target})
        nav_resp = _make_response("tool_calls", tool_calls=[tc])

        final_resp = _make_response("stop", content=f"Arrived at {expected_target}.")

        results = []

        def track_executor(name, inp):
            result = executor.execute(name, inp)
            results.append(result)
            return result

        with patch.object(
            planner.client.chat.completions,
            "create",
            side_effect=[nav_resp, final_resp],
        ):
            planner.conversation_history.clear()
            reply = planner.run_tool_loop(command, track_executor)

        # Navigation should succeed
        assert len(results) >= 1
        nav_result = results[0]
        assert nav_result["status"] == "arrived"
        assert nav_result["target"] == expected_target
