"""model provider agreements table"""
from alembic import op
from sqlalchemy import inspect
from workbuddy.db.models import Base

revision = "0013_model_agreement"
down_revision = "0012_billing_tax"
branch_labels = None
depends_on = None

TABLES = [
    "model_provider_agreements",
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
