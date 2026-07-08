"""Tests for robobench.notify (watch webhook alerting)."""

from __future__ import annotations

import json

from robobench.notify import WatchAlerter, make_watch_notifier, post_webhook


def test_alerter_alerts_on_first_unhealthy_only():
    a = WatchAlerter()
    assert a.filter("unhealthy", {"aspect": "clock_synced"}) == {
        "event": "unhealthy",
        "data": {"aspect": "clock_synced"},
    }
    assert a.filter("unhealthy", {"aspect": "clock_synced"}) is None


def test_alerter_alerts_on_return_to_healthy():
    a = WatchAlerter()
    assert a.filter("healthy", {}) is None  # healthy from the start: silence
    a.filter("unhealthy", {"aspect": "x"})
    assert a.filter("healthy", {}) == {"event": "healthy", "data": {}}
    assert a.filter("healthy", {}) is None  # staying healthy: silence


def test_alerter_always_alerts_escalate_recover_and_recover_error():
    a = WatchAlerter()
    assert a.filter("escalate", {"reason": "max_attempts"}) is not None
    assert a.filter("recover", {"outcome": "CONVERGED"}) is not None
    assert a.filter("recover_error", {"error": "boom"}) is not None


def test_alerter_ignores_noise_events():
    a = WatchAlerter()
    assert a.filter("cooldown", {}) is None
    assert a.filter("probe_error", {"error": "ssh"}) is None


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_post_webhook_sends_json(monkeypatch):
    sent = {}

    def fake_opener(req, timeout):
        sent["url"] = req.full_url
        sent["body"] = json.loads(req.data)
        sent["content_type"] = req.get_header("Content-type")
        return _FakeResponse()

    ok = post_webhook("http://hook.example/x", {"event": "unhealthy"}, opener=fake_opener)
    assert ok is True
    assert sent["url"] == "http://hook.example/x"
    assert sent["body"] == {"event": "unhealthy"}
    assert sent["content_type"] == "application/json"


def test_post_webhook_swallows_failures(capsys):
    def boom(req, timeout):
        raise OSError("connection refused")

    assert post_webhook("http://hook.example/x", {}, opener=boom) is False
    assert "webhook" in capsys.readouterr().err


def test_make_watch_notifier_posts_only_alert_worthy_events(monkeypatch):
    posts = []
    monkeypatch.setattr(
        "robobench.notify.post_webhook",
        lambda url, payload, **kw: posts.append((url, payload)) or True,
    )
    notify = make_watch_notifier(
        "http://hook.example/r", robot="tb", spawn=lambda fn: fn()
    )

    notify("healthy", {})
    notify("unhealthy", {"aspect": "clock_synced"})
    notify("unhealthy", {"aspect": "clock_synced"})
    notify("healthy", {})

    assert [p[1]["event"] for p in posts] == ["unhealthy", "healthy"]
    assert all(p[0] == "http://hook.example/r" for p in posts)
    assert all(p[1]["robot"] == "tb" for p in posts)


def test_make_watch_notifier_dispatches_off_the_caller(monkeypatch):
    """The POST is handed to `spawn`, not run inline, so a slow/dead webhook
    can never block the supervisor loop that calls notify()."""
    posted = []
    monkeypatch.setattr(
        "robobench.notify.post_webhook",
        lambda url, payload, **kw: posted.append(payload) or True,
    )
    deferred: list = []
    notify = make_watch_notifier("http://h/x", robot="tb", spawn=deferred.append)

    notify("escalate", {"reason": "max_attempts"})

    assert posted == []  # not performed inline
    assert len(deferred) == 1  # handed off to spawn
    deferred[0]()  # running the deferred job performs the POST
    assert posted and posted[0]["event"] == "escalate"
