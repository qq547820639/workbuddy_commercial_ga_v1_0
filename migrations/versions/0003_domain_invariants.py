"""document and enforce additional PostgreSQL domain checks"""
from alembic import op
revision = "0003_domain_invariants"
down_revision = "0002_postgres_rls"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql": return
    op.execute("ALTER TABLE missions ADD CONSTRAINT ck_mission_version_positive CHECK (version >= 1)")
    op.execute("ALTER TABLE work_items ADD CONSTRAINT ck_work_item_version_positive CHECK (version >= 1)")
    op.execute("ALTER TABLE agent_runs ADD CONSTRAINT ck_agent_run_version_positive CHECK (version >= 1)")
    op.execute("ALTER TABLE external_operations ADD CONSTRAINT ck_operation_hash_length CHECK (char_length(parameters_hash) = 64)")
    op.execute("ALTER TABLE approval_requests ADD CONSTRAINT ck_approval_hash_length CHECK (char_length(content_hash) = 64)")

def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql": return
    for table, name in [("approval_requests","ck_approval_hash_length"),("external_operations","ck_operation_hash_length"),("agent_runs","ck_agent_run_version_positive"),("work_items","ck_work_item_version_positive"),("missions","ck_mission_version_positive")]:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
