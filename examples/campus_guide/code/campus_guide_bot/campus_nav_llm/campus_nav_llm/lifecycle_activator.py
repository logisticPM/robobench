"""Persistent lifecycle activator for Nav2 under FastDDS Discovery Server.

Replaces CLI-based `ros2 lifecycle set` with a single persistent DDS
participant. Discovers all lifecycle services once, then transitions nodes
in the correct order — 10-20x faster than the CLI approach.

Why this exists (three stacked problems with CLI approach):
  1. Each `ros2 lifecycle set` spawns a new short-lived DDS participant,
     paying full service discovery cost every time (2-3s × 18 calls)
     Ref: ros2cli #779
  2. FastDDS request/reply topic race silently drops responses from
     short-lived participants ("failed to send response" timeouts)
     Ref: rmw_fastrtps #392
  3. Discovery Server only sends info to matching participants — each
     new CLI participant must re-discover from scratch
     Ref: rmw_fastrtps #499

Activation order (critical for AMCL map delivery):
  Phase 1: Configure all 9 nodes
  Phase 2: Activate map_server (publishes map)
  Phase 3: Activate AMCL (subscribes to /map — must be close in time)
  Phase 4: Reload map via load_map service (transient_local fallback)
  Phase 5: Activate remaining 7 Nav2 nodes

Usage:
    ros2 run campus_nav_llm lifecycle_activator --ros-args \
        -p namespace:=turtlebot468 \
        -p map_yaml:=/path/to/my_map.yaml

Exit code 0 on success, 1 on failure.
"""
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import rclpy
from rclpy.node import Node
from lifecycle_msgs.srv import ChangeState, GetState
from lifecycle_msgs.msg import Transition
from geometry_msgs.msg import PoseWithCovarianceStamped


# Optional: nav2_msgs may not be installed in all environments
try:
    from nav2_msgs.srv import LoadMap
    HAS_LOAD_MAP = True
except ImportError:
    HAS_LOAD_MAP = False


TRANSITION_CONFIGURE = Transition.TRANSITION_CONFIGURE   # 1
TRANSITION_ACTIVATE = Transition.TRANSITION_ACTIVATE     # 3

# ── Structured log for post-mortem troubleshooting ─────────────────────
_LOG_DIR = Path.home() / ".campus_nav_logs"


class _ActivationLog:
    """Append-only JSONL writer for lifecycle activation events."""

    def __init__(self):
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._path = _LOG_DIR / f"lifecycle_{ts}.jsonl"
        self._f = open(self._path, "a", encoding="utf-8")

    def log(self, event: str, **data):
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            **data,
        }
        self._f.write(json.dumps(record, default=str) + "\n")
        self._f.flush()

    def close(self):
        self._f.close()

# All Nav2 lifecycle nodes in desired activation order
LIFECYCLE_NODES = [
    "map_server",
    "amcl",
    "controller_server",
    "smoother_server",
    "planner_server",
    "behavior_server",
    "bt_navigator",
    "waypoint_follower",
    "velocity_smoother",
]


