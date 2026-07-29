from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from workbuddy.db.models import (
    AgentProfile, AgentRun, ApprovalDecision, ApprovalRequest, Artifact, CollaborationRequest, DispatchDecision, DispatchFeedback,
    Evidence, MailMessage, Mission, TeamConstitutionVersion, TeamDefinition, ToolGrant,
    WorkItem, WorkItemDependency, WorkflowVersion,
)
from workbuddy.domain.state_machine import (
    AGENT_RUN_TRANSITIONS, APPROVAL_TRANSITIONS, COLLABORATION_REQUEST_TRANSITIONS, MISSION_TRANSITIONS,
    WORK_ITEM_TRANSITIONS, AgentRunStatus, ApprovalStatus, CollaborationRequestStatus,
    MissionStatus, WorkItemStatus, transition,
)
from .audit import append_audit
from .common import content_hash, model_dict, utcnow
from .dispatch import propose_dispatch
from .planner import build_plan
from .tools import create_run_grants, revoke_run_grants
from .control import assert_not_paused
from .quality import QualityGateError, require_work_item_quality


class BusinessError(ValueError):
    pass


class ConflictError(BusinessError):
    pass


def _mission_transition(session: Session, mission: Mission, target: MissionStatus, actor: str, reason: str) -> Mission:
    current = MissionStatus(mission.status)
    mission.status = transition(current, target, MISSION_TRANSITIONS).value
    mission.version += 1
    append_audit(session, tenant_id=mission.tenant_id, actor_type="user" if actor == "owner" else "service",
                 actor_id=actor, action=f"mission.{target.value.lower()}", aggregate_type="mission",
                 aggregate_id=mission.id, aggregate_version=mission.version, payload={"from": current.value, "to": target.value, "reason": reason})
    return mission


def _work_transition(session: Session, item: WorkItem, target: WorkItemStatus, actor: str, reason: str) -> WorkItem:
    current = WorkItemStatus(item.status)
    item.status = transition(current, target, WORK_ITEM_TRANSITIONS).value
    item.version += 1
    append_audit(session, tenant_id=item.tenant_id, actor_type="agent" if actor.startswith("agent:") else "service",
                 actor_id=actor, action=f"work_item.{target.value.lower()}", aggregate_type="work_item",
                 aggregate_id=item.id, aggregate_version=item.version, payload={"from": current.value, "to": target.value, "reason": reason})
    return item


def _run_transition(session: Session, run: AgentRun, target: AgentRunStatus, actor: str, reason: str) -> AgentRun:
    current = AgentRunStatus(run.status)
    run.status = transition(current, target, AGENT_RUN_TRANSITIONS).value
    run.version += 1
    append_audit(session, tenant_id=run.tenant_id, actor_type="agent", actor_id=actor,
                 action=f"agent_run.{target.value.lower()}", aggregate_type="agent_run",
                 aggregate_id=run.id, aggregate_version=run.version, payload={"from": current.value, "to": target.value, "reason": reason})
    return run


def _collaboration_transition(session: Session, request: CollaborationRequest, target: CollaborationRequestStatus, actor: str, reason: str) -> CollaborationRequest:
    current = CollaborationRequestStatus(request.status)
    request.status = transition(current, target, COLLABORATION_REQUEST_TRANSITIONS).value
    append_audit(session, tenant_id=request.tenant_id, actor_type="agent" if actor.startswith("agent:") else "service",
                 actor_id=actor, action=f"collaboration.{target.value.lower()}", aggregate_type="collaboration_request",
                 aggregate_id=request.id, payload={"from": current.value, "to": target.value, "reason": reason})
    return request


def _get_collaboration(session: Session, collaboration_id: str) -> CollaborationRequest:
    request = session.scalar(select(CollaborationRequest).where(CollaborationRequest.id == collaboration_id))
    if not request:
        raise BusinessError("collaboration request not found")
    return request


_SUPPORTING_TEAMS_PREFIX = "__supporting_teams__:"


