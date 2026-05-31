from robobench.panels.recovery_controller import RecoveryController
from robobench.recovery.engine import RecoveryResult
from robobench.recovery.state import RobotState


def _state(**kw) -> RobotState:
    base = dict(
        rpi_reachable=True,
        discovery_server_ok=True,
        clock_synced=True,
        create3_topics=5,
        tb4_nodes_present=True,
        odom_publishing=True,
    )
    base.update(kw)
    return RobotState(**base)


class _SyncThread:
    """thread_factory that runs target synchronously on .start()."""

    def __init__(self, target, daemon=False):
        self._target = target

    def start(self):
        self._target()


class _NoStartThread:
    """thread_factory whose .start() does nothing (job stays 'running')."""

    def __init__(self, target, daemon=False):
        pass

    def start(self):
        pass


def test_preview_lists_nonnuclear_actions_for_failing_layer():
    ctrl = RecoveryController(build_engine=lambda job: None)
    out = ctrl.preview(_state(discovery_server_ok=False))
    assert out["failing_layer"] == "discovery_server_ok"
    assert out["would_try"] == ["restart_discovery_server"]


def test_preview_create3_excludes_nuclear_reboot():
    ctrl = RecoveryController(build_engine=lambda job: None)
    out = ctrl.preview(_state(create3_topics=0))
    assert out["failing_layer"] == "create3_topics"
    assert "restart_local_daemon" in out["would_try"]
    assert "reboot_create3" not in out["would_try"]


def test_preview_none_and_healthy_are_empty():
    ctrl = RecoveryController(build_engine=lambda job: None)
    assert ctrl.preview(None)["would_try"] == []
    assert ctrl.preview(_state())["would_try"] == []  # healthy -> first_broken None


def test_start_apply_runs_engine_and_finishes_done():
    class FakeEngine:
        def __init__(self, job):
            self._job = job

        def run(self):
            self._job.log("action", {"aspect": "clock_synced", "name": "sync_clock"})
            return RecoveryResult(outcome="CONVERGED", actions_taken=["sync_clock"])

    ctrl = RecoveryController(build_engine=FakeEngine, thread_factory=_SyncThread)
    assert ctrl.start_apply() is True
    snap = ctrl.job.snapshot()
    assert snap["status"] == "done"
    assert snap["outcome"] == "CONVERGED"
    assert snap["actions"] == ["sync_clock"]
    assert {"event": "action", "data": {"aspect": "clock_synced", "name": "sync_clock"}} in snap[
        "steps"
    ]


def test_start_apply_single_flight():
    ctrl = RecoveryController(build_engine=lambda job: None, thread_factory=_NoStartThread)
    assert ctrl.start_apply() is True  # job now 'running' (thread never ran)
    assert ctrl.start_apply() is False  # blocked


def test_start_apply_restarts_after_done():
    class FakeEngine:
        def __init__(self, job):
            pass

        def run(self):
            return RecoveryResult(outcome="CONVERGED", actions_taken=[])

    ctrl = RecoveryController(build_engine=FakeEngine, thread_factory=_SyncThread)
    assert ctrl.start_apply() is True   # runs synchronously -> done
    assert ctrl.job.status == "done"
    assert ctrl.start_apply() is True   # accepted again after done


def test_start_apply_engine_exception_sets_error():
    class BoomEngine:
        def __init__(self, job):
            pass

        def run(self):
            raise RuntimeError("ssh boom")

    ctrl = RecoveryController(build_engine=BoomEngine, thread_factory=_SyncThread)
    assert ctrl.start_apply() is True
    snap = ctrl.job.snapshot()
    assert snap["status"] == "done"
    assert snap["outcome"] == "ERROR"
    assert snap["error"] == "ssh boom"
