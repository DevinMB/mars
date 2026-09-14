"""How MARS maps Flink's job states.

The important case is RESTARTING. A stream job that starts cleanly and then cannot
reach its sink loops forever in that state, and Flink's own overview still lists it
under running jobs. Reporting it as healthy is the failure mode this guards."""
from __future__ import annotations

import pytest

from app.models import RunState
from app.submitter import _map_state


@pytest.mark.parametrize("flink_state", ["RUNNING", "CREATED", "INITIALIZING"])
def test_healthy_states_map_to_running(flink_state):
    assert _map_state(flink_state) == RunState.RUNNING.value


@pytest.mark.parametrize("flink_state", ["RESTARTING", "FAILING", "RECONCILING"])
def test_thrashing_states_are_not_reported_as_running(flink_state):
    # This is the regression that matters: a job looping on an unreachable sink
    # must never read as "running" in the console.
    assert _map_state(flink_state) == RunState.RESTARTING.value
    assert _map_state(flink_state) != RunState.RUNNING.value


def test_finished():
    assert _map_state("FINISHED") == RunState.FINISHED.value


@pytest.mark.parametrize("flink_state", ["CANCELED", "CANCELLING", "SUSPENDED"])
def test_cancelled_states(flink_state):
    assert _map_state(flink_state) == RunState.CANCELED.value


@pytest.mark.parametrize("flink_state", ["FAILED", "", "SOMETHING_NEW", None])
def test_unknown_states_fail_closed(flink_state):
    # An unrecognised state must not be optimistically treated as healthy.
    assert _map_state(flink_state) == RunState.FAILED.value