def _extract_supporting_team_keys(decision: DispatchDecision) -> list[str]:
    """Recover LLM-provided supporting team keys encoded into DispatchDecision.reasons.

    The DispatchDecision schema has no dedicated column for supporting_team_keys, so the
    keys are persisted as a single structured marker entry appended to ``reasons`` and
    stripped back out when confirm_dispatch consumes them.
    """
    keys: list[str] = []
    remaining: list[str] = []
    for reason in decision.reasons or []:
        if isinstance(reason, str) and reason.startswith(_SUPPORTING_TEAMS_PREFIX):
            raw = reason[len(_SUPPORTING_TEAMS_PREFIX):]
            keys.extend(k for k in raw.split(",") if k)
        else:
            remaining.append(reason)
    if keys:
        decision.reasons = remaining
    return keys


def _mail_datetime(value) -> datetime:
    if value is None:
        return utcnow()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return utcnow()
    return utcnow()


def ingest_mail(session: Session, tenant_id: str, payload: dict, actor: str = "mail-simulator") -> MailMessage:
    provider_id = payload["provider_message_id"]
    raw = {k: payload.get(k) for k in [
        "provider_thread_id", "rfc_message_id", "sender", "recipients", "subject",
        "body_text", "body_html", "received_at", "direction", "labels", "has_attachments",
    ]}
    new_hash = content_hash(raw)
    existing = session.scalar(select(MailMessage).where(
        MailMessage.tenant_id == tenant_id,
        MailMessage.provider_message_id == provider_id,
    ))
    if existing:
        changed = existing.content_hash != new_hash or existing.provider_deleted
        existing.provider_thread_id = payload.get("provider_thread_id") or existing.provider_thread_id
        existing.rfc_message_id = payload.get("rfc_message_id") or existing.rfc_message_id
        existing.sender = payload.get("sender", existing.sender)
        existing.recipients = payload.get("recipients", existing.recipients)
        existing.subject = payload.get("subject", existing.subject)
        existing.body_text = payload.get("body_text", existing.body_text)
        existing.body_html = payload.get("body_html", existing.body_html)
        existing.received_at = _mail_datetime(payload.get("received_at") or existing.received_at)
        existing.direction = payload.get("direction", existing.direction)
        existing.labels = payload.get("labels", existing.labels)
        existing.has_attachments = bool(payload.get("has_attachments", existing.has_attachments))
        existing.provider_deleted = False
        existing.processing_status = "UPDATED" if changed else existing.processing_status
        existing.content_hash = new_hash
        if changed:
            append_audit(session, tenant_id=tenant_id, actor_type="service", actor_id=actor,
                         action="mail.message_updated", aggregate_type="mail_message", aggregate_id=existing.id,
                         payload={"provider_message_id": provider_id, "subject": existing.subject})
        return existing
    message = MailMessage(
        tenant_id=tenant_id,
        provider_message_id=provider_id,
        provider_thread_id=payload.get("provider_thread_id"),
        rfc_message_id=payload.get("rfc_message_id"),
        sender=payload.get("sender") or "unknown", recipients=payload.get("recipients", []),
        subject=payload.get("subject") or "(no subject)", body_text=payload.get("body_text") or "(empty message)", body_html=payload.get("body_html"),
        received_at=_mail_datetime(payload.get("received_at")), content_hash=new_hash, processing_status="NEW",
        direction=payload.get("direction", "inbound"), labels=payload.get("labels", []),
        has_attachments=bool(payload.get("has_attachments", False)), provider_deleted=False,
    )
    session.add(message); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="service", actor_id=actor,
                 action="mail.message_ingested", aggregate_type="mail_message", aggregate_id=message.id,
                 payload={"provider_message_id": provider_id, "subject": message.subject})
    return message


