"""team tool allowlist (JSON config) and collaboration request state machine"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0020_team_tool_allowlist_and_collab_state"
down_revision = "0019_attestation_signing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("collaboration_requests")]
    if "response_reason" not in columns:
        op.add_column("collaboration_requests", sa.Column("response_reason", sa.Text, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("collaboration_requests")]
    if "response_reason" in columns:
        op.drop_column("collaboration_requests", "response_reason")
