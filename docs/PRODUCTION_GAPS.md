# Production and Commercial Gaps

This document tracks the twelve production and commercial gaps that separate a code-complete package from a truthfully commercially launched product.

For each gap, the **code-side automation** is now implemented — models, migrations, services, API endpoints, scripts, infrastructure templates and tests are in place. However, the **organizational evidence** — real accounts, signed contracts, external approvals, live data and accountable signatures — cannot be produced by code alone. The system enforces `NO_GO` until that evidence is provided.

## Gap status summary

| # | Gap | Code automation | Organizational evidence required |
|---|---|---|---|
| 1 | Formal pricing approval and signed customer contracts | `PricingApproval` model, approval workflow, catalog hash binding, subscription activation gate | Finance/product owner decision, signed customer contracts |
| 2 | Payment provider, bank settlement, tax and official invoice capability | `PaymentProvider` abstraction, `ManualProvider`, `StripeProvider` stub, tax engine, webhook verification, idempotent `UsageRecord` | Payment provider account, bank settlement, tax registration, official invoice qualification |
| 3 | Google Cloud and Microsoft Entra production applications | Terraform modules for GCP project, Cloud SQL, GCS, KMS, IAM; Entra app registration; Workload Identity Federation; CI/CD `terraform validate/plan` | Real GCP project, Entra tenant, DNS, TLS certificates, billing account |
| 4 | Production PostgreSQL, object storage, KMS/Secrets and DNS/TLS | SSE-KMS encryption for S3/GCS providers, object-store encryption preflight check, backup target validation | Production PostgreSQL instance, KMS key provisioning, DNS/TLS configuration |
| 5 | Model-provider agreement, regional processing and cost rates | `ModelProviderAgreement` model, DPA validation in production preflight, DB-backed cost rate estimation | Model provider account, signed DPA, regional processing approval, negotiated rates |
| 6 | Live mailbox, live send and UNKNOWN recovery evidence | Pre-send safety checks, `check_live_send_safety.py`, `unknown_recovery_drill.py` script | Live mailbox, verified live send evidence, real UNKNOWN recovery drill results |
| 7 | Independent penetration test and security remediation | `PentestReport` model, external third-party tester requirement, all-remediations gate for GA | Engaged independent pentest firm, real test report, remediation verification |
| 8 | Privacy, terms, DPA and subprocessors legal approval | `LegalReviewApproval` model, dual-review requirement (`legal_owner` + `privacy_owner`), compliance document versioning | Finalized legal text, lawyer review, jurisdiction-specific approval |
| 9 | Staffed P0–P3 support and On-call rota | `OnCallSchedule`, `OnCallShift`, `EscalationPolicy` models, 7-day coverage verification, `sla_check.py`, `oncall_drill.py` | Real on-call staff, escalation contacts, SLA monitoring, support team |
| 10 | At least three real Design Partners and measured value outcomes | `design_partner_profile` on `CustomerOnboarding`, `value_report.py` script, customer value metrics model | Three real design partners, measured time savings, adoption and quality data |
| 11 | 30-day incident-free production observation | `ObservationWindow` model, P0/P1 auto-reset, 30-day completion gate, `observation_check.py` | 30 consecutive days of production operation with zero P0/P1 incidents |
| 12 | Accountable Gate B/C/D/Production/Commercial/Value/GA signatures | HMAC-SHA256 cryptographic signatures on `GAAttestation`, signature verification during gate evaluation, `ga_signoff_bundle.py` | Real accountable signatories, signed evidence, organizational authority |

## How the system enforces each gap

### Gap 1 — Pricing approval
- Built-in plan prices are marked `REFERENCE_ONLY_UNTIL_COMMERCIAL_APPROVAL`.
- `PricingApproval` must exist in the database with a contract reference before a subscription can transition to `ACTIVE`.
- Setting `WORKBUDDY_COMMERCIAL_PRICING_APPROVED=true` is required to un-reference prices.

### Gap 2 — Payment and billing
- `PaymentProvider` protocol abstracts Stripe, manual and future providers.
- A configured live provider that cannot honour a request raises `ProviderNotConfigured` — it never silently degrades to manual.
- Invoice `PAID` requires a provider reference or explicit manual evidence.
- Tax engine applies region-based VAT/GST; webhook signatures are verified.

### Gap 3 — Cloud infrastructure
- Terraform modules define GCP project, Cloud SQL, GCS buckets, KMS keys, IAM bindings and Entra app registration.
- CI/CD runs `terraform validate` and `terraform plan` on every change.
- Workload Identity Federation removes the need for long-lived service-account keys.
- Real GCP project ID, Entra tenant ID and DNS/TLS must be supplied by the organization.

### Gap 4 — Production data infrastructure
- Object-store providers support SSE-KMS encryption; the preflight check reports when encryption is missing.
- Backup target validation ensures a bucket is configured.
- Production PostgreSQL, KMS key material and DNS/TLS certificates are organizational prerequisites.

### Gap 5 — Model provider agreement
- `ModelProviderAgreement` model tracks DPA status, processing region and cost rates.
- Production preflight checks that a valid DPA exists before live send is enabled.
- DB-backed cost rates replace hardcoded estimates.

### Gap 6 — Live send safety
- Pre-send safety checks validate recipient allowlists, feature flags and pilot gate enforcement.
- `unknown_recovery_drill.py` provides a repeatable drill script.
- Real live mailbox and verified UNKNOWN recovery evidence remain organizational.

### Gap 7 — Penetration test
- `PentestReport` model records test date, tester type, scope and remediation status.
- GA requires an external third-party test with `ALL_REMEDIATED` status.
- A real independent test report is still required.

### Gap 8 — Legal review
- `LegalReviewApproval` model requires both `legal_owner` and `privacy_owner` to approve each compliance document.
- Compliance documents are versioned with content hashes.
- Legal templates are explicitly marked as drafting checklists, not approved legal text.

### Gap 9 — On-call and support
- `OnCallSchedule`, `OnCallShift` and `EscalationPolicy` models track coverage.
- 7-day coverage verification ensures round-the-clock rotation.
- `sla_check.py` and `oncall_drill.py` validate SLA compliance and escalation readiness.
- Real staffed on-call rota and support team are organizational.

### Gap 10 — Design partners and value
- `design_partner_profile` on `CustomerOnboarding` tracks partner metadata.
- `value_report.py` generates a structured value-metrics report from recorded data.
- Customer value metrics are never auto-generated as proof of value.
- Three real design partners with measured outcomes are required.

### Gap 11 — Observation window
- `ObservationWindow` model tracks a 30-day window with P0/P1 incident counts.
- Any P0/P1 incident (support ticket, service incident or pilot incident) automatically resets the window.
- GA requires a `COMPLETED` observation window with zero P0/P1 incidents.
- `observation_check.py` provides a standalone checker.

### Gap 12 — Cryptographic gate signatures
- `GAAttestation` records include an HMAC-SHA256 `cryptographic_signature` and `signing_key_id`.
- Signatures bind the role, decision, evidence-snapshot hash, actor and timestamp.
- Gate evaluation verifies signatures cryptographically; invalid signatures block GO.
- `ga_signoff_bundle.py` exports a complete signed sign-off bundle.
- Real accountable signatories with organizational authority are still required.

## Honesty guarantee

Until all twelve gaps have both code automation **and** real organizational evidence:

- The system returns `NO_GO` for Production Pilot, Commercial, Value and GA gates.
- No trial, draft invoice, contract draft or simulated run is presented as commercial completion.
- Prices remain reference-only.
- Legal templates remain drafting checklists.
- Customer value metrics are never fabricated.
