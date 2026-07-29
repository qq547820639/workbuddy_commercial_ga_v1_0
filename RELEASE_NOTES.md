# Commercial GA v1.0 Release Notes

## New

- ProductPlan, TenantSubscription, UsageRecord, BillingEvent and Invoice;
- CustomerOnboarding with enforced stage requirements;
- SupportTicket and ServiceStatusIncident;
- ComplianceDocument and hash-bound TenantAgreement;
- CustomerValueMetric;
- GAReleaseProgram, GAEvidence and GAAttestation;
- commercial, support, status, compliance, organization and GA APIs;
- automatic metering for model calls, AgentRuns and verified live sends;
- Commercial GA operations UI and CLI tools;
- Alembic migration 0010 and PostgreSQL forced RLS for every new tenant table.

## Gap-closure automation (12 gaps)

- Gap 1: PricingApproval model with catalog hash binding and subscription activation gate;
- Gap 2: PaymentProvider abstraction (Manual/Stripe), tax engine, webhook verification;
- Gap 3: Terraform IaC for GCP/Entra, Workload Identity Federation, CI/CD terraform validate/plan;
- Gap 4: SSE-KMS object store encryption for S3 and GCS providers;
- Gap 5: ModelProviderAgreement with DPA validation and DB-backed cost rates;
- Gap 6: Pre-send safety checks and UNKNOWN recovery drill script;
- Gap 7: PentestReport tracking with external third-party and all-remediations GA gate;
- Gap 8: LegalReviewApproval with dual-role (legal_owner + privacy_owner) requirement;
- Gap 9: OnCallSchedule, OnCallShift, EscalationPolicy with 7-day coverage and SLA checker;
- Gap 10: Design partner profiles and value metrics reporting;
- Gap 11: 30-day observation window with P0/P1 auto-reset and GA completion gate;
- Gap 12: HMAC-SHA256 cryptographic signatures on GA attestations with verification;
- Alembic migrations 0011-0019 for gap-closure tables;
- 10 new operational scripts (billing_dry_run, check_live_send_safety, unknown_recovery_drill, sla_check, oncall_drill, value_report, observation_check, ga_signoff_bundle, submit_pentest_evidence, submit_cloud_setup_evidence);
- 9 Terraform modules (31 .tf files) for GCP and Entra production infrastructure;
- 7 Prometheus alert rules for GA gate monitoring;
- SLSA Level 3 provenance and Workload Identity Federation in CI/CD;
- 9 new automated tests for gap-closure regression coverage (56 total).

## Safety

- Prices are reference-only until formally approved;
- paid subscription activation requires commercial approval and provider/contract reference;
- invoice payment requires provider reference or explicit manual evidence;
- onboarding cannot skip stages or mandatory controls;
- GA signatures are invalidated by evidence snapshot changes;
- GA attestations include cryptographic signatures verified during gate evaluation;
- observation window auto-resets on P0/P1 incidents; 30-day completion required for GA;
- GA remains NO_GO without linked Production Pilot GO and real operating evidence.
