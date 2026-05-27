"""Task Executor Node — Phase 1.1.

Receives tool commands from LLM Planner, executes them against ROS
subsystems, and returns structured results.

Phase 1.1 tools:
  - navigate_to: Navigate to a named location
  - get_robot_position: Get current pose + nearby locations
  - speak: Log a message for the user
  - cancel_navigation: Abort current navigation goal
  - clear_costmap: Clear local/global costmaps for recovery
  - get_navigation_status: Check if navigation is in progress
"""
import json
import math
import time
import threading
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from campus_nav_llm.location_resolver import LocationResolver
from campus_nav_llm.event_logger import EventLogger, NullEventLogger

logger = logging.getLogger(__name__)

# Navigation timeout (seconds) — prevent infinite blocking
NAV_TIMEOUT = 120.0
# Progress report interval (seconds)
PROGRESS_INTERVAL = 3.0

# AMCL covariance threshold — sum of xx + yy diagonal.
# Above this, localization is considered unreliable.
# Ref: CMU Q Robotics Lab uses ~0.5-0.65 per axis; Nav2 #4402 documents
# covariance growth during rotation. We use combined threshold.
AMCL_COV_THRESHOLD = 1.0  # sum of cov[0] (xx) + cov[7] (yy)

# Map boundary padding (meters) — reject goals outside map + padding
MAP_BOUNDARY_PADDING = 1.0

# Relocalization: spin duration and velocity for collecting laser data
# Ref: Nav2 AutoLocalization pattern — rotate in place after global_localization
RELOCALIZE_SPIN_SPEED = 0.5   # rad/s
RELOCALIZE_SPIN_DURATION = 14.0  # seconds (~1 full rotation at 0.5 rad/s)
_RELOC_TICK_PERIOD = 0.1  # seconds — cmd_vel publish rate during spin (10 Hz)


def do_relocalize(node, cancel_check=None) -> dict:
    """Spin-to-refine relocalization: rotate in place to collect laser data.

    Never calls global_localization (which scatters particles across the entire
    map and requires far more than 14s to converge in practice). Instead, just
    spins to let AMCL refine the current pose estimate with fresh laser scans.

    Ref: Nav2 TimedBehavior pattern — timer publishes cmd_vel on the ROS
    executor thread, keeping it free for AMCL callbacks. The calling thread
    (ThreadPoolExecutor worker) waits on threading.Event.

    Args:
        node: ROS node with ._global_loc_client, ._cmd_vel_pub, .executor_core
        cancel_check: Optional callable returning True to abort spin early.

    Returns:
        dict with status key ("success", "partial", "cancelled", or "error").
    """
    from geometry_msgs.msg import Twist

    health = node.executor_core.get_localization_health()
    current_cov = health.get("covariance_xy", float("inf"))
    node.get_logger().info(
        f"Relocalization: spin-to-refine (current covariance: {current_cov:.3f})"
    )

    node.get_logger().info(
        f"Spinning in place for {RELOCALIZE_SPIN_DURATION:.0f}s to collect laser data..."
    )

    # Phase 2: Timer-based spin (Nav2 TimedBehavior pattern)
    spin_done = threading.Event()
    spin_result = {"cancelled": False}

    twist = Twist()
    twist.angular.z = RELOCALIZE_SPIN_SPEED
    spin_start = time.monotonic()

    def _spin_tick():
        elapsed = time.monotonic() - spin_start

        if cancel_check is not None and cancel_check():
            node._cmd_vel_pub.publish(Twist())
            spin_result["cancelled"] = True
            spin_timer.cancel()
            spin_done.set()
            return

        if elapsed >= RELOCALIZE_SPIN_DURATION:
            node._cmd_vel_pub.publish(Twist())
            spin_timer.cancel()
            spin_done.set()
            return

        node._cmd_vel_pub.publish(twist)

    spin_timer = node.create_timer(_RELOC_TICK_PERIOD, _spin_tick)
    spin_done.wait(timeout=RELOCALIZE_SPIN_DURATION + 5.0)

    if not spin_done.is_set():
        spin_timer.cancel()
        node._cmd_vel_pub.publish(Twist())

    node.destroy_timer(spin_timer)

    if spin_result["cancelled"]:
        node.get_logger().info("Relocalization cancelled by user")
        return {"status": "cancelled"}

    health = node.executor_core.get_localization_health()
    if health["healthy"]:
        node.get_logger().info(
            f"Relocalization succeeded (covariance: {health.get('covariance_xy', -1):.4f})"
        )
        return {"status": "success", "localization": health}
    else:
        node.get_logger().warning(
            f"Relocalization finished but localization still unhealthy: {health.get('reason', '')}"
        )
        return {
            "status": "partial",
            "localization": health,
            "hint": "Try setting initial pose manually via RViz2 or deploy.sh",
        }


