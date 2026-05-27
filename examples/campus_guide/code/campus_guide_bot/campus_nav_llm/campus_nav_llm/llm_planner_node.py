"""LLM Planner Node — Phase 2.

Receives user natural language input, runs LLM Tool Call loop via
OpenRouter (OpenAI-compatible API), executes tools in-process via
embedded TaskExecutorCore (no DDS round-trip).

Architecture: ROSA-inspired in-process tool execution.
  Ref: NASA JPL ROSA — @tool functions are direct Python calls
  in the same process, eliminating DDS message loss.

Features:
  - In-process tool execution (TaskExecutorCore embedded in planner)
  - Simple command fast path (regex → direct execution, skip LLM)
  - LLM retry with exponential backoff
  - AMCL covariance monitoring + relocalization
  - /system_status health aggregation
  - Guaranteed reply on every user input
  - Cancel support mid-tool-loop
"""
import copy
import json
import os
import re
import threading
import logging
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import random
import time as _time

from openai import OpenAI

from campus_nav_llm.location_resolver import LocationResolver, load_semantic_map

logger = logging.getLogger(__name__)

# LLM API retry settings
# Ref: OpenAI SDK retry pattern; NASA JPL ROSA uses similar backoff for cloud APIs
LLM_MAX_RETRIES = 3
LLM_RETRY_BASE_DELAY = 1.0  # seconds, doubles each attempt
LLM_RETRY_JITTER = 0.5      # random jitter to avoid thundering herd

# Auto-load API key from .env or dashboard's saved key file
def _load_dotenv():
    # 1. Try .env files
    for search_dir in [Path.cwd(), Path(__file__).parent.parent, Path.home()]:
        env_file = search_dir / ".env"
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())
            logger.info("Loaded .env from %s", env_file)
            return

    # 2. Try dashboard's saved API key file (set via web UI)
    for key_path in [
        Path(__file__).parent.parent.parent.parent / "dashboard" / ".openrouter_key",
        Path.home() / "CS5335TurtleBot" / "dashboard" / ".openrouter_key",
    ]:
        if key_path.exists():
            key = key_path.read_text().strip()
            if key:
                os.environ.setdefault("OPENROUTER_API_KEY", key)
                logger.info("Loaded API key from %s", key_path)
                return
_load_dotenv()

MAX_TOOL_ITERATIONS = 10

# Regex patterns for simple commands that can bypass LLM
_SIMPLE_NAV_PATTERNS = [
    re.compile(r"^(?:go|navigate|take me|move|drive)\s+(?:to\s+)?(.+)$", re.I),
    re.compile(r"^(?:bring me to|head to|go to)\s+(.+)$", re.I),
]
_STOP_PATTERNS = [
    re.compile(r"^(?:stop|cancel|halt|abort|don't go|nevermind).*$", re.I),
]
_POSITION_PATTERNS = [
    re.compile(r"^(?:where am i|where are you|current position|my position|what'?s? my (?:location|position)).*$", re.I),
]

