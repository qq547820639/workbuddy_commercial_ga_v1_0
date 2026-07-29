from __future__ import annotations

import httpx

from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.connectors.gmail import GmailConnector, GmailNotConfigured
from workbuddy.connectors.microsoft_graph import GraphNotConfigured, MicrosoftGraphConnector
from workbuddy.db.models import ApprovalRequest, ExternalOperation, MailAccount, Mission, OperationAttempt
from workbuddy.domain.state_machine import OPERATION_TRANSITIONS, ExternalOperationStatus, MissionStatus, transition
from workbuddy.settings import Settings, settings
from .audit import append_audit
from .business import BusinessError, ConflictError, _mission_transition
from .common import content_hash, utcnow
from .policies import PolicyViolation, email_hashes, validate_email_action


class ExternalActionError(BusinessError):
    pass


def _operation_transition(
    session: Session,
    op: ExternalOperation,
    target: ExternalOperationStatus,
    actor: str,
    reason: str,
) -> ExternalOperation:
    current = ExternalOperationStatus(op.status)
    op.status = transition(current, target, OPERATION_TRANSITIONS).value
    append_audit(
        session,
        tenant_id=op.tenant_id,
        actor_type="service",
        actor_id=actor,
        action=f"external_operation.{target.value.lower()}",
        aggregate_type="external_operation",
        aggregate_id=op.id,
        payload={"from": current.value, "to": target.value, "reason": reason, "demo_mode": op.demo_mode},
    )
    return op


def prepare_external_operation(
    session: Session,
    tenant_id: str,
    approval_id: str,
    operation_key: str,
    cfg: Settings = settings,
) -> ExternalOperation:
    approval = session.scalar(select(ApprovalRequest).where(ApprovalRequest.id == approval_id, ApprovalRequest.tenant_id == tenant_id))
    if not approval or approval.status != "APPROVED":
        raise ExternalActionError("approved request required")
    mission = session.scalar(select(Mission).where(Mission.id == approval.mission_id, Mission.tenant_id == tenant_id))
    if not mission:
        raise ExternalActionError("mission not found")
    # Approval binds the exact action hash and the pre-decision Mission version.
    # The APPROVED status transition itself increments Mission.version once and is allowed.
    if mission.version not in {approval.mission_version, approval.mission_version + 1}:
        approval.status = "INVALIDATED"
        raise ConflictError("approval invalidated because mission content changed")
    if content_hash(approval.exact_action) != approval.content_hash:
        approval.status = "INVALIDATED"
        raise ConflictError("approval content hash no longer matches exact action")
    existing = session.scalar(select(ExternalOperation).where(ExternalOperation.tenant_id == tenant_id, ExternalOperation.operation_key == operation_key))
    if existing:
        return existing
    action = dict(approval.exact_action)
    hashes = email_hashes(action)
    account = None
    if action.get("account_id"):
        account = session.scalar(select(MailAccount).where(MailAccount.id == action["account_id"], MailAccount.tenant_id == tenant_id))
    live = bool(cfg.live_send_ready and account and account.send_enabled)
    if live:
        validate_email_action(session, tenant_id, mission.id, action, cfg)
        if cfg.require_pilot_for_live_send:
            from .pilot import live_send_pilot_preflight
            try:
                live_send_pilot_preflight(session, tenant_id, account.id)
            except ValueError as exc:
                raise PolicyViolation(str(exc)) from exc
    op = ExternalOperation(
        tenant_id=tenant_id,
        mission_id=mission.id,
        approval_request_id=approval.id,
        operation_key=operation_key,
        operation_type="email_send",
        status=ExternalOperationStatus.PREPARED.value,
        parameters=action,
        parameters_hash=hashes["parameters_hash"],
        recipient_hash=hashes["recipient_hash"],
        body_hash=hashes["body_hash"],
        attachment_hash=hashes["attachment_hash"],
        demo_mode=not live,
    )
    session.add(op)
    session.flush()
    reason = "live-send policy and allowlist passed" if live else "live sending disabled or mailbox send scope unavailable; operation remains demo-only"
    _operation_transition(session, op, ExternalOperationStatus.POLICY_REVIEWED, "external-action-policy", reason)
    _operation_transition(session, op, ExternalOperationStatus.APPROVED, "external-action-policy", "exact approved action is frozen")
    return op