def create_dispatch(session: Session, tenant_id: str, mail_id: str) -> DispatchDecision:
    message = session.scalar(select(MailMessage).where(MailMessage.id == mail_id, MailMessage.tenant_id == tenant_id))
    if not message:
        raise BusinessError("mail message not found")
    if message.provider_deleted:
        raise BusinessError("provider-deleted mail cannot be dispatched")
    existing = session.scalar(select(DispatchDecision).where(DispatchDecision.mail_message_id == message.id, DispatchDecision.status == "PROPOSED"))
    if existing:
        return existing
    proposal = propose_dispatch(session, tenant_id, message)
    reasons = list(proposal["reasons"])
    supporting_keys = list(proposal.get("supporting_team_keys", []))
    if supporting_keys:
        # Persist supporting team keys alongside reasons so confirm_dispatch can auto-open
        # collaboration requests without re-invoking the model. See _extract_supporting_team_keys.
        reasons.append(f"{_SUPPORTING_TEAMS_PREFIX}{','.join(supporting_keys)}")
    decision = DispatchDecision(
        tenant_id=tenant_id, mail_message_id=message.id,
        suggested_team_id=proposal["team"].id,
        suggested_workflow_id=proposal["workflow"].id if proposal["workflow"] else None,
        business_type=proposal["business_type"], risk_level=proposal["risk_level"],
        confidence=proposal["confidence"], reasons=reasons,
        missing_information=proposal["missing_information"], status="PROPOSED",
        model_invocation_id=proposal.get("model_invocation_id"), review_required=proposal.get("review_required", True),
    )
    message.processing_status = "DISPATCH_PROPOSED"
    session.add(decision); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="service", actor_id="dispatcher",
                 action="dispatch.proposed", aggregate_type="dispatch_decision", aggregate_id=decision.id,
                 payload={"mail_message_id": message.id, "suggested_team_id": decision.suggested_team_id,
                          "risk_level": decision.risk_level, "confidence": decision.confidence})
    return decision


def confirm_dispatch(session: Session, tenant_id: str, decision_id: str, team_key: str | None, workflow_key: str | None, actor: str = "owner") -> Mission:
    decision = session.scalar(select(DispatchDecision).where(DispatchDecision.id == decision_id, DispatchDecision.tenant_id == tenant_id))
    if not decision:
        raise BusinessError("dispatch decision not found")
    message = session.get(MailMessage, decision.mail_message_id)
    team = session.scalar(select(TeamDefinition).where(TeamDefinition.tenant_id == tenant_id, TeamDefinition.team_key == team_key)) if team_key else session.get(TeamDefinition, decision.suggested_team_id)
    if not team:
        raise BusinessError("team not found")
    workflow = session.scalar(select(WorkflowVersion).where(WorkflowVersion.team_id == team.id, WorkflowVersion.workflow_key == workflow_key, WorkflowVersion.status == "published").order_by(WorkflowVersion.version.desc()).limit(1)) if workflow_key else session.get(WorkflowVersion, decision.suggested_workflow_id) if decision.suggested_workflow_id else None
    if not workflow:
        workflow = session.scalar(select(WorkflowVersion).where(WorkflowVersion.team_id == team.id, WorkflowVersion.status == "published").order_by(WorkflowVersion.workflow_key).limit(1))
    constitution = session.scalar(select(TeamConstitutionVersion).where(TeamConstitutionVersion.team_id == team.id, TeamConstitutionVersion.status == "published").order_by(TeamConstitutionVersion.version.desc()).limit(1))
    lead = session.scalar(select(AgentProfile).where(AgentProfile.team_id == team.id, AgentProfile.is_lead.is_(True), AgentProfile.status == "active"))
    mission = session.scalar(select(Mission).where(Mission.tenant_id == tenant_id, Mission.source_type == "email", Mission.source_id == message.id))
    if mission:
        return mission
    mission = Mission(
        tenant_id=tenant_id, source_type="email", source_id=message.id, title=message.subject,
        objective=f"由 {team.name} 处理邮件并形成可验收成果：{message.subject}",
        risk_level=decision.risk_level, status=MissionStatus.INGESTED.value,
        primary_team_id=team.id, lead_agent_profile_id=lead.id if lead else None,
        constitution_version_id=constitution.id if constitution else None,
        workflow_version_id=workflow.id if workflow else None,
    )
    session.add(mission); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="service", actor_id="dispatcher",
                 action="mission.created", aggregate_type="mission", aggregate_id=mission.id,
                 aggregate_version=mission.version, payload={"source_id": message.id, "team_id": team.id})
    _mission_transition(session, mission, MissionStatus.DISPATCH_REVIEW, actor, "老板确认调度建议")
    _mission_transition(session, mission, MissionStatus.ROUTED, actor, "任务进入专家团主理人队列")
    decision.status = "CONFIRMED"; decision.confirmed_team_id = team.id; decision.confirmed_workflow_id = workflow.id if workflow else None
    session.add(DispatchFeedback(tenant_id=tenant_id, dispatch_decision_id=decision.id, suggested_team_id=decision.suggested_team_id, confirmed_team_id=team.id, suggested_risk_level=decision.risk_level, corrected_risk_level=None, actor_id=actor, comment="owner confirmed or corrected shadow routing"))
    _auto_create_collaboration_requests(session, tenant_id, mission, team, decision, actor)
    message.processing_status = "ROUTED"
    return mission