class TaskExecutorCore:
    """Core tool dispatch logic — no ROS dependency.

    Navigation is delegated via the `navigator` interface.
    For testing, pass a mock navigator.
    """

    def __init__(self, semantic_map: dict, navigator=None):
        self.resolver = LocationResolver(semantic_map)
        self.navigator = navigator
        self._robot_pose = {"x": 0.0, "y": 0.0, "theta": 0.0}
        self._pose_lock = threading.Lock()
        self._nav_active = False
        self._nav_lock = threading.Lock()
        self._progress_callback = None  # set by ROS node
        self._status_callback = None    # set by ROS node

        # AMCL covariance tracking
        # Ref: nav2_amcl publishes covariance in PoseWithCovarianceStamped;
        # CMU Q Robotics Lab uses diagonal values to assess localization quality
        self._amcl_covariance_xy = 0.0  # cov[0] + cov[7]
        self._amcl_last_update = 0.0    # monotonic timestamp
        self._cov_lock = threading.Lock()

        # Map bounds for goal pre-validation (computed from semantic map)
        # Ref: ROSA (NASA JPL) validates tool parameters before execution
        xs = [loc["x"] for loc in semantic_map.get("locations", {}).values()]
        ys = [loc["y"] for loc in semantic_map.get("locations", {}).values()]
        if xs and ys:
            self._map_x_range = (min(xs) - MAP_BOUNDARY_PADDING, max(xs) + MAP_BOUNDARY_PADDING)
            self._map_y_range = (min(ys) - MAP_BOUNDARY_PADDING, max(ys) + MAP_BOUNDARY_PADDING)
        else:
            self._map_x_range = (-100, 100)
            self._map_y_range = (-100, 100)

        # Relocalization callback — set by ROS node (calls global_localization service + spin)
        self._relocalize_callback = None

        self._dispatch = {
            "navigate_to": self._navigate,
            "navigate_route": self._navigate_route,
            "get_robot_position": self._get_position,
            "speak": self._speak,
            "cancel_navigation": self._cancel_navigation,
            "clear_costmap": self._clear_costmap,
            "get_navigation_status": self._get_nav_status,
            "relocalize": self._relocalize,
        }

        # Use NullEventLogger in test mode (no navigator) to avoid file pollution
        self._evt = EventLogger() if navigator is not None else NullEventLogger()

    def update_pose(self, x: float, y: float, theta: float):
        """Update the robot's current pose (called by AMCL subscriber)."""
        with self._pose_lock:
            self._robot_pose = {
                "x": round(x, 3),
                "y": round(y, 3),
                "theta": round(theta, 3),
            }

    def get_pose(self) -> dict:
        with self._pose_lock:
            return dict(self._robot_pose)

    def update_covariance(self, cov_xx: float, cov_yy: float):
        """Update AMCL covariance (called by AMCL subscriber)."""
        with self._cov_lock:
            self._amcl_covariance_xy = cov_xx + cov_yy
            self._amcl_last_update = time.monotonic()

    def get_localization_health(self) -> dict:
        """Check localization quality based on AMCL covariance.

        Ref: CMU Q Robotics Lab threshold; Nav2 #4402 covariance behavior.
        """
        with self._cov_lock:
            cov = self._amcl_covariance_xy
            age = time.monotonic() - self._amcl_last_update if self._amcl_last_update > 0 else float("inf")

        if age > 10.0:
            return {"healthy": False, "reason": "AMCL not publishing (no update in {:.0f}s)".format(age)}
        if cov > AMCL_COV_THRESHOLD:
            return {"healthy": False, "reason": f"Localization uncertain (covariance {cov:.3f} > {AMCL_COV_THRESHOLD})"}
        return {"healthy": True, "covariance_xy": round(cov, 4), "age_s": round(age, 1)}

    def get_system_status(self) -> dict:
        """Aggregate system health for /system_status topic.

        Ref: ROS 2 diagnostics framework (ros/diagnostics); TurtleBot4 diagnostics package.
        """
        loc_health = self.get_localization_health()
        with self._nav_lock:
            nav_active = self._nav_active
        nav_ready = self.navigator is not None

        status = "ok"
        issues = []
        if not loc_health["healthy"]:
            status = "degraded"
            issues.append(loc_health["reason"])
        if not nav_ready:
            status = "error"
            issues.append("Navigator not initialized")

        return {
            "status": status,
            "localization": loc_health,
            "navigation_active": nav_active,
            "navigator_ready": nav_ready,
            "issues": issues,
        }

    def _validate_goal(self, name: str, x: float, y: float) -> str | None:
        """Pre-validate navigation goal. Returns error string or None if OK.

        Ref: ROSA (NASA JPL) validates tool parameters before execution;
        Nav2 costmap getCost() API for obstacle checking.
        """
        # Check map bounds
        if not (self._map_x_range[0] <= x <= self._map_x_range[1]):
            return f"Goal '{name}' x={x:.2f} is outside map range {self._map_x_range}"
        if not (self._map_y_range[0] <= y <= self._map_y_range[1]):
            return f"Goal '{name}' y={y:.2f} is outside map range {self._map_y_range}"

        # Check localization health
        loc = self.get_localization_health()
        if not loc["healthy"]:
            return f"Cannot navigate: {loc['reason']}. Use the relocalize tool first."

        return None

    def execute(self, tool_name: str, tool_input: dict, request_id: str = "") -> dict:
        """Execute a tool call and return the result dict."""
        handler = self._dispatch.get(tool_name)
        if not handler:
            result = {"error": f"Unknown tool: {tool_name}", "request_id": request_id}
            self._evt.log("tool_error", {"tool": tool_name, "error": result["error"], "request_id": request_id})
            return result
        t0 = time.monotonic()
        try:
            result = handler(tool_input)
            result["request_id"] = request_id
            elapsed = round(time.monotonic() - t0, 3)
            self._evt.log("tool_exec", {
                "tool": tool_name,
                "input": {k: v for k, v in (tool_input or {}).items() if not k.startswith("_")},
                "status": result.get("status", result.get("error", "ok")),
                "elapsed_s": elapsed,
                "request_id": request_id,
            })
            return result
        except Exception as e:
            elapsed = round(time.monotonic() - t0, 3)
            logger.error("Tool %s failed: %s", tool_name, e)
            self._evt.log("tool_error", {
                "tool": tool_name,
                "error": str(e),
                "elapsed_s": elapsed,
                "request_id": request_id,
            })
            return {"error": str(e), "request_id": request_id}

    def _navigate(self, inp: dict) -> dict:
        loc_name = inp.get("location_name", "")
        resolved = self.resolver.resolve(loc_name)
        if not resolved:
            return {
                "error": f"Unknown location: '{loc_name}'",
                "available": self.resolver.location_names,
            }

        name, info = resolved
        target_x, target_y = info["x"], info["y"]
        facing_deg = info.get("facing_deg", 0)

        if self.navigator is None:
            return {
                "status": "arrived",
                "target": name,
                "position": {"x": target_x, "y": target_y},
                "note": "simulated (no navigator)",
            }

        # Pre-validate goal before sending to Nav2
        validation_error = self._validate_goal(name, target_x, target_y)
        if validation_error:
            return {
                "status": "rejected",
                "target": name,
                "error": validation_error,
            }

        # Check if already navigating
        with self._nav_lock:
            if self._nav_active:
                return {
                    "status": "rejected",
                    "error": "Navigation already in progress. Cancel first.",
                }
            self._nav_active = True

        try:
            goal = _make_pose_stamped(
                self.navigator, target_x, target_y, facing_deg
            )
            self.navigator.goToPose(goal)

            start_time = time.monotonic()
            last_progress = start_time

            while not self.navigator.isTaskComplete():
                elapsed = time.monotonic() - start_time

                # Timeout guard
                if elapsed > NAV_TIMEOUT:
                    self.navigator.cancelTask()
                    return {
                        "status": "failed",
                        "target": name,
                        "error": f"Navigation timed out after {NAV_TIMEOUT:.0f}s",
                    }

                # Progress feedback
                now = time.monotonic()
                if now - last_progress >= PROGRESS_INTERVAL:
                    last_progress = now
                    pose = self.get_pose()
                    dist = math.hypot(
                        target_x - pose["x"], target_y - pose["y"]
                    )
                    progress = {
                        "type": "nav_progress",
                        "target": name,
                        "distance_remaining_m": round(dist, 2),
                        "elapsed_s": round(elapsed, 1),
                    }
                    if self._progress_callback:
                        self._progress_callback(progress)

                time.sleep(0.5)

            nav_result = self.navigator.getResult()
            from nav2_simple_commander.robot_navigator import TaskResult

            result_map = {
                TaskResult.SUCCEEDED: "arrived",
                TaskResult.CANCELED: "canceled",
                TaskResult.FAILED: "failed",
                TaskResult.UNKNOWN: "unknown",
            }
            status = result_map.get(nav_result, "failed")

            result = {
                "status": status,
                "target": name,
                "position": {"x": target_x, "y": target_y},
            }

            if status != "arrived":
                result["error"] = f"Nav2 returned: {nav_result}"
                result["recovery_hint"] = (
                    "Try clear_costmap then retry, or choose a different location."
                )

            # Post-navigation localization health check
            post_health = self.get_localization_health()
            if not post_health["healthy"]:
                result["localization_warning"] = post_health["reason"]
                result["recovery_hint"] = (
                    "Localization degraded after navigation. "
                    "Run relocalize to restore accuracy before next navigation."
                )

            return result

        except Exception as e:
            return {
                "status": "failed",
                "target": name,
                "error": str(e),
            }
        finally:
            with self._nav_lock:
                self._nav_active = False

    def _navigate_route(self, inp: dict) -> dict:
        """Navigate to multiple locations sequentially.

        Automatically checks localization health between stops and
        triggers relocalize if needed. Stops the route if any
        navigation fails/is canceled or if cancel is requested.
        """
        locations = inp.get("locations", [])
        if not locations:
            return {"error": "No locations provided"}
        if len(locations) < 2:
            return self._navigate({"location_name": locations[0]})

        cancel_check = inp.get("_cancel_check")
        results = []
        completed = 0

        for i, loc_name in enumerate(locations):
            # Check cancel between stops
            if cancel_check and cancel_check():
                results.append({"target": loc_name, "status": "canceled", "reason": "route canceled by user"})
                break

            nav_result = self._navigate({"location_name": loc_name})
            results.append(nav_result)
            status = nav_result.get("status")

            if status != "arrived":
                break  # Stop route on failure/cancel/rejection

            completed += 1

            # Auto-relocalize between stops if localization degraded
            if i < len(locations) - 1 and nav_result.get("localization_warning"):
                if self._relocalize_callback is not None:
                    kwargs = {}
                    if cancel_check:
                        kwargs["cancel_check"] = cancel_check
                    reloc = self._relocalize_callback(**kwargs)
                    results.append({
                        "type": "auto_relocalize",
                        "after": loc_name,
                        "status": reloc.get("status", "unknown"),
                    })

        return {
            "status": "completed" if completed == len(locations) else "partial",
            "completed": completed,
            "total": len(locations),
            "stops": results,
        }

    def _get_position(self, inp: dict) -> dict:
        pose = self.get_pose()
        nearby = self.resolver.get_nearby(pose["x"], pose["y"], radius=3.0)
        return {**pose, "nearby_locations": nearby}

    def _speak(self, inp: dict) -> dict:
        text = inp.get("text", "")
        logger.info("Robot says: %s", text)
        return {"status": "spoken", "text": text}

    def _cancel_navigation(self, inp: dict) -> dict:
        with self._nav_lock:
            if not self._nav_active:
                return {"status": "no_navigation_active"}

        if self.navigator is None:
            return {"status": "canceled", "note": "simulated"}

        try:
            self.navigator.cancelTask()
            return {"status": "canceled"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _clear_costmap(self, inp: dict) -> dict:
        if self.navigator is None:
            return {"status": "cleared", "note": "simulated"}

        try:
            self.navigator.clearAllCostmaps()
            return {"status": "cleared", "note": "Local and global costmaps cleared"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _get_nav_status(self, inp: dict) -> dict:
        with self._nav_lock:
            active = self._nav_active
        pose = self.get_pose()
        return {
            "navigation_active": active,
            "current_pose": pose,
        }

    def _relocalize(self, inp: dict) -> dict:
        """Trigger global relocalization: spread particles + spin to collect data.

        Ref: Nav2 reinitialize_global_localization service;
        Nav2 AutoLocalization BT pattern (spread particles → spin → backup → spin).

        The optional _cancel_check key in inp is forwarded to the callback
        so the spin phase can be interrupted by the user.
        """
        if self._relocalize_callback is None:
            return {"status": "error", "error": "Relocalization not available (no ROS context)"}

        try:
            kwargs = {}
            if "_cancel_check" in inp:
                kwargs["cancel_check"] = inp["_cancel_check"]
            result = self._relocalize_callback(**kwargs)
            return result
        except Exception as e:
            return {"status": "error", "error": str(e)}


def _make_pose_stamped(navigator, x: float, y: float, facing_deg: float):
    """Build a PoseStamped goal from world coordinates and facing angle.

    facing_deg uses standard math convention (0=east, 90=north, CCW positive).
    Converts directly to quaternion without discrete angle mapping.
    """
    from geometry_msgs.msg import PoseStamped

    yaw = math.radians(facing_deg)

    pose = PoseStamped()
    pose.header.frame_id = "map"
    pose.header.stamp = navigator.get_clock().now().to_msg()
    pose.pose.position.x = x
    pose.pose.position.y = y
    pose.pose.orientation.z = math.sin(yaw / 2)
    pose.pose.orientation.w = math.cos(yaw / 2)
    return pose


# ── ROS 2 Node wrapper ──

def create_ros_node():
    """Factory function to create the ROS 2 node."""
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
    from std_srvs.srv import Empty
    from nav2_simple_commander.robot_navigator import BasicNavigator

    class TaskExecutorNode(Node):
        def __init__(self):
            super().__init__("task_executor")

            # Load semantic map
            self.declare_parameter("semantic_map_path", "semantic_map.json")
            map_path = self.get_parameter("semantic_map_path").value
            from campus_nav_llm.location_resolver import load_semantic_map
            semantic_map = load_semantic_map(map_path)

            # Initialize navigator with namespace
            self.declare_parameter("robot_namespace", "turtlebot468")
            ns = self.get_parameter("robot_namespace").value
            navigator = BasicNavigator(namespace=ns)

            # Do NOT call waitUntilNav2Active() — it uses lifecycle service
            # discovery which is broken under FastDDS Discovery Server
            # (Nav2 #3560). deploy.sh handles manual lifecycle activation
            # and sets the initial pose externally.
            self.get_logger().info(
                "Task Executor starting (Nav2 activation handled by deploy.sh)"
            )

            # Wait for navigate_to_pose action server instead
            self.get_logger().info("Waiting for navigate_to_pose action server...")
            if not navigator.nav_to_pose_client.wait_for_server(timeout_sec=120.0):
                self.get_logger().error(
                    "navigate_to_pose action server not available after 120s"
                )
                raise RuntimeError("Nav2 action server not ready — is deploy.sh still running?")
            self.get_logger().info("navigate_to_pose action server is available")

            self.executor_core = TaskExecutorCore(semantic_map, navigator)

            # Wire up progress callback
            self.pub_progress = self.create_publisher(
                String, "/nav_progress", 10
            )
            self.executor_core._progress_callback = self._on_progress

            # AMCL pose subscription (namespaced)
            amcl_topic = f"/{ns}/amcl_pose" if ns else "/amcl_pose"
            self.create_subscription(
                PoseWithCovarianceStamped,
                amcl_topic,
                self._on_amcl,
                10,
            )

            # System status publisher (1 Hz)
            # Ref: ROS 2 diagnostics framework; TurtleBot4 diagnostics package
            self.pub_status = self.create_publisher(String, "/system_status", 10)
            self.executor_core._status_callback = self._publish_status
            self.create_timer(1.0, self._publish_status)

            # Relocalization: global_localization service + cmd_vel spin
            # Ref: Nav2 reinitialize_global_localization service (std_srvs/Empty)
            #      Nav2 AutoLocalization BT pattern
            global_loc_srv = f"/{ns}/reinitialize_global_localization" if ns else "/reinitialize_global_localization"
            self._global_loc_client = self.create_client(Empty, global_loc_srv)
            cmd_vel_topic = f"/{ns}/cmd_vel" if ns else "/cmd_vel"
            self._cmd_vel_pub = self.create_publisher(Twist, cmd_vel_topic, 10)
            self.executor_core._relocalize_callback = self._do_relocalize

            # Tool command / result pub-sub
            self.sub_cmd = self.create_subscription(
                String, "/tool_cmd", self._on_tool_cmd, 10
            )
            self.pub_result = self.create_publisher(
                String, "/tool_result", 10
            )
            self.pub_reply = self.create_publisher(
                String, "/robot_reply", 10
            )

            # Thread pool: 1 slot for navigation (long-running), 1 for quick queries
            # Ref: prevents unbounded thread creation from rapid tool_cmd messages
            self._thread_pool = ThreadPoolExecutor(max_workers=2)

            self.get_logger().info("Task Executor ready (Phase 1.2: 7 tools)")

        def _on_progress(self, progress: dict):
            """Publish navigation progress to /nav_progress topic."""
            self.pub_progress.publish(String(data=json.dumps(progress)))
            self.get_logger().info(
                "Nav progress: %.1fm to %s (%.0fs elapsed)",
                progress["distance_remaining_m"],
                progress["target"],
                progress["elapsed_s"],
            )

        def _on_amcl(self, msg):
            p = msg.pose.pose
            q = p.orientation
            yaw = math.atan2(
                2 * (q.w * q.z + q.x * q.y),
                1 - 2 * (q.y * q.y + q.z * q.z),
            )
            self.executor_core.update_pose(
                p.position.x, p.position.y, yaw
            )
            # Track covariance for localization health monitoring
            # covariance is a 36-element array (6x6 row-major)
            cov = msg.pose.covariance
            self.executor_core.update_covariance(cov[0], cov[7])

        def _publish_status(self):
            """Publish system health at 1 Hz."""
            status = self.executor_core.get_system_status()
            self.pub_status.publish(String(data=json.dumps(status)))

        def _do_relocalize(self, cancel_check=None) -> dict:
            return do_relocalize(self, cancel_check=cancel_check)

        def _on_tool_cmd(self, msg):
            self._thread_pool.submit(self._execute, msg.data)

        def _execute(self, cmd_json):
            """Execute a tool command and ALWAYS publish /tool_result.

            Ref: ROSA — tools must never return None or raise unhandled exceptions.
                 OpenAI docs — return errors as tool results, not exceptions.
            """
            request_id = ""
            try:
                cmd = json.loads(cmd_json)
                name = cmd.get("tool_name", "")
                inp = cmd.get("tool_input", {})
                request_id = cmd.get("request_id", "")

                result = self.executor_core.execute(name, inp, request_id)

                # If speak, also publish to /robot_reply
                if name == "speak" and "text" in result:
                    self.pub_reply.publish(String(data=result["text"]))

            except json.JSONDecodeError as e:
                logger.error("Invalid tool_cmd JSON: %s", e)
                result = {"error": f"Invalid command JSON: {e}", "request_id": request_id}
            except Exception as e:
                logger.error("Tool execution error: %s", e)
                result = {"error": str(e), "request_id": request_id}

            # ALWAYS publish result — planner is blocked waiting on this
            self.pub_result.publish(String(data=json.dumps(result)))

    return TaskExecutorNode


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
        node._thread_pool.shutdown(wait=False)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
