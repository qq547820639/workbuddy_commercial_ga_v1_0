from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from workbuddy.api.deps import TenantContext, actor_id, db_session, require_tenant, set_tenant_context, tenant_id
from workbuddy.api.schemas import (
    AgentOutputIn, ApprovalDecisionIn, CollaborationIn, CollaborationResponseIn, ControlIn, DeleteOperationalDataIn, DependencyIn, DispatchConfirmIn, MailIn, MemoryDecisionIn, MemoryProposalIn, OperationExecuteIn,
    OperationPrepareIn, OperationVerifyIn, PlanIn, ToolInvokeIn, VersionAction, WorkItemReviewIn, WorkItemUpdateIn,
)
from workbuddy.connectors.gmail import GmailConnector, GmailNotConfigured
from workbuddy.db.models import (
    AgentProfile, AgentRun, ApprovalDecision, ApprovalRequest, Artifact, AuditEvent, CollaborationRequest, DispatchDecision, DispatchFeedback, Evidence,
    ExternalOperation, MailAccount, MailMessage, MemoryRecord, Mission, ModelInvocation, OperationAttempt, OutboxEvent, ProviderWebhookEvent, QualityEvaluation, SkillDefinition, SkillRelease, SyncRun,
    SystemControl, TeamConstitutionVersion, TeamDefinition, ToolCall, ToolDefinition, ToolGrant, WebhookBinding, WorkItem, WorkItemDependency, WorkflowVersion,
)
from workbuddy.db.session import make_engine
from workbuddy.services.audit import append_audit, verify_audit_chain
from workbuddy.services._transitions import BusinessError, ConflictError
from workbuddy.services.mission_service import (
    accept_mission, approve_plan, confirm_dispatch, create_dispatch, decide_approval,
    ingest_mail, lead_review_mission, plan_mission, review_work_item, start_execution,
    start_work_item, submit_agent_run,
)
from workbuddy.services.collaboration_service import request_collaboration, respond_collaboration
from workbuddy.services.common import content_hash, model_dict, utcnow
from workbuddy.services.outbox import publish_batch
from workbuddy.services.seed import seed_all
from workbuddy.services.skills import SkillValidationError, import_skill, publish_skill
from workbuddy.services.tools import ToolPolicyError, invoke_tool
from workbuddy.services.governance import GovernanceError, add_dependency, decide_memory, propose_memory, remove_dependency, update_work_item
from workbuddy.services.lifecycle import delete_operational_data
from workbuddy.services.mail_sync import upsert_gmail_message
from workbuddy.services.control import PausedError, set_control
from workbuddy.services.context import correlation_id_var
from workbuddy.services.scheduler import scheduler_tick
from workbuddy.services.external_actions import prepare_external_operation, execute_external_operation, verify_unknown_external_operation
from workbuddy.settings import settings


def _serialize(obj: Any) -> dict[str, Any]:
    return model_dict(obj)


