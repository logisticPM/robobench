"""Lint the workstation's FastDDS Discovery Server environment.

Pure function over an env mapping — no ROS2, SSH, or network. Tells the user
whether their shell is configured to actually see the robot's graph, catching
the CLIENT-vs-SUPER_CLIENT / wrong-RMW / missing-server gotcha. See
docs/architecture.md section 5 for the connection mode.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

_FASTRTPS = "rmw_fastrtps_cpp"
_TRUTHY = frozenset({"true", "1", "yes"})


@dataclass(frozen=True)
class DdsFinding:
    """One environment check result."""

    level: Literal["ok", "warn", "error"]
    check: Literal["rmw", "discovery_server", "super_client"]
    message: str


def _lint_rmw(environ: Mapping[str, str]) -> DdsFinding:
    rmw = environ.get("RMW_IMPLEMENTATION", "").strip()
    if not rmw:
        return DdsFinding(
            "warn",
            "rmw",
            "RMW_IMPLEMENTATION not set — relying on the ROS distro default; "
            "export RMW_IMPLEMENTATION=rmw_fastrtps_cpp to be sure the Discovery Server works.",
        )
    if rmw != _FASTRTPS:
        return DdsFinding(
            "error",
            "rmw",
            f"RMW_IMPLEMENTATION={rmw} — the FastDDS Discovery Server needs "
            f"rmw_fastrtps_cpp; {rmw} can't join it.",
        )
    return DdsFinding("ok", "rmw", "RMW_IMPLEMENTATION=rmw_fastrtps_cpp")


def _lint_discovery_server(environ: Mapping[str, str], expected_server: str | None) -> DdsFinding:
    value = environ.get("ROS_DISCOVERY_SERVER", "").strip()
    if not value:
        return DdsFinding(
            "error",
            "discovery_server",
            "ROS_DISCOVERY_SERVER not set — you're on Simple Discovery (multicast), "
            "which won't reach the robot's Discovery Server.",
        )
    # substring match so a ;-separated multi-server ROS_DISCOVERY_SERVER still matches
    if expected_server and expected_server not in value:
        return DdsFinding(
            "warn",
            "discovery_server",
            f"ROS_DISCOVERY_SERVER={value} but config expects {expected_server}.",
        )
    suffix = " (matches config)" if expected_server else ""
    return DdsFinding("ok", "discovery_server", f"ROS_DISCOVERY_SERVER={value}{suffix}")


def _lint_super_client(environ: Mapping[str, str]) -> DdsFinding:
    raw = environ.get("ROS_SUPER_CLIENT", "").strip()
    if raw.lower() in _TRUTHY:
        return DdsFinding("ok", "super_client", f"ROS_SUPER_CLIENT={raw}")
    state = f"ROS_SUPER_CLIENT={raw} is not truthy" if raw else "ROS_SUPER_CLIENT not set"
    if environ.get("FASTRTPS_DEFAULT_PROFILES_FILE", "").strip():
        return DdsFinding(
            "ok",
            "super_client",
            f"{state}; using FASTRTPS_DEFAULT_PROFILES_FILE "
            "(ensure that profile declares SUPER_CLIENT).",
        )
    if environ.get("ROS_DISCOVERY_SERVER", "").strip():
        return DdsFinding(
            "error",
            "super_client",
            f"{state} — connected as a plain CLIENT; ros2 topic list/node list will "
            "look empty even though the robot is fine. Fix: export ROS_SUPER_CLIENT=True.",
        )
    return DdsFinding("warn", "super_client", f"{state}.")


def lint_dds_env(
    environ: Mapping[str, str], expected_server: str | None = None
) -> list[DdsFinding]:
    """Return findings for the three DDS env checks (rmw, server, super-client).

    Always returns exactly three findings in order. ``expected_server`` is the
    config's ``ip:port`` (omitted -> the server-address cross-check is skipped).
    Never raises.
    """
    return [
        _lint_rmw(environ),
        _lint_discovery_server(environ, expected_server),
        _lint_super_client(environ),
    ]
