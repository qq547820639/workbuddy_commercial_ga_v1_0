from __future__ import annotations

import sys
if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum
    class StrEnum(str, Enum):
        __str__ = str.__str__
from typing import Mapping, Set, TypeVar


class MissionStatus(StrEnum):
    INGESTED = "INGESTED"
    DISPATCH_REVIEW = "DISPATCH_REVIEW"
    ROUTED = "ROUTED"
    LEAD_TRIAGE = "LEAD_TRIAGE"
    PLANNING = "PLANNING"
    READY = "READY"
    EXECUTING = "EXECUTING"
    LEAD_REVIEW = "LEAD_REVIEW"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVED = "APPROVED"
    ACTION_EXECUTING = "ACTION_EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class WorkItemStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    WAITING_DEPENDENCY = "WAITING_DEPENDENCY"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AgentRunStatus(StrEnum):
    CREATED = "CREATED"
    CONTEXT_PREPARED = "CONTEXT_PREPARED"
    RUNNING = "RUNNING"
    TOOL_WAIT = "TOOL_WAIT"
    OUTPUT_SUBMITTED = "OUTPUT_SUBMITTED"
    CLOSED = "CLOSED"
    TIMED_OUT = "TIMED_OUT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    QUARANTINED = "QUARANTINED"


class ApprovalStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    CANCELLED = "CANCELLED"


class ExternalOperationStatus(StrEnum):
    PREPARED = "PREPARED"
    POLICY_REVIEWED = "POLICY_REVIEWED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"


class CollaborationRequestStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


MISSION_TRANSITIONS: Mapping[MissionStatus, Set[MissionStatus]] = {
    MissionStatus.INGESTED: {MissionStatus.DISPATCH_REVIEW, MissionStatus.CANCELLED},
    MissionStatus.DISPATCH_REVIEW: {MissionStatus.ROUTED, MissionStatus.NEEDS_INFORMATION, MissionStatus.CANCELLED},
    MissionStatus.ROUTED: {MissionStatus.LEAD_TRIAGE, MissionStatus.CANCELLED},
    MissionStatus.LEAD_TRIAGE: {MissionStatus.PLANNING, MissionStatus.NEEDS_INFORMATION, MissionStatus.BLOCKED, MissionStatus.CANCELLED},
    MissionStatus.PLANNING: {MissionStatus.READY, MissionStatus.NEEDS_INFORMATION, MissionStatus.BLOCKED, MissionStatus.CANCELLED},
    MissionStatus.READY: {MissionStatus.EXECUTING, MissionStatus.CANCELLED},
    MissionStatus.EXECUTING: {MissionStatus.LEAD_REVIEW, MissionStatus.BLOCKED, MissionStatus.FAILED, MissionStatus.CANCELLED},
    MissionStatus.LEAD_REVIEW: {MissionStatus.EXECUTING, MissionStatus.APPROVAL_REQUIRED, MissionStatus.COMPLETED, MissionStatus.BLOCKED, MissionStatus.CANCELLED},
    MissionStatus.APPROVAL_REQUIRED: {MissionStatus.APPROVED, MissionStatus.EXECUTING, MissionStatus.CANCELLED},
    MissionStatus.APPROVED: {MissionStatus.ACTION_EXECUTING, MissionStatus.CANCELLED},
    MissionStatus.ACTION_EXECUTING: {MissionStatus.VERIFYING, MissionStatus.FAILED, MissionStatus.UNKNOWN},
    MissionStatus.VERIFYING: {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.UNKNOWN},
    MissionStatus.NEEDS_INFORMATION: {MissionStatus.LEAD_TRIAGE, MissionStatus.PLANNING, MissionStatus.CANCELLED},
    MissionStatus.BLOCKED: {MissionStatus.LEAD_TRIAGE, MissionStatus.PLANNING, MissionStatus.EXECUTING, MissionStatus.CANCELLED},
    MissionStatus.UNKNOWN: {MissionStatus.VERIFYING, MissionStatus.COMPLETED, MissionStatus.FAILED},
    MissionStatus.FAILED: set(), MissionStatus.CANCELLED: set(), MissionStatus.COMPLETED: set(),
}

