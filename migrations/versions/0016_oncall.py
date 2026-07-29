"""on-call schedules, shifts and escalation policies"""
from alembic import op
from sqlalchemy import inspect
from workbuddy.db.models import Base

revision = "0016_oncall"
down_revision = "0015_legal_review"
branch_labels = None
depends_on = None

TABLES = [
    "oncall_schedules", "oncall_shifts", "escalation_policies",
]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[t] for t in TABLES], checkfirst=True)
    if bind.dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
            op.execute(f'''CREATE POLICY tenant_isolation ON "{table}"
                USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
                WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))''')


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table in reversed(TABLES):
        if table in existing:
            if bind.dialect.name == "postgresql":
                op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
                op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
            op.drop_table(table)
