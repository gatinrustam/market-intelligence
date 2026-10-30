from alembic import op
from app.storage.models import Base
revision = 'e50001'
down_revision = None
branch_labels = depends_on = None
def upgrade(): Base.metadata.create_all(op.get_bind())
def downgrade(): raise RuntimeError('Evaluation audit history must not be dropped by downgrade')
