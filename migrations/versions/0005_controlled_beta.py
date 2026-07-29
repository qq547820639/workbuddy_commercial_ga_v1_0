"""controlled beta operational, model, quality and provider tables"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from workbuddy.db.models import Base

revision = "0005_controlled_beta"
down_revision = "0004_audit_sequence"
branch_labels = None
depends_on = None

NEW_TABLES = [
    "tenant_policies", "model_invocations", "dispatch_feedback", "sync_runs",
    "provider_webhook_events", "quality_evaluations", "operation_attempts",
]
NEW_TENANT_TABLES = [x for x in NEW_TABLES if x != "provider_webhook_events"]

COLUMNS = {
    "mail_accounts": [
        sa.Column("sync_status", sa.String(30), nullable=False, server_default="idle"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("send_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    ],
    "mail_messages": [
        sa.Column("direction", sa.String(20), nullable=False, server_default="inbound"),
        sa.Column("labels", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("has_attachments", sa.Boolean(), nullable=False, server_default=sa.false()),
    ],
    "dispatch_decisions": [
        sa.Column("model_invocation_id", sa.String(36), nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.true()),
    ],
    "agent_runs": [
        sa.Column("model_invocation_id", sa.String(36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    ],
    "external_operations": [
        sa.Column("recipient_hash", sa.String(64), nullable=True),
        sa.Column("body_hash", sa.String(64), nullable=True),
        sa.Column("attachment_hash", sa.String(64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
    ],
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for table, columns in COLUMNS.items():
        existing = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column.copy())
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[name] for name in NEW_TABLES], checkfirst=True)
    if bind.dialect.name == "postgresql":
        for table in NEW_TENANT_TABLES:
            policies = {p["name"] for p in inspector.get_table_options(table).get("policies", [])} if False else set()
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
            op.execute(f'''CREATE POLICY tenant_isolation ON "{table}"
                USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
                WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))''')
        op.execute('ALTER TABLE "provider_webhook_events" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "provider_webhook_events" FORCE ROW LEVEL SECURITY')
        op.execute('DROP POLICY IF EXISTS tenant_isolation ON "provider_webhook_events"')
        op.execute('''CREATE POLICY tenant_isolation ON "provider_webhook_events"
            USING (tenant_id IS NULL OR tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id IS NULL OR tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))''')


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for table in reversed(NEW_TABLES):
        if table in inspector.get_table_names():
            op.drop_table(table)
    inspector = inspect(bind)
    for table, columns in reversed(list(COLUMNS.items())):
        existing = {c["name"] for c in inspector.get_columns(table)}
        for column in reversed(columns):
            if column.name in existing:
                with op.batch_alter_table(table) as batch:
                    batch.drop_column(column.name)
