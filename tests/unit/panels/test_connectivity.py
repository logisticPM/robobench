# tests/unit/panels/test_connectivity.py
from robobench.panels.connectivity import CONNECTIVITY_ASPECTS, diagnose, first_broken_layer
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


def test_all_layers_ok_is_status_ok_even_if_odom_false():
    state = _state(odom_publishing=False)  # odom is downstream — ignored here
    result = diagnose(state)
    assert result["status"] == "OK"
    assert result["first_broken"] is None
    assert result["fixes"] == []
    assert [layer["name"] for layer in result["layers"]] == [a for a, _ in CONNECTIVITY_ASPECTS]


def test_first_broken_is_most_upstream():
    state = _state(discovery_server_ok=False, tb4_nodes_present=False)
    assert first_broken_layer(state) == "discovery_server_ok"
    result = diagnose(state)
    assert result["status"] == "FAIL"
    assert result["first_broken"] == "discovery_server_ok"
    assert result["fixes"], "FAIL should carry catalog fixes"


def test_create3_topics_zero_counts_as_broken():
    assert first_broken_layer(_state(create3_topics=0)) == "create3_topics"


def test_rpi_unreachable_is_first():
    state = _state(rpi_reachable=False, discovery_server_ok=False)
    assert first_broken_layer(state) == "rpi_reachable"


def test_none_is_unknown():
    result = diagnose(None)
    assert result["status"] == "UNKNOWN"
    assert result["layers"] == []
    assert result["first_broken"] is None
    assert result["fixes"] == []