def create_app(database_url: str | None = None, auto_seed: bool = True) -> FastAPI:
    engine = make_engine(database_url)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from workbuddy.db.models import Base
        Base.metadata.create_all(engine)
        if auto_seed:
            with SessionFactory() as session:
                seed_all(session)
        yield
        engine.dispose()

    app = FastAPI(title="WorkBuddy Expert Team OS", version="1.0.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.SessionLocal = SessionFactory

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        if settings.environment.lower() in {"production", "prod"}:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
        token = correlation_id_var.set(correlation_id)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            correlation_id_var.reset(token)

    @app.exception_handler(BusinessError)
    async def handle_business(_request: Request, exc: BusinessError):
        from fastapi.responses import JSONResponse
        status = 409 if isinstance(exc, ConflictError) else 422
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.exception_handler(SkillValidationError)
    async def handle_skill(_request: Request, exc: SkillValidationError):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ToolPolicyError)
    @app.exception_handler(GovernanceError)
    @app.exception_handler(PausedError)
    async def handle_governance(_request: Request, exc: ValueError):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/")
    def index():
        path = Path(__file__).resolve().parents[1] / "web" / "index.html"
        return FileResponse(path)

    @app.get("/health")
    def health(session: Session = Depends(db_session)):
        session.execute(select(1))
        return {"status": "ok", "version": "1.0.0", "mode": "commercial-ga", "environment": settings.environment, "model_provider": settings.model_provider, "live_send_enabled": settings.enable_live_email_send, "auth_mode": settings.auth_mode}

    @app.get("/health/live")
    def health_live():
        return {"status": "alive", "version": "1.0.0"}

    @app.get("/health/ready")
    def health_ready(session: Session = Depends(db_session)):
        session.execute(select(1))
        problems = []
        if settings.environment.lower() in {"production", "prod"}:
            if settings.auth_mode == "local_headers": problems.append("production cannot use local_headers authentication")
            if not settings.public_base_url.startswith("https://"): problems.append("production public base URL must use HTTPS")
            if settings.database_url.startswith("sqlite"): problems.append("production must use PostgreSQL")
            if settings.app_secret.startswith("local-development") or len(settings.app_secret) < 32: problems.append("application secret is not production strength")
            if not settings.token_encryption_key: problems.append("token encryption key is missing")
        return {"status": "ready" if not problems else "not_ready", "problems": problems, "environment": settings.environment, "commercial": {"pricing_approved": settings.commercial_pricing_approved, "billing_provider": settings.billing_provider}}

    @app.get("/auth/config")
    def auth_config():
        return {"mode": settings.auth_mode, "issuer": settings.auth_oidc_issuer, "audience": settings.auth_oidc_audience, "tenant_claim": settings.auth_tenant_claim, "roles_claim": settings.auth_roles_claim}

    @app.get("/v1/dashboard")
    def dashboard(ctx: TenantContext = Depends()):
        teams = ctx.session.scalars(select(TeamDefinition).where(TeamDefinition.tenant_id == ctx.tenant_id).order_by(TeamDefinition.name)).all()
        cards = []
        for team in teams:
            missions = ctx.session.scalars(select(Mission).where(Mission.tenant_id == ctx.tenant_id, Mission.primary_team_id == team.id)).all()
            lead = ctx.session.scalar(select(AgentProfile).where(AgentProfile.team_id == team.id, AgentProfile.is_lead.is_(True)))
            cards.append({
                "id": team.id, "team_key": team.team_key, "name": team.name,
                "lead": lead.name if lead else "未配置",
                "lead_queue": sum(m.status in {"ROUTED", "LEAD_TRIAGE", "PLANNING"} for m in missions),
                "active": sum(m.status not in {"COMPLETED", "FAILED", "CANCELLED"} for m in missions),
                "approval_required": sum(m.status == "APPROVAL_REQUIRED" for m in missions),
                "missions": [{"id": m.id, "title": m.title, "status": m.status} for m in missions[:5]],
            })
        return {
            "teams": cards,
            "inbox_pending": ctx.session.scalar(select(func.count()).select_from(MailMessage).where(MailMessage.tenant_id == ctx.tenant_id, MailMessage.processing_status.in_(["NEW", "DISPATCH_PROPOSED"]))) or 0,
            "active_runs": ctx.session.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.tenant_id == ctx.tenant_id, AgentRun.status.in_(["RUNNING", "TOOL_WAIT"]))) or 0,
            "pending_approvals": ctx.session.scalar(select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.tenant_id == ctx.tenant_id, ApprovalRequest.status == "PENDING")) or 0,
            "outbox_pending": ctx.session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.tenant_id == ctx.tenant_id, OutboxEvent.published_at.is_(None), OutboxEvent.dead_lettered.is_(False))) or 0,
        }

    @app.get("/v1/teams")
    def teams(ctx: TenantContext = Depends()):
        result = []
        for team in ctx.session.scalars(select(TeamDefinition).where(TeamDefinition.tenant_id == ctx.tenant_id).order_by(TeamDefinition.name)).all():
            constitution = ctx.session.scalar(select(TeamConstitutionVersion).where(TeamConstitutionVersion.team_id == team.id).order_by(TeamConstitutionVersion.version.desc()).limit(1))
            agents = ctx.session.scalars(select(AgentProfile).where(AgentProfile.team_id == team.id).order_by(AgentProfile.is_lead.desc(), AgentProfile.name)).all()
            workflows = ctx.session.scalars(select(WorkflowVersion).where(WorkflowVersion.team_id == team.id).order_by(WorkflowVersion.name)).all()
            result.append({**_serialize(team), "constitution": constitution.config if constitution else None,
                           "agents": [_serialize(a) for a in agents], "workflows": [_serialize(w) for w in workflows]})
        return result

    @app.get("/v1/skills")
    def skills(ctx: TenantContext = Depends()):
        rows = ctx.session.execute(select(SkillDefinition, SkillRelease).join(SkillRelease, SkillRelease.skill_id == SkillDefinition.id).where(SkillDefinition.tenant_id == ctx.tenant_id).order_by(SkillDefinition.name, SkillRelease.semantic_version)).all()
        return [{"definition": _serialize(d), "release": _serialize(r)} for d, r in rows]

    @app.post("/v1/skills/upload", status_code=201)
    async def upload_skill(file: UploadFile = File(...), ctx: TenantContext = Depends()):
        release = import_skill(ctx.session, ctx.tenant_id, file.filename or "uploaded-skill.txt", await file.read(), ctx.actor)
        return _serialize(release)

    @app.post("/v1/skills/{release_id}/publish")
    def publish_skill_route(release_id: str, ctx: TenantContext = Depends()):
        release = publish_skill(ctx.session, ctx.tenant_id, release_id, ctx.actor); return _serialize(release)

    @app.get("/v1/inbox")
    def inbox(ctx: TenantContext = Depends()):
        messages = ctx.session.scalars(select(MailMessage).where(MailMessage.tenant_id == ctx.tenant_id, MailMessage.provider_deleted.is_(False)).order_by(MailMessage.received_at.desc())).all()
        result = []
        for msg in messages:
            decision = ctx.session.scalar(select(DispatchDecision).where(DispatchDecision.mail_message_id == msg.id).order_by(DispatchDecision.created_at.desc()).limit(1))
            data = _serialize(msg); data["dispatch"] = _serialize(decision) if decision else None; result.append(data)
        return result

    @app.post("/v1/inbox/messages", status_code=201)
    def add_message(payload: MailIn, ctx: TenantContext = Depends()):
        message = ingest_mail(ctx.session, ctx.tenant_id, payload.model_dump()); return _serialize(message)

    @app.post("/v1/inbox/{mail_id}/dispatch")
    def dispatch(mail_id: str, ctx: TenantContext = Depends()):
        decision = create_dispatch(ctx.session, ctx.tenant_id, mail_id); return _serialize(decision)

    @app.get("/v1/dispatch")
    def dispatch_list(ctx: TenantContext = Depends()):
        rows = ctx.session.execute(select(DispatchDecision, MailMessage, TeamDefinition).join(MailMessage, MailMessage.id == DispatchDecision.mail_message_id).join(TeamDefinition, TeamDefinition.id == DispatchDecision.suggested_team_id).where(DispatchDecision.tenant_id == ctx.tenant_id).order_by(DispatchDecision.created_at.desc())).all()
        return [{"decision": _serialize(d), "mail": _serialize(m), "suggested_team": _serialize(t)} for d, m, t in rows]

    @app.post("/v1/dispatch/{decision_id}/confirm", status_code=201)
    def confirm(decision_id: str, payload: DispatchConfirmIn, ctx: TenantContext = Depends()):
        mission = confirm_dispatch(ctx.session, ctx.tenant_id, decision_id, payload.team_key, payload.workflow_key, ctx.actor); return _serialize(mission)

    @app.get("/v1/missions")
    def missions(status: str | None = None, team_id: str | None = None, ctx: TenantContext = Depends()):
        query = select(Mission).where(Mission.tenant_id == ctx.tenant_id)
        if status: query = query.where(Mission.status == status)
        if team_id: query = query.where(Mission.primary_team_id == team_id)
        return [_serialize(m) for m in ctx.session.scalars(query.order_by(Mission.updated_at.desc())).all()]

    @app.get("/v1/missions/{mission_id}")
    def mission_detail(mission_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        mission = session.scalar(select(Mission).where(Mission.id == mission_id, Mission.tenant_id == tid))
        if not mission: raise HTTPException(404, "mission not found")
        items = session.scalars(select(WorkItem).where(WorkItem.mission_id == mission.id).order_by(WorkItem.sequence)).all()
        deps = session.scalars(select(WorkItemDependency).where(WorkItemDependency.tenant_id == tid, WorkItemDependency.work_item_id.in_([i.id for i in items]) if items else False)).all()
        runs = session.scalars(select(AgentRun).where(AgentRun.mission_id == mission.id).order_by(AgentRun.created_at.desc())).all()
        artifacts = session.scalars(select(Artifact).where(Artifact.mission_id == mission.id).order_by(Artifact.created_at.desc())).all()
        approvals = session.scalars(select(ApprovalRequest).where(ApprovalRequest.mission_id == mission.id).order_by(ApprovalRequest.created_at.desc())).all()
        return {"mission": _serialize(mission), "work_items": [_serialize(i) for i in items],
                "dependencies": [_serialize(d) for d in deps], "agent_runs": [_serialize(r) for r in runs],
                "artifacts": [_serialize(a) for a in artifacts], "approvals": [_serialize(a) for a in approvals]}

    @app.post("/v1/missions/{mission_id}/accept")
    def accept(mission_id: str, payload: VersionAction, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        mission = accept_mission(session, tid, mission_id, payload.expected_version, actor); return _serialize(mission)

    @app.post("/v1/missions/{mission_id}/plan")
    def plan(mission_id: str, payload: PlanIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        mission = plan_mission(session, tid, mission_id, payload.expected_version, payload.workflow_key, actor); return _serialize(mission)

    @app.post("/v1/missions/{mission_id}/approve-plan")
    def plan_approve(mission_id: str, payload: VersionAction, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        mission = approve_plan(session, tid, mission_id, payload.expected_version, actor); return _serialize(mission)

    @app.post("/v1/missions/{mission_id}/start")
    def mission_start(mission_id: str, payload: VersionAction, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        mission = start_execution(session, tid, mission_id, payload.expected_version, actor); return _serialize(mission)

    @app.post("/v1/work-items/{work_item_id}/start", status_code=201)
    def item_start(work_item_id: str, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        run = start_work_item(session, tid, work_item_id, actor); return _serialize(run)

    @app.post("/v1/agent-runs/{run_id}/submit")
    def run_submit(run_id: str, payload: AgentOutputIn, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        run = submit_agent_run(session, tid, run_id, payload.output, payload.evidence); return _serialize(run)

    @app.post("/v1/work-items/{work_item_id}/review")
    def item_review(work_item_id: str, payload: WorkItemReviewIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        item = review_work_item(session, tid, work_item_id, payload.decision, payload.reason, actor); return _serialize(item)

    @app.post("/v1/missions/{mission_id}/lead-review")
    def mission_review(mission_id: str, payload: VersionAction, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        mission, approval = lead_review_mission(session, tid, mission_id, payload.expected_version, actor); return {"mission": _serialize(mission), "approval": _serialize(approval) if approval else None}

    @app.patch("/v1/work-items/{work_item_id}")
    def work_item_update(work_item_id: str, payload: WorkItemUpdateIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        changes = payload.model_dump(exclude={"expected_version"}, exclude_none=True)
        item = update_work_item(session, tid, work_item_id, payload.expected_version, changes, actor); return _serialize(item)

    @app.post("/v1/missions/{mission_id}/dependencies", status_code=201)
    def dependency_add(mission_id: str, payload: DependencyIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        dep = add_dependency(session, tid, mission_id, payload.work_item_id, payload.depends_on_id, actor); return _serialize(dep)

    @app.delete("/v1/dependencies/{dependency_id}", status_code=204)
    def dependency_remove(dependency_id: str, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        remove_dependency(session, tid, dependency_id, actor); return None

    @app.get("/v1/tools")
    def tools(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        return [_serialize(t) for t in session.scalars(select(ToolDefinition).where(ToolDefinition.tenant_id == tid).order_by(ToolDefinition.name)).all()]

    @app.get("/v1/agent-runs/{run_id}/tools")
    def run_tools(run_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        rows = session.execute(select(ToolGrant, ToolDefinition).join(ToolDefinition, ToolDefinition.id == ToolGrant.tool_id).where(ToolGrant.tenant_id == tid, ToolGrant.agent_run_id == run_id)).all()
        return [{"grant": _serialize(g), "tool": _serialize(t)} for g, t in rows]

    @app.post("/v1/agent-runs/{run_id}/tools/{tool_key}/invoke")
    def tool_invoke(run_id: str, tool_key: str, payload: ToolInvokeIn, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        call = invoke_tool(session, tid, run_id, tool_key, payload.action, payload.parameters); return _serialize(call)

    @app.get("/v1/collaborations")
    def collaborations(mission_id: str | None = None, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        query = select(CollaborationRequest).where(CollaborationRequest.tenant_id == tid)
        if mission_id: query = query.where(CollaborationRequest.mission_id == mission_id)
        return [_serialize(r) for r in session.scalars(query.order_by(CollaborationRequest.created_at.desc())).all()]

    @app.post("/v1/missions/{mission_id}/collaborations", status_code=201)
    def collaboration_create(mission_id: str, payload: CollaborationIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        item = request_collaboration(session, tid, mission_id, payload.receiving_team_key, payload.objective, payload.expected_artifact, payload.input_scope, actor); return _serialize(item)

    @app.post("/v1/collaborations/{request_id}/respond")
    def collaboration_respond(request_id: str, payload: CollaborationResponseIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        item = respond_collaboration(session, tid, request_id, payload.status, payload.response, actor); return _serialize(item)

    @app.get("/v1/memory")
    def memory(status: str | None = None, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        query = select(MemoryRecord).where(MemoryRecord.tenant_id == tid)
        if status: query = query.where(MemoryRecord.status == status)
        return [_serialize(r) for r in session.scalars(query.order_by(MemoryRecord.created_at.desc())).all()]

    @app.post("/v1/memory", status_code=201)
    def memory_create(payload: MemoryProposalIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        record = propose_memory(session, tid, payload.mission_id, payload.memory_type, payload.subject_key, payload.content, payload.source_artifact_id, actor); return _serialize(record)

    @app.post("/v1/memory/{record_id}/decision")
    def memory_decision(record_id: str, payload: MemoryDecisionIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        record = decide_memory(session, tid, record_id, payload.decision, actor); return _serialize(record)

    @app.get("/v1/approvals")
    def approvals(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        return [_serialize(a) for a in session.scalars(select(ApprovalRequest).where(ApprovalRequest.tenant_id == tid).order_by(ApprovalRequest.created_at.desc())).all()]

    @app.post("/v1/approvals/{approval_id}/decision")
    def approval_decision(approval_id: str, payload: ApprovalDecisionIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        approval = decide_approval(session, tid, approval_id, payload.decision, payload.reason, actor); return _serialize(approval)

    @app.post("/v1/operations", status_code=201)
    def operation_prepare(payload: OperationPrepareIn, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        op = prepare_external_operation(session, tid, payload.approval_id, payload.operation_key); return _serialize(op)

    @app.post("/v1/operations/{operation_id}/execute")
    def operation_execute(operation_id: str, payload: OperationExecuteIn, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        op = execute_external_operation(session, tid, operation_id, simulate_unknown=payload.simulate_unknown); return _serialize(op)

    @app.post("/v1/operations/{operation_id}/verify")
    def operation_verify(operation_id: str, payload: OperationVerifyIn, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        op = verify_unknown_external_operation(session, tid, operation_id, payload.outcome); return _serialize(op)

    @app.get("/v1/operations")
    def operations(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        return [_serialize(o) for o in session.scalars(select(ExternalOperation).where(ExternalOperation.tenant_id == tid).order_by(ExternalOperation.created_at.desc())).all()]

    @app.get("/v1/audit")
    def audit(limit: int = Query(default=200, ge=1, le=1000), tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        return [_serialize(e) for e in session.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tid).order_by(AuditEvent.occurred_at.desc()).limit(limit)).all()]

    @app.get("/v1/audit/verify")
    def audit_verify(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        valid, broken_at = verify_audit_chain(session, tid); return {"valid": valid, "broken_at": broken_at}

    @app.post("/v1/outbox/publish")
    def outbox_publish(ctx: TenantContext = Depends()):
        return publish_batch(ctx.session, tenant_id=ctx.tenant_id)

    @app.post("/v1/demo/bootstrap")
    def demo_bootstrap(ctx: TenantContext = Depends()):
        samples = [
            {"provider_message_id": "demo:sales:1", "sender": "Sarah Chen <sarah@techbridge.io>", "recipients": ["owner@workbuddy.local"], "subject": "Partnership Proposal — revenue split and Thursday call", "body_text": "We suggest changing the revenue split to 60/40. Can we finalize on Thursday? Please confirm the commercial terms."},
            {"provider_message_id": "demo:ops:1", "sender": "王小明 <wang@acme.co>", "recipients": ["owner@workbuddy.local"], "subject": "产品上线延期风险 — 后端性能问题", "body_text": "并发超过 500 时响应变慢，建议推迟 1-2 周上线。需要确认交期和恢复计划。"},
            {"provider_message_id": "demo:cs:1", "sender": "客户服务 <client@example.com>", "recipients": ["owner@workbuddy.local"], "subject": "客户投诉：服务故障影响续约", "body_text": "系统故障已经影响业务，我们正在考虑取消续约并要求退款。请尽快给出解决方案。"},
        ]
        result = []
        for sample in samples:
            msg = ingest_mail(ctx.session, ctx.tenant_id, sample)
            decision = create_dispatch(ctx.session, ctx.tenant_id, msg.id)
            result.append({"mail_id": msg.id, "dispatch_id": decision.id})
        return {"created_or_reused": result}

    @app.post("/v1/demo/reset")
    def demo_reset(ctx: TenantContext = Depends()):
        # Preserve organization, workflows and skills; clear operational data in dependency order.
        delete_operational_data(ctx.session, ctx.tenant_id, include_audit=True)
        return {"status": "reset", "preserved": ["teams", "constitutions", "workflows", "agents", "skills"]}

    @app.post("/v1/scheduler/tick")
    def scheduler_run(ctx: TenantContext = Depends()):
        return scheduler_tick(ctx.session, ctx.tenant_id)

    @app.get("/v1/metrics")
    def metrics(ctx: TenantContext = Depends()):
        def counts(model, field):
            return {str(k): v for k, v in ctx.session.execute(select(field, func.count()).where(model.tenant_id == ctx.tenant_id).group_by(field)).all()}
        return {
            "missions_by_status": counts(Mission, Mission.status),
            "runs_by_status": counts(AgentRun, AgentRun.status),
            "approvals_by_status": counts(ApprovalRequest, ApprovalRequest.status),
            "operations_by_status": counts(ExternalOperation, ExternalOperation.status),
            "tool_calls_by_status": counts(ToolCall, ToolCall.status),
            "audit_events": ctx.session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == ctx.tenant_id)) or 0,
        }

    @app.get("/v1/controls")
    def controls(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        return [_serialize(c) for c in session.scalars(select(SystemControl).where(SystemControl.tenant_id == tid).order_by(SystemControl.scope_type, SystemControl.scope_id)).all()]

    @app.post("/v1/controls")
    def control_change(payload: ControlIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
        row = set_control(session, tid, payload.scope_type, payload.scope_id, payload.paused, payload.reason, actor); return _serialize(row)

    @app.get("/v1/privacy/export")
    def privacy_export(ctx: TenantContext = Depends()):
        return {
            "tenant_id": ctx.tenant_id,
            "exported_at": utcnow().isoformat(),
            "mail_messages": [_serialize(x) for x in ctx.session.scalars(select(MailMessage).where(MailMessage.tenant_id == ctx.tenant_id)).all()],
            "missions": [_serialize(x) for x in ctx.session.scalars(select(Mission).where(Mission.tenant_id == ctx.tenant_id)).all()],
            "work_items": [_serialize(x) for x in ctx.session.scalars(select(WorkItem).where(WorkItem.tenant_id == ctx.tenant_id)).all()],
            "artifacts": [_serialize(x) for x in ctx.session.scalars(select(Artifact).where(Artifact.tenant_id == ctx.tenant_id)).all()],
            "memory": [_serialize(x) for x in ctx.session.scalars(select(MemoryRecord).where(MemoryRecord.tenant_id == ctx.tenant_id)).all()],
        }

    @app.post("/v1/privacy/delete-operational-data")
    def privacy_delete(payload: DeleteOperationalDataIn, ctx: TenantContext = Depends()):
        preserved_audit_count = ctx.session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == ctx.tenant_id)) or 0
        delete_operational_data(ctx.session, ctx.tenant_id)
        append_audit(ctx.session, tenant_id=ctx.tenant_id, actor_type="user", actor_id=ctx.actor, action="privacy.operational_data_deleted", aggregate_type="tenant", aggregate_id=ctx.tenant_id, payload={"audit_events_preserved_before_delete": preserved_audit_count})
        return {"deleted": True, "audit_preserved": True, "organization_configuration_preserved": True}

    gmail = GmailConnector()

    @app.get("/v1/connectors/gmail/start")
    def gmail_start(enable_send: bool = Query(default=False), tid: str = Depends(tenant_id), actor: str = Depends(actor_id)):
        try:
            return {"configured": True, "authorization_url": gmail.authorization_url(tid, actor, enable_send=enable_send), "send_scope_requested": enable_send}
        except GmailNotConfigured as exc:
            return {"configured": False, "detail": str(exc), "required_env": ["WORKBUDDY_GMAIL_CLIENT_ID", "WORKBUDDY_GMAIL_CLIENT_SECRET"]}

    @app.get("/v1/connectors/gmail/callback")
    def gmail_callback(code: str, state: str, session: Session = Depends(db_session)):
        try:
            claims = gmail.decode_state(state)
            set_tenant_context(session, claims["tenant_id"])
            require_tenant(session, claims["tenant_id"])
            token = gmail.exchange_code(code)
            profile = gmail.profile(token["access_token"])
            address = profile["emailAddress"].lower()
            account = gmail.save_credentials(session, claims["tenant_id"], address, token)
            account.cursor = str(profile.get("historyId", "")) or None
            session.flush()
            binding = session.scalar(select(WebhookBinding).where(WebhookBinding.provider == "gmail", WebhookBinding.external_key == address))
            if not binding:
                binding = WebhookBinding(provider="gmail", external_key=address, tenant_id=claims["tenant_id"], account_id=account.id)
                session.add(binding)
            else:
                binding.tenant_id = claims["tenant_id"]; binding.account_id = account.id; binding.active = True
            return RedirectResponse(url="/?gmail=connected")
        except Exception as exc:
            raise HTTPException(400, f"Gmail connection failed: {exc}") from exc

    @app.get("/v1/connectors/gmail/accounts")
    def gmail_accounts(ctx: TenantContext = Depends()):
        rows = ctx.session.scalars(select(MailAccount).where(MailAccount.tenant_id == ctx.tenant_id, MailAccount.provider == "gmail").order_by(MailAccount.created_at.desc())).all()
        return [{k: v for k, v in _serialize(a).items() if k != "encrypted_credentials"} for a in rows]

    @app.post("/v1/connectors/gmail/accounts/{account_id}/sync")
    def gmail_sync(account_id: str, limit: int = Query(default=50, ge=1, le=500), tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        account = session.scalar(select(MailAccount).where(MailAccount.id == account_id, MailAccount.tenant_id == tid, MailAccount.provider == "gmail"))
        if not account:
            raise HTTPException(404, "Gmail account not found")
        run = SyncRun(tenant_id=tid, account_id=account.id, provider="gmail", sync_type="initial", status="RUNNING", cursor_before=account.cursor)
        session.add(run); session.flush(); account.sync_status = "running"
        try:
            access_token = gmail.valid_access_token(session, account)
            refs = gmail.list_message_refs(access_token, limit=limit)
            created = reused = 0
            for ref in refs:
                c, r = upsert_gmail_message(session, tid, gmail, ref["id"], access_token=access_token, account_id=account.id, actor="gmail-connector")
                created += c; reused += r
            profile = gmail.profile(access_token)
            account.cursor = str(profile.get("historyId", account.cursor or "")) or account.cursor
            account.status = "active"; account.sync_status = "idle"; account.last_synced_at = utcnow(); account.last_error = None
            run.status = "SUCCEEDED"; run.cursor_after = account.cursor; run.created_count = created; run.reused_count = reused; run.finished_at = utcnow()
            return _serialize(run)
        except Exception as exc:
            account.status = "error"; account.sync_status = "error"; account.last_error = str(exc)
            run.status = "FAILED"; run.error = str(exc); run.finished_at = utcnow()
            session.commit()  # persist failure diagnostic before raising (unit_of_work would rollback)
            raise HTTPException(502, f"Gmail sync failed: {exc}") from exc

    @app.post("/v1/connectors/gmail/accounts/{account_id}/watch")
    def gmail_watch(account_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
        account = session.scalar(select(MailAccount).where(MailAccount.id == account_id, MailAccount.tenant_id == tid, MailAccount.provider == "gmail"))
        if not account:
            raise HTTPException(404, "Gmail account not found")
        try:
            token = gmail.valid_access_token(session, account)
            result = gmail.register_watch(token, settings.gmail_topic_name)
            account.cursor = str(result.get("historyId", account.cursor or "")) or account.cursor
            if result.get("expiration"):
                from datetime import datetime, timezone
                account.watch_expires_at = datetime.fromtimestamp(int(result["expiration"]) / 1000, tz=timezone.utc)
            return {"history_id": account.cursor, "expiration": account.watch_expires_at.isoformat() if account.watch_expires_at else None}
        except Exception as exc:
            raise HTTPException(502, f"Gmail watch registration failed: {exc}") from exc

    @app.post("/v1/connectors/gmail/webhook")
    async def gmail_webhook(request: Request, token: str | None = Query(default=None), session: Session = Depends(db_session)):
        import base64, json
        if settings.gmail_pubsub_verification_token and token != settings.gmail_pubsub_verification_token:
            raise HTTPException(401, "invalid Pub/Sub verification token")
        envelope = await request.json()
        pubsub_message = envelope.get("message") or {}
        encoded = pubsub_message.get("data")
        if not encoded:
            raise HTTPException(400, "Pub/Sub message data is missing")
        event_id = str(pubsub_message.get("messageId") or content_hash(envelope))
        notification = json.loads(base64.b64decode(encoded).decode())
        address = str(notification.get("emailAddress") or "").lower()
        latest_notice = str(notification.get("historyId", ""))
        binding = session.scalar(select(WebhookBinding).where(
            WebhookBinding.provider == "gmail", WebhookBinding.external_key == address, WebhookBinding.active.is_(True),
        ))
        if not binding:
            return {"accepted": True, "ignored": "unknown account binding"}
        set_tenant_context(session, binding.tenant_id)
        account = session.scalar(select(MailAccount).where(
            MailAccount.id == binding.account_id, MailAccount.tenant_id == binding.tenant_id, MailAccount.provider == "gmail",
        ))
        if not account:
            return {"accepted": True, "ignored": "stale account binding"}
        existing_event = session.scalar(select(ProviderWebhookEvent).where(ProviderWebhookEvent.provider == "gmail", ProviderWebhookEvent.provider_event_id == event_id))
        if existing_event:
            return {"accepted": True, "duplicate": True}
        event = ProviderWebhookEvent(tenant_id=account.tenant_id, provider="gmail", provider_event_id=event_id, payload_hash=content_hash(envelope), status="RECEIVED")
        session.add(event); session.flush()
        if not account.cursor:
            account.cursor = latest_notice; event.status = "CURSOR_INITIALIZED"; return {"accepted": True, "initialized_cursor": latest_notice}
        run = SyncRun(tenant_id=account.tenant_id, account_id=account.id, provider="gmail", sync_type="history", status="RUNNING", cursor_before=account.cursor)
        session.add(run); account.sync_status = "running"
        try:
            access_token = gmail.valid_access_token(session, account)
            changes, latest = gmail.history_changes(access_token, account.cursor)
            created = reused = deleted = 0
            for mid in changes["upsert_ids"]:
                c, r = upsert_gmail_message(session, account.tenant_id, gmail, mid, access_token=access_token, account_id=account.id, actor="gmail-history-sync")
                created += c; reused += r
            for mid in changes["deleted_ids"]:
                message = session.scalar(select(MailMessage).where(
                    MailMessage.tenant_id == account.tenant_id,
                    MailMessage.provider_message_id == f"gmail:{mid}",
                ))
                if message and not message.provider_deleted:
                    message.provider_deleted = True
                    message.processing_status = "PROVIDER_DELETED"
                    deleted += 1
                    append_audit(session, tenant_id=account.tenant_id, actor_type="service", actor_id="gmail-history-sync",
                                 action="mail.message_provider_deleted", aggregate_type="mail_message", aggregate_id=message.id,
                                 payload={"provider_message_id": message.provider_message_id})
            account.cursor = latest or latest_notice; account.status = "active"; account.sync_status = "idle"; account.last_synced_at = utcnow(); account.last_error = None
            run.status = "SUCCEEDED"; run.cursor_after = account.cursor; run.created_count = created; run.reused_count = reused; run.deleted_count = deleted; run.finished_at = utcnow(); event.status = "PROCESSED"
            return {"accepted": True, "created": created, "reused": reused, "deleted": deleted, "cursor": account.cursor}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                account.status = "RESYNC_REQUIRED"; account.sync_status = "error"; account.last_error = "history cursor expired"
                run.status = "FAILED"; run.error = "history cursor expired"; run.finished_at = utcnow(); event.status = "RESYNC_REQUIRED"
                return {"accepted": True, "status": "RESYNC_REQUIRED"}
            run.status = "FAILED"; run.error = str(exc); run.finished_at = utcnow(); event.status = "FAILED"; session.commit(); raise

    from workbuddy.api.beta_routes import router as beta_router
    from workbuddy.api.pilot_routes import router as pilot_router
    from workbuddy.api.ops_routes import router as ops_router
    from workbuddy.api.commercial_routes import router as commercial_router
    from workbuddy.api.team_routes import router as team_router
    app.include_router(beta_router)
    app.include_router(pilot_router)
    app.include_router(ops_router)
    app.include_router(commercial_router)
    app.include_router(team_router)
    return app


app = create_app()
