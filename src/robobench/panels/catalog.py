"""Failure catalog: maps each diagnostic check to candidate causes + fixes.

This is the "tell me how to fix it" half of robobench. When a panel reports
WARN or FAIL, the server attaches matching cases so the user sees concrete next
steps, not just a red light. The fixes live as data in
``robobench/data/cases/*.yaml`` (loaded via ``robobench.cases``); this module
maps robobench's internal panel/aspect keys onto the robot-agnostic
``subsystem`` vocabulary and projects matching cases to the
``{cause, fix, link}`` shape the dashboard panels expect.
"""

from __future__ import annotations

from robobench.cases import find_cases, load_cases

# Bridge between robobench's panel/aspect keys (left) and the robot-agnostic
# ``subsystem`` vocabulary from robobench.cases (right). A check_name not listed
# here yields no canned fixes — register a new key here when a new panel/aspect
# is wired up.
_KEY_TO_SUBSYSTEM: dict[str, str] = {
    "dds_graph": "networking",
    "discovery_server_ok": "networking",
    "rpi_reachable": "networking",
    "clock_offset": "time_sync",
    "clock_synced": "time_sync",
    "tf_tree": "transform",
    "sensor_rate": "sensor",
    "tb4_nodes_present": "lifecycle",
    "create3_topics": "base",
    "odom_publishing": "base",
}


def lookup_fixes(
    check_name: str, status: str, *, robot_model: str | None = None
) -> list[dict]:
    """Return catalog fixes for a check when its status is WARN/FAIL.

    OK/UNKNOWN -> [] (nothing to fix). Unknown check names -> [] (no canned
    advice yet) rather than raising. Each entry is
    ``{"cause": str, "fix": str, "link": str | None}``
    for backward compatibility with the dashboard panels. ``robot_model=None``
    (the default) returns every case in the matched subsystem.
    """
    if status not in ("WARN", "FAIL"):
        return []
    subsystem = _KEY_TO_SUBSYSTEM.get(check_name)
    if subsystem is None:
        return []
    cases = find_cases(load_cases(), subsystem=subsystem, robot_model=robot_model)
    return [
        {"cause": c.cause, "fix": c.fix, "link": c.links[0] if c.links else None}
        for c in cases
    ]
