"""Tests for LLM Planner — tool definitions, system prompt, fast path, and mock API loop."""
import json
from unittest.mock import MagicMock, patch

import pytest

from campus_nav_llm.llm_planner_node import TOOLS, LLMPlannerCore, MAX_TOOL_ITERATIONS


class TestToolDefinitions:
    """Validate that Phase 1.1 tool schemas are well-formed."""

    def test_has_7_tools(self):
        assert len(TOOLS) == 7

    def test_tool_names(self):
        names = {t["function"]["name"] for t in TOOLS}
        assert names == {
            "navigate_to", "get_robot_position", "speak",
            "cancel_navigation", "clear_costmap", "get_navigation_status",
            "relocalize",
        }

    def test_navigate_to_has_required_param(self):
        tool = next(t for t in TOOLS if t["function"]["name"] == "navigate_to")
        params = tool["function"]["parameters"]
        assert "location_name" in params["properties"]
        assert "location_name" in params["required"]

    def test_speak_has_required_param(self):
        tool = next(t for t in TOOLS if t["function"]["name"] == "speak")
        params = tool["function"]["parameters"]
        assert "text" in params["properties"]
        assert "text" in params["required"]

    def test_get_position_has_no_required(self):
        tool = next(t for t in TOOLS if t["function"]["name"] == "get_robot_position")
        params = tool["function"]["parameters"]
        assert "required" not in params or len(params.get("required", [])) == 0

    def test_all_tools_have_description(self):
        for tool in TOOLS:
            assert "description" in tool["function"]
            assert len(tool["function"]["description"]) > 10

    def test_all_tools_have_input_schema(self):
        for tool in TOOLS:
            assert "parameters" in tool["function"]
            assert tool["function"]["parameters"]["type"] == "object"


