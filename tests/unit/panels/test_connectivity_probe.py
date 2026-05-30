# tests/unit/panels/test_connectivity_probe.py
from robobench.panels.connectivity_probe import run_connectivity_probe
from robobench.panels.state import DiagnosticState
from robobench.recovery.state import RobotState

_OK = RobotState(True, True, True, 5, True, True)
_BAD = RobotState(True, False, True, 0, False, True)


def test_loop_writes_connectivity_each_cycle_and_stops():
    state = DiagnosticState()
    reports = iter([_BAD, _OK])

    class Probe:
        def read_connectivity(self):
            return next(reports)

    counter = {"n": 0}

    def fake_sleep(_seconds):
        counter["n"] += 1

    run_connectivity_probe(
        state,
        Probe(),
        interval=1.0,
        sleep=fake_sleep,
        should_stop=lambda: counter["n"] >= 2,
    )
    assert state.connectivity() == _OK  # last write wins
    assert counter["n"] == 2  # exactly two cycles


def test_loop_survives_probe_exception():
    state = DiagnosticState()
    calls = {"probe": 0, "sleep": 0}

    class Probe:
        def read_connectivity(self):
            calls["probe"] += 1
            if calls["probe"] == 1:
                raise RuntimeError("ssh boom")
            return _OK

    def fake_sleep(_seconds):
        calls["sleep"] += 1

    run_connectivity_probe(
        state,
        Probe(),
        interval=0.0,
        sleep=fake_sleep,
        should_stop=lambda: calls["sleep"] >= 2,
    )
    # first cycle raised but was swallowed; second cycle wrote a result
    assert state.connectivity() == _OK
