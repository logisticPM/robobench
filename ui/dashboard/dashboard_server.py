"""TurtleBot Dashboard — real-time map, LLM chat, and system status.

Serves a web UI that shows the robot on the map, lets you send commands,
and displays system health. Bridges to ROS 2 via subscriptions.

Usage:
    python dashboard_server.py              # Demo mode (no ROS)
    python dashboard_server.py --ros        # Real mode with ROS 2
"""
import argparse
import asyncio
import json
import logging
import math
import os
import signal
import shlex
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger("dashboard")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

# ── Map metadata (from my_map.yaml) ──
MAP_RESOLUTION = 0.05  # meters per pixel
MAP_ORIGIN_X = -8.1
MAP_ORIGIN_Y = -8.64
MAP_WIDTH = 349   # pixels
MAP_HEIGHT = 406  # pixels

# ── Semantic map (loaded at startup) ──
SEMANTIC_MAP = {}

# ── Global state ──
_main_loop = None
_broadcast_queue = None
_active_ws: set[WebSocket] = set()
_ws_lock = None
_ros_node = None

# Robot state (updated by ROS or demo)
_robot_state = {
    "x": 0.0, "y": 0.0, "theta": 0.0,
    "covariance_xy": 0.0,
    "system_status": "unknown",
    "nav_active": False,
    "issues": [],
}
_state_lock = threading.Lock()


def load_semantic_map():
    """Load semantic_map.json for location markers."""
    global SEMANTIC_MAP
    candidates = [
        Path(__file__).parent.parent / "campus_guide_bot" / "campus_nav_llm" / "semantic" / "semantic_map.json",
        Path(__file__).parent / "semantic_map.json",
    ]
    for p in candidates:
        if p.exists():
            with open(p) as f:
                data = json.load(f)
            SEMANTIC_MAP = data.get("locations", {})
            logger.info("Loaded %d locations from %s", len(SEMANTIC_MAP), p)
            return
    logger.warning("semantic_map.json not found")


def world_to_pixel(x: float, y: float) -> tuple[int, int]:
    """Convert world coordinates (meters) to map pixel coordinates."""
    px = int((x - MAP_ORIGIN_X) / MAP_RESOLUTION)
    py = int(MAP_HEIGHT - (y - MAP_ORIGIN_Y) / MAP_RESOLUTION)
    return px, py


# ── ROS 2 Bridge ──

ROS_AVAILABLE = False
try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    from geometry_msgs.msg import PoseWithCovarianceStamped
    ROS_AVAILABLE = True
except ImportError:
    pass


class DashboardBridgeNode:
    """ROS 2 node that subscribes to robot topics and pushes to WebSocket."""

    def __init__(self, ns="turtlebot468"):
        self.node = rclpy.create_node("dashboard_bridge")
        self.ns = ns

        # Subscriptions
        amcl_topic = f"/{ns}/amcl_pose" if ns else "/amcl_pose"
        self.node.create_subscription(PoseWithCovarianceStamped, amcl_topic, self._on_amcl, 10)
        self.node.create_subscription(String, "/robot_reply", self._on_reply, 10)
        self.node.create_subscription(String, "/tool_result", self._on_tool_result, 10)
        self.node.create_subscription(String, "/tool_cmd", self._on_tool_cmd, 10)
        self.node.create_subscription(String, "/system_status", self._on_system_status, 10)
        self.node.create_subscription(String, "/nav_progress", self._on_nav_progress, 10)

        # Battery state subscription
        try:
            from sensor_msgs.msg import BatteryState
            battery_topic = f"/{ns}/battery_state" if ns else "/battery_state"
            self.node.create_subscription(BatteryState, battery_topic, self._on_battery, 10)
        except ImportError:
            logger.warning("sensor_msgs not available — battery status disabled")

        # Topic health tracking (updated by callbacks)
        self._topic_health = {"amcl": 0.0, "battery": 0.0}

        # Publishers
        self.pub_input = self.node.create_publisher(String, "/user_input", 10)
        initialpose_topic = f"/{ns}/initialpose" if ns else "/initialpose"
        self.pub_initialpose = self.node.create_publisher(
            PoseWithCovarianceStamped, initialpose_topic, 10)

        # Topic health timer (1 Hz) — checks which topics are alive
        self.node.create_timer(2.0, self._publish_topic_health)

        logger.info("ROS bridge ready (namespace: %s)", ns)

    def publish_command(self, text: str):
        self.pub_input.publish(String(data=text))
        logger.info("Published to /user_input: %s", text[:80])

    def _on_amcl(self, msg):
        p = msg.pose.pose
        q = p.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        cov = msg.pose.covariance
        cov_xy = cov[0] + cov[7]

        self._topic_health["amcl"] = time.time()
        with _state_lock:
            _robot_state["x"] = round(p.position.x, 3)
            _robot_state["y"] = round(p.position.y, 3)
            _robot_state["theta"] = round(yaw, 3)
            _robot_state["covariance_xy"] = round(cov_xy, 4)
            _robot_state["_amcl_ts"] = time.time()

        px, py = world_to_pixel(p.position.x, p.position.y)
        _enqueue({"type": "pose", "x": p.position.x, "y": p.position.y,
                   "theta": yaw, "px": px, "py": py, "cov": round(cov_xy, 4)})

    def _on_reply(self, msg):
        _enqueue({"type": "robot_reply", "text": msg.data})

    def _on_tool_result(self, msg):
        try:
            data = json.loads(msg.data)
            _enqueue({"type": "tool_result", "data": data})
        except json.JSONDecodeError:
            pass

    def _on_tool_cmd(self, msg):
        try:
            data = json.loads(msg.data)
            _enqueue({"type": "tool_cmd", "tool": data.get("tool_name", ""),
                       "input": data.get("tool_input", {})})
        except json.JSONDecodeError:
            pass

    def _on_system_status(self, msg):
        try:
            data = json.loads(msg.data)
            with _state_lock:
                _robot_state["system_status"] = data.get("status", "unknown")
                _robot_state["nav_active"] = data.get("navigation_active", False)
                _robot_state["issues"] = data.get("issues", [])
            _robot_state["_sys_ts"] = time.time()
            _enqueue({"type": "system_status", "data": data})
        except json.JSONDecodeError:
            pass

    def _on_nav_progress(self, msg):
        try:
            data = json.loads(msg.data)
            _enqueue({"type": "nav_progress", "data": data})
        except json.JSONDecodeError:
            pass

    def _on_battery(self, msg):
        pct = round(msg.percentage * 100) if msg.percentage <= 1.0 else round(msg.percentage)
        voltage = round(msg.voltage, 1)
        self._topic_health["battery"] = time.time()
        with _state_lock:
            _robot_state["battery_pct"] = pct
            _robot_state["battery_voltage"] = voltage
        _enqueue({"type": "battery", "pct": pct, "voltage": voltage})

    def _publish_topic_health(self):
        """Publish which topics are alive based on recent callback timestamps."""
        now = time.time()
        self._topic_health["amcl"] = _robot_state.get("_amcl_ts", 0.0)
        # system_status comes from llm_planner at 1Hz
        sys_ts = _robot_state.get("_sys_ts", 0.0)
        health = {
            "amcl": now - self._topic_health["amcl"] < 5.0 if self._topic_health["amcl"] else False,
            "battery": now - self._topic_health["battery"] < 10.0 if self._topic_health["battery"] else False,
            "system_status": now - sys_ts < 5.0 if sys_ts else False,
        }
        _enqueue({"type": "topic_health", "data": health})


def _enqueue(msg: dict):
    """Thread-safe enqueue for broadcast."""
    if _main_loop and _broadcast_queue:
        asyncio.run_coroutine_threadsafe(_broadcast_queue.put(msg), _main_loop)


def _publish_initial_pose(x: float, y: float, theta: float):
    """Publish initial pose via the ROS bridge node."""
    if not _ros_node:
        return
    try:
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.orientation.z = math.sin(theta / 2)
        msg.pose.pose.orientation.w = math.cos(theta / 2)
        _ros_node.pub_initialpose.publish(msg)
        _enqueue({"type": "system", "text": f"Initial pose set: ({x:.2f}, {y:.2f}, \u03b8={theta:.2f})"})
        logger.info("Published initial pose: (%.2f, %.2f, %.2f)", x, y, theta)
    except Exception as e:
        _enqueue({"type": "system", "text": f"Failed to set pose: {e}"})
        logger.error("Failed to publish initial pose: %s", e)


def _ros_spin_thread():
    global _ros_node
    try:
        rclpy.init()
        _ros_node = DashboardBridgeNode()
        rclpy.spin(_ros_node.node)
    except Exception as e:
        logger.error("ROS spin error: %s", e)
    finally:
        if _ros_node:
            _ros_node.node.destroy_node()
        rclpy.try_shutdown()


# ── Demo mode ──

_demo_task = None

async def _demo_pose_loop():
    """Simulate robot moving between locations in demo mode."""
    locations = list(SEMANTIC_MAP.values())
    if not locations:
        return
    idx = 0
    while True:
        loc = locations[idx % len(locations)]
        x, y = loc["x"], loc["y"]
        theta = math.radians(loc.get("facing_deg", 0))
        px, py = world_to_pixel(x, y)
        await _broadcast_queue.put({
            "type": "pose", "x": x, "y": y, "theta": theta,
            "px": px, "py": py, "cov": 0.05,
        })
        await _broadcast_queue.put({
            "type": "system_status",
            "data": {"status": "ok", "localization": {"healthy": True, "covariance_xy": 0.05},
                     "navigation_active": False, "navigator_ready": True, "issues": []},
        })
        await asyncio.sleep(5)
        idx += 1