def execute_external_operation(
    session: Session,
    tenant_id: str,
    operation_id: str,
    *,
    simulate_unknown: bool = False,
    gmail: GmailConnector | None = None,
    graph: MicrosoftGraphConnector | None = None,
    cfg: Settings = settings,
) -> ExternalOperation:
    op = session.scalar(select(ExternalOperation).where(ExternalOperation.id == operation_id, ExternalOperation.tenant_id == tenant_id))
    if not op:
        raise ExternalActionError("operation not found")
    if op.status == ExternalOperationStatus.SUCCEEDED.value:
        return op
    if op.status == ExternalOperationStatus.UNKNOWN.value:
        raise ExternalActionError("UNKNOWN operations must be verified before another attempt")
    if op.status != ExternalOperationStatus.APPROVED.value:
        raise ExternalActionError("operation is not approved for execution")
    mission = session.scalar(select(Mission).where(Mission.id == op.mission_id, Mission.tenant_id == tenant_id))
    if not mission:
        raise ExternalActionError("mission not found")
    approval = session.get(ApprovalRequest, op.approval_request_id) if op.approval_request_id else None
    if not approval or approval.status != "APPROVED" or mission.version not in {approval.mission_version, approval.mission_version + 1}:
        raise ConflictError("operation approval is missing, invalidated, or stale")
    current_hashes = email_hashes(op.parameters)
    if current_hashes["parameters_hash"] != op.parameters_hash or current_hashes["recipient_hash"] != op.recipient_hash or current_hashes["body_hash"] != op.body_hash:
        approval.status = "INVALIDATED"
        raise ConflictError("operation parameters changed after approval")

    op.attempt_count += 1
    attempt = OperationAttempt(
        tenant_id=tenant_id,
        operation_id=op.id,
        attempt_number=op.attempt_count,
        status="STARTED",
        request_hash=op.parameters_hash,
    )
    session.add(attempt)
    session.flush()
    _operation_transition(session, op, ExternalOperationStatus.EXECUTING, "external-action-service", "provider attempt started")
    op.executed_at = utcnow()
    if mission.status == MissionStatus.APPROVED.value:
        _mission_transition(session, mission, MissionStatus.ACTION_EXECUTING, "external-action-service", "approved external action started")

    if simulate_unknown:
        attempt.status = "UNKNOWN"
        attempt.error = "simulated network interruption"
        op.error_code = "SIMULATED_UNKNOWN"
        _operation_transition(session, op, ExternalOperationStatus.UNKNOWN, "external-action-service", "result is unknown; direct retry is prohibited")
        _mission_transition(session, mission, MissionStatus.UNKNOWN, "external-action-service", "external action result is unknown")
        return op

    if op.demo_mode:
        _operation_transition(session, op, ExternalOperationStatus.VERIFYING, "external-action-service", "verify safe demo result")
        if mission.status == MissionStatus.ACTION_EXECUTING.value:
            _mission_transition(session, mission, MissionStatus.VERIFYING, "external-action-service", "verify demo result")
        op.provider_result = {"mode": "demo", "message": "No real email was sent.", "policy": "live send remains disabled"}
        op.provider_reference = f"demo:{op.id}"
        op.verified_at = utcnow()
        attempt.status = "SUCCEEDED"
        attempt.provider_reference = op.provider_reference
        attempt.response = op.provider_result
        _operation_transition(session, op, ExternalOperationStatus.SUCCEEDED, "external-action-service", "demo result verified")
        _mission_transition(session, mission, MissionStatus.COMPLETED, "external-action-service", "demo external action completed")
        return op

    try:
        validate_email_action(session, tenant_id, mission.id, op.parameters, cfg)
        account_id = op.parameters.get("account_id")
        account = session.scalar(select(MailAccount).where(MailAccount.id == account_id, MailAccount.tenant_id == tenant_id))
        if not account or not account.send_enabled:
            raise PolicyViolation("mail account does not have separately granted send scope")
        if account.provider == "gmail":
            connector = gmail or GmailConnector(cfg)
            token = connector.valid_access_token(session, account)
            result = connector.send_message(token, op.parameters)
            provider_id = result["id"]
            op.provider_reference = provider_id
            attempt.provider_reference = provider_id
            _operation_transition(session, op, ExternalOperationStatus.VERIFYING, "gmail-connector", "Gmail accepted message; verify provider record")
            if mission.status == MissionStatus.ACTION_EXECUTING.value:
                _mission_transition(session, mission, MissionStatus.VERIFYING, "gmail-connector", "verify Gmail message")
            verification = connector.verify_sent(token, provider_id)
        elif account.provider == "graph":
            connector = graph or MicrosoftGraphConnector(cfg)
            token = connector.valid_access_token(session, account)
            result = connector.send_message(token, op.parameters)
            provider_id = result["id"]
            op.provider_reference = provider_id
            attempt.provider_reference = provider_id
            _operation_transition(session, op, ExternalOperationStatus.VERIFYING, "graph-connector", "Graph accepted draft send; verify message record")
            if mission.status == MissionStatus.ACTION_EXECUTING.value:
                _mission_transition(session, mission, MissionStatus.VERIFYING, "graph-connector", "verify Graph message")
            verification = connector.verify_sent(token, provider_id)
        else:
            raise ExternalActionError(f"unsupported mail provider: {account.provider}")
        op.provider_result = {"send": result, "verification": verification}
        if not verification.get("verified"):
            op.error_code = "PROVIDER_NOT_VERIFIED"
            attempt.status = "UNKNOWN"
            attempt.response = op.provider_result
            _operation_transition(session, op, ExternalOperationStatus.UNKNOWN, "external-action-service", "provider record could not be verified")
            _mission_transition(session, mission, MissionStatus.UNKNOWN, "external-action-service", "provider send result is unverified")
            return op
        op.verified_at = utcnow()
        from .pilot import record_system_gate_evidence
        record_system_gate_evidence(
            session, tenant_id, account.id, evidence_type="live_send_verification",
            source=account.provider, metrics={"operation_id": op.id, "provider_reference": provider_id, "verified": True},
        )
        attempt.status = "SUCCEEDED"
        attempt.response = op.provider_result
        _operation_transition(session, op, ExternalOperationStatus.SUCCEEDED, "external-action-service", "provider send result verified")
        _mission_transition(session, mission, MissionStatus.COMPLETED, "external-action-service", "approved email sent and verified")
        from .commercial import record_usage
        record_usage(session, tenant_id, metric_key="live_email_sends", quantity=1, unit="message", source_type="external_operation", source_id=op.id, idempotency_key=f"external-operation:{op.id}:verified-send")
        return op
    except httpx.HTTPStatusError as exc:
        attempt.status = "UNKNOWN" if exc.response.status_code >= 500 else "FAILED"
        attempt.error = str(exc)
        op.error_code = f"HTTP_{exc.response.status_code}"
        if exc.response.status_code >= 500:
            _operation_transition(session, op, ExternalOperationStatus.UNKNOWN, "external-action-service", "provider error leaves send result uncertain")
            _mission_transition(session, mission, MissionStatus.UNKNOWN, "external-action-service", "provider result uncertain")
        else:
            _operation_transition(session, op, ExternalOperationStatus.FAILED, "external-action-service", "provider rejected external action")
            _mission_transition(session, mission, MissionStatus.FAILED, "external-action-service", "provider rejected email send")
        return op
    except httpx.RequestError as exc:
        # A transport failure can happen after the Provider accepted the request.
        # Preserve the attempt and force verification instead of risking a duplicate send.
        attempt.status = "UNKNOWN"
        attempt.error = str(exc)
        op.error_code = "PROVIDER_TRANSPORT_ERROR"
        _operation_transition(session, op, ExternalOperationStatus.UNKNOWN, "external-action-service", "network failure leaves provider acceptance uncertain")
        _mission_transition(session, mission, MissionStatus.UNKNOWN, "external-action-service", "network failure leaves external action result uncertain")
        return op
    except (PolicyViolation, GmailNotConfigured, GraphNotConfigured, ExternalActionError) as exc:
        attempt.status = "FAILED"
        attempt.error = str(exc)
        op.error_code = type(exc).__name__.upper()
        _operation_transition(session, op, ExternalOperationStatus.FAILED, "external-action-service", str(exc))
        _mission_transition(session, mission, MissionStatus.FAILED, "external-action-service", "external action failed before provider acceptance")
        return op
    except Exception as exc:  # defensive boundary around third-party Provider adapters
        attempt.status = "UNKNOWN"
        attempt.error = f"{type(exc).__name__}: {exc}"
        op.error_code = "UNEXPECTED_PROVIDER_ERROR"
        _operation_transition(session, op, ExternalOperationStatus.UNKNOWN, "external-action-service", "unexpected provider error leaves result uncertain")
        _mission_transition(session, mission, MissionStatus.UNKNOWN, "external-action-service", "unexpected provider error leaves external action result uncertain")
        return op