class LifecycleActivator(Node):
    """Single-participant lifecycle activator for Nav2 nodes."""

    def __init__(self):
        super().__init__("lifecycle_activator")

        self.declare_parameter("namespace", "turtlebot468")
        self.declare_parameter("map_yaml", "")
        self.declare_parameter("service_timeout", 15.0)
        self.declare_parameter("discovery_timeout", 90.0)
        self.declare_parameter("initial_pose_x", 0.0)
        self.declare_parameter("initial_pose_y", 0.0)
        self.declare_parameter("initial_pose_yaw", 0.0)

        self.ns = self.get_parameter("namespace").value
        self.map_yaml = self.get_parameter("map_yaml").value
        self.svc_timeout = self.get_parameter("service_timeout").value
        self.disc_timeout = self.get_parameter("discovery_timeout").value
        self.init_x = self.get_parameter("initial_pose_x").value
        self.init_y = self.get_parameter("initial_pose_y").value
        self.init_yaw = self.get_parameter("initial_pose_yaw").value

        # Create ALL service clients up front (one DDS participant, one
        # discovery cost — the whole point of this node)
        self._change = {}
        self._state = {}
        for name in LIFECYCLE_NODES:
            prefix = f"/{self.ns}/{name}" if self.ns else f"/{name}"
            self._change[name] = self.create_client(
                ChangeState, f"{prefix}/change_state"
            )
            self._state[name] = self.create_client(
                GetState, f"{prefix}/get_state"
            )

        # load_map client (for Phase 4)
        self._load_map = None
        if HAS_LOAD_MAP and self.map_yaml:
            srv = f"/{self.ns}/map_server/load_map" if self.ns else "/map_server/load_map"
            self._load_map = self.create_client(LoadMap, srv)

        # Initial pose publisher (Phase 3.5 — after AMCL activation, before Nav2)
        initialpose_topic = f"/{self.ns}/initialpose" if self.ns else "/initialpose"
        self._initialpose_pub = self.create_publisher(
            PoseWithCovarianceStamped, initialpose_topic, 10
        )

        self._log = _ActivationLog()
        self._log.log("init", namespace=self.ns, nodes=LIFECYCLE_NODES,
                       svc_timeout=self.svc_timeout, disc_timeout=self.disc_timeout)
        self.get_logger().info(
            f"Created clients for {len(LIFECYCLE_NODES)} nodes (ns={self.ns})"
        )
        self.get_logger().info(f"Structured log: {self._log._path}")

    # ── Service helpers ──────────────────────────────────────────────

    def _get_state(self, name: str, retries: int = 3) -> str:
        """Get lifecycle state with retries (FastDDS may drop responses)."""
        state_timeout = min(self.svc_timeout, 5.0)
        for attempt in range(retries):
            t0 = time.monotonic()
            future = self._state[name].call_async(GetState.Request())
            rclpy.spin_until_future_complete(self, future, timeout_sec=state_timeout)
            elapsed = round(time.monotonic() - t0, 3)
            if future.result() is not None:
                state = future.result().current_state.label
                self._log.log("get_state", node=name, state=state,
                              elapsed_s=elapsed, attempt=attempt + 1)
                return state
            if attempt < retries - 1:
                self.get_logger().info(
                    f"  {name}: get_state timeout, retrying ({attempt + 1}/{retries})"
                )
                self._log.log("get_state_timeout", node=name,
                              elapsed_s=elapsed, attempt=attempt + 1, max_retries=retries)
                time.sleep(2)
        self._log.log("get_state_failed", node=name, retries=retries)
        return "unknown"

    def _transition(self, name: str, transition_id: int) -> bool:
        """Send a lifecycle transition. Response may be lost under FastDDS."""
        req = ChangeState.Request()
        req.transition.id = transition_id
        future = self._change[name].call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=self.svc_timeout)
        if future.result() is not None:
            return future.result().success
        # Response lost (rmw_fastrtps #392) — doesn't mean it failed.
        # Caller should poll state to verify.
        return False

    def _poll_state(self, name: str, target: str, timeout: float = 30.0) -> bool:
        """Poll get_state until target state is reached or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self._get_state(name, retries=1)
            if state == target:
                return True
            if state == "unknown":
                time.sleep(2)
            else:
                time.sleep(1)
        return False

    # ── Discovery ────────────────────────────────────────────────────

    def wait_for_services(self) -> bool:
        """Block until all lifecycle services are discovered."""
        self.get_logger().info("Discovering lifecycle services...")
        deadline = time.monotonic() + self.disc_timeout
        pending = set(LIFECYCLE_NODES)

        while pending and time.monotonic() < deadline:
            newly_found = set()
            for name in pending:
                if (self._change[name].service_is_ready() and
                        self._state[name].service_is_ready()):
                    self.get_logger().info(f"  {name}: ready")
                    newly_found.add(name)
            pending -= newly_found
            if pending:
                remaining = int(deadline - time.monotonic())
                self.get_logger().info(
                    f"  Waiting for {len(pending)} services... "
                    f"({remaining}s remaining)"
                )
                rclpy.spin_once(self, timeout_sec=2.0)

        if pending:
            self.get_logger().error(
                f"Discovery timeout — missing: {', '.join(sorted(pending))}"
            )
            self._log.log("discovery_failed", missing=sorted(pending),
                          elapsed_s=round(time.monotonic() - (deadline - self.disc_timeout), 1))
            return False

        disc_time = round(time.monotonic() - (deadline - self.disc_timeout), 1)
        self._log.log("discovery_done", elapsed_s=disc_time, nodes=len(LIFECYCLE_NODES))
        self.get_logger().info("All services discovered")
        return True

    # ── Node transitions ─────────────────────────────────────────────

    def configure_node(self, name: str) -> bool:
        """Configure a node (unconfigured -> inactive) with retry + polling.

        FastDDS may drop service responses, so we:
        1. Check current state (with retries for dropped get_state responses)
        2. Send configure transition (response may be lost)
        3. Poll state until "inactive" or timeout (node may take time to configure)
        """
        state = self._get_state(name)
        if state in ("inactive", "active"):
            self.get_logger().info(f"  {name}: skip configure ({state})")
            return True

        # State might be "unknown" (lost response) or "unconfigured"
        # Either way, send configure — it's idempotent if already configuring
        self.get_logger().info(f"  {name}: configuring (was {state})...")
        self._transition(name, TRANSITION_CONFIGURE)
        # Don't trust the response — poll for actual state
        # Nodes like planner_server take several seconds to load costmap plugins
        if self._poll_state(name, "inactive", timeout=30.0):
            self.get_logger().info(f"  {name}: configured")
            return True

        # Final check — maybe it's already active (configured + activated by someone)
        final = self._get_state(name)
        if final in ("inactive", "active"):
            self.get_logger().info(f"  {name}: configured ({final})")
            return True

        self.get_logger().error(f"  {name}: configure FAILED (state={final})")
        self._log.log("configure_failed", node=name, final_state=final)
        return False

    def activate_node(self, name: str) -> bool:
        """Activate a node (inactive -> active) with retry + polling."""
        state = self._get_state(name)
        if state == "active":
            self.get_logger().info(f"  {name}: already active")
            return True

        if state not in ("inactive", "unknown"):
            self.get_logger().error(
                f"  {name}: cannot activate (state={state}, expected inactive)"
            )
            return False

        self.get_logger().info(f"  {name}: activating...")
        self._transition(name, TRANSITION_ACTIVATE)
        if self._poll_state(name, "active", timeout=30.0):
            self.get_logger().info(f"  {name}: active")
            return True

        final = self._get_state(name)
        if final == "active":
            self.get_logger().info(f"  {name}: active")
            return True

        self.get_logger().error(f"  {name}: activate FAILED (state={final})")
        self._log.log("activate_failed", node=name, final_state=final)
        return False

    def reload_map(self) -> bool:
        """Force map republication — transient_local fallback for AMCL."""
        if not self._load_map:
            self.get_logger().info("  Skipping map reload (no map_yaml or nav2_msgs)")
            return True
        if not self._load_map.wait_for_service(timeout_sec=self.svc_timeout):
            self.get_logger().warn("  load_map service not available")
            return False
        req = LoadMap.Request()
        req.map_url = self.map_yaml
        future = self._load_map.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=self.svc_timeout)
        if future.result() is not None and future.result().result == 0:
            self.get_logger().info("  Map reloaded")
            return True
        self.get_logger().warn("  Map reload returned non-zero or timed out")
        return False

    def publish_initial_pose(self) -> None:
        """Publish initial pose to AMCL so it can start publishing map→odom TF.

        Must be called after AMCL is activated and before Nav2 costmap nodes
        are activated, because costmaps block waiting for the map frame.
        Publishes 3 times with 1s gaps to ensure AMCL receives it.
        """
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        # Use stamp=0 so AMCL uses latest available TF instead of a specific time.
        # This avoids "extrapolation into the future/past" errors caused by
        # clock mismatch between laptop (AMCL) and RPi (odom TF source).
        msg.header.stamp.sec = 0
        msg.header.stamp.nanosec = 0
        msg.pose.pose.position.x = self.init_x
        msg.pose.pose.position.y = self.init_y
        msg.pose.pose.orientation.z = math.sin(self.init_yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(self.init_yaw / 2.0)

        self.get_logger().info(
            f"  Publishing initial pose ({self.init_x:.2f}, {self.init_y:.2f}, "
            f"yaw={self.init_yaw:.2f}) — 3 attempts..."
        )
        for i in range(3):
            self._initialpose_pub.publish(msg)
            time.sleep(1)
        self.get_logger().info("  Initial pose published")

    # ── Rollback ──────────────────────────────────────────────────────

    def rollback(self, activated_nodes: list[str]):
        """Deactivate and cleanup nodes in reverse order on failure.

        Ref: Nav2 lifecycle_manager does this via reset(true) — transitions
        all nodes through deactivate → cleanup in reverse bringup order.
        Ref: lifecycle_manager.cpp, Nav2 issue #2752.
        """
        if not activated_nodes:
            return
        self.get_logger().warn(
            f"Rolling back {len(activated_nodes)} nodes (reverse order)..."
        )
        for name in reversed(activated_nodes):
            state = self._get_state(name, retries=1)
            if state == "active":
                self.get_logger().info(f"  {name}: deactivating...")
                self._transition(name, Transition.TRANSITION_DEACTIVATE)
                time.sleep(1)
            state = self._get_state(name, retries=1)
            if state == "inactive":
                self.get_logger().info(f"  {name}: cleaning up...")
                self._transition(name, Transition.TRANSITION_CLEANUP)
                time.sleep(0.5)
        self.get_logger().warn("Rollback complete — nodes returned to unconfigured")

    # ── Main sequence ────────────────────────────────────────────────

    def run(self) -> bool:
        """Execute full activation sequence. Returns True on success."""
        t0 = time.monotonic()

        # Discover services (single DDS participant — pay cost once)
        if not self.wait_for_services():
            return False

        t_disc = time.monotonic() - t0
        self.get_logger().info(f"Discovery took {t_disc:.1f}s")

        # Adaptive DDS settling — instead of hardcoded sleep, probe with
        # a get_state call until it succeeds. This adapts to actual DDS readiness.
        # Ref: rmw_fastrtps #392 — request/reply matching is async after
        #      service_is_ready(); ROS 2 best practice is wait_for_service()
        #      or probe calls, not fixed sleep.
        self.get_logger().info("Probing DDS readiness...")
        probe_node = LIFECYCLE_NODES[0]  # map_server is always first to be ready
        for attempt in range(5):
            state = self._get_state(probe_node, retries=1)
            if state != "unknown":
                self.get_logger().info(
                    f"  DDS ready (probe: {probe_node} = {state}, attempt {attempt + 1})"
                )
                break
            self.get_logger().info(f"  Probe timeout, retrying... ({attempt + 1}/5)")
            time.sleep(2)
        else:
            self.get_logger().warn("  DDS probe did not converge — proceeding anyway")

        # Track activated nodes for rollback on failure
        # Ref: Nav2 lifecycle_manager reset(true) — reverse-order deactivate+cleanup
        activated = []

        # Phase 1: Configure all nodes
        self.get_logger().info("=== Phase 1: Configure all nodes ===")
        failed = [n for n in LIFECYCLE_NODES if not self.configure_node(n)]
        if failed:
            self.get_logger().error(f"Configure failed: {', '.join(failed)}")
            return False

        # Phase 2: Activate map_server (publishes the map)
        self.get_logger().info("=== Phase 2: Activate map_server ===")
        if not self.activate_node("map_server"):
            self.rollback(activated)
            return False
        activated.append("map_server")

        # Phase 3: Activate AMCL right after (subscribes to /map)
        self.get_logger().info("=== Phase 3: Activate AMCL ===")
        if not self.activate_node("amcl"):
            self.rollback(activated)
            return False
        activated.append("amcl")

        # Phase 4: Reload map as transient_local fallback
        self.get_logger().info("=== Phase 4: Reload map ===")
        self.reload_map()

        # Phase 4.5: Set initial pose BEFORE activating Nav2 nodes
        # AMCL needs initial pose to publish map→odom TF.
        # Without this TF, costmap nodes block during activation waiting
        # for the map frame, causing a 30s+ timeout per node.
        self.get_logger().info("=== Phase 4.5: Set initial pose ===")
        self.publish_initial_pose()
        # Give AMCL time to process and start publishing TF
        time.sleep(2)

        # Phase 5: Activate remaining Nav2 nodes
        self.get_logger().info("=== Phase 5: Activate Nav2 stack ===")
        nav2 = [n for n in LIFECYCLE_NODES if n not in ("map_server", "amcl")]
        failed = []
        for n in nav2:
            if self.activate_node(n):
                activated.append(n)
            else:
                failed.append(n)

        elapsed = time.monotonic() - t0
        if failed:
            self.get_logger().error(
                f"FAILED: {', '.join(failed)} ({elapsed:.1f}s total)"
            )
            self._log.log("run_failed", failed=failed, activated=activated,
                          elapsed_s=round(elapsed, 1), discovery_s=round(t_disc, 1))
            self.rollback(activated)
            return False

        self.get_logger().info(
            f"=== All {len(LIFECYCLE_NODES)} nodes active "
            f"({elapsed:.1f}s total, discovery={t_disc:.1f}s) ==="
        )
        self._log.log("run_success", activated=activated,
                      elapsed_s=round(elapsed, 1), discovery_s=round(t_disc, 1))
        return True


def main():
    rclpy.init()
    node = LifecycleActivator()
    try:
        success = node.run()
    except KeyboardInterrupt:
        node._log.log("interrupted", reason="KeyboardInterrupt")
        success = False
    except Exception as e:
        node._log.log("crash", error=str(e))
        success = False
    finally:
        node._log.close()
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass  # Avoid double-shutdown crash (ExternalShutdownException)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