async def _demo_handle_command(text: str):
    """Simulate robot response in demo mode."""
    await _broadcast_queue.put({"type": "command_sent", "text": text, "channel": "DEMO"})
    await asyncio.sleep(1.0)
    await _broadcast_queue.put({"type": "robot_reply", "text": f"[DEMO] Processing: {text}"})
    await asyncio.sleep(2.0)
    await _broadcast_queue.put({"type": "robot_reply", "text": f"[DEMO] Done."})


# ── Pre-flight Checks ──
# Runs a series of checks before deployment to catch common issues.

def _run_preflight_checks() -> list[dict]:
    """Run all pre-deployment checks and return structured results."""
    checks = []
    robot_ip = DEPLOY_CONFIG["robot_ip"]
    robot_user = DEPLOY_CONFIG["robot_user"]
    robot_pass = DEPLOY_CONFIG["robot_pass"]
    ns = DEPLOY_CONFIG["robot_ns"]

    def _ssh_cmd(remote_cmd: str, timeout: int = 10) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["sshpass", "-p", robot_pass,
             "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
             f"{robot_user}@{robot_ip}", remote_cmd],
            capture_output=True, text=True, timeout=timeout,
        )

    # 1. Ping RPi
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "2", robot_ip],
                           capture_output=True, timeout=5)
        if r.returncode == 0:
            checks.append({"id": "rpi_ping", "name": "RPi Reachable",
                           "status": "pass", "detail": f"{robot_ip} responded"})
        else:
            checks.append({"id": "rpi_ping", "name": "RPi Reachable",
                           "status": "fail", "detail": f"{robot_ip} unreachable",
                           "critical": True})
            # If RPi is unreachable, skip all SSH-dependent checks
            checks.append({"id": "clock_sync", "name": "Clock Sync",
                           "status": "skip", "detail": "Skipped — RPi unreachable"})
            checks.append({"id": "discovery_server", "name": "Discovery Server",
                           "status": "skip", "detail": "Skipped — RPi unreachable"})
            checks.append({"id": "odom_topic", "name": "Odom Publishing",
                           "status": "skip", "detail": "Skipped — RPi unreachable"})
            checks.append({"id": "ros2_daemon", "name": "ROS2 Daemon",
                           "status": "skip", "detail": "Skipped — RPi unreachable"})
            return checks
    except Exception as e:
        checks.append({"id": "rpi_ping", "name": "RPi Reachable",
                       "status": "fail", "detail": str(e), "critical": True})
        return checks

    # 2. Clock drift check + chrony sync
    try:
        r = _ssh_cmd("date +%s")
        if r.returncode == 0:
            robot_time = int(r.stdout.strip())
            local_time = int(time.time())
            drift = abs(local_time - robot_time)
            if drift > 2:
                # Attempt chrony makestep
                sync_r = _ssh_cmd("sudo chronyc -a makestep", timeout=10)
                # Re-check drift
                r2 = _ssh_cmd("date +%s")
                if r2.returncode == 0:
                    new_drift = abs(int(time.time()) - int(r2.stdout.strip()))
                    if new_drift <= 2:
                        checks.append({"id": "clock_sync", "name": "Clock Sync",
                                       "status": "pass",
                                       "detail": f"Fixed: {drift}s → {new_drift}s after chrony makestep"})
                    else:
                        checks.append({"id": "clock_sync", "name": "Clock Sync",
                                       "status": "warn",
                                       "detail": f"Drift {new_drift}s after sync (was {drift}s). AMCL may stall.",
                                       "critical": True})
                else:
                    checks.append({"id": "clock_sync", "name": "Clock Sync",
                                   "status": "warn",
                                   "detail": f"Drift was {drift}s, sync attempted but couldn't verify"})
            else:
                checks.append({"id": "clock_sync", "name": "Clock Sync",
                               "status": "pass", "detail": f"Drift {drift}s (OK)"})
        else:
            checks.append({"id": "clock_sync", "name": "Clock Sync",
                           "status": "warn", "detail": "SSH succeeded but date command failed"})
    except subprocess.TimeoutExpired:
        checks.append({"id": "clock_sync", "name": "Clock Sync",
                       "status": "warn", "detail": "SSH timeout checking clock"})
    except Exception as e:
        checks.append({"id": "clock_sync", "name": "Clock Sync",
                       "status": "warn", "detail": str(e)})

    # 3. Discovery Server running on RPi — verify port is actually listening
    try:
        r = _ssh_cmd("ss -ulnp | grep 11811 | wc -l")
        port_listening = r.returncode == 0 and int(r.stdout.strip()) > 0
        r2 = _ssh_cmd("ps aux | grep fast-discovery | grep -v grep | wc -l")
        proc_running = r2.returncode == 0 and int(r2.stdout.strip()) > 0

        if port_listening:
            checks.append({"id": "discovery_server", "name": "Discovery Server",
                           "status": "pass", "detail": "Listening on port 11811",
                           "fix": None})
        elif proc_running:
            checks.append({"id": "discovery_server", "name": "Discovery Server",
                           "status": "fail",
                           "detail": "Process exists but port 11811 NOT listening (zombie) — restart needed",
                           "critical": True, "fix": "restart_discovery"})
        else:
            checks.append({"id": "discovery_server", "name": "Discovery Server",
                           "status": "fail", "detail": "NOT running on RPi",
                           "critical": True, "fix": "restart_discovery"})
    except Exception as e:
        checks.append({"id": "discovery_server", "name": "Discovery Server",
                       "status": "warn", "detail": str(e), "fix": "restart_discovery"})

    # 4. Odom topic publishing — diagnose root cause before picking fix
    # NOTE: /etc/turtlebot4/setup.bash sets ROS_SUPER_CLIENT=False when stdin
    # is not a terminal (i.e. over sshpass/SSH). Must override to True so
    # ros2 commands can discover topics via the Discovery Server.
    _ros_prefix = (
        f"source /etc/turtlebot4/setup.bash && "
        f"export ROS_SUPER_CLIENT=True && "
    )
    try:
        r = _ssh_cmd(
            f"{_ros_prefix}timeout 15 ros2 topic echo /{ns}/odom --once 2>&1 | head -5",
            timeout=25,
        )
        output = (r.stdout + r.stderr).strip()
        if "header" in output or "position" in output or "pose" in output:
            checks.append({"id": "odom_topic", "name": "Odom Publishing",
                           "status": "pass", "detail": f"/{ns}/odom is active",
                           "fix": None})
        else:
            # Odom is dead — diagnose WHY to pick the right fix
            diag_fix, diag_detail = _diagnose_odom_failure(
                _ssh_cmd, _ros_prefix, ns, output
            )
            checks.append({"id": "odom_topic", "name": "Odom Publishing",
                           "status": "fail", "detail": diag_detail,
                           "critical": True, "fix": diag_fix})
    except subprocess.TimeoutExpired:
        # Timeout — still diagnose
        diag_fix, diag_detail = _diagnose_odom_failure(
            _ssh_cmd, _ros_prefix, ns, "odom echo timed out"
        )
        checks.append({"id": "odom_topic", "name": "Odom Publishing",
                       "status": "fail", "detail": diag_detail,
                       "critical": True, "fix": diag_fix})
    except Exception as e:
        checks.append({"id": "odom_topic", "name": "Odom Publishing",
                       "status": "warn", "detail": str(e), "fix": "restart_create3_app"})

    # 5. ROS2 daemon + topic visibility (local)
    try:
        subprocess.run(["ros2", "daemon", "stop"], capture_output=True, timeout=10)
        time.sleep(1)
        subprocess.run(["ros2", "daemon", "start"], capture_output=True, timeout=10)
        time.sleep(2)
        env = {**os.environ,
               "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
               "ROS_DISCOVERY_SERVER": f"{robot_ip}:{DEPLOY_CONFIG['discovery_port']}",
               "ROS_SUPER_CLIENT": "True"}
        r = subprocess.run(["ros2", "topic", "list"],
                           capture_output=True, text=True, timeout=10, env=env)
        topics = [l for l in r.stdout.strip().split("\n") if l.strip()]
        topic_count = len(topics)
        if topic_count > 5:
            checks.append({"id": "ros2_daemon", "name": "ROS2 Daemon",
                           "status": "pass",
                           "detail": f"Restarted — {topic_count} topics visible"})
        elif topic_count > 0:
            checks.append({"id": "ros2_daemon", "name": "ROS2 Daemon",
                           "status": "warn",
                           "detail": f"Only {topic_count} topics visible (expected >5)"})
        else:
            checks.append({"id": "ros2_daemon", "name": "ROS2 Daemon",
                           "status": "warn",
                           "detail": "0 topics — Discovery Server may be down"})
    except Exception as e:
        checks.append({"id": "ros2_daemon", "name": "ROS2 Daemon",
                       "status": "warn", "detail": str(e)})

    return checks


# ── Deploy Engine ──
# Runs deploy.sh steps as subprocess, streams output to WebSocket.

_deploy_lock = threading.Lock()
_deploy_running = False
_deploy_process: subprocess.Popen | None = None

DEPLOY_SCRIPT = Path(__file__).parent.parent / "deploy.sh"
CONFIG_FILE = Path(__file__).parent.parent / "config.yaml"
APIKEY_FILE = Path(__file__).parent / ".openrouter_key"  # gitignored

