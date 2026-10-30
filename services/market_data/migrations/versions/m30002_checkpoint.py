"""Durable candle repair checkpoint independent of newest WebSocket candle."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME
revision='m30002'
down_revision='m30001'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('collection_checkpoints',sa.Column('name',sa.String(32),primary_key=True),sa.Column('cursor_at',sa.DateTime().with_variant(DATETIME(fsp=6),'mysql','mariadb'),nullable=False))
def downgrade():op.drop_table('collection_checkpoints')
