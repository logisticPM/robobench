from robobench.panels.recovery_job import RecoveryJob


def test_log_appends_steps():
    job = RecoveryJob()
    job.log("probe", {"healthy": False})
    job.log("action", {"name": "sync_clock"})
    assert job.snapshot()["steps"] == [
        {"event": "probe", "data": {"healthy": False}},
        {"event": "action", "data": {"name": "sync_clock"}},
    ]


def test_begin_resets_and_marks_running():
    job = RecoveryJob()
    job.log("old", {})
    job.begin()
    snap = job.snapshot()
    assert snap["status"] == "running"
    assert snap["steps"] == []
    assert snap["started_at"] is not None
    assert snap["finished_at"] is None


def test_finish_records_outcome_and_actions():
    job = RecoveryJob()
    job.begin()
    job.finish("CONVERGED", ["sync_clock", "restart_discovery_server"])
    snap = job.snapshot()
    assert snap["status"] == "done"
    assert snap["outcome"] == "CONVERGED"
    assert snap["actions"] == ["sync_clock", "restart_discovery_server"]
    assert snap["error"] is None
    assert snap["finished_at"] is not None


def test_finish_with_error():
    job = RecoveryJob()
    job.begin()
    job.finish("ERROR", [], error="ssh boom")
    snap = job.snapshot()
    assert snap["status"] == "done"
    assert snap["error"] == "ssh boom"


def test_status_property():
    job = RecoveryJob()
    assert job.status == "idle"
    job.begin()
    assert job.status == "running"


def test_begin_returns_false_when_already_running():
    job = RecoveryJob()
    assert job.begin() is True
    assert job.begin() is False
