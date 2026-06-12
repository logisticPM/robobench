"""Command-line entry point for the robobench tool.

Usage examples (Phase A — v0.1):

    robobench --version
    robobench check --robot turtlebot4 \\
        --ip 192.168.50.31 --ssh-user ubuntu --ssh-pass turtlebot4 \\
        --namespace turtlebot468
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from robobench import __version__
from robobench.cases import load_cases
from robobench.config import load_adapter_config, render_config_template
from robobench.dds_check import lint_dds_env
from robobench.eventlog import EventLogger
from robobench.eventreport import _RECOGNIZED_EVENTS, format_report, latest_event_log, parse_events
from robobench.recovery.engine import _LADDER
from robobench.robots.turtlebot4 import TurtleBot4Adapter
from robobench.robots.turtlebot4_probe import TurtleBot4Probe
from robobench.robots.turtlebot4_recovery import build_turtlebot4_recovery

try:
    import uvicorn

    from robobench.panels.demo import DEMO_EXPECTED_NODES, seed_demo_state
    from robobench.panels.recovery_controller import RecoveryController
    from robobench.panels.server import create_app
    from robobench.panels.state import DiagnosticState

    _DASHBOARD_AVAILABLE = True
except ImportError:
    _DASHBOARD_AVAILABLE = False

# Clock offset severity thresholds (seconds)
_CLOCK_OK_THRESHOLD = 2.0
_CLOCK_WARN_THRESHOLD = 10.0

_SUPER_CLIENT_CASE_ID = "connected-as-client-not-super-client"


def _adapter_from_config(config_path: str) -> TurtleBot4Adapter:
    """Build a TurtleBot4Adapter from config.yaml, dropping config-only keys
    (e.g. dds.discovery_port, which the dashboard reads but the adapter doesn't take)."""
    kwargs = load_adapter_config(Path(config_path))
    kwargs.pop("discovery_port", None)
    return TurtleBot4Adapter(**kwargs)


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _build_parser() -> argparse.ArgumentParser:  # noqa: PLR0915
    parser = argparse.ArgumentParser(prog="robobench")
    parser.add_argument("--version", action="version", version=f"robobench {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Run hardware diagnostics against a robot.")
    check.add_argument("--robot", required=True, choices=["turtlebot4"])
    check.add_argument("--ip", required=True)
    check.add_argument("--ssh-user", required=True)
    check.add_argument("--ssh-pass", required=True)
    check.add_argument("--namespace", required=True)
    check.add_argument("--workspace-dir", default="~/CS5335TurtleBot")
    check.set_defaults(func=_cmd_check)

    bringup = subparsers.add_parser(
        "bringup", help="Run full bring-up: clock sync, build, launch, activate, health."
    )
    bringup.add_argument("--robot", required=True, choices=["turtlebot4"])
    bringup.add_argument("--config", required=True, help="Path to config.yaml")
    bringup.add_argument("--workstation-ip", required=True)
    bringup.add_argument("--map-yaml", required=True)
    bringup.add_argument(
        "--initial-pose",
        nargs=3,
        metavar=("X", "Y", "THETA"),
        type=float,
        default=None,
    )
    bringup.add_argument(
        "--pose",
        default=None,
        help="Named pose from config.yaml known_poses, or 'x y theta'.",
    )
    bringup.add_argument("--skip-clock", action="store_true")
    bringup.add_argument("--skip-build", action="store_true")
    bringup.set_defaults(func=_cmd_bringup)

    health = subparsers.add_parser("health", help="Print JSON health report.")
    health.add_argument("--robot", required=True, choices=["turtlebot4"])
    health.add_argument("--config", required=True)
    health.set_defaults(func=_cmd_health)

    shutdown = subparsers.add_parser("shutdown", help="Stop the navigation stack cleanly.")
    shutdown.add_argument("--robot", required=True, choices=["turtlebot4"])
    shutdown.add_argument("--config", required=True)
    shutdown.set_defaults(func=_cmd_shutdown)

    dashboard = subparsers.add_parser("dashboard", help="Start the diagnostic dashboard server.")
    dashboard.add_argument("--robot", required=True, choices=["turtlebot4"])
    dashboard.add_argument("--config", required=True)
    dashboard.add_argument("--port", type=int, default=8080)
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument(
        "--demo",
        action="store_true",
        help="Seed synthetic data instead of connecting to a robot (no ROS2 needed).",
    )
    dashboard.add_argument(
        "--no-ssh-probe",
        action="store_true",
        help="Disable the SSH connectivity probe (pure-DDS dashboard).",
    )
    dashboard.add_argument(
        "--ssh-probe-interval",
        type=_positive_float,
        default=20.0,
        help="Seconds between SSH connectivity probes (default 20).",
    )
    dashboard.set_defaults(func=_cmd_dashboard)

    preflight = subparsers.add_parser(
        "preflight", help="Read-only bring-up diagnosis (no fixes applied)."
    )
    preflight.add_argument("--robot", required=True, choices=["turtlebot4"])
    preflight.add_argument("--config", required=True)
    preflight.set_defaults(func=_cmd_preflight)

    recover = subparsers.add_parser(
        "recover", help="Drive a stuck robot back to a healthy bring-up state."
    )
    recover.add_argument("--robot", required=True, choices=["turtlebot4"])
    recover.add_argument("--config", required=True)
    recover.add_argument(
        "--deadline", type=float, default=180.0, help="Max seconds to keep trying (default 180)."
    )
    recover.add_argument(
        "--allow-reboot",
        action="store_true",
        help="Permit the NUCLEAR Create3 full reboot (off by default).",
    )
    recover.add_argument(
        "--dry-run", action="store_true", help="Print the plan from current state; apply nothing."
    )
    recover.set_defaults(func=_cmd_recover)

    bridge = subparsers.add_parser(
        "bridge",
        help="Relay robot topics from the Discovery Server to local Simple Discovery.",
    )
    bridge.add_argument("--robot", required=True, choices=["turtlebot4"])
    bridge.add_argument("--config", required=True)
    bridge.set_defaults(func=_cmd_bridge)

    odom_tf = subparsers.add_parser(
        "odom-tf",
        help="Republish odom->base_link TF when the Create3 doesn't bridge it.",
    )
    odom_tf.add_argument("--robot", required=True, choices=["turtlebot4"])
    odom_tf.add_argument("--config", required=True)
    odom_tf.set_defaults(func=_cmd_odom_tf)

    init = subparsers.add_parser("init", help="Scaffold a starter config.yaml.")
    init.add_argument("--ip", help="Robot IP (default: a placeholder you edit).")
    init.add_argument("--ssh-user")
    init.add_argument("--ssh-pass")
    init.add_argument("--namespace")
    init.add_argument(
        "--output", default="config.yaml", help="Output path (default: ./config.yaml)."
    )
    init.add_argument("--force", action="store_true", help="Overwrite an existing file.")
    init.set_defaults(func=_cmd_init)

    report = subparsers.add_parser(
        "report", help="Summarize a recovery/preflight session log (post-mortem)."
    )
    report.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Session log to read (default: latest events_*.jsonl in ~/.robobench/logs).",
    )
    report.set_defaults(func=_cmd_report)

    watch = subparsers.add_parser(
        "watch",
        help="Continuously supervise a robot (monitor-only; --auto-recover to act).",
    )
    watch.add_argument("--robot", required=True, choices=["turtlebot4"])
    watch.add_argument("--config", required=True)
    watch.add_argument(
        "--auto-recover",
        action="store_true",
        help="Let the supervisor invoke recovery on unhealthy state (off by default).",
    )
    watch.add_argument(
        "--interval",
        type=_positive_float,
        default=20.0,
        help="Seconds between probes (default 20).",
    )
    watch.add_argument(
        "--recover-cooldown",
        type=_positive_float,
        default=60.0,
        help="Min seconds between recovery attempts (default 60).",
    )
    watch.add_argument(
        "--max-recover-attempts",
        type=_positive_int,
        default=3,
        help="Consecutive failed recoveries before escalating to monitor-only (default 3).",
    )
    watch.add_argument(
        "--webhook",
        default=None,
        help="POST JSON alerts (unhealthy/healthy transitions, escalations, "
        "recovery attempts) to this URL.",
    )
    watch.set_defaults(func=_cmd_watch)

    dds_check = subparsers.add_parser(
        "dds-check",
        help="Lint your shell's DDS env (Discovery Server / SUPER_CLIENT / RMW).",
    )
    dds_check.add_argument(
        "--config",
        default=None,
        help="Optional: cross-check ROS_DISCOVERY_SERVER against config's ip:discovery_port.",
    )
    dds_check.set_defaults(func=_cmd_dds_check)

    return parser