# Phase 1.2: 7 tools (OpenAI function calling format)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "navigate_to",
            "description": (
                "Navigate to a named location from the semantic map. "
                "The location must exist in the map. Use exact location "
                "names or known aliases."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location_name": {
                        "type": "string",
                        "description": "Name or alias of the target location",
                    }
                },
                "required": ["location_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_route",
            "description": (
                "Navigate to multiple locations in order. Use this instead of "
                "multiple navigate_to calls when the user wants to visit several "
                "places sequentially. Automatically handles relocalization between "
                "stops if needed. Stops early if any navigation fails or is canceled."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "locations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of location names to visit",
                    }
                },
                "required": ["locations"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_robot_position",
            "description": "Get the robot's current (x, y, theta) position on the map and nearby locations.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "speak",
            "description": "Say something to the user (status update, greeting, confirmation, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to say to the user"}
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_navigation",
            "description": "Cancel the current navigation goal. Use when the user wants to stop or change destination.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_costmap",
            "description": (
                "Clear the local and global costmaps. Use as a recovery "
                "action when navigation fails due to stale obstacle data."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_navigation_status",
            "description": "Check if navigation is currently in progress and get the robot's current pose.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relocalize",
            "description": (
                "Re-localize the robot when localization is lost or uncertain. "
                "Spreads AMCL particles across the map and spins the robot in place "
                "to collect laser data. Takes ~15 seconds. Use when navigate_to "
                "fails due to localization uncertainty."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


class LLMPlannerCore:
    """Core LLM planner logic — no ROS dependency.

    This class manages the LLM Tool Call loop via OpenRouter.
    Tool execution is delegated via the `tool_executor` callback.
    """

    def __init__(
        self,
        semantic_map: dict,
        model: str = "anthropic/claude-sonnet-4-6",
        api_key: str | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
    ):
        self.client = OpenAI(
            api_key=api_key or os.environ.get("OPENROUTER_API_KEY", ""),
            base_url=base_url,
        )
        self.model = model
        self.resolver = LocationResolver(semantic_map)
        self.conversation_history: list[dict] = []
        self._lock = threading.Lock()

    def _call_llm_with_retry(self, api_messages: list) -> object:
        """Call the LLM API with exponential backoff retry.

        Retries on transient errors (connection, rate limit, timeout, 5xx).
        Does NOT retry on auth errors or bad requests.
        Ref: OpenAI Python SDK retry pattern; tenacity library backoff strategy.
        """
        last_error = None
        delay = LLM_RETRY_BASE_DELAY

        for attempt in range(1, LLM_MAX_RETRIES + 1):
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=1024,
                    tools=TOOLS,
                    messages=api_messages,
                )
            except Exception as e:
                last_error = e
                err_name = type(e).__name__

                # Non-retryable errors — fail immediately
                if "AuthenticationError" in err_name or "BadRequestError" in err_name:
                    raise

                if attempt < LLM_MAX_RETRIES:
                    jitter = random.uniform(0, LLM_RETRY_JITTER)
                    wait = delay + jitter
                    logger.warning(
                        "LLM API attempt %d/%d failed (%s: %s), retrying in %.1fs",
                        attempt, LLM_MAX_RETRIES, err_name, e, wait,
                    )
                    _time.sleep(wait)
                    delay *= 2

        raise last_error

    def build_system_prompt(self) -> str:
        """Build the system prompt with available locations."""
        locations_text = self.resolver.get_all_locations_text()

        return (
            "You are a navigation assistant running on a TurtleBot 4 robot "
            "inside a classroom at Northeastern University Vancouver.\n\n"
            f"Available locations:\n{locations_text}\n\n"
            "Instructions:\n"
            "- Use tools to complete tasks step by step.\n"
            "- Always call navigate_to with the exact location name from the map.\n"
            "- If the user asks about your position, use get_robot_position.\n"
            "- After navigating, confirm arrival with a speak tool call.\n"
            "- Never guess coordinates; always use named locations.\n"
            "- If the user's request is ambiguous, use speak to ask for clarification.\n"
            "- For multi-stop tasks (e.g. 'go to A then B then C'), use navigate_route with the list of locations.\n"
            "- If navigation fails, try clear_costmap then retry once.\n"
            "- If navigation is rejected due to localization uncertainty, use relocalize first, then retry.\n"
            "- If navigate_to returns a localization_warning, call relocalize immediately before any further navigation.\n"
            "- If the user says stop/cancel, use cancel_navigation immediately.\n"
        )

    def try_fast_path(self, user_input: str) -> tuple[str, dict] | None:
        """Try to match simple commands without calling the LLM.

        Returns (tool_name, tool_input) if matched, or None.
        """
        text = user_input.strip()

        # Stop commands
        for pattern in _STOP_PATTERNS:
            if pattern.match(text):
                return ("cancel_navigation", {})

        # Position queries
        for pattern in _POSITION_PATTERNS:
            if pattern.match(text):
                return ("get_robot_position", {})

        # Simple navigation commands
        for pattern in _SIMPLE_NAV_PATTERNS:
            m = pattern.match(text)
            if m:
                location = m.group(1).strip().rstrip("?.!")
                # Strip leading articles (the, a, an)
                location = re.sub(r"^(?:the|a|an)\s+", "", location, flags=re.I)
                # Only fast-path if we can resolve the location
                if self.resolver.resolve(location):
                    return ("navigate_to", {"location_name": location})

        return None

    def run_tool_loop(
        self,
        user_input: str,
        tool_executor: callable,
        cancel_check: callable = None,
    ) -> str:
        """Run the LLM Tool Call loop for a user input.

        Args:
            user_input: Natural language command from user.
            tool_executor: Callback function(tool_name, tool_input) -> dict.
                           Called for each tool the LLM wants to invoke.
            cancel_check: Optional callable() -> bool. If it returns True,
                          the loop exits early with a cancellation message.

        Returns:
            Final text reply from the LLM.
        """
        with self._lock:
            self.conversation_history.append(
                {"role": "user", "content": user_input}
            )
            # Trim history while preserving message boundaries
            self._trim_history()
            # Deep copy to prevent concurrent threads from corrupting shared dicts
            messages = copy.deepcopy(self.conversation_history)

        system_prompt = self.build_system_prompt()

        for iteration in range(MAX_TOOL_ITERATIONS):
            if cancel_check and cancel_check():
                logger.info("Tool loop canceled by user at iteration %d", iteration)
                return "Request canceled."
            try:
                api_messages = [
                    {"role": "system", "content": system_prompt}
                ] + messages

                response = self._call_llm_with_retry(api_messages)
            except Exception as e:
                error_msg = f"LLM API error after {LLM_MAX_RETRIES} attempts: {e}"
                logger.error(error_msg)
                return error_msg

            choice = response.choices[0]

            # stop: LLM is done, extract text reply
            if choice.finish_reason == "stop":
                reply = choice.message.content or "Done."
                with self._lock:
                    # Sync tool call/result messages accumulated during the loop
                    self.conversation_history = messages[:]
                    self.conversation_history.append(
                        {"role": "assistant", "content": reply}
                    )
                return reply

            # length: response truncated at max_tokens — return what we got
            if choice.finish_reason == "length":
                reply = choice.message.content or "Response was too long and got cut off."
                logger.warning("LLM response truncated (finish_reason=length)")
                with self._lock:
                    self.conversation_history = messages[:]
                    self.conversation_history.append(
                        {"role": "assistant", "content": reply}
                    )
                return reply

            # tool_calls: execute tool(s) and continue loop
            if choice.finish_reason == "tool_calls":
                # Append assistant message with tool calls
                messages.append(choice.message.model_dump())

                for tc in choice.message.tool_calls:
                    logger.info(
                        "[%d/%d] Tool: %s(%s)",
                        iteration + 1,
                        MAX_TOOL_ITERATIONS,
                        tc.function.name,
                        tc.function.arguments,
                    )

                    # Execute tool via callback
                    try:
                        tool_input = json.loads(tc.function.arguments)
                        result = tool_executor(tc.function.name, tool_input)
                    except Exception as e:
                        result = {"error": str(e)}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    })

        return "I could not complete the task within the step limit."

    def _trim_history(self):
        """Trim conversation history to ~20 messages, preserving tool boundaries.

        Never cut between an assistant tool_calls message and its tool results,
        as that would corrupt the conversation for the API.
        """
        if len(self.conversation_history) <= 20:
            return

        # Find a safe cut point — don't split tool call sequences
        history = self.conversation_history
        cut = len(history) - 20

        # Walk forward from cut to find a safe boundary
        while cut < len(history):
            msg = history[cut]
            # Safe to cut before a user message
            if msg.get("role") == "user":
                break
            cut += 1

        if cut >= len(history):
            cut = len(history) - 20

        self.conversation_history = history[cut:]


