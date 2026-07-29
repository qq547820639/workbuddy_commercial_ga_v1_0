# Billing and Metering

## Currency

All internal monetary amounts are stored as integer Chinese yuan fen (`CNY fen`). No binary floating-point money fields are used.

## Reference plan catalog

Starter, Growth and Scale are reference plans for implementation and testing. They are not approved commercial offers. `WORKBUDDY_COMMERCIAL_PRICING_APPROVED=false` is the safe default.

## Subscription lifecycle

```text
TRIALING → ACTIVE → PAST_DUE → ACTIVE / CANCELLED
TRIALING → CANCELLED
```

Paid activation requires:

1. accountable commercial price approval;
2. a contract or payment-provider confirmation reference.

## Metered events

- `model_input_tokens`;
- `model_output_tokens`;
- `model_cost_cny_fen`;
- `agent_runs`;
- `live_email_sends`.

Usage records have tenant-scoped idempotency keys. Replayed model, worker or provider events do not double count.

## Invoice lifecycle

```text
DRAFT → OPEN → PAID
DRAFT / OPEN → VOID
```

An invoice cannot become `PAID` without a provider reference or a deliberately recorded manual payment evidence flag. In production, replace manual reconciliation with a selected payment provider and verified webhook adapter.

## Not implemented as a fake

- card collection;
- tax calculation by jurisdiction;
- official Chinese fapiao issuance;
- bank settlement;
- refunds and chargebacks;
- payment-provider webhooks.

Those require actual legal entity, tax and provider accounts.