WORK_ITEM_TRANSITIONS: Mapping[WorkItemStatus, Set[WorkItemStatus]] = {
    WorkItemStatus.DRAFT: {WorkItemStatus.READY, WorkItemStatus.CANCELLED},
    WorkItemStatus.READY: {WorkItemStatus.WAITING_DEPENDENCY, WorkItemStatus.ASSIGNED, WorkItemStatus.CANCELLED},
    WorkItemStatus.WAITING_DEPENDENCY: {WorkItemStatus.ASSIGNED, WorkItemStatus.BLOCKED, WorkItemStatus.CANCELLED},
    WorkItemStatus.ASSIGNED: {WorkItemStatus.RUNNING, WorkItemStatus.BLOCKED, WorkItemStatus.CANCELLED},
    WorkItemStatus.RUNNING: {WorkItemStatus.SUBMITTED, WorkItemStatus.BLOCKED, WorkItemStatus.FAILED, WorkItemStatus.CANCELLED},
    WorkItemStatus.SUBMITTED: {WorkItemStatus.ACCEPTED, WorkItemStatus.REVISION_REQUIRED, WorkItemStatus.BLOCKED},
    WorkItemStatus.REVISION_REQUIRED: {WorkItemStatus.ASSIGNED, WorkItemStatus.CANCELLED},
    WorkItemStatus.BLOCKED: {WorkItemStatus.READY, WorkItemStatus.ASSIGNED, WorkItemStatus.CANCELLED},
    WorkItemStatus.ACCEPTED: set(), WorkItemStatus.FAILED: set(), WorkItemStatus.CANCELLED: set(),
}

AGENT_RUN_TRANSITIONS: Mapping[AgentRunStatus, Set[AgentRunStatus]] = {
    AgentRunStatus.CREATED: {AgentRunStatus.CONTEXT_PREPARED, AgentRunStatus.CANCELLED},
    AgentRunStatus.CONTEXT_PREPARED: {AgentRunStatus.RUNNING, AgentRunStatus.CANCELLED, AgentRunStatus.QUARANTINED},
    AgentRunStatus.RUNNING: {AgentRunStatus.TOOL_WAIT, AgentRunStatus.OUTPUT_SUBMITTED, AgentRunStatus.TIMED_OUT, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED, AgentRunStatus.QUARANTINED},
    AgentRunStatus.TOOL_WAIT: {AgentRunStatus.RUNNING, AgentRunStatus.TIMED_OUT, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED},
    AgentRunStatus.OUTPUT_SUBMITTED: {AgentRunStatus.CLOSED, AgentRunStatus.QUARANTINED},
    AgentRunStatus.TIMED_OUT: {AgentRunStatus.CLOSED},
    AgentRunStatus.FAILED: {AgentRunStatus.CLOSED},
    AgentRunStatus.CANCELLED: {AgentRunStatus.CLOSED},
    AgentRunStatus.QUARANTINED: {AgentRunStatus.CLOSED},
    AgentRunStatus.CLOSED: set(),
}

APPROVAL_TRANSITIONS: Mapping[ApprovalStatus, Set[ApprovalStatus]] = {
    ApprovalStatus.DRAFT: {ApprovalStatus.PENDING, ApprovalStatus.CANCELLED},
    ApprovalStatus.PENDING: {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.CHANGES_REQUESTED, ApprovalStatus.EXPIRED, ApprovalStatus.INVALIDATED, ApprovalStatus.CANCELLED},
    ApprovalStatus.CHANGES_REQUESTED: {ApprovalStatus.INVALIDATED},
    ApprovalStatus.APPROVED: {ApprovalStatus.INVALIDATED},
    ApprovalStatus.REJECTED: set(), ApprovalStatus.EXPIRED: set(), ApprovalStatus.INVALIDATED: set(), ApprovalStatus.CANCELLED: set(),
}

