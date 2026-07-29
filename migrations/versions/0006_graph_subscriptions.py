"""add Microsoft Graph subscription tracking"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006_graph_subscriptions"
down_revision = "0005_controlled_beta"
branch_labels = None
depends_on = None

COLUMNS = [
    sa.Column("provider_subscription_id", sa.String(300), nullable=True),
    sa.Column("subscription_resource", sa.String(500), nullable=True),
    sa.Column("subscription_client_state", sa.String(500), nullable=True),
]

def upgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in inspect(bind).get_columns("mail_accounts")}
    for column in COLUMNS:
        if column.name not in existing:
            op.add_column("mail_accounts", column.copy())

def downgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in inspect(bind).get_columns("mail_accounts")}
    for column in reversed(COLUMNS):
        if column.name in existing:
            with op.batch_alter_table("mail_accounts") as batch:
                batch.drop_column(column.name)
