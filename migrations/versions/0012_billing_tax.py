"""add tax_type and tax_region columns to invoices"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0012_billing_tax"
down_revision = "0011_pricing_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("invoices")]
    if "tax_type" not in columns:
        op.add_column("invoices", sa.Column("tax_type", sa.String(30), nullable=False, server_default="VAT"))
    if "tax_region" not in columns:
        op.add_column("invoices", sa.Column("tax_region", sa.String(30), nullable=False, server_default="CN"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("invoices")]
    if "tax_region" in columns:
        op.drop_column("invoices", "tax_region")
    if "tax_type" in columns:
        op.drop_column("invoices", "tax_type")
