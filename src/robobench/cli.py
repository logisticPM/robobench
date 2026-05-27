"""Command-line entry point for the robobench tool.

Usage examples (Phase A — v0.1):

    robobench --version
    robobench check --robot turtlebot4 \\
        --ip 192.168.50.31 --ssh-user ubuntu --ssh-pass turtlebot4 \\
        --namespace turtlebot468
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from robobench import __version__
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