# ── ROS 2 Node wrapper (only imported when rclpy is available) ──

def create_ros_node():
    """Factory function to create the ROS 2 node.

    Import rclpy only when actually running on the robot.
    """
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from nav2_simple_commander.robot_navigator import BasicNavigator
    from rclpy.executors import SingleThreadedExecutor
    from action_msgs.msg import GoalStatus
    from nav2_msgs.srv import ClearEntireCostmap
    import math as _math

    from campus_nav_llm.task_executor_node import TaskExecutorCore

    def _wait_for_future(future, timeout_sec=30.0):
        """Block until a future completes, without spinning.

        The dedicated background executor processes callbacks that complete
        futures. This function just polls future.done() — no reentrancy risk.
        """
        import time as _t
        start = _t.monotonic()
        while not future.done():
            if _t.monotonic() - start > timeout_sec:
                raise TimeoutError(f"Future not completed within {timeout_sec}s")
            _t.sleep(0.05)

    class ThreadSafeNavigator(BasicNavigator):
        """BasicNavigator subclass safe to call from any thread.

        Requires a dedicated SingleThreadedExecutor spinning this node
        in a background thread. Replaces rclpy.spin_until_future_complete
        with future.done() polling, since the background executor already
        processes callbacks that complete the futures.

        This eliminates "generator already executing" errors caused by
        concurrent rclpy.spin_until_future_complete calls on the same node.
        """

        def goToPose(self, pose, behavior_tree=''):
            from nav2_msgs.action import NavigateToPose
            self.debug("Waiting for 'NavigateToPose' action server")
            while not self.nav_to_pose_client.wait_for_server(timeout_sec=1.0):
                self.info("'NavigateToPose' action server not available, waiting...")

            goal_msg = NavigateToPose.Goal()
            goal_msg.pose = pose
            goal_msg.behavior_tree = behavior_tree

            self.info(f'Navigating to goal: {pose.pose.position.x} {pose.pose.position.y}...')
            send_goal_future = self.nav_to_pose_client.send_goal_async(
                goal_msg, self._feedbackCallback)

            _wait_for_future(send_goal_future)
            self.goal_handle = send_goal_future.result()

            if not self.goal_handle.accepted:
                self.error('Goal was rejected!')
                return False

            self.result_future = self.goal_handle.get_result_async()
            return True

        def isTaskComplete(self):
            if not self.result_future:
                return True
            if not self.result_future.done():
                return False
            result = self.result_future.result()
            if result is not None:
                self.status = result.status
                if self.status != GoalStatus.STATUS_SUCCEEDED:
                    self.debug(f'Task failed with status code: {self.status}')
                    return True
            self.debug('Task succeeded!')
            return True

        def cancelTask(self):
            self.info('Canceling current task.')
            if self.result_future and self.goal_handle:
                future = self.goal_handle.cancel_goal_async()
                _wait_for_future(future, timeout_sec=10.0)

        def clearLocalCostmap(self):
            while not self.clear_costmap_local_srv.wait_for_service(timeout_sec=1.0):
                self.info('Clear local costmaps service not available, waiting...')
            req = ClearEntireCostmap.Request()
            future = self.clear_costmap_local_srv.call_async(req)
            _wait_for_future(future, timeout_sec=10.0)

        def clearGlobalCostmap(self):
            while not self.clear_costmap_global_srv.wait_for_service(timeout_sec=1.0):
                self.info('Clear global costmaps service not available, waiting...')
            req = ClearEntireCostmap.Request()
            future = self.clear_costmap_global_srv.call_async(req)
            _wait_for_future(future, timeout_sec=10.0)

    class LLMPlannerNode(Node):
        def __init__(self):
            super().__init__("llm_planner")

            # Parameters
            self.declare_parameter("semantic_map_path", "semantic_map.json")
            self.declare_parameter("robot_namespace", "turtlebot468")
            map_path = self.get_parameter("semantic_map_path").value
            ns = self.get_parameter("robot_namespace").value
            semantic_map = load_semantic_map(map_path)

            self.planner = LLMPlannerCore(semantic_map)

            # ── In-process tool executor (no DDS round-trip) ──
            # Ref: ROSA (NASA JPL) — tools are direct function calls in the
            #      same process, not remote RPC. This eliminates DDS message
            #      loss under FastDDS Discovery Server.
            # Wait for Nav2 action server with retry.
            # lifecycle_activator may still be running (25-50s), so we retry
            # rather than failing on the first 30s timeout.
            navigator = ThreadSafeNavigator(namespace=ns)

            # Spin the navigator on a dedicated background executor.
            # This processes action/service callbacks continuously so that
            # futures complete without calling rclpy.spin_until_future_complete.
            # Eliminates "generator already executing" from concurrent spinning.
            self._nav_executor = SingleThreadedExecutor()
            self._nav_executor.add_node(navigator)
            self._nav_spin_thread = threading.Thread(
                target=self._nav_executor.spin, daemon=True
            )
            self._nav_spin_thread.start()

            self.get_logger().info("Waiting for navigate_to_pose action server...")
            server_ready = False
            for attempt in range(4):  # 4 × 30s = 120s total
                if navigator.nav_to_pose_client.wait_for_server(timeout_sec=30.0):
                    server_ready = True
                    break
                self.get_logger().info(
                    f"  Action server not yet available (attempt {attempt + 1}/4)..."
                )
            if not server_ready:
                self.get_logger().error(
                    "navigate_to_pose action server not available after 120s — "
                    "navigation will not work"
                )
                raise RuntimeError("Nav2 action server not ready — is deploy.sh still running?")
            self.get_logger().info("Action server available")

            self.executor_core = TaskExecutorCore(semantic_map, navigator)

            # Wire AMCL pose updates into the executor core
            amcl_topic = f"/{ns}/amcl_pose" if ns else "/amcl_pose"
            self.create_subscription(
                PoseWithCovarianceStamped, amcl_topic, self._on_amcl, 10
            )

            # Progress callback
            self.pub_progress = self.create_publisher(String, "/nav_progress", 10)
            self.executor_core._progress_callback = self._on_progress

            # System status (1 Hz)
            self.pub_status = self.create_publisher(String, "/system_status", 10)
            self.create_timer(1.0, self._publish_status)

            # Relocalization: wire up global_localization service + cmd_vel
            # Ref: Nav2 reinitialize_global_localization service
            from geometry_msgs.msg import Twist
            from std_srvs.srv import Empty as EmptySrv
            global_loc_srv = f"/{ns}/reinitialize_global_localization" if ns else "/reinitialize_global_localization"
            self._global_loc_client = self.create_client(EmptySrv, global_loc_srv)
            cmd_vel_topic = f"/{ns}/cmd_vel" if ns else "/cmd_vel"
            self._cmd_vel_pub = self.create_publisher(Twist, cmd_vel_topic, 10)
            self.executor_core._relocalize_callback = self._do_relocalize

            # Pub/Sub for user input and replies
            self.sub_input = self.create_subscription(
                String, "/user_input", self._on_user_input, 10
            )
            self.pub_reply = self.create_publisher(String, "/robot_reply", 10)

            # Also publish tool events for dashboard observability
            self.pub_tool_cmd = self.create_publisher(String, "/tool_cmd", 10)
            self.pub_tool_result = self.create_publisher(String, "/tool_result", 10)

            # Allow cancel to interrupt current processing
            self._processing = False
            self._processing_lock = threading.Lock()
            self._cancel_requested = False

            # Thread pool for user input processing
            self._thread_pool = ThreadPoolExecutor(max_workers=2)

            # AMCL health watchdog — auto-recover when AMCL stops publishing
            # Republishes initial pose at last known position to restart AMCL
            # without needing to spin the robot (relocalize).
            # PoseWithCovarianceStamped already imported in enclosing create_ros_node() scope
            amcl_initialpose_topic = f"/{ns}/initialpose" if ns else "/initialpose"
            self._pub_initialpose = self.create_publisher(
                PoseWithCovarianceStamped, amcl_initialpose_topic, 10
            )
            self._amcl_watchdog_recovering = False
            self._amcl_last_recovery = 0.0
            self._amcl_recovery_count = 0
            self.create_timer(3.0, self._amcl_watchdog)

            self.get_logger().info("LLM Planner ready (in-process executor, 7 tools, AMCL watchdog active)")

            from campus_nav_llm.event_logger import EventLogger
            self._evt = self.executor_core._evt  # share the same session log
            self._evt.log("session_start", {
                "node": "llm_planner",
                "namespace": ns,
            })

        def _on_amcl(self, msg):
            """Forward AMCL pose to in-process executor core."""
            p = msg.pose.pose
            q = p.orientation
            yaw = _math.atan2(
                2 * (q.w * q.z + q.x * q.y),
                1 - 2 * (q.y * q.y + q.z * q.z),
            )
            self.executor_core.update_pose(p.position.x, p.position.y, yaw)
            cov = msg.pose.covariance
            self.executor_core.update_covariance(cov[0], cov[7])

        def _on_progress(self, progress: dict):
            self.pub_progress.publish(String(data=json.dumps(progress)))

        def _publish_status(self):
            status = self.executor_core.get_system_status()
            self.pub_status.publish(String(data=json.dumps(status)))

        def _do_relocalize(self, cancel_check=None) -> dict:
            from campus_nav_llm.task_executor_node import do_relocalize
            return do_relocalize(self, cancel_check=cancel_check)

        def _amcl_watchdog(self):
            """Auto-recover AMCL when it stops publishing.

            Checks AMCL health every 3s. If no pose update for >15s:
            1. Republish initial pose at last known position (resets particle filter)
            2. Trigger chrony clock sync on RPi (common cause of AMCL stall)

            This avoids needing manual relocalize (which spins the robot).
            Cooldown: min 30s between recovery attempts to avoid thrashing.
            """
            import time as _time

            health = self.executor_core.get_localization_health()
            if health["healthy"]:
                if self._amcl_watchdog_recovering:
                    self.get_logger().info("AMCL recovered — publishing again")
                    self._amcl_watchdog_recovering = False
                return

            age = health.get("age_s", 0)
            reason = health.get("reason", "unknown")

            # Only act if AMCL has been stale for >15s (not just momentary)
            if "not publishing" not in reason:
                return  # high covariance is not a stall — let it settle

            # Cooldown: don't retry within 30s of last recovery
            now = _time.monotonic()
            if now - self._amcl_last_recovery < 30.0:
                return

            self._amcl_watchdog_recovering = True
            self._amcl_last_recovery = now
            self._amcl_recovery_count += 1

            self.get_logger().warn(
                f"AMCL watchdog: {reason} — auto-recovering "
                f"(attempt #{self._amcl_recovery_count})"
            )

            # Step 1: Trigger clock sync (fire-and-forget in background)
            def _sync_clock():
                import subprocess
                try:
                    subprocess.run(
                        ["sshpass", "-p", "turtlebot4", "ssh",
                         "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=3",
                         "ubuntu@192.168.50.31", "sudo chronyc -a makestep"],
                        capture_output=True, timeout=10,
                    )
                except Exception:
                    pass
            threading.Thread(target=_sync_clock, daemon=True).start()

            # Step 2: Republish initial pose at last known position
            pose = self.executor_core.get_pose()
            if pose["x"] == 0.0 and pose["y"] == 0.0:
                self.get_logger().warn("AMCL watchdog: no known pose, skipping recovery")
                return

            msg = PoseWithCovarianceStamped()
            msg.header.frame_id = "map"
            # stamp=0 tells AMCL to use current time (avoids clock issues)
            msg.header.stamp.sec = 0
            msg.header.stamp.nanosec = 0
            msg.pose.pose.position.x = pose["x"]
            msg.pose.pose.position.y = pose["y"]
            # Convert yaw back to quaternion
            import math
            msg.pose.pose.orientation.z = math.sin(pose["theta"] / 2.0)
            msg.pose.pose.orientation.w = math.cos(pose["theta"] / 2.0)
            # Set covariance (moderate uncertainty — let AMCL refine)
            msg.pose.covariance[0] = 0.1   # x variance
            msg.pose.covariance[7] = 0.1   # y variance
            msg.pose.covariance[35] = 0.05  # yaw variance

            self._pub_initialpose.publish(msg)
            self.get_logger().info(
                f"AMCL watchdog: republished initial pose at "
                f"({pose['x']:.2f}, {pose['y']:.2f}, yaw={pose['theta']:.2f})"
            )

            self._evt.log("amcl_watchdog_recovery", {
                "attempt": self._amcl_recovery_count,
                "pose_x": pose["x"],
                "pose_y": pose["y"],
                "reason": reason,
            })

        def _on_user_input(self, msg):
            user_input = msg.data.strip()
            if not user_input:
                return

            is_cancel = any(p.match(user_input) for p in _STOP_PATTERNS)

            with self._processing_lock:
                if self._processing and not is_cancel:
                    self.get_logger().warn(
                        f"Already processing, ignoring: {user_input[:50]}"
                    )
                    self.pub_reply.publish(String(
                        data="I'm still working on the previous command. Please wait or say 'cancel'."
                    ))
                    return
                if is_cancel and self._processing:
                    self._cancel_requested = True
                self._processing = True

            self._thread_pool.submit(self._handle_input, user_input)

        def _local_tool_executor(self, tool_name, tool_input):
            """Execute tool via in-process function call — no DDS round-trip.

            Ref: ROSA (NASA JPL) — @tool functions are direct Python calls in
            the same process. Eliminates DDS message loss entirely.

            Also publishes to /tool_cmd and /tool_result for dashboard
            observability (fire-and-forget, loss is acceptable for monitoring).
            """
            request_id = str(uuid.uuid4())

            # Publish tool_cmd for dashboard (observability only, not critical)
            try:
                self.pub_tool_cmd.publish(String(data=json.dumps({
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "request_id": request_id,
                })))
            except Exception:
                pass  # observability, not critical

            # Inject cancel_check for relocalize tool
            if tool_name == "relocalize":
                tool_input = dict(tool_input) if tool_input else {}
                tool_input["_cancel_check"] = lambda: self._cancel_requested

            # Direct in-process execution — the core fix
            result = self.executor_core.execute(tool_name, tool_input, request_id)

            # Publish tool_result for dashboard (observability only)
            try:
                self.pub_tool_result.publish(String(data=json.dumps(result)))
            except Exception:
                pass

            # Speak tool: also publish to /robot_reply
            if tool_name == "speak" and "text" in result:
                self.pub_reply.publish(String(data=result["text"]))

            return result

        def _handle_input(self, user_input):
            """Process user input with guaranteed reply.

            Ref: ROSA (NASA JPL) — every tool returns a string, never None.
                 OpenAI docs — return errors as tool results, not exceptions.
                 LangChain — handle_tool_error=True catches all tool failures.
            Every code path MUST publish to /robot_reply.
            """
            reply = None
            t0 = __import__("time").monotonic()
            path_type = "unknown"
            try:
                self.get_logger().info(f"Processing: {user_input}")
                self._cancel_requested = False
                self._evt.log("user_input", {"text": user_input})

                # Try fast path first (simple commands skip LLM)
                fast = self.planner.try_fast_path(user_input)
                if fast:
                    tool_name, tool_input = fast
                    path_type = "fast"
                    self.get_logger().info(
                        f"Fast path: {tool_name}({tool_input})"
                    )
                    result = self._local_tool_executor(tool_name, tool_input)
                    reply = self._format_fast_reply(tool_name, result)

                    # Update conversation history so LLM has context of fast-path commands
                    with self.planner._lock:
                        self.planner.conversation_history.append(
                            {"role": "user", "content": user_input}
                        )
                        self.planner.conversation_history.append(
                            {"role": "assistant", "content": reply}
                        )
                        self.planner._trim_history()
                else:
                    # Full LLM tool loop
                    path_type = "llm"
                    reply = self.planner.run_tool_loop(
                        user_input, self._local_tool_executor,
                        cancel_check=lambda: self._cancel_requested,
                    )
            except Exception as e:
                # Guaranteed error reply — never swallow exceptions silently
                path_type = "error"
                reply = f"Sorry, something went wrong: {e}"
                self.get_logger().error(f"_handle_input error: {e}")
                self._evt.log("handle_error", {"input": user_input, "error": str(e)})
            finally:
                # ALWAYS publish a reply — this is the guaranteed-return pattern
                # Ref: ROSA "every invoke() returns a string"
                if reply is None:
                    reply = "Sorry, I couldn't process that command."
                self.pub_reply.publish(String(data=reply))
                self.get_logger().info(f"Reply: {reply[:100]}")
                elapsed = round(__import__("time").monotonic() - t0, 3)
                self._evt.log("interaction", {
                    "input": user_input,
                    "reply": reply[:200],
                    "path": path_type,
                    "elapsed_s": elapsed,
                })
                with self._processing_lock:
                    self._processing = False
                    self._cancel_requested = False

        def _format_fast_reply(self, tool_name: str, result: dict) -> str:
            """Generate a human-readable reply for fast-path tool results."""
            if tool_name == "navigate_to":
                status = result.get("status", "unknown")
                target = result.get("target", "unknown")
                loc_warning = result.get("localization_warning")

                if status == "arrived":
                    if loc_warning:
                        self.get_logger().warn(
                            f"Post-nav localization degraded: {loc_warning}, auto-relocalizing"
                        )
                        reloc_result = self._local_tool_executor("relocalize", {})
                        reloc_status = reloc_result.get("status", "unknown")
                        if reloc_status == "success":
                            return f"Arrived at {target}. Localization refreshed automatically."
                        else:
                            return (
                                f"Arrived at {target}, but localization is degraded "
                                f"({loc_warning}). Auto-relocalize {reloc_status}. "
                                f"You may need to run relocalize manually."
                            )
                    return f"Arrived at {target}."
                elif status == "canceled":
                    return f"Navigation to {target} was canceled."
                else:
                    error = result.get("error", "unknown error")
                    return f"Failed to reach {target}: {error}"

            elif tool_name == "cancel_navigation":
                status = result.get("status", "unknown")
                if status == "no_navigation_active":
                    return "No navigation is currently active."
                return "Navigation canceled."

            elif tool_name == "get_robot_position":
                x = result.get("x", 0)
                y = result.get("y", 0)
                nearby = result.get("nearby_locations", [])
                if nearby:
                    closest = nearby[0]["name"]
                    dist = nearby[0]["distance_m"]
                    return f"I'm at ({x:.1f}, {y:.1f}), near {closest} ({dist:.1f}m away)."
                return f"I'm at ({x:.1f}, {y:.1f})."

            return json.dumps(result)

    return LLMPlannerNode


def main():
    import rclpy

    rclpy.init()
    NodeClass = create_ros_node()
    node = NodeClass()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if hasattr(node, '_nav_executor'):
            node._nav_executor.shutdown()
        node._thread_pool.shutdown(wait=False)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