# Load shared config (single source of truth)
DEPLOY_CONFIG = {
    "robot_ip": "192.168.50.31",
    "robot_user": "ubuntu",
    "robot_pass": "turtlebot4",
    "robot_ns": "turtlebot468",
    "ws_dir": os.path.expanduser("~/CS5335TurtleBot"),
    "discovery_port": "11811",
}

def _load_config():
    """Load config.yaml — shared with deploy.sh."""
    if not CONFIG_FILE.exists():
        logger.warning("config.yaml not found, using defaults")
        return
    try:
        import yaml
        with open(CONFIG_FILE) as f:
            cfg = yaml.safe_load(f)
        r = cfg.get("robot", {})
        d = cfg.get("dds", {})
        w = cfg.get("workspace", {})
        DEPLOY_CONFIG["robot_ip"] = r.get("ip", DEPLOY_CONFIG["robot_ip"])
        DEPLOY_CONFIG["robot_user"] = r.get("ssh_user", DEPLOY_CONFIG["robot_user"])
        DEPLOY_CONFIG["robot_pass"] = r.get("ssh_pass", DEPLOY_CONFIG["robot_pass"])
        DEPLOY_CONFIG["robot_ns"] = r.get("namespace", DEPLOY_CONFIG["robot_ns"])
        DEPLOY_CONFIG["discovery_port"] = str(d.get("discovery_port", DEPLOY_CONFIG["discovery_port"]))
        DEPLOY_CONFIG["ws_dir"] = os.path.expanduser(w.get("dir", DEPLOY_CONFIG["ws_dir"]))
        logger.info("Loaded config from %s", CONFIG_FILE)
    except ImportError:
        logger.warning("PyYAML not installed, using default config")
    except Exception as e:
        logger.warning("Failed to load config.yaml: %s", e)


def _deploy_log(level: str, text: str, step: str = ""):
    """Send deploy log line to all WebSocket clients."""
    _enqueue({
        "type": "deploy_log",
        "level": level,   # info, warn, error, step, done
        "text": text,
        "step": step,
    })


def _run_deploy(pose: str = "front_door", skip_build: bool = False, skip_clock: bool = False):
    """Run deploy.sh in a subprocess, streaming output via WebSocket."""
    global _deploy_running, _deploy_process

    with _deploy_lock:
        if _deploy_running:
            _deploy_log("warn", "Deploy already in progress")
            return
        _deploy_running = True

    _deploy_log("step", "Starting deployment...", "init")

    try:
        # Build command
        cmd = ["bash", str(DEPLOY_SCRIPT), "--pose", pose]
        if skip_build:
            cmd.append("--skip-build")
        if skip_clock:
            cmd.append("--skip-clock")

        # Set environment for the subprocess
        env = os.environ.copy()
        env["RMW_IMPLEMENTATION"] = "rmw_fastrtps_cpp"
        env["ROS_DISCOVERY_SERVER"] = f"{DEPLOY_CONFIG['robot_ip']}:{DEPLOY_CONFIG['discovery_port']}"
        env["ROS_SUPER_CLIENT"] = "True"

        # Pass saved OpenRouter API key if available
        if APIKEY_FILE.exists():
            saved_key = APIKEY_FILE.read_text().strip()
            if saved_key:
                env["OPENROUTER_API_KEY"] = saved_key

        _deploy_log("info", f"Command: {' '.join(cmd)}")

        _deploy_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            start_new_session=True,  # create process group so we can kill all children
        )

        # Stream output line by line
        for line in _deploy_process.stdout:
            line = line.rstrip()
            if not line:
                continue

            # Parse log level from deploy.sh output
            if "[ERROR]" in line:
                level = "error"
            elif "[WARN]" in line:
                level = "warn"
            elif "━━━ Step" in line:
                level = "step"
                # Extract step name
                step_match = line.split("Step ")[-1] if "Step " in line else ""
                _deploy_log(level, line, step_match)
                continue
            elif "[DEPLOY]" in line:
                level = "info"
            else:
                level = "info"

            _deploy_log(level, line)

        proc = _deploy_process
        if proc is not None:
            proc.wait()
            rc = proc.returncode
            if rc == 0:
                _deploy_log("done", "Deployment completed successfully")
            elif rc == -15 or rc == -9:
                # SIGTERM (-15) or SIGKILL (-9) from stop button
                _deploy_log("done", "Deployment stopped by user")
            else:
                _deploy_log("error", f"Deployment failed (exit code {rc})")
        else:
            # Process was killed by _stop_deploy which already logged
            pass

    except FileNotFoundError:
        _deploy_log("error", f"deploy.sh not found at {DEPLOY_SCRIPT}")
    except Exception as e:
        _deploy_log("error", f"Deploy error: {e}")
    finally:
        _deploy_process = None
        with _deploy_lock:
            _deploy_running = False


def _stop_deploy():
    """Kill running deploy process and all its children (ros2 launch, etc.)."""
    global _deploy_process, _deploy_running
    proc = _deploy_process
    if proc and proc.poll() is None:
        try:
            # SIGKILL the entire process group immediately — SIGTERM is unreliable
            # because ros2 launch/run may spawn children in sub-groups that ignore it
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            pass
        # Fallback: kill any orphaned processes that escaped the process group
        for pattern in ["deploy.sh", "lifecycle_activator", "navigation_mode.launch"]:
            subprocess.run(
                ["pkill", "-9", "-f", pattern],
                capture_output=True, timeout=3,
            )
        _deploy_log("done", "Deploy process and children terminated")
    else:
        _deploy_log("done", "No deploy process running")
    # Force-reset state so the next deploy isn't blocked
    _deploy_process = None
    with _deploy_lock:
        _deploy_running = False


# ── FastAPI app ──

USE_ROS = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _main_loop, _broadcast_queue, _ws_lock, _demo_task
    _main_loop = asyncio.get_event_loop()
    _broadcast_queue = asyncio.Queue()
    _ws_lock = asyncio.Lock()

    _load_config()
    load_semantic_map()

    broadcast_task = asyncio.create_task(_broadcaster())

    if USE_ROS and ROS_AVAILABLE:
        threading.Thread(target=_ros_spin_thread, daemon=True).start()
        logger.info("ROS 2 bridge started")
    else:
        _demo_task = asyncio.create_task(_demo_pose_loop())
        logger.info("Running in DEMO mode (no ROS 2)")

    yield

    broadcast_task.cancel()
    if _demo_task:
        _demo_task.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


async def _broadcaster():
    """Fan out queued messages to all connected WebSocket clients."""
    while True:
        msg = await _broadcast_queue.get()
        payload = json.dumps(msg)
        async with _ws_lock:
            dead = []
            for ws in _active_ws:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                _active_ws.discard(ws)


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/map-info")
async def map_info():
    """Return map metadata and semantic locations for the frontend."""
    locations = {}
    for name, loc in SEMANTIC_MAP.items():
        px, py = world_to_pixel(loc["x"], loc["y"])
        locations[name] = {
            "x": loc["x"], "y": loc["y"],
            "px": px, "py": py,
            "facing_deg": loc.get("facing_deg", 0),
            "description": loc.get("description", ""),
            "aliases": loc.get("aliases", []),
        }
    return JSONResponse({
        "map": {
            "width": MAP_WIDTH, "height": MAP_HEIGHT,
            "resolution": MAP_RESOLUTION,
            "origin_x": MAP_ORIGIN_X, "origin_y": MAP_ORIGIN_Y,
        },
        "locations": locations,
        "ros_connected": USE_ROS and ROS_AVAILABLE,
    })


def _validate_location(x: float, y: float) -> dict:
    """Check if a coordinate is reachable: not on wall, not too close to obstacles.

    Returns {"ok": True, "clearance": float} or {"ok": False, "reason": str, "suggestion": {...}}.
    """
    map_pgm = Path(__file__).parent.parent / "campus_guide_bot" / "campus_nav_llm" / "maps" / "my_map.pgm"
    if not map_pgm.exists():
        return {"ok": True, "clearance": -1, "warning": "Map file not found, skipping validation"}

    try:
        import numpy as np
        from PIL import Image

        arr = np.array(Image.open(map_pgm))
        h, w = arr.shape
        robot_radius = 0.175
        safety_margin = 0.05
        min_clearance = robot_radius + safety_margin

        px = int((x - MAP_ORIGIN_X) / MAP_RESOLUTION)
        py = int(h - 1 - (y - MAP_ORIGIN_Y) / MAP_RESOLUTION)

        if not (0 <= px < w and 0 <= py < h):
            return {"ok": False, "reason": "Out of map bounds"}

        pixel_val = arr[py, px]
        if pixel_val == 0:
            reason = "On a wall (pixel=0)"
        elif pixel_val == 205:
            reason = "In unknown area (pixel=205)"
        else:
            # Check clearance from nearest obstacle
            search_r = 20
            min_dist = float("inf")
            for dy in range(-search_r, search_r + 1):
                for dx in range(-search_r, search_r + 1):
                    ny, nx = py + dy, px + dx
                    if 0 <= ny < h and 0 <= nx < w and arr[ny, nx] == 0:
                        d = ((dx * MAP_RESOLUTION) ** 2 + (dy * MAP_RESOLUTION) ** 2) ** 0.5
                        if d < min_dist:
                            min_dist = d
            if min_dist < min_clearance:
                reason = f"Too close to obstacle ({min_dist:.3f}m < {min_clearance:.3f}m required)"
            else:
                return {"ok": True, "clearance": round(min_dist, 3)}

        # Find nearest safe point
        best_dist = float("inf")
        best_wx, best_wy = None, None
        search_r = 30
        for dy in range(-search_r, search_r + 1):
            for dx in range(-search_r, search_r + 1):
                ny, nx = py + dy, px + dx
                if not (0 <= ny < h and 0 <= nx < w and arr[ny, nx] == 254):
                    continue
                # Check clearance at this candidate
                cdist = float("inf")
                for ddy in range(-20, 21):
                    for ddx in range(-20, 21):
                        nny, nnx = ny + ddy, nx + ddx
                        if 0 <= nny < h and 0 <= nnx < w and arr[nny, nnx] == 0:
                            d = ((ddx * MAP_RESOLUTION) ** 2 + (ddy * MAP_RESOLUTION) ** 2) ** 0.5
                            if d < cdist:
                                cdist = d
                if cdist >= min_clearance:
                    pixel_dist = (dx ** 2 + dy ** 2) ** 0.5
                    if pixel_dist < best_dist:
                        best_dist = pixel_dist
                        best_wx = nx * MAP_RESOLUTION + MAP_ORIGIN_X
                        best_wy = (h - 1 - ny) * MAP_RESOLUTION + MAP_ORIGIN_Y

        result = {"ok": False, "reason": reason}
        if best_wx is not None:
            result["suggestion"] = {"x": round(best_wx, 3), "y": round(best_wy, 3)}
        return result
    except ImportError:
        return {"ok": True, "clearance": -1, "warning": "numpy/PIL not installed, skipping validation"}
    except Exception as e:
        logger.warning("Location validation error: %s", e)
        return {"ok": True, "clearance": -1, "warning": str(e)}


