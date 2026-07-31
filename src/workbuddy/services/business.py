"""Compatibility re-export — import from the split service modules directly.

This module is kept for backward compatibility; new code should import from
``_transitions``, ``mission_service``, ``collaboration_service``, or
``constitution_service`` directly.
"""
from __future__ import annotations

from ._transitions import BusinessError, ConflictError, _collaboration_transition, _mission_transition, _run_transition, _work_transition
from .mission_service import (
    _auto_create_collaboration_requests, _extract_supporting_team_keys, _get_mission,
    _get_work_item, _mail_datetime, _SUPPORTING_TEAMS_PREFIX, _version,
    accept_mission, approve_plan, confirm_dispatch, create_dispatch, decide_approval,
    ingest_mail, lead_review_mission, plan_mission, review_work_item, start_execution,
    start_work_item, submit_agent_run,
)
from .collaboration_service import (
    _get_collaboration, accept_collaboration, complete_collaboration_with_artifact,
    decline_collaboration, get_collaboration_artifacts, request_collaboration,
    respond_collaboration, start_collaboration_work,
)
from .constitution_service import (
    CONSTITUTION_TRANSITIONS, _constitution_transition, _get_constitution,
    approve_constitution, create_constitution_draft, publish_constitution,
    submit_constitution_for_review,
)
