# Tenant Provisioning and Exit

## Provisioning

Use an administrator database identity:

```bash
PYTHONPATH=src python scripts/provision_tenant.py \
  --name 'Customer Company' \
  --owner-email owner@customer.example \
  --owner-name 'Customer Owner'
```

The command creates a unique tenant, applies tenant context, seeds expert teams and Skills, creates the owner and activates the tenant.

## User management

Tenant owners can invite users and update roles through `/v1/organization/users`. User quotas are checked against the active subscription.

## Exit

Before deletion:

1. pause the company and external writes;
2. export operational, commercial and audit records;
3. revoke Gmail, Microsoft, model and tool credentials;
4. verify pending and `UNKNOWN` operations;
5. apply contractual retention requirements;
6. obtain accountable approval;
7. delete only eligible operational records;
8. preserve required audit and legal evidence.

`tenant_exit_export.py` exports data only. It intentionally cannot delete data.