OPERATION_TRANSITIONS: Mapping[ExternalOperationStatus, Set[ExternalOperationStatus]] = {
    ExternalOperationStatus.PREPARED: {ExternalOperationStatus.POLICY_REVIEWED, ExternalOperationStatus.BLOCKED, ExternalOperationStatus.CANCELLED},
    ExternalOperationStatus.POLICY_REVIEWED: {ExternalOperationStatus.APPROVAL_REQUIRED, ExternalOperationStatus.APPROVED, ExternalOperationStatus.BLOCKED, ExternalOperationStatus.CANCELLED},
    ExternalOperationStatus.APPROVAL_REQUIRED: {ExternalOperationStatus.APPROVED, ExternalOperationStatus.BLOCKED, ExternalOperationStatus.CANCELLED},
    ExternalOperationStatus.APPROVED: {ExternalOperationStatus.EXECUTING, ExternalOperationStatus.CANCELLED},
    ExternalOperationStatus.EXECUTING: {ExternalOperationStatus.VERIFYING, ExternalOperationStatus.FAILED, ExternalOperationStatus.UNKNOWN},
    ExternalOperationStatus.VERIFYING: {ExternalOperationStatus.SUCCEEDED, ExternalOperationStatus.FAILED, ExternalOperationStatus.UNKNOWN},
    ExternalOperationStatus.UNKNOWN: {ExternalOperationStatus.VERIFYING, ExternalOperationStatus.SUCCEEDED, ExternalOperationStatus.FAILED},
    ExternalOperationStatus.BLOCKED: set(), ExternalOperationStatus.FAILED: set(), ExternalOperationStatus.SUCCEEDED: set(), ExternalOperationStatus.CANCELLED: set(),
}

COLLABORATION_REQUEST_TRANSITIONS: Mapping[CollaborationRequestStatus, Set[CollaborationRequestStatus]] = {
    CollaborationRequestStatus.PENDING: {CollaborationRequestStatus.ACCEPTED, CollaborationRequestStatus.DECLINED, CollaborationRequestStatus.CANCELLED},
    CollaborationRequestStatus.ACCEPTED: {CollaborationRequestStatus.IN_PROGRESS, CollaborationRequestStatus.DECLINED},
    CollaborationRequestStatus.IN_PROGRESS: {CollaborationRequestStatus.COMPLETED, CollaborationRequestStatus.FAILED, CollaborationRequestStatus.CANCELLED},
    CollaborationRequestStatus.COMPLETED: set(), CollaborationRequestStatus.DECLINED: set(), CollaborationRequestStatus.FAILED: set(), CollaborationRequestStatus.CANCELLED: set(),
}

S = TypeVar("S", bound=StrEnum)


class InvalidTransition(ValueError):
    pass


_TRANSITION_TABLES: Mapping[type, Mapping] = {
    MissionStatus: MISSION_TRANSITIONS,
    WorkItemStatus: WORK_ITEM_TRANSITIONS,
    AgentRunStatus: AGENT_RUN_TRANSITIONS,
    ApprovalStatus: APPROVAL_TRANSITIONS,
    ExternalOperationStatus: OPERATION_TRANSITIONS,
    CollaborationRequestStatus: COLLABORATION_REQUEST_TRANSITIONS,
}


def transition(current: S, target: S, table: Mapping[S, Set[S]] | None = None) -> S:
    if table is None:
        table = _TRANSITION_TABLES.get(type(current))
        if table is None:
            raise InvalidTransition(f"no transition table for {type(current).__name__}")
    if target not in table.get(current, set()):
        raise InvalidTransition(f"illegal transition: {current} -> {target}")
    return target
