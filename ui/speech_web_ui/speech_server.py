"""
Speech-to-Command Web Bridge for TurtleBot468.

Serves the web UI and bridges browser speech input → ROS2 /user_input topic.
Also relays /robot_reply and /tool_result back to the browser via WebSocket.

Run:
    python speech_server.py
or (with ROS2 sourced):
    python speech_server.py --ros
"""
import asyncio
import threading
import json
import argparse
import logging
from typing import Set
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── Global state (set up during lifespan) ─────────────────────────────────────
_main_loop: asyncio.AbstractEventLoop | None = None
_broadcast_queue: asyncio.Queue | None = None
_ros_node = None
_active_ws: Set[WebSocket] = set()
_ws_lock: asyncio.Lock | None = None

ROS_AVAILABLE = False
try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    ROS_AVAILABLE = True
    logger.info("rclpy found — ROS2 mode available")
except ImportError:
    logger.warning("rclpy not found — starting in DEMO mode (no robot commands sent)")


# ── ROS2 Bridge Node ──────────────────────────────────────────────────────────

class SpeechBridgeNode:
    """Thin wrapper around a rclpy Node that bridges WebSocket ↔ ROS2."""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        from rclpy.node import Node
        from std_msgs.msg import String

        self._loop = loop
        self._queue = queue

        self._node = Node("speech_web_bridge")
        self._pub = self._node.create_publisher(String, "/user_input", 10)
        self._node.create_subscription(String, "/robot_reply", self._on_reply, 10)
        self._node.create_subscription(String, "/tool_result", self._on_tool_result, 10)
        logger.info("SpeechBridgeNode ready — pub /user_input, sub /robot_reply /tool_result")

    @property
    def node(self):
        return self._node

    def publish_command(self, text: str):
        from std_msgs.msg import String
        msg = String()
        msg.data = text
        self._pub.publish(msg)
        logger.info("→ /user_input: %s", text)

    def _push(self, payload: dict):
        asyncio.run_coroutine_threadsafe(self._queue.put(payload), self._loop)

    def _on_reply(self, msg):
        self._push({"type": "robot_reply", "text": msg.data})

    def _on_tool_result(self, msg):
        try:
            data = json.loads(msg.data)
            self._push({"type": "nav_status", "data": data})
        except Exception:
            pass


# ── Async broadcast task ──────────────────────────────────────────────────────

async def _broadcaster():
    """Forward messages from the queue to every connected WebSocket."""
    while True:
        payload = await _broadcast_queue.get()
        dead: Set[WebSocket] = set()
        async with _ws_lock:
            snapshot = set(_active_ws)
        for ws in snapshot:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(ws)
        if dead:
            async with _ws_lock:
                _active_ws.difference_update(dead)


# ── ROS2 spin thread ──────────────────────────────────────────────────────────

def _ros_spin_thread():
    global _ros_node
    rclpy.init()
    _ros_node = SpeechBridgeNode(_main_loop, _broadcast_queue)
    try:
        rclpy.spin(_ros_node.node)
    except Exception as e:
        logger.error("ROS spin error: %s", e)
    finally:
        _ros_node.node.destroy_node()
        rclpy.shutdown()
        logger.info("ROS2 shutdown")


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _main_loop, _broadcast_queue, _ws_lock
    _main_loop = asyncio.get_running_loop()
    _broadcast_queue = asyncio.Queue()
    _ws_lock = asyncio.Lock()

    asyncio.create_task(_broadcaster())

    if ROS_AVAILABLE and app.state.use_ros:
        t = threading.Thread(target=_ros_spin_thread, daemon=True, name="ros-spin")
        t.start()
        logger.info("ROS2 spin thread started")
    else:
        logger.info("Running without ROS2 (demo mode)")

    yield  # app is running

    logger.info("Shutting down speech server")


app = FastAPI(title="TurtleBot468 Speech Commander", lifespan=lifespan)
app.state.use_ros = False  # overridden by CLI arg

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_file.read_text(), status_code=200)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "ros_available": ROS_AVAILABLE,
        "ros_connected": _ros_node is not None,
        "ws_clients": len(_active_ws),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    async with _ws_lock:
        _active_ws.add(websocket)
    logger.info("WebSocket connected (total: %d)", len(_active_ws))

    # Send initial status
    await websocket.send_json({
        "type": "server_status",
        "ros_connected": _ros_node is not None,
        "demo_mode": not (ROS_AVAILABLE and app.state.use_ros),
    })

    pending_tasks: list[asyncio.Task] = []
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "speech_command":
                text = data.get("text", "").strip()
                if not text:
                    continue

                logger.info("Speech command received: %s", text)

                if _ros_node is not None:
                    _ros_node.publish_command(text)
                    await websocket.send_json({
                        "type": "command_sent",
                        "text": text,
                        "channel": "ROS2 /user_input",
                    })
                else:
                    # Demo mode — echo back a fake response
                    await websocket.send_json({
                        "type": "command_sent",
                        "text": text,
                        "channel": "DEMO (no ROS2)",
                    })
                    # Simulate robot reply after a delay
                    async def _fake_reply(t: str, ws: WebSocket):
                        try:
                            await asyncio.sleep(1.5)
                            await ws.send_json({
                                "type": "robot_reply",
                                "text": f"[DEMO] Navigating to {t.split()[-1]} ...",
                            })
                            await asyncio.sleep(3.0)
                            await ws.send_json({
                                "type": "nav_status",
                                "data": {"status": "arrived", "target": t.split()[-1]},
                            })
                        except Exception:
                            pass  # WebSocket closed during delay — safe to ignore
                    pending_tasks.append(asyncio.create_task(_fake_reply(text, websocket)))

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        for task in pending_tasks:
            task.cancel()
        async with _ws_lock:
            _active_ws.discard(websocket)
        logger.info("WebSocket disconnected (total: %d)", len(_active_ws))


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TurtleBot468 Speech Web Bridge")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8888, help="Bind port (default: 8888)")
    parser.add_argument("--ros", action="store_true", help="Enable ROS2 (requires sourced ROS2 env)")
    parser.add_argument("--reload", action="store_true", help="Enable hot-reload (dev mode)")
    args = parser.parse_args()

    app.state.use_ros = args.ros and ROS_AVAILABLE

    if args.ros and not ROS_AVAILABLE:
        logger.warning("--ros requested but rclpy not available; running in DEMO mode")

    logger.info("Starting speech server on http://%s:%d  (ROS2=%s)", args.host, args.port, app.state.use_ros)
    uvicorn.run(
        "speech_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
