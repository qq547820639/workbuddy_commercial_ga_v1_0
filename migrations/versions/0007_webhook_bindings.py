"""add global webhook-to-tenant routing bindings"""
from alembic import op
from sqlalchemy import inspect
from workbuddy.db.models import Base

revision = "0007_webhook_bindings"
down_revision = "0006_graph_subscriptions"
branch_labels = None
depends_on = None

TABLE = "webhook_bindings"

def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[TABLE]], checkfirst=True)
    # Deliberately do not enable tenant RLS. This table is a minimal routing index
    # queried before the webhook handler knows the tenant. It is never exposed via API.

def downgrade() -> None:
    bind = op.get_bind()
    if TABLE in inspect(bind).get_table_names():
        op.drop_table(TABLE)