def _auto_create_collaboration_requests(session: Session, tenant_id: str, mission: Mission, primary_team: TeamDefinition, decision: DispatchDecision, actor: str) -> list[CollaborationRequest]:
    """Open a PENDING CollaborationRequest toward each supporting team the LLM identified.

    Supporting team keys are recovered from the structured marker persisted in
    ``DispatchDecision.reasons`` (see ``create_dispatch``). Requests are idempotent: a
    pre-existing PENDING request for the same mission + receiving team is reused so that
    re-confirming a dispatch does not duplicate collaboration work.
    """
    supporting_team_keys = _extract_supporting_team_keys(decision)
    if not supporting_team_keys:
        return []
    created: list[CollaborationRequest] = []
    for team_key in supporting_team_keys:
        supporting_team = session.scalar(select(TeamDefinition).where(
            TeamDefinition.tenant_id == tenant_id, TeamDefinition.team_key == team_key,
        ))
        if not supporting_team or supporting_team.id == primary_team.id:
            continue
        existing = session.scalar(select(CollaborationRequest).where(
            CollaborationRequest.mission_id == mission.id,
            CollaborationRequest.receiving_team_id == supporting_team.id,
            CollaborationRequest.status == CollaborationRequestStatus.PENDING.value,
        ))
        if existing:
            created.append(existing)
            continue
        request = CollaborationRequest(
            tenant_id=tenant_id, mission_id=mission.id,
            sending_team_id=primary_team.id, receiving_team_id=supporting_team.id,
            objective=f"协助处理 {decision.business_type} 相关子任务",
            input_scope={"source_mission_id": mission.id, "business_type": decision.business_type, "dispatch_decision_id": decision.id},
            expected_artifact="支持团队的调查结果或交付物",
            status=CollaborationRequestStatus.PENDING.value,
        )
        session.add(request); session.flush()
        append_audit(session, tenant_id=tenant_id, actor_type="service", actor_id="dispatcher",
                     action="collaboration.auto_requested", aggregate_type="collaboration_request", aggregate_id=request.id,
                     payload={"mission_id": mission.id, "sending_team_id": primary_team.id, "receiving_team_id": supporting_team.id, "team_key": team_key})
        created.append(request)
    return created


def accept_mission(session: Session, tenant_id: str, mission_id: str, expected_version: int, actor: str = "lead") -> Mission:
    mission = _get_mission(session, tenant_id, mission_id)
    _version(mission.version, expected_version)
    return _mission_transition(session, mission, MissionStatus.LEAD_TRIAGE, actor, "主理人接单并核验归属")


def plan_mission(session: Session, tenant_id: str, mission_id: str, expected_version: int, workflow_key: str | None = None, actor: str = "lead") -> Mission:
    mission = _get_mission(session, tenant_id, mission_id)
    _version(mission.version, expected_version)
    if mission.status == MissionStatus.LEAD_TRIAGE.value:
        _mission_transition(session, mission, MissionStatus.PLANNING, actor, "主理人开始规划")
    elif mission.status != MissionStatus.PLANNING.value:
        raise BusinessError("mission is not ready for planning")
    workflow = session.get(WorkflowVersion, mission.workflow_version_id) if mission.workflow_version_id else None
    if workflow_key:
        workflow = session.scalar(select(WorkflowVersion).where(WorkflowVersion.team_id == mission.primary_team_id, WorkflowVersion.workflow_key == workflow_key, WorkflowVersion.status == "published").order_by(WorkflowVersion.version.desc()).limit(1))
    if not workflow:
        raise BusinessError("published workflow not found")
    mission.workflow_version_id = workflow.id
    build_plan(session, tenant_id, mission.id, workflow, mission.primary_team_id, mission.objective)
    mission.plan_version += 1; mission.version += 1
    append_audit(session, tenant_id=tenant_id, actor_type="agent", actor_id=actor,
                 action="mission.plan_created", aggregate_type="mission", aggregate_id=mission.id,
                 aggregate_version=mission.version, payload={"plan_version": mission.plan_version, "workflow_id": workflow.id})
    return mission


