"""create WorkBuddy core domain tables"""
from alembic import op
from workbuddy.db.models import Base
revision = "0001_core_domain"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())

def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
