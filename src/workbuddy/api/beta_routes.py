from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from workbuddy.api.deps import actor_id, db_session, require_tenant, set_tenant_context, tenant_id
from workbuddy.api.schemas import AgentExecuteIn, DispatchFeedbackIn, SkillTestIn, TenantPolicyIn
from workbuddy.connectors.microsoft_graph import GraphNotConfigured, MicrosoftGraphConnector
from workbuddy.db.models import (
    DispatchDecision, DispatchFeedback, ExternalOperation, MailAccount, MailMessage, ModelInvocation,
    OperationAttempt, ProviderWebhookEvent, QualityEvaluation, SyncRun, TeamDefinition,
    TenantPolicy, WebhookBinding,
)
from workbuddy.services.audit import append_audit
from workbuddy.services.business import ingest_mail
from workbuddy.services.common import content_hash, model_dict, utcnow
from workbuddy.services.executor import execute_agent_run
from workbuddy.services.mail_sync import MailSyncError, sync_graph_folder
from workbuddy.services.policies import ensure_default_policies
from workbuddy.services.quality import quality_dashboard
from workbuddy.services.skills import test_skill_release
from workbuddy.settings import settings

router = APIRouter()


def serialize(obj: Any) -> dict[str, Any]:
    return model_dict(obj)