def approve_plan(session: Session, tenant_id: str, mission_id: str, expected_version: int, actor: str = "owner") -> Mission:
    mission = _get_mission(session, tenant_id, mission_id); _version(mission.version, expected_version)
    items = session.scalars(select(WorkItem).where(WorkItem.mission_id == mission.id).order_by(WorkItem.sequence)).all()
    if not items:
        raise BusinessError("mission plan has no work items")
    deps = session.scalars(select(WorkItemDependency).where(WorkItemDependency.tenant_id == tenant_id)).all()
    dependent_ids = {d.work_item_id for d in deps if any(i.id == d.work_item_id for i in items)}
    for item in items:
        _work_transition(session, item, WorkItemStatus.READY, actor, "计划获批")
        if item.id in dependent_ids:
            _work_transition(session, item, WorkItemStatus.WAITING_DEPENDENCY, actor, "等待前置工作项")
    return _mission_transition(session, mission, MissionStatus.READY, actor, "老板批准任务清单")


def start_execution(session: Session, tenant_id: str, mission_id: str, expected_version: int, actor: str = "lead") -> Mission:
    mission = _get_mission(session, tenant_id, mission_id); _version(mission.version, expected_version)
    assert_not_paused(session, tenant_id, mission)
    return _mission_transition(session, mission, MissionStatus.EXECUTING, actor, "主理人启动执行")


def start_work_item(session: Session, tenant_id: str, work_item_id: str, actor: str = "lead") -> AgentRun:
    item = _get_work_item(session, tenant_id, work_item_id)
    assert_not_paused(session, tenant_id, _get_mission(session, tenant_id, item.mission_id))
    deps = session.scalars(select(WorkItemDependency).where(WorkItemDependency.work_item_id == item.id)).all()
    if deps:
        dep_items = session.scalars(select(WorkItem).where(WorkItem.id.in_([d.depends_on_id for d in deps]))).all()
        if any(d.status != WorkItemStatus.ACCEPTED.value for d in dep_items):
            raise ConflictError("work item dependencies are not accepted")
        if item.status == WorkItemStatus.WAITING_DEPENDENCY.value:
            _work_transition(session, item, WorkItemStatus.ASSIGNED, actor, "依赖已满足")
    elif item.status == WorkItemStatus.READY.value:
        _work_transition(session, item, WorkItemStatus.ASSIGNED, actor, "分派给长期 AgentProfile")
    elif item.status == WorkItemStatus.REVISION_REQUIRED.value:
        _work_transition(session, item, WorkItemStatus.ASSIGNED, actor, "创建返工运行实例")
    elif item.status == WorkItemStatus.BLOCKED.value:
        _work_transition(session, item, WorkItemStatus.ASSIGNED, actor, "主理人确认解除阻塞并创建新的运行实例")
    elif item.status == WorkItemStatus.ASSIGNED.value:
        pass
    else:
        raise BusinessError(f"work item cannot start from {item.status}")
    _work_transition(session, item, WorkItemStatus.RUNNING, actor, "启动任务级 AgentRun")
    run = AgentRun(
        tenant_id=tenant_id, mission_id=item.mission_id, work_item_id=item.id,
        agent_profile_id=item.assigned_agent_profile_id, skill_release_id=item.skill_release_id,
        status=AgentRunStatus.CREATED.value, data_scope="current_mission",
        budget={"max_steps": 12, "max_tool_calls": 8, "timeout_seconds": 600},
        input_snapshot=item.input_snapshot,
    )
    session.add(run); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="service", actor_id="agent-runtime",
                 action="agent_run.created", aggregate_type="agent_run", aggregate_id=run.id,
                 payload={"work_item_id": item.id, "agent_profile_id": run.agent_profile_id, "skill_release_id": run.skill_release_id})
    create_run_grants(session, run)
    _run_transition(session, run, AgentRunStatus.CONTEXT_PREPARED, f"agent:{run.agent_profile_id}", "准备任务隔离上下文与任务级工具授权")
    _run_transition(session, run, AgentRunStatus.RUNNING, f"agent:{run.agent_profile_id}", "开始执行")
    return run


