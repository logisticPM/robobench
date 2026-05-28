"""Command-line entry point for the robobench tool.

Usage examples (Phase A — v0.1):

    robobench --version
    robobench check --robot turtlebot4 \\
        --ip 192.168.50.31 --ssh-user ubuntu --ssh-pass turtlebot4 \\
        --namespace turtlebot468
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from robobench import __version__
from robobench.config import load_adapter_config
from robobench.robots.turtlebot4 import TurtleBot4Adapter

# Clock offset severity thresholds (seconds)
_CLOCK_OK_THRESHOLD = 2.0
_CLOCK_WARN_THRESHOLD = 10.0


def _build_parser() -> argparse.ArgumentParser:
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
        required=True,
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
    kwargs = load_adapter_config(Path(args.config))
    adapter = TurtleBot4Adapter(**kwargs)

    x, y, theta = args.initial_pose
    print(f"[1/5] clock sync ({'skipped' if args.skip_clock else 'running'}) ...")
    if not args.skip_clock:
        adapter.setup_clock_sync(workstation_ip=args.workstation_ip)
    print(f"[2/5] build ({'skipped' if args.skip_build else 'running'}) ...")
    if not args.skip_build:
        adapter.build()
    print("[3/5] launch ...")
    adapter.launch()
    print("[4/5] activate lifecycle ...")
    adapter.activate_lifecycle(map_yaml=args.map_yaml)
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
    adapter = TurtleBot4Adapter(**load_adapter_config(Path(args.config)))
    report = adapter.health_check()
    print(json.dumps(report, indent=2))
    return 0 if report["overall"] != "UNHEALTHY" else 1


def _cmd_shutdown(args: argparse.Namespace) -> int:
    if args.robot != "turtlebot4":
        print(f"unsupported robot: {args.robot}", file=sys.stderr)
        return 2
    adapter = TurtleBot4Adapter(**load_adapter_config(Path(args.config)))
    adapter.shutdown()
    print("shutdown complete")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
