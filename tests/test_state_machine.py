import pytest
from workbuddy.domain.state_machine import (
    MISSION_TRANSITIONS, OPERATION_TRANSITIONS, ExternalOperationStatus,
    InvalidTransition, MissionStatus, transition,
)


def test_mission_cannot_skip_lead_review():
    with pytest.raises(InvalidTransition):
        transition(MissionStatus.EXECUTING, MissionStatus.COMPLETED, MISSION_TRANSITIONS)


def test_unknown_operation_cannot_retry_directly():
    with pytest.raises(InvalidTransition):
        transition(ExternalOperationStatus.UNKNOWN, ExternalOperationStatus.EXECUTING, OPERATION_TRANSITIONS)
