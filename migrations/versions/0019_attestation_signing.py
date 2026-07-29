"""add cryptographic signature to ga_attestations"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0019_attestation_signing"
down_revision = "0018_observation_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("ga_attestations")]
    if "cryptographic_signature" not in columns:
        op.add_column("ga_attestations", sa.Column("cryptographic_signature", sa.Text, nullable=True))
    if "signing_key_id" not in columns:
        op.add_column("ga_attestations", sa.Column("signing_key_id", sa.String(200), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("ga_attestations")]
    if "signing_key_id" in columns:
        op.drop_column("ga_attestations", "signing_key_id")
    if "cryptographic_signature" in columns:
        op.drop_column("ga_attestations", "cryptographic_signature")