@app.post("/api/locations")
async def add_location(request: Request):
    """Add a new location to semantic_map.json and config.yaml."""
    data = await request.json()
    name = data.get("name", "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "Name is required"})

    x = float(data.get("x", 0))
    y = float(data.get("y", 0))
    facing_deg = float(data.get("facing_deg", 0))
    description = data.get("description", "")
    aliases = data.get("aliases", [])
    area = data.get("area", "")

    # Find semantic_map.json
    sem_path = Path(__file__).parent.parent / "campus_guide_bot" / "campus_nav_llm" / "semantic" / "semantic_map.json"
    if not sem_path.exists():
        return JSONResponse({"ok": False, "error": f"semantic_map.json not found at {sem_path}"})

    try:
        with open(sem_path) as f:
            sem_data = json.load(f)

        if name in sem_data.get("locations", {}):
            return JSONResponse({"ok": False, "error": f"Location '{name}' already exists"})

        # Validate position is reachable
        validation = _validate_location(x, y)
        if not validation["ok"]:
            resp = {"ok": False, "error": f"Invalid position: {validation['reason']}"}
            if "suggestion" in validation:
                resp["suggestion"] = validation["suggestion"]
                resp["error"] += f" — suggested: ({validation['suggestion']['x']:.3f}, {validation['suggestion']['y']:.3f})"
            return JSONResponse(resp)

        # Add to semantic_map.json
        sem_data["locations"][name] = {
            "x": round(x, 3),
            "y": round(y, 3),
            "facing_deg": facing_deg,
            "description": description,
            "aliases": aliases,
            "area": area,
        }
        _save_semantic_and_config(sem_path, sem_data)

        # Update in-memory state
        SEMANTIC_MAP[name] = sem_data["locations"][name]
        logger.info("Added location '%s' at (%.3f, %.3f)", name, x, y)

        return JSONResponse({"ok": True, "message": f"Location '{name}' saved"})
    except Exception as e:
        logger.error("Failed to save location: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


def _save_semantic_and_config(sem_path, sem_data):
    """Write semantic_map.json (source + install copy) and update config.yaml."""
    import math
    with open(sem_path, "w") as f:
        json.dump(sem_data, f, indent=2)
        f.write("\n")
    # Install copy
    install_copy = Path(__file__).parent.parent / "install" / "campus_nav_llm" / "share" / "campus_nav_llm" / "semantic" / "semantic_map.json"
    if install_copy.exists():
        with open(install_copy, "w") as f:
            json.dump(sem_data, f, indent=2)
            f.write("\n")
    # Sync config.yaml known_poses
    if CONFIG_FILE.exists():
        try:
            import yaml
            with open(CONFIG_FILE) as f:
                cfg = yaml.safe_load(f)
            if "known_poses" not in cfg:
                cfg["known_poses"] = {}
            # Rebuild known_poses from semantic_map locations
            # Use underscored keys to match deploy.sh bash associative array
            new_poses = {}
            for name, loc in sem_data.get("locations", {}).items():
                key = name.replace(" ", "_")
                theta = math.radians(loc.get("facing_deg", 0))
                if theta > math.pi:
                    theta -= 2 * math.pi
                new_poses[key] = {
                    "x": round(loc["x"], 2),
                    "y": round(loc["y"], 2),
                    "theta": round(theta, 2),
                }
            cfg["known_poses"] = new_poses
            # Write config.yaml preserving inline flow style for poses
            # to match the original format deploy.sh expects
            lines = []
            for section in ("robot", "dds", "workspace"):
                if section in cfg:
                    lines.append(f"{section}:")
                    for k, v in cfg[section].items():
                        val = f'"{v}"' if isinstance(v, str) else v
                        lines.append(f"  {k}: {val}")
            lines.append("")
            lines.append("known_poses:")
            for pose_name, pose in cfg["known_poses"].items():
                lines.append(f"  {pose_name}:     {{ x: {pose['x']},  y: {pose['y']},  theta: {pose['theta']} }}")
            lines.append("")
            with open(CONFIG_FILE, "w") as f:
                f.write("\n".join(lines))
        except Exception as e:
            logger.warning("Could not update config.yaml: %s", e)


@app.put("/api/locations/{name}")
async def update_location(name: str, request: Request):
    """Update an existing location in semantic_map.json and config.yaml."""
    data = await request.json()
    sem_path = Path(__file__).parent.parent / "campus_guide_bot" / "campus_nav_llm" / "semantic" / "semantic_map.json"
    if not sem_path.exists():
        return JSONResponse({"ok": False, "error": "semantic_map.json not found"})
    try:
        with open(sem_path) as f:
            sem_data = json.load(f)
        if name not in sem_data.get("locations", {}):
            return JSONResponse({"ok": False, "error": f"Location '{name}' not found"})

        loc = sem_data["locations"][name]
        new_x = round(float(data.get("x", loc["x"])), 3)
        new_y = round(float(data.get("y", loc["y"])), 3)

        # Validate if coordinates changed
        if new_x != loc["x"] or new_y != loc["y"]:
            validation = _validate_location(new_x, new_y)
            if not validation["ok"]:
                resp = {"ok": False, "error": f"Invalid position: {validation['reason']}"}
                if "suggestion" in validation:
                    resp["suggestion"] = validation["suggestion"]
                    resp["error"] += f" — suggested: ({validation['suggestion']['x']:.3f}, {validation['suggestion']['y']:.3f})"
                return JSONResponse(resp)

        loc["x"] = new_x
        loc["y"] = new_y
        loc["facing_deg"] = float(data.get("facing_deg", loc.get("facing_deg", 0)))
        loc["description"] = data.get("description", loc.get("description", ""))
        loc["aliases"] = data.get("aliases", loc.get("aliases", []))
        loc["area"] = data.get("area", loc.get("area", ""))

        _save_semantic_and_config(sem_path, sem_data)
        SEMANTIC_MAP[name] = loc
        logger.info("Updated location '%s' to (%.3f, %.3f)", name, loc["x"], loc["y"])
        return JSONResponse({"ok": True, "message": f"Location '{name}' updated"})
    except Exception as e:
        logger.error("Failed to update location: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


@app.delete("/api/locations/{name}")
async def delete_location(name: str):
    """Delete a location from semantic_map.json and config.yaml."""
    sem_path = Path(__file__).parent.parent / "campus_guide_bot" / "campus_nav_llm" / "semantic" / "semantic_map.json"
    if not sem_path.exists():
        return JSONResponse({"ok": False, "error": "semantic_map.json not found"})
    try:
        with open(sem_path) as f:
            sem_data = json.load(f)
        if name not in sem_data.get("locations", {}):
            return JSONResponse({"ok": False, "error": f"Location '{name}' not found"})

        del sem_data["locations"][name]
        _save_semantic_and_config(sem_path, sem_data)
        SEMANTIC_MAP.pop(name, None)
        logger.info("Deleted location '%s'", name)
        return JSONResponse({"ok": True, "message": f"Location '{name}' deleted"})
    except Exception as e:
        logger.error("Failed to delete location: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})


def _diagnose_odom_failure(ssh_cmd_fn, ros_prefix: str, ns: str, initial_output: str):
    """Diagnose WHY odom is not publishing and return (fix_action, detail_message).

    Decision tree:
      1. No Create3 nodes at all      → full_recovery (GUID mismatch, need full reboot)
      2. Create3 nodes but no topics   → restart_turtlebot4 (stale DDS, daemon cache)
      3. Topics exist, turtlebot4 nodes missing → restart_turtlebot4 (TB4 service stale)
      4. Everything registered but odom dead    → restart_create3_app (Create3 app issue)
    """
    try:
        # Check node list (fast, doesn't depend on topic discovery)
        r = ssh_cmd_fn(
            f"{ros_prefix}ros2 daemon stop 2>/dev/null; ros2 daemon start 2>/dev/null; "
            f"ros2 node list 2>&1",
            timeout=20,
        )
        node_output = r.stdout.strip()
        nodes = [n for n in node_output.split("\n") if n.startswith("/")]
        create3_nodes = [n for n in nodes if "_do_not_use" in n]
        tb4_nodes = [n for n in nodes if n.startswith(f"/{ns}/") and "_do_not_use" not in n]

        if not create3_nodes:
            return ("full_recovery",
                    "No Create3 nodes found — GUID mismatch, need full reboot")

        if not tb4_nodes:
            return ("restart_turtlebot4",
                    f"Create3 nodes OK ({len(create3_nodes)}) but turtlebot4 nodes missing — TB4 service stale (restart it)")

        # Both node types exist — check if odom topic is advertised
        r2 = ssh_cmd_fn(
            f"{ros_prefix}ros2 topic list 2>&1 | grep '/{ns}/odom'",
            timeout=15,
        )
        if f"/{ns}/odom" in r2.stdout:
            return ("restart_create3_app",
                    f"/{ns}/odom topic exists but no data — Create3 app may be stuck")

        # Topics not visible despite nodes existing — DDS/daemon issue
        # Check topic count
        r3 = ssh_cmd_fn(
            f"{ros_prefix}ros2 topic list 2>&1 | grep -c '/{ns}/'",
            timeout=15,
        )
        topic_count = 0
        try:
            topic_count = int(r3.stdout.strip().split("\n")[-1].strip())
        except (ValueError, IndexError):
            pass

        if topic_count == 0:
            return ("restart_turtlebot4",
                    f"Nodes registered ({len(tb4_nodes)} TB4 + {len(create3_nodes)} Create3) but 0 topics visible — DDS stale, restart TB4 service")
        else:
            return ("restart_create3_app",
                    f"{topic_count} topics visible but /{ns}/odom missing — Create3 app issue")

    except Exception as e:
        return ("restart_create3_app",
                f"Diagnosis error: {e} — original: {initial_output[:80]}")


# ── Pre-flight API ──

@app.post("/api/preflight")
async def run_preflight():
    """Run pre-deployment checks and return structured results."""
    result = await asyncio.get_event_loop().run_in_executor(None, _run_preflight_checks)
    all_passed = all(c["status"] in ("pass", "skip") for c in result)
    has_critical_fail = any(c.get("critical") and c["status"] == "fail" for c in result)
    return JSONResponse({
        "ok": True,
        "checks": result,
        "all_passed": all_passed,
        "deploy_blocked": has_critical_fail,
        "ts": time.time(),
    })


# ── Pre-flight Fix Actions ──
# One-click fixes for failed preflight checks.

def _ssh_fix(remote_cmd: str, timeout: int = 30) -> dict:
    """Run a fix command on the RPi via SSH."""
    robot_ip = DEPLOY_CONFIG["robot_ip"]
    robot_user = DEPLOY_CONFIG["robot_user"]
    robot_pass = DEPLOY_CONFIG["robot_pass"]
    try:
        r = subprocess.run(
            ["sshpass", "-p", robot_pass,
             "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
             f"{robot_user}@{robot_ip}", remote_cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return {"ok": r.returncode == 0,
                "output": (r.stdout + r.stderr).strip()[:300]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "SSH timeout"}
    except Exception as e:
        return {"ok": False, "output": str(e)}


@app.post("/api/preflight/fix/{action}")
async def preflight_fix(action: str):
    """Run a fix action for a failed preflight check."""
    ns = DEPLOY_CONFIG["robot_ns"]

    if action == "restart_discovery":
        def _do():
            # Kill stale processes, clean shared memory, restart via systemd
            _enqueue({"type": "system", "text": "[preflight] Restarting Discovery Server..."})
            r1 = _ssh_fix(
                "sudo systemctl stop discovery.service 2>/dev/null; "
                "sudo killall -9 fast-discovery-server fastdds 2>/dev/null; "
                "sudo rm -rf /dev/shm/fastrtps_* /dev/shm/fast_datasharing* 2>/dev/null; "
                "sleep 1; "
                "sudo systemctl start discovery.service; "
                "sleep 3; ss -ulnp | grep 11811 | wc -l",
                timeout=20,
            )
            # Check last line for wc -l count; any non-zero means port is listening
            try:
                port_up = r1["ok"] and int(r1["output"].strip().split("\n")[-1].strip()) > 0
            except (ValueError, IndexError):
                port_up = False
            if port_up:
                return {"ok": True,
                        "message": "Discovery Server restarted (new GUID) — Create3 cached old GUID, needs full reboot to reconnect",
                        "chain_fix": "full_recovery"}
            return {"ok": False, "error": "Discovery Server restarted but port not listening"}
        result = await asyncio.get_event_loop().run_in_executor(None, _do)
        return JSONResponse(result)

    elif action == "full_recovery":
        def _do():
            """Full recovery chain:
            1. Clean stale DDS shared memory
            2. Reboot Create3 (full reboot to reinitialize DDS)
            3. Wait for Create3 webserver + ROS topics to register
            4. Restart turtlebot4.service AFTER Create3 topics are up
            5. Restart local ros2 daemon
            6. Verify odom + sync clock
            """
            steps = []

            # Step 1: Clean stale DDS shared memory on RPi
            _enqueue({"type": "system", "text": "[preflight] Step 1/6: Cleaning stale DDS shared memory..."})
            _ssh_fix("sudo rm -rf /dev/shm/fastrtps_* /dev/shm/fast_datasharing* 2>/dev/null || true", timeout=10)
            steps.append("DDS shared memory cleaned")

            # Step 2: Reboot Create3 — timeout is expected (Create3 shuts down mid-request)
            _enqueue({"type": "system", "text": "[preflight] Step 2/6: Rebooting Create3 (full reboot)..."})
            _ssh_fix(
                "curl -s --connect-timeout 10 --max-time 15 -X POST http://192.168.186.2/api/reboot 2>&1 || true",
                timeout=25,
            )
            steps.append("Create3 reboot sent")

            # Step 3: Wait for Create3 webserver, then wait for ROS topics to register
            # Note: /api/firmware-version returns HTML (with DOCTYPE) — that IS a valid response.
            # Any HTTP response from the webserver means Create3 is back.
            _enqueue({"type": "system", "text": "[preflight] Step 3/6: Waiting for Create3 to reboot (~2-3 min)..."})
            create3_up = False
            for attempt in range(18):  # 18 x 10s = 3 minutes max
                time.sleep(10)
                r = _ssh_fix(
                    "curl -s --connect-timeout 5 --max-time 8 http://192.168.186.2/home 2>&1 | head -3",
                    timeout=15,
                )
                resp = r.get("output", "")
                if r["ok"] and resp and ("DOCTYPE" in resp or "html" in resp.lower() or "create3" in resp.lower() or len(resp.strip()) > 10):
                    create3_up = True
                    _enqueue({"type": "system", "text": f"[preflight] Create3 webserver responding ({(attempt+1)*10}s)"})
                    break
                else:
                    _enqueue({"type": "system", "text": f"[preflight] Create3 still booting... ({(attempt+1)*10}s)"})

            if not create3_up:
                return {"ok": False, "error": "Create3 did not come back after 3 minutes"}
            steps.append("Create3 webserver back")

            # Wait for Create3 ROS topics to register with Discovery Server
            # Webserver comes up well before ROS nodes — need to poll topic list
            _enqueue({"type": "system", "text": "[preflight] Waiting for Create3 ROS topics to register..."})
            topics_registered = False
            for attempt in range(9):  # 9 x 10s = 90s max
                time.sleep(10)
                r = _ssh_fix(
                    f"source /etc/turtlebot4/setup.bash && "
                    f"export ROS_SUPER_CLIENT=True && "
                    f"ros2 topic list 2>&1 | grep -c '/{ns}/'",
                    timeout=15,
                )
                count = 0
                try:
                    count = int(r["output"].strip().split("\n")[-1].strip())
                except (ValueError, IndexError):
                    pass
                if count >= 3:
                    topics_registered = True
                    _enqueue({"type": "system", "text": f"[preflight] Create3 topics registered ({count} topics found)"})
                    break
                _enqueue({"type": "system", "text": f"[preflight] Create3 topics: {count} so far... ({(attempt+1)*10}s)"})

            if not topics_registered:
                return {"ok": False, "error": "Create3 rebooted but ROS topics did not register with Discovery Server"}
            steps.append("Create3 topics registered")

            # Step 4: NOW restart turtlebot4.service — Create3 topics are up,
            # so robot_state_publisher can find odom frames
            _enqueue({"type": "system", "text": "[preflight] Step 4/6: Restarting turtlebot4.service..."})
            r = _ssh_fix("sudo systemctl restart turtlebot4.service", timeout=15)
            if not r["ok"]:
                return {"ok": False, "error": f"turtlebot4.service restart failed: {r['output']}"}
            _enqueue({"type": "system", "text": "[preflight] Waiting 20s for turtlebot4 nodes to initialize..."})
            time.sleep(20)
            steps.append("turtlebot4.service restarted")

            # Step 5: Restart local ros2 daemon (clear stale topic cache on laptop)
            _enqueue({"type": "system", "text": "[preflight] Step 5/6: Restarting ROS2 daemon..."})
            try:
                subprocess.run(["ros2", "daemon", "stop"], capture_output=True, timeout=10)
                time.sleep(1)
                subprocess.run(["ros2", "daemon", "start"], capture_output=True, timeout=10)
                time.sleep(2)
            except Exception:
                pass
            steps.append("ROS2 daemon restarted")

            # Step 6: Verify odom is actually publishing data
            _enqueue({"type": "system", "text": "[preflight] Step 6/6: Verifying odom publishing..."})
            odom_ok = False
            for attempt in range(4):
                r = _ssh_fix(
                    f"source /etc/turtlebot4/setup.bash && "
                    f"export ROS_SUPER_CLIENT=True && "
                    f"timeout 15 ros2 topic echo /{ns}/odom --once 2>&1 | head -5",
                    timeout=25,
                )
                if r["ok"] and ("position" in r["output"] or "header" in r["output"] or "pose" in r["output"]):
                    odom_ok = True
                    break
                _enqueue({"type": "system", "text": f"[preflight] Odom not yet... retry {attempt+2}/4"})
                time.sleep(10)

            if odom_ok:
                _enqueue({"type": "system", "text": "[preflight] Syncing clock..."})
                _ssh_fix("sudo chronyc -a makestep", timeout=10)
                steps.append("Odom verified + clock synced")
                return {"ok": True,
                        "message": "Full recovery complete: " + " → ".join(steps)}
            else:
                steps.append("Odom NOT verified")
                return {"ok": False,
                        "error": "Recovery completed but odom still not publishing. Steps: " + " → ".join(steps)}

        result = await asyncio.get_event_loop().run_in_executor(None, _do)
        return JSONResponse(result)

    elif action == "restart_turtlebot4":
        def _do():
            # Step 1: Restart turtlebot4.service
            _enqueue({"type": "system", "text": "[preflight] Step 1/4: Restarting turtlebot4.service..."})
            r = _ssh_fix("sudo systemctl restart turtlebot4.service", timeout=15)
            if not r["ok"]:
                return {"ok": False, "error": f"Failed: {r['output']}"}

            # Step 2: Restart ros2 daemon on RPi (clear stale topic cache)
            _enqueue({"type": "system", "text": "[preflight] Step 2/4: Restarting ROS2 daemon on RPi..."})
            _ssh_fix(
                "source /etc/turtlebot4/setup.bash && "
                "ros2 daemon stop 2>/dev/null; ros2 daemon start 2>/dev/null",
                timeout=15,
            )

            # Step 3: Wait for nodes to register, poll topic list
            _enqueue({"type": "system", "text": "[preflight] Step 3/4: Waiting for TB4 nodes to register..."})
            topics_ok = False
            for attempt in range(6):  # 6 x 5s = 30s max
                time.sleep(5)
                r = _ssh_fix(
                    f"source /etc/turtlebot4/setup.bash && "
                    f"export ROS_SUPER_CLIENT=True && "
                    f"ros2 topic list 2>&1 | grep -c '/{ns}/'",
                    timeout=15,
                )
                count = 0
                try:
                    count = int(r["output"].strip().split("\n")[-1].strip())
                except (ValueError, IndexError):
                    pass
                if count >= 5:
                    topics_ok = True
                    _enqueue({"type": "system", "text": f"[preflight] {count} topics registered ({(attempt+1)*5}s)"})
                    break
                _enqueue({"type": "system", "text": f"[preflight] {count} topics so far... ({(attempt+1)*5}s)"})

            # Step 4: Verify odom specifically
            _enqueue({"type": "system", "text": "[preflight] Step 4/4: Verifying odom..."})
            odom_ok = False
            for attempt in range(3):
                r = _ssh_fix(
                    f"source /etc/turtlebot4/setup.bash && "
                    f"export ROS_SUPER_CLIENT=True && "
                    f"timeout 10 ros2 topic echo /{ns}/odom --once 2>&1 | head -5",
                    timeout=20,
                )
                if r["ok"] and ("position" in r["output"] or "header" in r["output"] or "pose" in r["output"]):
                    odom_ok = True
                    break
                _enqueue({"type": "system", "text": f"[preflight] Odom not yet... retry {attempt+2}/3"})
                time.sleep(5)

            if odom_ok:
                return {"ok": True,
                        "message": "TB4 service restarted — odom verified!"}
            elif topics_ok:
                return {"ok": False,
                        "error": "TB4 restarted, topics visible, but odom not publishing — Create3 app may be stuck",
                        "chain_fix": "restart_create3_app"}
            else:
                return {"ok": False,
                        "error": "TB4 restarted but topics not registering — may need full recovery",
                        "chain_fix": "full_recovery"}
        result = await asyncio.get_event_loop().run_in_executor(None, _do)
        return JSONResponse(result)

    elif action == "restart_create3_app":
        def _do():
            # Quick pre-checks before sending restart
            _enqueue({"type": "system", "text": "[preflight] Checking Discovery Server..."})
            ds_check = _ssh_fix("ss -ulnp | grep 11811 | wc -l", timeout=10)
            ds_healthy = False
            try:
                ds_healthy = ds_check["ok"] and int(ds_check["output"].strip().split("\n")[-1].strip()) > 0
            except (ValueError, IndexError):
                pass
            if not ds_healthy:
                return {"ok": False,
                        "error": "Discovery Server not healthy — fix Discovery Server first",
                        "chain_fix": "restart_discovery"}

            # Check if ANY Create3 topics exist — if zero, it's a GUID
            # mismatch and app restart cannot fix it (DDS not reinitialized).
            _enqueue({"type": "system", "text": "[preflight] Checking Create3 topic registration..."})
            r = _ssh_fix(
                f"source /etc/turtlebot4/setup.bash && "
                f"export ROS_SUPER_CLIENT=True && "
                f"ros2 topic list 2>&1 | grep -c '/{ns}/'",
                timeout=15,
            )
            create3_topic_count = 0
            try:
                create3_topic_count = int(r["output"].strip().split("\n")[-1].strip())
            except (ValueError, IndexError):
                pass

            if create3_topic_count == 0:
                _enqueue({"type": "system", "text": "[preflight] No Create3 topics — GUID mismatch, need full reboot."})
                return {"ok": False,
                        "error": "No Create3 topics found — GUID mismatch (app restart cannot fix DDS). Full reboot required.",
                        "chain_fix": "full_recovery"}

            # Send restart command and return immediately.
            # Frontend active polling via /api/odom-status handles the rest.
            _enqueue({"type": "system", "text": "[preflight] Sending Create3 app restart..."})
            r = _ssh_fix(
                "curl -s --connect-timeout 10 -X POST http://192.168.186.2/api/restart-app",
                timeout=20,
            )
            output = r.get("output", "")
            sent = r["ok"] or "Restarting" in output or "timeout" in output.lower()

            if sent:
                _enqueue({"type": "system", "text": "[preflight] Restart command sent — active polling will track odom recovery"})
                return {"ok": True, "pending_odom": True,
                        "message": "Create3 app restart sent — watch odom status above"}
            else:
                return {"ok": False,
                        "error": f"Create3 app restart failed: {output or 'no response'}",
                        "chain_fix": "full_recovery"}

        result = await asyncio.get_event_loop().run_in_executor(None, _do)
        return JSONResponse(result)

    elif action == "restart_ros2_daemon":
        def _do():
            try:
                subprocess.run(["ros2", "daemon", "stop"], capture_output=True, timeout=10)
                time.sleep(1)
                subprocess.run(["ros2", "daemon", "start"], capture_output=True, timeout=10)
                return {"ok": True, "message": "ROS2 daemon restarted"}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        result = await asyncio.get_event_loop().run_in_executor(None, _do)
        return JSONResponse(result)

    else:
        return JSONResponse({"ok": False, "error": f"Unknown fix action: {action}"})


# ── Create3 Management ──
# Proxies commands to the Create3 base via RPi SSH tunnel.
# Create3 webserver is at 192.168.186.2 on the RPi's USB network.

_CREATE3_IP = "192.168.186.2"

def _create3_api(endpoint: str) -> dict:
    """Call Create3 webserver API via RPi SSH tunnel."""
    import subprocess
    robot_ip = DEPLOY_CONFIG["robot_ip"]
    robot_user = DEPLOY_CONFIG["robot_user"]
    robot_pass = DEPLOY_CONFIG["robot_pass"]
    # Use sshpass + ssh to curl the Create3 API from the RPi
    cmd = [
        "sshpass", "-p", robot_pass,
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
        f"{robot_user}@{robot_ip}",
        f"curl -s -X POST http://{_CREATE3_IP}/api/{endpoint}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        logger.info("Create3 %s: %s", endpoint, result.stdout[:100])
        return {"ok": True, "message": f"Create3 {endpoint} sent", "response": result.stdout[:200]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "SSH timeout (Create3 unreachable?)"}
    except FileNotFoundError:
        return {"ok": False, "error": "sshpass not installed (apt install sshpass)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_odom_poll_count = 0  # Track consecutive polls to know when to restart daemon

@app.get("/api/odom-status")
async def odom_status():
    """Quick non-blocking check: is odom topic currently publishing?

    Returns {"publishing": bool, "detail": str}.
    Used by the frontend to actively poll odom status during fix actions.

    Key insight from deploy logs: ros2 daemon cache is often stale under
    FastDDS Discovery Server. Topic list may show odom missing even when
    Create3 is publishing. Every 3rd poll, we restart the daemon to clear
    stale cache (project_ros2_daemon_cache.md).
    """
    def _do():
        global _odom_poll_count
        _odom_poll_count += 1
        ns = DEPLOY_CONFIG["robot_ns"]
        robot_ip = DEPLOY_CONFIG["robot_ip"]
        robot_pass = DEPLOY_CONFIG["robot_pass"]
        robot_user = DEPLOY_CONFIG["robot_user"]
        env = {**os.environ,
               "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
               "ROS_DISCOVERY_SERVER": f"{robot_ip}:{DEPLOY_CONFIG['discovery_port']}",
               "ROS_SUPER_CLIENT": "True"}

        # Every 3rd poll: restart ros2 daemon to clear stale topic cache.
        # Under FastDDS Discovery Server, daemon cache is the #1 cause of
        # "odom missing" false negatives (see project_ros2_daemon_cache.md).
        if _odom_poll_count % 3 == 0:
            try:
                subprocess.run(["ros2", "daemon", "stop"], capture_output=True, timeout=5)
                time.sleep(0.5)
                subprocess.run(["ros2", "daemon", "start"], capture_output=True, timeout=5)
                time.sleep(1)
            except Exception:
                pass

        # Step 1: Check local topic list
        odom_visible = False
        topic_count = 0
        try:
            r = subprocess.run(
                ["ros2", "topic", "list"],
                capture_output=True, text=True, timeout=8, env=env,
            )
            topics = [t.strip() for t in r.stdout.strip().split("\n") if t.strip()]
            topic_count = len(topics)
            odom_visible = any(f"/{ns}/odom" == t for t in topics)
        except Exception:
            pass

        if not odom_visible:
            # Distinguish: is it daemon cache issue or genuinely missing?
            detail = f"/{ns}/odom not in topic list ({topic_count} topics visible)"
            if topic_count <= 2:
                detail += " — daemon cache may be stale"
            return {"publishing": False, "detail": detail}

        # Step 2: odom in topic list — verify data is flowing.
        # Use ros2 topic hz locally first (fast), fall back to RPi SSH echo.
        try:
            r = subprocess.run(
                ["ros2", "topic", "hz", f"/{ns}/odom", "--window", "2"],
                capture_output=True, text=True, timeout=5, env=env,
            )
            output = r.stdout + r.stderr
            if "average rate" in output:
                _odom_poll_count = 0
                return {"publishing": True, "detail": "odom publishing (hz confirmed)"}
        except Exception:
            pass

        # Step 3: local hz inconclusive — verify via RPi (authoritative but slower)
        try:
            ssh_r = subprocess.run(
                ["sshpass", "-p", robot_pass,
                 "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=3",
                 f"{robot_user}@{robot_ip}",
                 f"source /etc/turtlebot4/setup.bash && "
                 f"export ROS_SUPER_CLIENT=True && "
                 f"timeout 5 ros2 topic echo /{ns}/odom --once 2>&1 | head -3"],
                capture_output=True, text=True, timeout=12,
            )
            out = ssh_r.stdout + ssh_r.stderr
            if "header" in out or "position" in out or "pose" in out:
                _odom_poll_count = 0
                return {"publishing": True, "detail": "odom publishing (RPi verified)"}
        except Exception:
            pass

        return {"publishing": False, "detail": f"/{ns}/odom listed but no data flowing"}

    result = await asyncio.get_event_loop().run_in_executor(None, _do)
    return JSONResponse(result)


@app.post("/api/create3/sync-clock")
async def create3_sync_clock():
    """Restart NTP on Create3 to fix clock drift."""
    result = await asyncio.get_event_loop().run_in_executor(
        None, _create3_api, "restart-ntpd"
    )
    return JSONResponse(result)


@app.post("/api/create3/restart-app")
async def create3_restart_app():
    """Restart Create3 ROS application (recovers odom/scan)."""
    result = await asyncio.get_event_loop().run_in_executor(
        None, _create3_api, "restart-app"
    )
    return JSONResponse(result)


@app.post("/api/create3/reboot")
async def create3_reboot():
    """Full hardware reboot of Create3."""
    result = await asyncio.get_event_loop().run_in_executor(
        None, _create3_api, "reboot"
    )
    return JSONResponse(result)


# ── RPi Management ──

# ── Dock/Undock ──

@app.post("/api/undock")
async def undock_robot():
    """Send undock action goal to Create3."""
    def _do():
        import subprocess
        ns = DEPLOY_CONFIG["robot_ns"]
        cmd = [
            "ros2", "action", "send_goal",
            f"/{ns}/undock", "irobot_create_msgs/action/Undock", "{}",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stdout + result.stderr
            if "SUCCEEDED" in output or "is_docked: false" in output:
                return {"ok": True, "message": "Undock succeeded — robot is free to navigate"}
            if result.returncode == 0:
                return {"ok": True, "message": "Undock command sent", "output": output[:200]}
            return {"ok": False, "error": output[:300]}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Undock timed out (30s)"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    result = await asyncio.get_event_loop().run_in_executor(None, _do)
    return JSONResponse(result)


@app.post("/api/dock")
async def dock_robot():
    """Send dock action goal to Create3."""
    def _do():
        import subprocess
        ns = DEPLOY_CONFIG["robot_ns"]
        cmd = [
            "ros2", "action", "send_goal",
            f"/{ns}/dock", "irobot_create_msgs/action/Dock", "{}",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            output = result.stdout + result.stderr
            if "SUCCEEDED" in output or "is_docked: true" in output:
                return {"ok": True, "message": "Dock succeeded — robot is charging"}
            if result.returncode == 0:
                return {"ok": True, "message": "Dock command sent", "output": output[:200]}
            return {"ok": False, "error": output[:300]}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Dock timed out (60s)"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    result = await asyncio.get_event_loop().run_in_executor(None, _do)
    return JSONResponse(result)


@app.post("/api/rpi/restart-turtlebot4")
async def rpi_restart_service():
    """Restart turtlebot4.service on RPi via SSH."""
    def _do():
        import subprocess
        robot_ip = DEPLOY_CONFIG["robot_ip"]
        robot_user = DEPLOY_CONFIG["robot_user"]
        robot_pass = DEPLOY_CONFIG["robot_pass"]
        cmd = [
            "sshpass", "-p", robot_pass,
            "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
            f"{robot_user}@{robot_ip}",
            "sudo systemctl restart turtlebot4.service",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return {"ok": True, "message": "turtlebot4.service restarted — wait 30s for topics"}
            return {"ok": False, "error": f"Exit code {result.returncode}: {result.stderr[:200]}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "SSH timeout"}
        except FileNotFoundError:
            return {"ok": False, "error": "sshpass not installed"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    result = await asyncio.get_event_loop().run_in_executor(None, _do)
    return JSONResponse(result)


@app.post("/api/restart-ros2-daemon")
async def restart_ros2_daemon():
    """Restart the local ros2 daemon to fix stale topic/node cache.

    Under FastDDS Discovery Server, ros2 topic list can return empty results
    even when all nodes are running. Restarting the daemon fixes this.
    """
    def _do():
        import subprocess
        try:
            subprocess.run(["ros2", "daemon", "stop"], capture_output=True, timeout=10)
            time.sleep(1)
            subprocess.run(["ros2", "daemon", "start"], capture_output=True, timeout=10)
            time.sleep(2)
            result = subprocess.run(
                ["ros2", "topic", "list"], capture_output=True, text=True, timeout=10
            )
            topic_count = len([l for l in result.stdout.strip().split("\n") if l.strip()])
            return {"ok": True, "message": f"ROS2 daemon restarted — {topic_count} topics visible"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    result = await asyncio.get_event_loop().run_in_executor(None, _do)
    return JSONResponse(result)


# ── System Logs ──

@app.get("/api/logs/list")
async def list_logs():
    """List available log files across all log sources."""
    import re
    ws_dir = DEPLOY_CONFIG["ws_dir"]
    event_dir = Path.home() / ".campus_nav_logs"
    deploy_dir = Path(ws_dir) / "log" / "deploy"

    logs = []

    # Deploy logs
    if deploy_dir.is_dir():
        for f in sorted(deploy_dir.glob("deploy_*.log"), reverse=True):
            size_kb = f.stat().st_size / 1024
            logs.append({
                "id": f.stem,
                "type": "deploy",
                "name": f.name,
                "path": str(f),
                "size_kb": round(size_kb, 1),
                "mtime": f.stat().st_mtime,
            })

    # Lifecycle logs
    if event_dir.is_dir():
        for f in sorted(event_dir.glob("lifecycle_*.jsonl"), reverse=True):
            size_kb = f.stat().st_size / 1024
            logs.append({
                "id": f.stem,
                "type": "lifecycle",
                "name": f.name,
                "path": str(f),
                "size_kb": round(size_kb, 1),
                "mtime": f.stat().st_mtime,
            })

    # Event logs
    if event_dir.is_dir():
        for f in sorted(event_dir.glob("events_*.jsonl"), reverse=True):
            size_kb = f.stat().st_size / 1024
            logs.append({
                "id": f.stem,
                "type": "events",
                "name": f.name,
                "path": str(f),
                "size_kb": round(size_kb, 1),
                "mtime": f.stat().st_mtime,
            })

    # Session notes
    ws = Path(ws_dir)
    for f in sorted(ws.glob("SESSION_NOTES_*.md"), reverse=True):
        size_kb = f.stat().st_size / 1024
        logs.append({
            "id": f.stem,
            "type": "session",
            "name": f.name,
            "path": str(f),
            "size_kb": round(size_kb, 1),
            "mtime": f.stat().st_mtime,
        })

    return JSONResponse({"ok": True, "logs": logs})


@app.get("/api/logs/read/{log_id:path}")
async def read_log(log_id: str, tail: int = 200):
    """Read a log file by ID. Returns last `tail` lines."""
    ws_dir = DEPLOY_CONFIG["ws_dir"]
    event_dir = Path.home() / ".campus_nav_logs"
    deploy_dir = Path(ws_dir) / "log" / "deploy"

    # Find the file
    target = None
    for d in [deploy_dir, event_dir, Path(ws_dir)]:
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.stem == log_id:
                target = f
                break
        if target:
            break

    if not target or not target.is_file():
        return JSONResponse({"ok": False, "error": f"Log not found: {log_id}"})

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        if tail and total > tail:
            lines = lines[-tail:]
            truncated = True
        else:
            truncated = False

        # Strip ANSI escape codes for clean display
        import re
        ansi_re = re.compile(r'\x1b\[[0-9;]*m')
        clean_lines = [ansi_re.sub('', l) for l in lines]

        # For JSONL files, parse into structured entries
        is_jsonl = target.suffix == ".jsonl"
        parsed = []
        if is_jsonl:
            for line in clean_lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed.append(json.loads(line))
                except json.JSONDecodeError:
                    parsed.append({"raw": line})

        return JSONResponse({
            "ok": True,
            "name": target.name,
            "type": target.suffix,
            "total_lines": total,
            "truncated": truncated,
            "content": "\n".join(clean_lines) if not is_jsonl else None,
            "entries": parsed if is_jsonl else None,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.get("/api/logs/diagnostics")
async def diagnostics():
    """Run a quick diagnostic check and return structured results."""
    def _do():
        results = []

        # 1. Check Discovery Server
        robot_ip = DEPLOY_CONFIG["robot_ip"]
        robot_user = DEPLOY_CONFIG["robot_user"]
        robot_pass = DEPLOY_CONFIG["robot_pass"]

        # Local checks
        try:
            r = subprocess.run(
                ["ros2", "node", "list"],
                capture_output=True, text=True, timeout=10,
                env={**os.environ,
                     "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
                     "ROS_DISCOVERY_SERVER": f"{robot_ip}:{DEPLOY_CONFIG['discovery_port']}",
                     "ROS_SUPER_CLIENT": "True"},
            )
            node_count = len([l for l in r.stdout.strip().split("\n") if l.strip()])
            results.append({"check": "ROS2 Nodes", "status": "ok" if node_count > 2 else "warn",
                            "detail": f"{node_count} nodes found"})
        except Exception as e:
            results.append({"check": "ROS2 Nodes", "status": "error", "detail": str(e)})

        try:
            r = subprocess.run(
                ["ros2", "topic", "list"],
                capture_output=True, text=True, timeout=10,
                env={**os.environ,
                     "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
                     "ROS_DISCOVERY_SERVER": f"{robot_ip}:{DEPLOY_CONFIG['discovery_port']}",
                     "ROS_SUPER_CLIENT": "True"},
            )
            topic_count = len([l for l in r.stdout.strip().split("\n") if l.strip()])
            status = "ok" if topic_count > 5 else "warn" if topic_count > 2 else "error"
            hint = ""
            if topic_count <= 2:
                hint = " — try Restart ROS2 Daemon (stale cache)"
            results.append({"check": "ROS2 Topics", "status": status,
                            "detail": f"{topic_count} topics{hint}"})
        except Exception as e:
            results.append({"check": "ROS2 Topics", "status": "error", "detail": str(e)})

        # RPi connectivity
        try:
            r = subprocess.run(
                ["ping", "-c", "1", "-W", "2", robot_ip],
                capture_output=True, timeout=5)
            results.append({"check": "RPi Ping", "status": "ok" if r.returncode == 0 else "error",
                            "detail": f"{robot_ip} {'reachable' if r.returncode == 0 else 'unreachable'}"})
        except Exception as e:
            results.append({"check": "RPi Ping", "status": "error", "detail": str(e)})

        # RPi SSH + Discovery Server
        try:
            ssh_cmd = [
                "sshpass", "-p", robot_pass,
                "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                f"{robot_user}@{robot_ip}",
                "ps aux | grep fast-discovery | grep -v grep | wc -l"
            ]
            r = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            count = int(r.stdout.strip()) if r.returncode == 0 else 0
            results.append({"check": "Discovery Server", "status": "ok" if count > 0 else "error",
                            "detail": f"{'running' if count > 0 else 'NOT running'} on RPi"})
        except Exception as e:
            results.append({"check": "Discovery Server", "status": "error", "detail": str(e)})

        # Clock drift
        try:
            ssh_cmd = [
                "sshpass", "-p", robot_pass,
                "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                f"{robot_user}@{robot_ip}", "date +%s"
            ]
            r = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                robot_time = int(r.stdout.strip())
                local_time = int(time.time())
                drift = abs(local_time - robot_time)
                status = "ok" if drift <= 2 else "warn" if drift <= 5 else "error"
                results.append({"check": "Clock Drift", "status": status,
                                "detail": f"{drift}s (tolerance: 5s)"})
        except Exception:
            pass

        # Chrony status
        try:
            r = subprocess.run(["chronyc", "tracking"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                for line in r.stdout.split("\n"):
                    if "System time" in line:
                        results.append({"check": "Chrony (laptop)", "status": "ok",
                                        "detail": line.strip()})
                        break
        except Exception:
            results.append({"check": "Chrony (laptop)", "status": "warn", "detail": "chronyc not available"})

        return {"ok": True, "checks": results, "ts": time.time()}

    result = await asyncio.get_event_loop().run_in_executor(None, _do)
    return JSONResponse(result)


# ── Quality Report ──

@app.get("/api/quality-report")
async def quality_report():
    """Generate quality report from JSONL event logs."""
    try:
        import sys as _sys
        report_script = Path(__file__).parent.parent / "gen_quality_report.py"
        if not report_script.exists():
            return JSONResponse({"ok": False, "error": "gen_quality_report.py not found"})
        # Import the generate_report function
        _sys.path.insert(0, str(report_script.parent))
        from gen_quality_report import generate_report
        log_dir = str(Path.home() / ".campus_nav_logs")
        report = generate_report(log_dir, latest_only=False)
        return JSONResponse({"ok": True, "report": report})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.get("/api/deploy-status")
async def deploy_status():
    """Check if deploy is running."""
    with _deploy_lock:
        running = _deploy_running
    return JSONResponse({"running": running})


@app.post("/api/deploy-stop")
async def deploy_stop_http():
    """HTTP fallback for stopping deploy (WebSocket may be down)."""
    threading.Thread(target=_stop_deploy, daemon=True).start()
    return JSONResponse({"ok": True})


@app.get("/api/apikey")
async def get_apikey():
    """Return masked API key if saved."""
    if APIKEY_FILE.exists():
        key = APIKEY_FILE.read_text().strip()
        if key:
            masked = key[:7] + "..." + key[-4:] if len(key) > 14 else "****"
            return JSONResponse({"masked": masked})
    return JSONResponse({"masked": None})


@app.post("/api/apikey")
async def save_apikey(request: Request):
    """Save OpenRouter API key to disk."""
    try:
        body = await request.json()
        key = body.get("key", "").strip()
        if not key:
            return JSONResponse({"ok": False, "error": "Empty key"})
        APIKEY_FILE.write_text(key + "\n")
        APIKEY_FILE.chmod(0o600)
        masked = key[:7] + "..." + key[-4:] if len(key) > 14 else "****"
        logger.info("API key saved (%s)", masked)
        return JSONResponse({"ok": True, "masked": masked})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    async with _ws_lock:
        _active_ws.add(ws)

    # Send initial state
    await ws.send_text(json.dumps({
        "type": "init",
        "ros_connected": USE_ROS and ROS_AVAILABLE,
        "demo_mode": not (USE_ROS and ROS_AVAILABLE),
    }))

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "command":
                text = msg.get("text", "").strip()
                if not text:
                    continue

                if USE_ROS and ROS_AVAILABLE and _ros_node:
                    _ros_node.publish_command(text)
                    await _broadcast_queue.put({
                        "type": "command_sent", "text": text, "channel": "ROS2",
                    })
                else:
                    asyncio.create_task(_demo_handle_command(text))

            elif msg.get("type") == "navigate_to":
                loc_name = msg.get("location", "")
                cmd = f"go to {loc_name}"
                if USE_ROS and ROS_AVAILABLE and _ros_node:
                    _ros_node.publish_command(cmd)
                    await _broadcast_queue.put({
                        "type": "command_sent", "text": cmd, "channel": "ROS2",
                    })
                else:
                    asyncio.create_task(_demo_handle_command(cmd))

            elif msg.get("type") == "deploy_start":
                pose = msg.get("pose", "front_door")
                skip_build = msg.get("skip_build", False)
                skip_clock = msg.get("skip_clock", False)
                # Run deploy in background thread to avoid blocking
                threading.Thread(
                    target=_run_deploy,
                    args=(pose, skip_build, skip_clock),
                    daemon=True,
                ).start()

            elif msg.get("type") == "deploy_stop":
                threading.Thread(target=_stop_deploy, daemon=True).start()

            elif msg.get("type") == "set_pose":
                x = msg.get("x", 0)
                y = msg.get("y", 0)
                theta = msg.get("theta", 0)
                if USE_ROS and ROS_AVAILABLE and _ros_node:
                    # Publish via ROS node directly (no subprocess)
                    threading.Thread(
                        target=_publish_initial_pose,
                        args=(x, y, theta),
                        daemon=True,
                    ).start()
                else:
                    await _broadcast_queue.put({
                        "type": "system", "text": f"[DEMO] Would set pose to ({x:.2f}, {y:.2f})"
                    })

    except WebSocketDisconnect:
        pass
    finally:
        async with _ws_lock:
            _active_ws.discard(ws)


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--ros", action="store_true", help="Enable ROS 2 bridge")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    USE_ROS = args.ros
    uvicorn.run(app, host="127.0.0.1", port=args.port)
