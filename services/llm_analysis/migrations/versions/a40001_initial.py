"""Stage 4 isolated persistence."""
from alembic import op
from app.storage.models import Base
revision='a40001'
down_revision=None
branch_labels=None
depends_on=None
def upgrade():Base.metadata.create_all(op.get_bind())
def downgrade():raise RuntimeError('Analysis audit is immutable; downgrade is intentionally unsupported')
