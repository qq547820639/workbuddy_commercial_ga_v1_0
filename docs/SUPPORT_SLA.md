# Support and Service Status

## Initial response targets

| Severity | Definition | Initial response target |
|---|---|---:|
| P0 | confirmed security/data or uncontrolled external-action emergency | 1 hour |
| P1 | major production outage or high business impact | 4 hours |
| P2 | degraded function with workaround | 24 hours |
| P3 | question, minor defect or enhancement | 72 hours |

The system calculates `sla_due_at` when a ticket is created. Resolving a ticket requires a resolution statement.

## Ticket lifecycle

```text
OPEN → IN_PROGRESS → WAITING_CUSTOMER → IN_PROGRESS → RESOLVED → CLOSED
```

## Service incidents

```text
INVESTIGATING → IDENTIFIED → MONITORING → RESOLVED
```

Every status update is retained in the incident update history and audit log. Customer-facing publication and notification integrations must be connected to the organization's actual status-page provider.
