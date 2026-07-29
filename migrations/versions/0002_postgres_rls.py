"""enable PostgreSQL tenant row-level security"""
from alembic import op
revision = "0002_postgres_rls"
down_revision = "0001_core_domain"
branch_labels = None
depends_on = None

TENANT_TABLES = [
    "users", "team_definitions", "team_constitution_versions", "workflow_versions",
    "agent_profiles", "skill_definitions", "skill_releases", "mail_accounts", "mail_messages",
    "dispatch_decisions", "missions", "work_items", "work_item_dependencies", "agent_runs",
    "artifacts", "evidence", "approval_requests", "approval_decisions", "external_operations",
    "audit_events", "outbox_events", "idempotency_records", "tool_definitions", "tool_grants",
    "tool_calls", "collaboration_requests", "memory_records", "system_controls",
]

def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'''CREATE POLICY tenant_isolation ON "{table}"
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))''')

def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in reversed(TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
