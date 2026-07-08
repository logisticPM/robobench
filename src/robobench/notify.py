"""Webhook alerting for `robobench watch`.

A pure transition policy (WatchAlerter) plus a stdlib-only webhook poster.
The policy dedupes the supervisor's once-per-cycle "unhealthy" heartbeat into
edge alerts — healthy->unhealthy, unhealthy->healthy — and always forwards
escalations and recovery attempts. Posting failures are logged to stderr and
swallowed, so a dead webhook can never take down the watch loop.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.request
from collections.abc import Callable

_DEFAULT_TIMEOUT_S = 5.0


def _spawn_daemon(fn: Callable[[], None]) -> None:
    """Run ``fn`` on a throwaway daemon thread (fire-and-forget)."""
    threading.Thread(target=fn, daemon=True).start()


class WatchAlerter:
    """Filters watch events down to the ones worth an outbound alert."""

    _ALWAYS = frozenset({"escalate", "recover", "recover_error"})

    def __init__(self) -> None:
        self._unhealthy = False

    def filter(self, event: str, data: dict) -> dict | None:
        """Return an alert payload for this event, or None to stay silent."""
        if event == "unhealthy":
            first = not self._unhealthy
            self._unhealthy = True
            return {"event": event, "data": data} if first else None
        if event == "healthy":
            recovered = self._unhealthy
            self._unhealthy = False
            return {"event": event, "data": data} if recovered else None
        if event in self._ALWAYS:
            return {"event": event, "data": data}
        return None


def post_webhook(
    url: str,
    payload: dict,
    *,
    timeout: float = _DEFAULT_TIMEOUT_S,
    opener: Callable = urllib.request.urlopen,
) -> bool:
    """POST ``payload`` as JSON to ``url``. Returns False (and logs) on failure."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, default=str).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout):
            pass
    except Exception as exc:  # noqa: BLE001 — a dead webhook must not kill the watch loop
        print(f"[watch] webhook post failed: {exc}", file=sys.stderr)
        return False
    return True


def make_watch_notifier(
    url: str,
    *,
    robot: str,
    alerter: WatchAlerter | None = None,
    spawn: Callable[[Callable[[], None]], None] | None = None,
) -> Callable[[str, dict], None]:
    """Build an emit-compatible callback that POSTs alert-worthy events to ``url``.

    The POST is handed to ``spawn`` (default: a daemon thread) so a slow or dead
    webhook can never block the supervisor loop that calls ``notify``.
    """
    gate = alerter or WatchAlerter()
    launch = spawn if spawn is not None else _spawn_daemon

    def notify(event: str, data: dict) -> None:
        payload = gate.filter(event, data)
        if payload is not None:
            launch(lambda: post_webhook(url, {"robot": robot, **payload}))

    return notify