def submit_agent_run(session: Session, tenant_id: str, run_id: str, output: dict, evidence_claims: list[dict] | None = None) -> AgentRun:
    run = session.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.tenant_id == tenant_id))
    if not run: raise BusinessError("agent run not found")
    if run.status != AgentRunStatus.RUNNING.value: raise BusinessError("agent run is not running")
    run.output = output
    _run_transition(session, run, AgentRunStatus.OUTPUT_SUBMITTED, f"agent:{run.agent_profile_id}", "提交结构化成果")
    artifact = Artifact(
        tenant_id=tenant_id, mission_id=run.mission_id, work_item_id=run.work_item_id, agent_run_id=run.id,
        artifact_type=output.get("type", "analysis"), title=output.get("title", "Agent 成果"),
        content=output, content_hash=content_hash(output),
    )
    session.add(artifact); session.flush()
    for claim in evidence_claims or []:
        session.add(Evidence(
            tenant_id=tenant_id, mission_id=run.mission_id, artifact_id=artifact.id,
            claim=claim["claim"], source_type=claim.get("source_type", "mail"),
            source_id=claim.get("source_id", "mission-source"), source_excerpt=claim.get("source_excerpt"),
            verification_status=claim.get("verification_status", "unverified"), confidence=int(claim.get("confidence", 60)),
            source_hash=content_hash(claim),
        ))
    _run_transition(session, run, AgentRunStatus.CLOSED, f"agent:{run.agent_profile_id}", "成果已保存，销毁临时运行上下文")
    revoke_run_grants(session, run)
    run.context_cleared = True; run.close_reason = "output_saved_and_temporary_context_cleared"
    item = _get_work_item(session, tenant_id, run.work_item_id)
    _work_transition(session, item, WorkItemStatus.SUBMITTED, f"agent:{run.agent_profile_id}", "等待主理人验收")
    return run


def review_work_item(session: Session, tenant_id: str, work_item_id: str, decision: str, reason: str, actor: str = "lead") -> WorkItem:
    item = _get_work_item(session, tenant_id, work_item_id)
    if item.status != WorkItemStatus.SUBMITTED.value: raise BusinessError("work item is not submitted")
    if decision == "accept":
        try:
            require_work_item_quality(session, tenant_id, work_item_id)
        except QualityGateError as exc:
            raise BusinessError(str(exc)) from exc
    target = WorkItemStatus.ACCEPTED if decision == "accept" else WorkItemStatus.REVISION_REQUIRED
    _work_transition(session, item, target, actor, reason)
    if target == WorkItemStatus.ACCEPTED:
        blocked = session.scalars(select(WorkItemDependency).where(WorkItemDependency.depends_on_id == item.id)).all()
        for dep in blocked:
            downstream = session.get(WorkItem, dep.work_item_id)
            all_deps = session.scalars(select(WorkItemDependency).where(WorkItemDependency.work_item_id == downstream.id)).all()
            dep_items = session.scalars(select(WorkItem).where(WorkItem.id.in_([d.depends_on_id for d in all_deps]))).all()
            if all(d.status == WorkItemStatus.ACCEPTED.value for d in dep_items) and downstream.status == WorkItemStatus.WAITING_DEPENDENCY.value:
                _work_transition(session, downstream, WorkItemStatus.ASSIGNED, actor, "全部依赖已验收，可启动")
    return item


