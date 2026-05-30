"""Failure catalog: maps each diagnostic check to candidate causes + fixes.

This is the "tell me how to fix it" half of robobench. When a panel reports
WARN or FAIL, the server attaches the matching catalog entries so the user
sees concrete next steps, not just a red light.

Each entry is ``{"cause": str, "fix": str, "link": str | None}``.
Keep entries terse and actionable — they render in a small panel.
"""

from __future__ import annotations

FAILURE_CATALOG: dict[str, list[dict]] = {
    "clock_offset": [
        {
            "cause": "Workstation and robot clocks drifted apart.",
            "fix": "Run `robobench bringup` (configures chrony), or manually: "
            "`ssh <robot> 'sudo chronyc -a makestep'`.",
            "link": "https://docs.ros.org/en/rolling/Tutorials/Demos/Time.html",
        },
        {
            "cause": "Workstation isn't serving NTP, so the robot can't follow it.",
            "fix": "Add `allow 192.168.0.0/16` and `local stratum 10` to "
            "/etc/chrony/chrony.conf, then `sudo systemctl restart chrony`.",
            "link": None,
        },
    ],
    "sensor_rate": [
        {
            "cause": "LiDAR/IMU not publishing, or QoS mismatch (BEST_EFFORT vs RELIABLE).",
            "fix": "Check the sensor is powered and the driver node is up "
            "(`ros2 node list`); confirm your subscriber QoS matches the publisher.",
            "link": None,
        },
        {
            "cause": "Network saturation dropping sensor packets.",
            "fix": "Check WiFi signal / switch to ethernet; inspect `ros2 topic hz` "
            "for the raw rate at the source.",
            "link": None,
        },
    ],
    "tf_tree": [
        {
            "cause": "A TF publisher died, leaving a stale/broken edge.",
            "fix": "Identify the broken parent->child edge, find which node should "
            "publish it (`ros2 topic info /tf`), and restart that node.",
            "link": "https://docs.ros.org/en/rolling/Concepts/About-Tf2.html",
        },
        {
            "cause": "Clock skew makes fresh transforms look stale.",
            "fix": "Fix clock sync first (see the clock panel) — TF staleness is "
            "often a symptom of clock drift, not a missing publisher.",
            "link": None,
        },
        {
            "cause": "Create3 isn't bridging the odom->base_link TF.",
            "fix": "Run `robobench odom-tf --robot turtlebot4 --config config.yaml` "
            "to republish odom->base_link from /odom.",
            "link": None,
        },
    ],
    "dds_graph": [
        {
            "cause": "Expected node never came up or crashed under Discovery Server.",
            "fix": "Re-run `robobench-lifecycle-activator`; check the node's log. "
            "FastDDS Discovery Server can silently drop late joiners (Nav2 #3560).",
            "link": "https://github.com/ros-navigation/navigation2/issues/3560",
        },
        {
            "cause": "Discovery Server not reachable from the workstation.",
            "fix": "Verify `ROS_DISCOVERY_SERVER` env var and that the server port "
            "(default 11811) is listening on the robot.",
            "link": None,
        },
    ],
}


def lookup_fixes(check_name: str, status: str) -> list[dict]:
    """Return catalog entries for a check when its status is WARN/FAIL.

    OK / UNKNOWN return an empty list (nothing to fix). Unknown check names
    return an empty list rather than raising — callers pass whatever check
    ran, and a missing catalog entry just means "no canned advice yet".
    """
    if status not in ("WARN", "FAIL"):
        return []
    return list(FAILURE_CATALOG.get(check_name, []))
