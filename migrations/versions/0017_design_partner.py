"""add design partner profile to customer_onboardings"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0017_design_partner"
down_revision = "0016_oncall"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("customer_onboardings")]
    if "design_partner_profile" not in columns:
        op.add_column("customer_onboardings", sa.Column("design_partner_profile", sa.JSON, nullable=False, server_default="{}"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("customer_onboardings")]
    if "design_partner_profile" in columns:
        op.drop_column("customer_onboardings", "design_partner_profile")