def lead_review_mission(session: Session, tenant_id: str, mission_id: str, expected_version: int, actor: str = "lead") -> tuple[Mission, ApprovalRequest | None]:
    mission = _get_mission(session, tenant_id, mission_id); _version(mission.version, expected_version)
    items = session.scalars(select(WorkItem).where(WorkItem.mission_id == mission.id)).all()
    if not items or any(i.status != WorkItemStatus.ACCEPTED.value for i in items):
        raise ConflictError("all work items must be accepted before mission review")
    _mission_transition(session, mission, MissionStatus.LEAD_REVIEW, actor, "主理人整合所有成果")
    high_risk = mission.risk_level in {"high", "critical"}
    if not high_risk:
        return _mission_transition(session, mission, MissionStatus.COMPLETED, actor, "内部低风险成果完成"), None
    _mission_transition(session, mission, MissionStatus.APPROVAL_REQUIRED, actor, "高风险外部动作需要老板审批")
    source = session.get(MailMessage, mission.source_id) if mission.source_type == "email" else None
    recipient = source.sender if source else ""
    from email.utils import parseaddr
    recipient_address = parseaddr(recipient)[1] or recipient
    artifacts = session.scalars(select(Artifact).where(Artifact.mission_id == mission.id).order_by(Artifact.created_at)).all()
    summaries = [str((a.content or {}).get("summary", a.title)) for a in artifacts]
    body_text = "您好，\n\n" + "\n\n".join(summaries[-3:]) + "\n\n以上内容由 WorkBuddy 专家团整理，并已由主理人复核。"
    exact_action = {
        "type": "email_send", "mission_id": mission.id, "account_id": source.account_id if source else None,
        "provider_thread_id": source.provider_thread_id if source else None,
        "in_reply_to": source.rfc_message_id if source else None, "references": source.rfc_message_id if source else None,
        "to": [recipient_address] if recipient_address else [], "cc": [], "bcc": [],
        "subject": f"Re: {mission.title}", "body_text": body_text, "body_html": None, "attachments": [],
        "content_version": mission.version, "evidence_count": session.scalar(select(func.count()).select_from(Evidence).where(Evidence.mission_id == mission.id)) or 0,
    }
    approval = ApprovalRequest(
        tenant_id=tenant_id, mission_id=mission.id, status=ApprovalStatus.PENDING.value,
        decision_question="是否批准执行此精确邮件发送动作？",
        recommendation="批准前核对收件人、正文、金额、日期、承诺与附件。真实发送仅在独立发送权限和白名单均启用时发生。",
        alternatives=[{"key": "revise", "label": "退回主理人修改"}, {"key": "no_send", "label": "仅保留内部成果"}],
        exact_action=exact_action, content_hash=content_hash(exact_action), mission_version=mission.version,
        expires_at=utcnow() + timedelta(days=2),
    )
    session.add(approval); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="agent", actor_id=actor,
                 action="approval.requested", aggregate_type="approval_request", aggregate_id=approval.id,
                 payload={"mission_id": mission.id, "content_hash": approval.content_hash})
    return mission, approval


def decide_approval(session: Session, tenant_id: str, approval_id: str, decision: str, reason: str, actor: str = "owner") -> ApprovalRequest:
    approval = session.scalar(select(ApprovalRequest).where(ApprovalRequest.id == approval_id, ApprovalRequest.tenant_id == tenant_id))
    if not approval: raise BusinessError("approval not found")
    mission = _get_mission(session, tenant_id, approval.mission_id)
    if mission.version != approval.mission_version:
        approval.status = ApprovalStatus.INVALIDATED.value
        append_audit(session, tenant_id=tenant_id, actor_type="service", actor_id="approval-policy",
                     action="approval.invalidated", aggregate_type="approval_request", aggregate_id=approval.id,
                     payload={"reason": "mission version changed"})
        raise ConflictError("approval invalidated because mission version changed")
    target = ApprovalStatus.APPROVED if decision == "approve" else ApprovalStatus.REJECTED if decision == "reject" else ApprovalStatus.CHANGES_REQUESTED
    approval.status = transition(ApprovalStatus(approval.status), target, APPROVAL_TRANSITIONS).value
    session.add(ApprovalDecision(tenant_id=tenant_id, approval_request_id=approval.id, decision=decision, actor_id=actor, reason=reason))
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor,
                 action="approval.decided", aggregate_type="approval_request", aggregate_id=approval.id,
                 payload={"decision": decision, "reason": reason})
    if target == ApprovalStatus.APPROVED:
        _mission_transition(session, mission, MissionStatus.APPROVED, actor, "老板批准精确动作版本")
    elif target in {ApprovalStatus.REJECTED, ApprovalStatus.CHANGES_REQUESTED}:
        _mission_transition(session, mission, MissionStatus.EXECUTING, actor, "退回专家团修改")
    return approval


def _get_mission(session: Session, tenant_id: str, mission_id: str) -> Mission:
    mission = session.scalar(select(Mission).where(Mission.id == mission_id, Mission.tenant_id == tenant_id))
    if not mission: raise BusinessError("mission not found")
    return mission


