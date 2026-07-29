"""add provider-side mail deletion state"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0008_provider_mail_state"
down_revision = "0007_webhook_bindings"
branch_labels = None
depends_on = None

COLUMN = sa.Column("provider_deleted", sa.Boolean(), nullable=False, server_default=sa.false())

def upgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in inspect(bind).get_columns("mail_messages")}
    if COLUMN.name not in existing:
        op.add_column("mail_messages", COLUMN.copy())
    if bind.dialect.name == "postgresql":
        indexes = {i["name"] for i in inspect(bind).get_indexes("mail_messages")}
        if "ix_mail_messages_provider_deleted" not in indexes:
            op.create_index("ix_mail_messages_provider_deleted", "mail_messages", ["provider_deleted"], unique=False)

def downgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in inspect(bind).get_columns("mail_messages")}
    if COLUMN.name in existing:
        if bind.dialect.name == "postgresql":
            op.drop_index("ix_mail_messages_provider_deleted", table_name="mail_messages")
        with op.batch_alter_table("mail_messages") as batch:
            batch.drop_column("provider_deleted")