class TestSystemPrompt:
    """Test the system prompt generation."""

    def test_prompt_contains_locations(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        prompt = planner.build_system_prompt()
        assert "whiteboard" in prompt
        assert "desk_1" in prompt
        assert "entrance" in prompt

    def test_prompt_contains_aliases(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        prompt = planner.build_system_prompt()
        assert "board" in prompt
        assert "door" in prompt

    def test_prompt_contains_instructions(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        prompt = planner.build_system_prompt()
        assert "navigate_to" in prompt
        assert "named locations" in prompt

    def test_prompt_mentions_turtlebot(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        prompt = planner.build_system_prompt()
        assert "TurtleBot 4" in prompt

    def test_prompt_mentions_recovery(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        prompt = planner.build_system_prompt()
        assert "clear_costmap" in prompt
        assert "cancel" in prompt.lower()


class TestFastPath:
    """Test simple command fast path (bypass LLM)."""

    def test_simple_go_to(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        result = planner.try_fast_path("go to whiteboard")
        assert result == ("navigate_to", {"location_name": "whiteboard"})

    def test_navigate_to(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        result = planner.try_fast_path("navigate to desk_1")
        assert result == ("navigate_to", {"location_name": "desk_1"})

    def test_take_me_to(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        result = planner.try_fast_path("take me to entrance")
        assert result == ("navigate_to", {"location_name": "entrance"})

    def test_stop_command(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        result = planner.try_fast_path("stop")
        assert result == ("cancel_navigation", {})

    def test_cancel_command(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        result = planner.try_fast_path("cancel")
        assert result == ("cancel_navigation", {})

    def test_where_am_i(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        result = planner.try_fast_path("where am I?")
        assert result == ("get_robot_position", {})

    def test_unknown_location_no_fast_path(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        # 'library' doesn't exist in the map, so fast path should return None
        result = planner.try_fast_path("go to library")
        assert result is None

    def test_complex_command_no_fast_path(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        result = planner.try_fast_path("go to desk 1 and then the whiteboard")
        assert result is None

    def test_alias_fast_path(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        result = planner.try_fast_path("go to the door")
        assert result is not None
        assert result[0] == "navigate_to"


class TestMaxIterations:
    """Test that the iteration limit is correctly set."""

    def test_max_iterations_is_10(self):
        assert MAX_TOOL_ITERATIONS == 10


class TestConversationHistory:
    """Test conversation history management."""

    def test_history_starts_empty(self, sample_semantic_map):
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        assert len(planner.conversation_history) == 0

    def test_history_trimming_preserves_user_boundary(self, sample_semantic_map):
        """History trimming should cut at a user message boundary."""
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")
        # Add 25 alternating messages
        for i in range(25):
            role = "user" if i % 2 == 0 else "assistant"
            planner.conversation_history.append(
                {"role": role, "content": f"message {i}"}
            )
        planner._trim_history()
        assert len(planner.conversation_history) <= 20
        # First message after trim should be a user message
        assert planner.conversation_history[0]["role"] == "user"


# ── Mock helpers for OpenAI-compatible responses ──

def _make_tool_call(name, arguments, tc_id="tc_1"):
    """Create a mock OpenAI tool call object."""
    tc = MagicMock()
    tc.id = tc_id
    tc.type = "function"
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


def _make_choice(finish_reason, content=None, tool_calls=None):
    """Create a mock OpenAI choice object."""
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
    """Create a mock OpenAI API response."""
    resp = MagicMock()
    resp.choices = [_make_choice(finish_reason, content, tool_calls)]
    return resp


class TestToolLoopWithMock:
    """Test the tool call loop with a mocked OpenRouter API."""

    def test_simple_text_response(self, sample_semantic_map):
        """LLM returns text without tools -> immediate reply."""
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")

        mock_response = _make_response("stop", content="I'll go to the whiteboard!")

        with patch.object(planner.client.chat.completions, "create", return_value=mock_response):
            result = planner.run_tool_loop("go to whiteboard", lambda n, i: {})
            assert result == "I'll go to the whiteboard!"

    def test_tool_call_then_text(self, sample_semantic_map):
        """LLM calls navigate_to, gets result, then returns text."""
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")

        # First response: tool_calls
        tc = _make_tool_call("navigate_to", {"location_name": "whiteboard"})
        tool_response = _make_response("tool_calls", tool_calls=[tc])

        # Second response: stop with text
        text_response = _make_response("stop", content="Arrived at the whiteboard!")

        with patch.object(
            planner.client.chat.completions,
            "create",
            side_effect=[tool_response, text_response],
        ):
            executor_calls = []

            def mock_executor(name, inp):
                executor_calls.append((name, inp))
                return {"status": "arrived", "target": "whiteboard"}

            result = planner.run_tool_loop("go to whiteboard", mock_executor)
            assert result == "Arrived at the whiteboard!"
            assert len(executor_calls) == 1
            assert executor_calls[0][0] == "navigate_to"

    def test_api_error_returns_error_message(self, sample_semantic_map):
        """API exception should return an error string, not crash."""
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")

        with patch.object(
            planner.client.chat.completions,
            "create",
            side_effect=Exception("API rate limit"),
        ):
            result = planner.run_tool_loop("go somewhere", lambda n, i: {})
            assert "error" in result.lower()
            assert "rate limit" in result.lower()

    def test_iteration_limit(self, sample_semantic_map):
        """If LLM keeps calling tools, loop should stop at MAX_TOOL_ITERATIONS."""
        planner = LLMPlannerCore(sample_semantic_map, api_key="fake")

        tc = _make_tool_call("get_robot_position", {})
        tool_response = _make_response("tool_calls", tool_calls=[tc])

        with patch.object(
            planner.client.chat.completions,
            "create",
            return_value=tool_response,
        ):
            result = planner.run_tool_loop(
                "keep checking position",
                lambda n, i: {"x": 0, "y": 0, "theta": 0},
            )
            assert "step limit" in result.lower()