def _cmd_check(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2

    adapter = TurtleBot4Adapter(
        ip=args.ip,
        ssh_user=args.ssh_user,
        ssh_pass=args.ssh_pass,
        namespace=args.namespace,
        workspace_dir=args.workspace_dir,
    )

    print(f"Checking clock offset against {args.ip} ...")
    try:
        offset = adapter.check_clock_offset()
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    abs_offset = abs(offset)
    if abs_offset < _CLOCK_OK_THRESHOLD:
        severity = "OK"
    elif abs_offset < _CLOCK_WARN_THRESHOLD:
        severity = "WARN"
    else:
        severity = "FAIL"
    print(f"  clock offset: {offset:+.2f}s  [{severity}]")
    return 0 if severity != "FAIL" else 1


def _cmd_bringup(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    adapter = _adapter_from_config(args.config)

    from robobench.config import load_known_poses, resolve_pose  # noqa: PLC0415

    if args.pose is not None:
        x, y, theta = resolve_pose(args.pose, load_known_poses(Path(args.config)))
    elif args.initial_pose is not None:
        x, y, theta = args.initial_pose
    else:
        print("bringup requires --pose or --initial-pose", file=sys.stderr)
        return 2
    print(f"[1/5] clock sync ({'skipped' if args.skip_clock else 'running'}) ...")
    if not args.skip_clock:
        adapter.setup_clock_sync(workstation_ip=args.workstation_ip)
    print(f"[2/5] build ({'skipped' if args.skip_build else 'running'}) ...")
    if not args.skip_build:
        adapter.build()
    print("[3/5] launch ...")
    adapter.launch()
    print("[4/5] activate lifecycle ...")
    adapter.activate_lifecycle(map_yaml=args.map_yaml, initial_pose=(x, y, theta))
    adapter.set_initial_pose(x, y, theta)
    print("[5/5] health check ...")
    report = adapter.health_check()
    print(f"  overall: {report['overall']}")
    for name, check in report["checks"].items():
        print(f"    {name}: {check['status']}")
    return 0 if report["overall"] != "UNHEALTHY" else 1


def _cmd_health(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    adapter = _adapter_from_config(args.config)
    report = adapter.health_check()
    print(json.dumps(report, indent=2))
    return 0 if report["overall"] != "UNHEALTHY" else 1


def _cmd_shutdown(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    adapter = _adapter_from_config(args.config)
    adapter.shutdown()
    print("shutdown complete")
    return 0


_DEFAULT_EXPECTED_NODES = [
    "/map_server",
    "/amcl",
    "/controller_server",
    "/planner_server",
    "/behavior_server",
    "/bt_navigator",
    "/waypoint_follower",
    "/velocity_smoother",
]


def _safe_run_bridge(state, namespace: str, discovery_server: str | None = None) -> None:
    """Run the bridge, swallowing the no-ROS2 RuntimeError so the web server
    stays up (panels degrade to UNKNOWN/empty instead of crashing)."""
    from robobench.panels.bridge import run_bridge  # noqa: PLC0415

    try:
        run_bridge(state, namespace=namespace, discovery_server=discovery_server)
    except RuntimeError as exc:
        print(f"[dashboard] bridge not started: {exc}", file=sys.stderr)


def _demo_refresh_loop(state) -> None:
    """Re-seed demo data on a timer so the 'fresh' TF edges stay fresh.

    A real robot continuously republishes TF; demo mode must mimic that or the
    fresh transforms go stale (the panel checks freshness against wall-clock
    time, which keeps advancing). The deliberately-stale edge stays stale."""
    import time  # noqa: PLC0415

    while True:  # pragma: no cover
        time.sleep(0.5)
        seed_demo_state(state, now=time.time())


def _cmd_dashboard(args: argparse.Namespace) -> int:
    if not _DASHBOARD_AVAILABLE:
        print(
            "dashboard requires the 'dashboard' extra: pip install 'robobench[dashboard]'",
            file=sys.stderr,
        )
        return 2
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2

    kwargs = load_adapter_config(Path(args.config))
    namespace = kwargs["namespace"]

    state = DiagnosticState()
    recovery = None
    if args.demo:
        import time  # noqa: PLC0415

        seed_demo_state(state, now=time.time())
        from robobench.recovery.state import RobotState  # noqa: PLC0415

        state.set_connectivity(
            RobotState(
                rpi_reachable=True,
                discovery_server_ok=False,
                clock_synced=True,
                create3_topics=0,
                tb4_nodes_present=False,
                odom_publishing=True,  # sentinel: odom not checked in the connectivity path
            )
        )
        threading.Thread(target=_demo_refresh_loop, args=(state,), daemon=True).start()
        expected_nodes = DEMO_EXPECTED_NODES
        print("[dashboard] demo mode — serving synthetic data (no robot needed)")
    else:
        discovery_server = f"{kwargs['ip']}:{kwargs['discovery_port']}"
        threading.Thread(
            target=_safe_run_bridge,
            args=(state, namespace, discovery_server),
            daemon=True,
        ).start()
        print(f"[dashboard] connecting via Discovery Server {discovery_server}")
        if not args.no_ssh_probe:
            from robobench.panels.connectivity_probe import run_connectivity_probe  # noqa: PLC0415

            probe = TurtleBot4Probe(
                ip=kwargs["ip"],
                ssh_user=kwargs["ssh_user"],
                ssh_pass=kwargs["ssh_pass"],
                namespace=namespace,
                discovery_port=kwargs["discovery_port"],
            )
            threading.Thread(
                target=run_connectivity_probe,
                args=(state, probe),
                kwargs={"interval": args.ssh_probe_interval},
                daemon=True,
            ).start()
            print(f"[dashboard] SSH connectivity probe every {args.ssh_probe_interval:.0f}s")
        expected_nodes = _DEFAULT_EXPECTED_NODES
        recovery = RecoveryController(
            build_engine=lambda job: build_turtlebot4_recovery(
                ip=kwargs["ip"],
                ssh_user=kwargs["ssh_user"],
                ssh_pass=kwargs["ssh_pass"],
                namespace=namespace,
                allow_reboot=False,
                deadline_s=180.0,
                discovery_port=kwargs["discovery_port"],
                event_log=job,
            ),
        )

    from robobench.panels.history import run_history_sampler  # noqa: PLC0415

    threading.Thread(target=run_history_sampler, args=(state,), daemon=True).start()

    app = create_app(state, namespace=namespace, expected_nodes=expected_nodes, recovery=recovery)
    print(f"robobench dashboard on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _cmd_preflight(args: argparse.Namespace) -> int:

    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    kwargs = load_adapter_config(Path(args.config))
    probe = TurtleBot4Probe(
        ip=kwargs["ip"],
        ssh_user=kwargs["ssh_user"],
        ssh_pass=kwargs["ssh_pass"],
        namespace=kwargs["namespace"],
        discovery_port=kwargs["discovery_port"],
    )
    state = probe.read()
    event_log = EventLogger()
    try:
        event_log.log("preflight", dataclasses.asdict(state))
    finally:
        event_log.close()
    aspect = state.failing_aspect()
    would_do = [a for asp, a, _nuke in _LADDER if asp == aspect]
    print(
        json.dumps(
            {
                "healthy": state.is_healthy(),
                "failing_aspect": aspect,
                "would_try": would_do,
                "state": dataclasses.asdict(state),
            },
            indent=2,
        )
    )
    print(f"event log: {event_log.path}", file=sys.stderr)
    return 0 if state.is_healthy() else 1


def _cmd_recover(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    kwargs = load_adapter_config(Path(args.config))

    if args.dry_run:
        probe = TurtleBot4Probe(
            ip=kwargs["ip"],
            ssh_user=kwargs["ssh_user"],
            ssh_pass=kwargs["ssh_pass"],
            namespace=kwargs["namespace"],
            discovery_port=kwargs["discovery_port"],
        )
        state = probe.read()
        aspect = state.failing_aspect()
        if aspect is None:
            print("[dry-run] robot is healthy; nothing to recover")
            return 0
        if aspect == "rpi_reachable":
            print(
                "[dry-run] robot unreachable (ping failed) — check power/network; "
                "recovery cannot fix this remotely"
            )
            return 0
        would_do = [
            a for asp, a, nuke in _LADDER if asp == aspect and (args.allow_reboot or not nuke)
        ]
        print(f"[dry-run] failing aspect: {aspect}")
        if would_do:
            for a in would_do:
                print(f"[dry-run] would try: {a}")
        else:
            print(
                "[dry-run] no non-nuclear action available "
                "(pass --allow-reboot to permit the Create3 reboot)"
            )
        return 0

    event_log = EventLogger()
    engine = build_turtlebot4_recovery(
        ip=kwargs["ip"],
        ssh_user=kwargs["ssh_user"],
        ssh_pass=kwargs["ssh_pass"],
        namespace=kwargs["namespace"],
        allow_reboot=args.allow_reboot,
        deadline_s=args.deadline,
        discovery_port=kwargs["discovery_port"],
        event_log=event_log,
    )
    try:
        result = engine.run()
    finally:
        event_log.close()
    print(f"recovery outcome: {result.outcome}")
    for a in result.actions_taken:
        print(f"  applied: {a}")
    print(f"event log: {event_log.path}")
    if result.outcome == "NEEDS_HUMAN":
        print("  robot unreachable — check power and network.", file=sys.stderr)
    return 0 if result.outcome == "CONVERGED" else 1


def _cmd_bridge(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    kwargs = load_adapter_config(Path(args.config))
    namespace = kwargs["namespace"]
    discovery_server = f"{kwargs['ip']}:{kwargs['discovery_port']}"
    from robobench.relay.runner import run_dds_bridge  # noqa: PLC0415

    print(f"[bridge] relaying {namespace} topics via Discovery Server {discovery_server}")
    print("[bridge] Ctrl+C to stop.")
    try:
        run_dds_bridge(namespace=namespace, discovery_server=discovery_server)
    except RuntimeError as exc:
        print(f"[bridge] not started: {exc}", file=sys.stderr)
        return 2
    return 0


def _cmd_odom_tf(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    namespace = load_adapter_config(Path(args.config))["namespace"]
    from robobench.diagnostics.odom_tf import run_odom_tf_publisher  # noqa: PLC0415

    print(f"[odom-tf] publishing odom->base_link TF for {namespace}. Ctrl+C to stop.")
    try:
        run_odom_tf_publisher(namespace=namespace)
    except RuntimeError as exc:
        print(f"[odom-tf] not started: {exc}", file=sys.stderr)
        return 2
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.output)
    if target.exists() and not args.force:
        print(f"error: {target} already exists (use --force to overwrite)", file=sys.stderr)
        return 2
    target.write_text(
        render_config_template(
            ip=args.ip,
            ssh_user=args.ssh_user,
            ssh_pass=args.ssh_pass,
            namespace=args.namespace,
        ),
        encoding="utf-8",
    )
    print(f"wrote {target}")
    print(
        f"next: edit it, then `robobench check --robot turtlebot4 ...` "
        f"or `robobench dashboard --robot turtlebot4 --config {target}`"
    )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    if args.path is not None:
        target = Path(args.path)
        if not target.exists():
            print(f"error: {target} not found", file=sys.stderr)
            return 1
    else:
        target = latest_event_log()
        if target is None:
            print("no session logs in ~/.robobench/logs/", file=sys.stderr)
            return 1
    records = parse_events(target.read_text(encoding="utf-8"))
    if not any(r.get("event") in _RECOGNIZED_EVENTS for r in records):
        print(f"no recognizable recover/preflight events in {target}", file=sys.stderr)
        return 2
    print(f"log: {target}")
    print(format_report(records))
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    import time as _time  # noqa: PLC0415

    from robobench.recovery.supervisor import run_supervisor  # noqa: PLC0415

    kwargs = load_adapter_config(Path(args.config))
    probe_obj = TurtleBot4Probe(
        ip=kwargs["ip"],
        ssh_user=kwargs["ssh_user"],
        ssh_pass=kwargs["ssh_pass"],
        namespace=kwargs["namespace"],
        discovery_port=kwargs["discovery_port"],
    )
    event_log = EventLogger()

    recover = None
    if args.auto_recover:

        def recover():
            return build_turtlebot4_recovery(
                ip=kwargs["ip"],
                ssh_user=kwargs["ssh_user"],
                ssh_pass=kwargs["ssh_pass"],
                namespace=kwargs["namespace"],
                allow_reboot=False,
                deadline_s=180.0,
                discovery_port=kwargs["discovery_port"],
                event_log=event_log,
            ).run()

    notify = None
    if args.webhook:
        from robobench.notify import make_watch_notifier  # noqa: PLC0415

        notify = make_watch_notifier(args.webhook, robot=kwargs["namespace"])
        print(f"[watch] alerting to webhook {args.webhook}")

    def emit(event: str, data: dict) -> None:
        event_log.log(f"watch_{event}", data)
        detail = data.get("aspect") or data.get("reason") or data.get("outcome") or ""
        suffix = f" ({detail})" if detail else ""
        stamp = _time.strftime("%H:%M:%S", _time.localtime())
        print(f"[watch] {stamp}  {event}{suffix}")
        if notify is not None:
            notify(event, data)

    mode = "auto-recover" if args.auto_recover else "monitor-only"
    print(
        f"[watch] supervising {kwargs['namespace']} "
        f"({mode}, every {args.interval:.0f}s) - Ctrl+C to stop"
    )
    print(f"[watch] event log: {event_log.path}")
    try:
        run_supervisor(
            probe_obj.read_connectivity,
            recover,
            interval=args.interval,
            cooldown_s=args.recover_cooldown,
            max_attempts=args.max_recover_attempts,
            sleep=_time.sleep,
            now=_time.monotonic,
            emit=emit,
        )
    except KeyboardInterrupt:
        print("\n[watch] stopped")
    finally:
        event_log.close()
    return 0


def _cmd_dds_check(args: argparse.Namespace) -> int:
    expected = None
    if args.config:
        kwargs = load_adapter_config(Path(args.config))
        expected = f"{kwargs['ip']}:{kwargs['discovery_port']}"

    findings = lint_dds_env(dict(os.environ), expected)
    for finding in findings:
        print(f"[dds-check] {finding.message}  [{finding.level.upper()}]")

    if any(f.check == "super_client" and f.level == "error" for f in findings):
        case = next((c for c in load_cases() if c.id == _SUPER_CLIENT_CASE_ID), None)
        if case is not None:
            print(f"  -> {case.fix}")

    errors = [f for f in findings if f.level == "error"]
    if errors:
        print(f"result: {len(errors)} error(s) — your shell won't see the robot's graph")
        return 1
    print("result: OK — your shell is configured to see the robot's graph")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        # RuntimeError is robobench's operational-failure type (SSH down,
        # command timeout, ROS2 missing) — show it cleanly, not as a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
