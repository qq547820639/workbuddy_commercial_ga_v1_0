from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from workbuddy.db.models import AgentRun, ApprovalRequest, Mission, WorkItem
from workbuddy.domain.state_machine import AGENT_RUN_TRANSITIONS, AgentRunStatus, ApprovalStatus, WorkItemStatus, transition
from .audit import append_audit


def scheduler_tick(session: Session, tenant_id: str) -> dict:
    now=datetime.now(timezone.utc); timed_out=expired=0
    runs=session.scalars(select(AgentRun).where(AgentRun.tenant_id==tenant_id,AgentRun.status.in_(["RUNNING","TOOL_WAIT"]))).all()
    for run in runs:
        updated=run.updated_at if run.updated_at.tzinfo else run.updated_at.replace(tzinfo=timezone.utc)
        timeout=int((run.budget or {}).get("timeout_seconds",600))
        if now>updated+timedelta(seconds=timeout):
            current=AgentRunStatus(run.status);run.status=transition(current,AgentRunStatus.TIMED_OUT,AGENT_RUN_TRANSITIONS).value;run.version+=1
            run.status=transition(AgentRunStatus.TIMED_OUT,AgentRunStatus.CLOSED,AGENT_RUN_TRANSITIONS).value;run.version+=1;run.context_cleared=True;run.close_reason="scheduler_timeout"
            item=session.get(WorkItem,run.work_item_id)
            if item and item.status==WorkItemStatus.RUNNING.value:item.status=WorkItemStatus.FAILED.value;item.version+=1
            append_audit(session,tenant_id=tenant_id,actor_type="service",actor_id="scheduler",action="agent_run.timed_out",aggregate_type="agent_run",aggregate_id=run.id,aggregate_version=run.version,payload={"timeout_seconds":timeout});timed_out+=1
    for approval in session.scalars(select(ApprovalRequest).where(ApprovalRequest.tenant_id==tenant_id,ApprovalRequest.status==ApprovalStatus.PENDING.value,ApprovalRequest.expires_at.is_not(None))).all():
        expires=approval.expires_at if approval.expires_at.tzinfo else approval.expires_at.replace(tzinfo=timezone.utc)
        if now>expires:
            approval.status=ApprovalStatus.EXPIRED.value;append_audit(session,tenant_id=tenant_id,actor_type="service",actor_id="scheduler",action="approval.expired",aggregate_type="approval_request",aggregate_id=approval.id,payload={});expired+=1
    ready=session.scalars(select(WorkItem).join(Mission,Mission.id==WorkItem.mission_id).where(WorkItem.tenant_id==tenant_id,Mission.status=="EXECUTING",WorkItem.status.in_(["READY","ASSIGNED"]))).all()
    session.commit();return {"timed_out_runs":timed_out,"expired_approvals":expired,"ready_work_items":[x.id for x in ready]}