def _get_work_item(session: Session, tenant_id: str, item_id: str) -> WorkItem:
    item = session.scalar(select(WorkItem).where(WorkItem.id == item_id, WorkItem.tenant_id == tenant_id))
    if not item: raise BusinessError("work item not found")
    return item


def _version(current: int, expected: int) -> None:
    if current != expected: raise ConflictError(f"version conflict: current={current}, expected={expected}")


# ---------------------------------------------------------------------------
# Cross-team collaboration lifecycle (dispatch → accept → execute → artifact)
# ---------------------------------------------------------------------------

def accept_collaboration(session: Session, collaboration_id: str, actor_id: str) -> CollaborationRequest:
    request = _get_collaboration(session, collaboration_id)
    if request.status != CollaborationRequestStatus.PENDING.value:
        raise BusinessError(f"collaboration request cannot be accepted from {request.status}")
    _collaboration_transition(session, request, CollaborationRequestStatus.ACCEPTED, actor_id, "接收团队接受协作请求")
    return request


def decline_collaboration(session: Session, collaboration_id: str, actor_id: str, reason: str) -> CollaborationRequest:
    request = _get_collaboration(session, collaboration_id)
    if request.status not in {CollaborationRequestStatus.PENDING.value, CollaborationRequestStatus.ACCEPTED.value}:
        raise BusinessError(f"collaboration request cannot be declined from {request.status}")
    _collaboration_transition(session, request, CollaborationRequestStatus.DECLINED, actor_id, reason)
    request.response_reason = reason
    return request


def start_collaboration_work(session: Session, collaboration_id: str) -> CollaborationRequest:
    request = _get_collaboration(session, collaboration_id)
    if request.status != CollaborationRequestStatus.ACCEPTED.value:
        raise BusinessError(f"collaboration request cannot start from {request.status}")
    _collaboration_transition(session, request, CollaborationRequestStatus.IN_PROGRESS, "service", "接收团队开始执行协作子任务")
    return request


def complete_collaboration_with_artifact(session: Session, collaboration_id: str, artifact_id: str, actor_id: str) -> CollaborationRequest:
    request = _get_collaboration(session, collaboration_id)
    if request.status != CollaborationRequestStatus.IN_PROGRESS.value:
        raise BusinessError(f"collaboration request cannot be completed from {request.status}")
    artifact = session.scalar(select(Artifact).where(
        Artifact.id == artifact_id, Artifact.tenant_id == request.tenant_id, Artifact.mission_id == request.mission_id,
    ))
    if not artifact:
        raise BusinessError("artifact not found in collaboration mission scope")
    _collaboration_transition(session, request, CollaborationRequestStatus.COMPLETED, actor_id, "接收团队回传协作 Artifact")
    response = dict(request.response or {})
    response.update({
        "artifact_id": artifact.id,
        "artifact_title": artifact.title,
        "artifact_type": artifact.artifact_type,
    })
    request.response = response
    request.response_reason = "协作完成并已回传 Artifact"
    return request


def get_collaboration_artifacts(session: Session, mission_id: str) -> list[dict[str, Any]]:
    """Return completed collaboration requests and their linked artifacts for a mission.

    The primary team's lead can use this to manually reference supporting-team deliverables
    when planning downstream WorkItems (e.g. by recording the collaboration_id and
    artifact_id in WorkItem.input_snapshot or Evidence).
    """
    requests = session.scalars(select(CollaborationRequest).where(
        CollaborationRequest.mission_id == mission_id,
        CollaborationRequest.status == CollaborationRequestStatus.COMPLETED.value,
    ).order_by(CollaborationRequest.updated_at.desc())).all()
    result: list[dict[str, Any]] = []
    for req in requests:
        artifact_id = (req.response or {}).get("artifact_id") if req.response else None
        artifact = session.get(Artifact, artifact_id) if artifact_id else None
        result.append({
            "collaboration_id": req.id,
            "sending_team_id": req.sending_team_id,
            "receiving_team_id": req.receiving_team_id,
            "objective": req.objective,
            "expected_artifact": req.expected_artifact,
            "status": req.status,
            "artifact_id": artifact_id,
            "artifact": model_dict(artifact) if artifact else None,
        })
    return result


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