def verify_unknown_external_operation(
    session: Session,
    tenant_id: str,
    operation_id: str,
    outcome: str,
) -> ExternalOperation:
    op = session.scalar(select(ExternalOperation).where(ExternalOperation.id == operation_id, ExternalOperation.tenant_id == tenant_id))
    if not op or op.status != ExternalOperationStatus.UNKNOWN.value:
        raise ExternalActionError("unknown operation not found")
    mission = session.scalar(select(Mission).where(Mission.id == op.mission_id, Mission.tenant_id == tenant_id))
    if not mission:
        raise ExternalActionError("mission not found")
    _operation_transition(session, op, ExternalOperationStatus.VERIFYING, "external-action-service", "operator/provider verification of unknown result")
    if mission.status == MissionStatus.UNKNOWN.value:
        _mission_transition(session, mission, MissionStatus.VERIFYING, "external-action-service", "verify unknown result")
    op.verified_at = utcnow()
    if outcome == "succeeded":
        op.provider_result = {**(op.provider_result or {}), "manual_verification": "succeeded"}
        account_id = op.parameters.get("account_id")
        if account_id and not op.demo_mode:
            from .pilot import record_system_gate_evidence
            record_system_gate_evidence(
                session, tenant_id, account_id, evidence_type="unknown_recovery_drill",
                source="operator_verification", metrics={"operation_id": op.id, "outcome": outcome, "verified": True},
            )
        _operation_transition(session, op, ExternalOperationStatus.SUCCEEDED, "external-action-service", "unknown result verified as succeeded")
        _mission_transition(session, mission, MissionStatus.COMPLETED, "external-action-service", "unknown result verified as succeeded")
    else:
        op.provider_result = {**(op.provider_result or {}), "manual_verification": "failed"}
        _operation_transition(session, op, ExternalOperationStatus.FAILED, "external-action-service", "unknown result verified as failed")
        _mission_transition(session, mission, MissionStatus.FAILED, "external-action-service", "unknown result verified as failed")
    return op
