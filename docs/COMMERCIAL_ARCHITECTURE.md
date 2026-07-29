# Commercial Architecture

The commercial layer is separate from the Agent execution layer.

```text
Organization / Users
        │
ProductPlan → TenantSubscription → Entitlements
        │                         │
        │                         ├── ModelInvocation metering
        │                         ├── AgentRun metering
        │                         └── verified live-send metering
        │
UsageRecord → Invoice Draft → OPEN → PAID / VOID
        │
CustomerOnboarding → Shadow → Agent Draft → Live Send → Completed
        │
Support / Status / Compliance / Value Metrics
        │
Production Pilot GO + Commercial/Value/GA Evidence + Attestations
        │
Commercial GA GO / NO_GO
```

## Separation of concerns

- Agent services cannot mark invoices paid.
- Billing records cannot grant external-action permission.
- A subscription quota can restrict usage, but cannot bypass approval policy.
- Legal documents are immutable versions; acceptance binds the exact hash.
- GA evidence is append-only and verified by accountable roles.
- GA GO does not replace the Production Pilot gates; it depends on them.

## Tenant isolation

All commercial entities contain `tenant_id`. Migration 0010 enables and forces PostgreSQL Row-Level Security on every commercial table. Provisioning is an administrator-only CLI because tenant creation cannot safely depend on a tenant-scoped API request.