@router.post("/v1/agent-runs/{run_id}/execute")
def execute_run(run_id: str, _payload: AgentExecuteIn, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    require_tenant(session, tid)
    run = execute_agent_run(session, tid, run_id)
    session.commit()
    if (run.close_reason or "").startswith("failed:"):
        raise HTTPException(status_code=502, detail={
            "message": "AgentRun failed; the failure record was persisted and the WorkItem was blocked.",
            "agent_run_id": run.id,
            "close_reason": run.close_reason,
            "output": run.output,
        })
    return serialize(run)




@router.post("/v1/skills/{release_id}/test")
def test_skill(release_id: str, payload: SkillTestIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    release = test_skill_release(session, tid, release_id, actor, payload.test_input)
    session.commit()
    return serialize(release)


@router.get("/v1/model/invocations")
def model_invocations(
    task_type: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    tid: str = Depends(tenant_id),
    session: Session = Depends(db_session),
):
    require_tenant(session, tid)
    query = select(ModelInvocation).where(ModelInvocation.tenant_id == tid)
    if task_type:
        query = query.where(ModelInvocation.task_type == task_type)
    return [serialize(x) for x in session.scalars(query.order_by(ModelInvocation.created_at.desc()).limit(limit)).all()]


@router.get("/v1/quality")
def quality(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    require_tenant(session, tid)
    return quality_dashboard(session, tid)


@router.get("/v1/pilot/dispatch-metrics")
def dispatch_metrics(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    require_tenant(session, tid)
    decisions = session.scalars(select(DispatchDecision).where(DispatchDecision.tenant_id == tid)).all()
    feedback = session.scalars(select(DispatchFeedback).where(DispatchFeedback.tenant_id == tid)).all()
    reviewed = len(feedback)
    correct = sum(1 for x in feedback if x.suggested_team_id == x.confirmed_team_id)
    high_risk = [d for d in decisions if d.risk_level in {"high", "critical"}]
    return {
        "shadow_mode": settings.dispatch_shadow_mode,
        "total_suggestions": len(decisions),
        "reviewed": reviewed,
        "team_accuracy": round(correct / reviewed * 100, 1) if reviewed else None,
        "correction_rate": round((reviewed - correct) / reviewed * 100, 1) if reviewed else None,
        "high_risk_suggestions": len(high_risk),
        "review_required": sum(1 for d in decisions if d.review_required),
        "average_confidence": round(sum(d.confidence for d in decisions) / len(decisions), 1) if decisions else None,
        "gate_b_thresholds": {"team_accuracy_min": 90, "high_risk_recall_target": 100},
    }


@router.post("/v1/dispatch/{decision_id}/feedback")
def add_dispatch_feedback(
    decision_id: str,
    payload: DispatchFeedbackIn,
    tid: str = Depends(tenant_id),
    actor: str = Depends(actor_id),
    session: Session = Depends(db_session),
):
    decision = session.scalar(select(DispatchDecision).where(DispatchDecision.id == decision_id, DispatchDecision.tenant_id == tid))
    if not decision:
        raise HTTPException(404, "dispatch decision not found")
    team = session.scalar(select(TeamDefinition).where(TeamDefinition.tenant_id == tid, TeamDefinition.team_key == payload.confirmed_team_key))
    if not team:
        raise HTTPException(422, "confirmed team not found")
    row = DispatchFeedback(
        tenant_id=tid,
        dispatch_decision_id=decision.id,
        suggested_team_id=decision.suggested_team_id,
        confirmed_team_id=team.id,
        suggested_risk_level=decision.risk_level,
        corrected_risk_level=payload.corrected_risk_level,
        actor_id=actor,
        comment=payload.comment,
    )
    session.add(row)
    append_audit(session, tenant_id=tid, actor_type="user", actor_id=actor, action="dispatch.feedback_recorded",
                 aggregate_type="dispatch_decision", aggregate_id=decision.id,
                 payload={"confirmed_team_id": team.id, "corrected_risk_level": payload.corrected_risk_level})
    session.commit()
    return serialize(row)


@router.get("/v1/pilot/sync-runs")
def sync_runs(limit: int = Query(default=200, ge=1, le=1000), tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    require_tenant(session, tid)
    return [serialize(x) for x in session.scalars(select(SyncRun).where(SyncRun.tenant_id == tid).order_by(SyncRun.created_at.desc()).limit(limit)).all()]


@router.get("/v1/policies/external-email")
def get_external_email_policy(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    require_tenant(session, tid)
    policy = ensure_default_policies(session, tid)
    session.commit()
    return serialize(policy)


@router.put("/v1/policies/external-email")
def update_external_email_policy(
    payload: TenantPolicyIn,
    tid: str = Depends(tenant_id),
    actor: str = Depends(actor_id),
    session: Session = Depends(db_session),
):
    policy = ensure_default_policies(session, tid)
    if payload.expected_version is not None and payload.expected_version != policy.version:
        raise HTTPException(409, f"version conflict: current={policy.version}, expected={payload.expected_version}")
    allowed = {
        "require_owner_approval", "allow_bcc", "allow_attachments", "daily_send_limit",
        "mission_send_limit", "allowed_recipient_domains", "allowed_recipient_addresses",
    }
    unknown = set(payload.config) - allowed
    if unknown:
        raise HTTPException(422, f"unknown policy fields: {sorted(unknown)}")
    policy.config = {**policy.config, **payload.config}
    policy.version += 1
    append_audit(session, tenant_id=tid, actor_type="user", actor_id=actor, action="policy.external_email_updated",
                 aggregate_type="tenant_policy", aggregate_id=policy.id, aggregate_version=policy.version,
                 payload={"changed_fields": sorted(payload.config)})
    session.commit()
    return serialize(policy)


@router.get("/v1/operations/{operation_id}/attempts")
def operation_attempts(operation_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    require_tenant(session, tid)
    return [serialize(x) for x in session.scalars(select(OperationAttempt).where(OperationAttempt.tenant_id == tid, OperationAttempt.operation_id == operation_id).order_by(OperationAttempt.attempt_number)).all()]


@router.get("/v1/beta/readiness")
def beta_readiness(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    require_tenant(session, tid)
    accounts = session.scalars(select(MailAccount).where(MailAccount.tenant_id == tid)).all()
    live_accounts = [a for a in accounts if a.send_enabled]
    model_success = session.scalar(select(func.count()).select_from(ModelInvocation).where(
        ModelInvocation.tenant_id == tid, ModelInvocation.status == "SUCCEEDED",
    )) or 0
    quality_count = session.scalar(select(func.count()).select_from(QualityEvaluation).where(
        QualityEvaluation.tenant_id == tid,
    )) or 0
    successful_syncs = session.scalar(select(func.count()).select_from(SyncRun).where(
        SyncRun.tenant_id == tid, SyncRun.status == "SUCCEEDED",
    )) or 0
    dispatch_reviews = session.scalar(select(func.count()).select_from(DispatchFeedback).where(
        DispatchFeedback.tenant_id == tid,
    )) or 0
    verified_live_operations = session.scalar(select(func.count()).select_from(ExternalOperation).where(
        ExternalOperation.tenant_id == tid,
        ExternalOperation.demo_mode.is_(False),
        ExternalOperation.status == "SUCCEEDED",
    )) or 0
    policy = ensure_default_policies(session, tid)
    policy_cfg = policy.config or {}
    deployment_allowlist = bool(settings.allowed_recipient_domains or settings.allowed_recipient_addresses)
    tenant_allowlist = bool(policy_cfg.get("allowed_recipient_domains") or policy_cfg.get("allowed_recipient_addresses"))
    checks = {
        "database": True,
        "model_gateway": settings.model_provider == "deterministic" or bool(settings.model_api_key),
        "mail_shadow_account": bool(accounts),
        "successful_mail_sync_observed": successful_syncs > 0,
        "dispatch_review_observed": dispatch_reviews > 0,
        "mail_send_scope": bool(live_accounts),
        "live_send_feature_flag": settings.enable_live_email_send,
        "deployment_recipient_allowlist": deployment_allowlist,
        "tenant_recipient_allowlist": tenant_allowlist,
        "model_invocations_observed": model_success > 0,
        "quality_evaluations_observed": quality_count > 0,
        "verified_live_send_observed": verified_live_operations > 0,
    }
    gate_b_preflight = checks["mail_shadow_account"]
    gate_b = all([gate_b_preflight, checks["successful_mail_sync_observed"], checks["dispatch_review_observed"]])
    gate_c = all([checks["model_gateway"], checks["model_invocations_observed"], checks["quality_evaluations_observed"]])
    gate_d_preflight = all([
        checks["mail_send_scope"], checks["live_send_feature_flag"],
        checks["deployment_recipient_allowlist"], checks["tenant_recipient_allowlist"],
    ])
    gate_d = gate_d_preflight and checks["verified_live_send_observed"]
    session.commit()  # persist the default tenant policy when this is the first readiness check
    return {
        "environment": settings.environment,
        "checks": checks,
        "gate_b_preflight_ready": gate_b_preflight,
        "gate_b_ready": gate_b,
        "gate_c_ready": gate_c,
        "gate_d_preflight_ready": gate_d_preflight,
        "gate_d_ready": gate_d,
        "note": "A gate is marked ready only after its required live evidence has been observed; cloud app registration, security review, DNS/TLS and provider drills remain operator-owned activities.",
    }


graph = MicrosoftGraphConnector()


@router.get("/v1/connectors/graph/start")
def graph_start(enable_send: bool = Query(default=False), tid: str = Depends(tenant_id), actor: str = Depends(actor_id)):
    try:
        return {"configured": True, "authorization_url": graph.authorization_url(tid, actor, enable_send=enable_send), "send_scope_requested": enable_send}
    except GraphNotConfigured as exc:
        return {"configured": False, "detail": str(exc), "required_env": ["WORKBUDDY_GRAPH_CLIENT_ID", "WORKBUDDY_GRAPH_CLIENT_SECRET"]}


@router.get("/v1/connectors/graph/callback")
def graph_callback(code: str, state: str, session: Session = Depends(db_session)):
    try:
        claims = graph.decode_state(state)
        set_tenant_context(session, claims["tenant_id"])
        require_tenant(session, claims["tenant_id"])
        token = graph.exchange_code(code, enable_send=bool(claims.get("enable_send")))
        profile = graph.profile(token["access_token"])
        address = profile.get("mail") or profile.get("userPrincipalName")
        account = graph.save_credentials(session, claims["tenant_id"], address, token)
        # Folder-scoped delta cursors are stored as an opaque JSON map.
        account.cursor = json.dumps({"inbox": None, "sentitems": None})
        session.commit()
        return RedirectResponse(url="/?graph=connected")
    except Exception as exc:
        raise HTTPException(400, f"Microsoft Graph connection failed: {exc}") from exc


@router.get("/v1/connectors/graph/accounts")
def graph_accounts(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    require_tenant(session, tid)
    rows = session.scalars(select(MailAccount).where(MailAccount.tenant_id == tid, MailAccount.provider == "graph").order_by(MailAccount.created_at.desc())).all()
    return [{k: v for k, v in serialize(a).items() if k != "encrypted_credentials"} for a in rows]


@router.post("/v1/connectors/graph/accounts/{account_id}/sync")
def graph_sync(
    account_id: str,
    folder_id: str = Query(default="inbox"),
    tid: str = Depends(tenant_id),
    session: Session = Depends(db_session),
):
    account = session.scalar(select(MailAccount).where(MailAccount.id == account_id, MailAccount.tenant_id == tid, MailAccount.provider == "graph"))
    if not account:
        raise HTTPException(404, "Microsoft Graph account not found")
    try:
        run = sync_graph_folder(session, tid, account, folder_id=folder_id, connector=graph)
        session.commit()
        return serialize(run)
    except MailSyncError as exc:
        session.commit()
        raise HTTPException(502, f"Microsoft Graph sync failed: {exc}") from exc


@router.post("/v1/connectors/graph/accounts/{account_id}/watch")
def graph_watch(account_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    account = session.scalar(select(MailAccount).where(MailAccount.id == account_id, MailAccount.tenant_id == tid, MailAccount.provider == "graph"))
    if not account:
        raise HTTPException(404, "Microsoft Graph account not found")
    try:
        token = graph.valid_access_token(session, account)
        import hmac
        client_state = settings.graph_webhook_client_state or hmac.new(settings.app_secret.encode(), account.id.encode(), hashlib.sha256).hexdigest()
        if account.provider_subscription_id:
            result = graph.renew_subscription(token, account.provider_subscription_id)
        else:
            webhook_url = f"{settings.public_base_url.rstrip('/')}/v1/connectors/graph/webhook"
            result = graph.create_subscription(token, webhook_url, client_state)
        old_subscription_id = account.provider_subscription_id
        account.provider_subscription_id = result.get("id") or account.provider_subscription_id
        account.subscription_resource = result.get("resource") or account.subscription_resource or "me/mailFolders('inbox')/messages"
        account.subscription_client_state = client_state
        session.flush()
        if old_subscription_id and old_subscription_id != account.provider_subscription_id:
            old_binding = session.scalar(select(WebhookBinding).where(WebhookBinding.provider == "graph", WebhookBinding.external_key == old_subscription_id))
            if old_binding:
                old_binding.active = False
        binding = session.scalar(select(WebhookBinding).where(WebhookBinding.provider == "graph", WebhookBinding.external_key == account.provider_subscription_id))
        if not binding:
            binding = WebhookBinding(
                provider="graph", external_key=account.provider_subscription_id, tenant_id=tid, account_id=account.id,
                verification_hash=content_hash(client_state), active=True,
            )
            session.add(binding)
        else:
            binding.tenant_id = tid; binding.account_id = account.id; binding.verification_hash = content_hash(client_state); binding.active = True
        expiration = result.get("expirationDateTime")
        if expiration:
            account.watch_expires_at = datetime.fromisoformat(expiration.replace("Z", "+00:00"))
        account.status = "active"
        account.last_error = None
        session.commit()
        return {"subscription_id": account.provider_subscription_id, "expiration": account.watch_expires_at, "resource": account.subscription_resource}
    except Exception as exc:
        account.last_error = str(exc)
        session.commit()
        raise HTTPException(502, f"Microsoft Graph subscription failed: {exc}") from exc


@router.get("/v1/connectors/graph/webhook", operation_id="graph_webhook_validation")
def graph_webhook_validation(validationToken: str = Query(...)):
    return PlainTextResponse(validationToken)


@router.post("/v1/connectors/graph/webhook", operation_id="graph_webhook_receive")
async def graph_webhook_receive(request: Request, session: Session = Depends(db_session)):
    payload = await request.json()
    accepted = duplicates = rejected = 0
    for notification in payload.get("value", []):
        subscription_id = notification.get("subscriptionId")
        binding = session.scalar(select(WebhookBinding).where(
            WebhookBinding.provider == "graph", WebhookBinding.external_key == subscription_id, WebhookBinding.active.is_(True),
        )) if subscription_id else None
        if not binding:
            rejected += 1
            continue
        set_tenant_context(session, binding.tenant_id)
        account = session.scalar(select(MailAccount).where(
            MailAccount.id == binding.account_id, MailAccount.tenant_id == binding.tenant_id, MailAccount.provider == "graph",
        ))
        expected_state = account.subscription_client_state if account else None
        supplied_state = notification.get("clientState") or ""
        if not account or not expected_state or content_hash(supplied_state) != binding.verification_hash:
            rejected += 1
            continue
        event_id = f"{subscription_id}:{notification.get('sequenceNumber','')}:{notification.get('resource','')}:{notification.get('lifecycleEvent','')}"
        if event_id.endswith(":::"):
            event_id = content_hash(notification)
        existing = session.scalar(select(ProviderWebhookEvent).where(
            ProviderWebhookEvent.provider == "graph",
            ProviderWebhookEvent.provider_event_id == event_id,
        ))
        if existing:
            duplicates += 1
            continue
        lifecycle = notification.get("lifecycleEvent")
        status = "LIFECYCLE" if lifecycle else "ACCEPTED"
        session.add(ProviderWebhookEvent(
            tenant_id=account.tenant_id, provider="graph", provider_event_id=event_id,
            payload_hash=content_hash(notification), status=status,
        ))
        account.sync_status = "pending"
        if lifecycle in {"subscriptionRemoved", "reauthorizationRequired", "missed"}:
            account.status = "subscription_attention"
            account.last_error = f"Graph lifecycle event: {lifecycle}"
        # A Graph batch can contain subscriptions from different tenants. Flush while
        # the resolved tenant context is active before switching to the next binding.
        session.flush()
        accepted += 1
    session.commit()
    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected, "note": "Notifications schedule folder delta sync; delta remains the source of truth."}


