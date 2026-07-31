from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from workbuddy.db.models import TeamConstitutionVersion, TeamDefinition
from ._transitions import BusinessError
from .audit import append_audit
from .common import content_hash


# ---------------------------------------------------------------------------
# Team constitution version lifecycle (draft → reviewing → approved → published)
# ---------------------------------------------------------------------------

# Inlined transitions: state_machine.py does not yet define a ConstitutionStatus
# machine, so legal transitions are validated here. A published version keeps its
# status forever; publishing a newer version simply supersedes it as the team's
# current charter (see confirm_dispatch, which resolves the max published version).
CONSTITUTION_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"reviewing"},
    "reviewing": {"approved"},
    "approved": {"published"},
    "published": set(),
}


def _get_constitution(session: Session, constitution_version_id: str) -> TeamConstitutionVersion:
    constitution = session.get(TeamConstitutionVersion, constitution_version_id)
    if not constitution:
        raise BusinessError("constitution version not found")
    return constitution


def _constitution_transition(session: Session, constitution: TeamConstitutionVersion, target: str, actor: str, reason: str) -> TeamConstitutionVersion:
    current = constitution.status
    if target not in CONSTITUTION_TRANSITIONS.get(current, set()):
        raise BusinessError(f"constitution cannot transition from {current} to {target}")
    constitution.status = target
    append_audit(session, tenant_id=constitution.tenant_id,
                 actor_type="user" if actor == "owner" else "service",
                 actor_id=actor, action=f"constitution.{target}", aggregate_type="team_constitution_version",
                 aggregate_id=constitution.id, aggregate_version=constitution.version,
                 payload={"from": current, "to": target, "reason": reason})
    return constitution


def create_constitution_draft(session: Session, team_id: str, config: dict[str, Any], actor_id: str) -> TeamConstitutionVersion:
    """Create a new draft constitution version for a team.

    The version number is computed as the team's current max version + 1. Existing
    published versions are left untouched; the draft only becomes the team's current
    charter once it reaches ``published`` and a newer Mission resolves it via
    ``confirm_dispatch``.
    """
    team = session.get(TeamDefinition, team_id)
    if not team:
        raise BusinessError("team not found")
    max_version = session.scalar(select(func.coalesce(func.max(TeamConstitutionVersion.version), 0)).where(TeamConstitutionVersion.team_id == team_id))
    new_version = int(max_version) + 1
    draft = TeamConstitutionVersion(
        tenant_id=team.tenant_id, team_id=team_id, version=new_version,
        status="draft", config=config, content_hash=content_hash(config),
    )
    session.add(draft); session.flush()
    append_audit(session, tenant_id=team.tenant_id,
                 actor_type="user" if actor_id == "owner" else "service",
                 actor_id=actor_id, action="constitution.draft_created", aggregate_type="team_constitution_version",
                 aggregate_id=draft.id, aggregate_version=draft.version,
                 payload={"team_id": team_id, "version": new_version})
    return draft


def submit_constitution_for_review(session: Session, constitution_version_id: str, actor_id: str) -> TeamConstitutionVersion:
    constitution = _get_constitution(session, constitution_version_id)
    return _constitution_transition(session, constitution, "reviewing", actor_id, "提交章程版本进入审核")


def approve_constitution(session: Session, constitution_version_id: str, actor_id: str) -> TeamConstitutionVersion:
    constitution = _get_constitution(session, constitution_version_id)
    return _constitution_transition(session, constitution, "approved", actor_id, "审核通过章程版本")


def publish_constitution(session: Session, constitution_version_id: str, actor_id: str) -> TeamConstitutionVersion:
    """Promote an approved constitution version to published.

    The newly published version becomes the team's current charter: subsequent
    Missions resolve it via ``confirm_dispatch`` (max published version). The previous
    published version keeps its status and remains bound to in-flight Missions via
    ``Mission.constitution_version_id`` — it is never rewritten here.
    """
    constitution = _get_constitution(session, constitution_version_id)
    return _constitution_transition(session, constitution, "published", actor_id, "发布章程版本成为团队当前生效章程")
